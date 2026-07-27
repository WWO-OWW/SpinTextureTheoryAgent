from __future__ import annotations

import hashlib
import json
import platform
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CROSS_ENGINE_SCHEMA_VERSION = "1.0.0"
DEFAULT_CORE3_SPECS = PROJECT_ROOT / "cross_engine_specs" / "core3"
DEFAULT_CORE3_OUTPUT = PROJECT_ROOT / "analysis" / "cross_engine" / "core3_latest"
RUNNER_PATH = Path(__file__).resolve()

CheckMethod = Literal["sympy_exact", "sympy_plus_mpmath", "not_applicable"]
CheckStatus = Literal["passed", "failed", "not_applicable"]

EXPECTED_CHECK_IDS: dict[str, tuple[str, ...]] = {
    "afm_stripe_sot_full": (
        "a4_sympy_unit_constraint",
        "a4_wall_metric_coefficients",
        "a4_sot_projection_coefficients",
        "a4_periodic_hessian_coefficients",
        "a4_localization_limits",
        "a4_terminal_equation_equivalence",
    ),
    "fm_skyrmion_sot_full": (
        "b1_topological_charge",
        "b1_metric_coefficient",
        "b1_gyrotropic_sign_bridge",
        "b1_damping_like_sot_projection",
        "b1_localized_field_like_boundary",
        "b1_full_thiele_equation_equivalence",
    ),
    "afm_skyrmion_sot_full": (
        "b2_neel_topological_charge",
        "b2_metric_mass_damping_coefficients",
        "b2_field_like_sot_projection",
        "b2_localized_damping_like_boundary",
        "b2_compensated_gyro_cancellation",
        "b2_inertial_mass_positive",
        "b2_full_inertial_equation_equivalence",
    ),
}


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


def _stored_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def _positive_decimal(value: str, label: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} must be a decimal string") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return parsed


def _load_engines() -> tuple[Any, Any]:
    try:
        import mpmath as mp
        import sympy as sp
    except ImportError as exc:
        raise ValueError(
            "Cross-engine validation requires the optional 'cross-engine' dependencies: "
            "pip install -e '.[cross-engine]'"
        ) from exc
    return sp, mp


class CrossEngineProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: Literal["rigid_sech_tanh_wall", "localized_radial_power_skyrmion"]
    definition: str = Field(min_length=1)
    radial_exponent: int | None = Field(default=None, ge=2)
    boundary_conditions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profile(self) -> "CrossEngineProfile":
        if self.family == "localized_radial_power_skyrmion" and self.radial_exponent is None:
            raise ValueError("Localized radial profiles require radial_exponent")
        if self.family == "rigid_sech_tanh_wall" and self.radial_exponent is not None:
            raise ValueError("Wall profiles cannot declare radial_exponent")
        return self


class CrossEngineSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(pattern=r"^[a-z0-9_]+$")
    values: dict[str, float]

    @model_validator(mode="after")
    def validate_values(self) -> "CrossEngineSample":
        if not self.values:
            raise ValueError("Cross-engine samples cannot be empty")
        return self


class CrossEngineCheckSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(pattern=r"^[a-z0-9_]+$")
    category: str = Field(min_length=1)
    method: CheckMethod
    required: bool
    not_applicable_reason: str | None = None

    @model_validator(mode="after")
    def validate_method(self) -> "CrossEngineCheckSpec":
        if self.method == "not_applicable":
            if self.required:
                raise ValueError("not_applicable checks cannot be required")
            if not self.not_applicable_reason:
                raise ValueError("not_applicable checks require a reason")
        elif not self.required or self.not_applicable_reason is not None:
            raise ValueError("Executable checks must be required and cannot have an N/A reason")
        return self


class CrossEngineIndependence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_input_artifacts: list[str] = Field(min_length=1)
    prohibited_input_artifacts: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_disjoint_inputs(self) -> "CrossEngineIndependence":
        overlap = set(self.allowed_input_artifacts) & set(self.prohibited_input_artifacts)
        if overlap:
            raise ValueError("Allowed and prohibited cross-engine inputs overlap")
        return self


class CrossEngineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[CROSS_ENGINE_SCHEMA_VERSION] = CROSS_ENGINE_SCHEMA_VERSION
    spec_id: str = Field(pattern=r"^[a-z0-9_]+$")
    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    route_id: str = Field(pattern=r"^[a-z0-9_]+$")
    claim_scope: str = Field(min_length=1)
    profile: CrossEngineProfile
    precision_digits: list[int] = Field(min_length=3)
    absolute_tolerance: str
    relative_tolerance: str
    samples: list[CrossEngineSample] = Field(min_length=1)
    checks: list[CrossEngineCheckSpec] = Field(min_length=1)
    independence: CrossEngineIndependence

    @model_validator(mode="after")
    def validate_contract(self) -> "CrossEngineSpec":
        expected = EXPECTED_CHECK_IDS.get(self.route_id)
        if expected is None:
            raise ValueError(f"Unsupported cross-engine route: {self.route_id}")
        check_ids = tuple(check.check_id for check in self.checks)
        if check_ids != expected:
            raise ValueError(
                f"Cross-engine checks for {self.route_id} must match the frozen ordered contract"
            )
        if self.precision_digits != sorted(set(self.precision_digits)):
            raise ValueError("Precision digits must be unique and strictly increasing")
        if self.precision_digits[0] < 30:
            raise ValueError("Cross-engine quadrature must start at 30 digits or higher")
        _positive_decimal(self.absolute_tolerance, "absolute_tolerance")
        _positive_decimal(self.relative_tolerance, "relative_tolerance")
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("Cross-engine sample IDs must be unique")
        if len(self.independence.allowed_input_artifacts) != 1:
            raise ValueError("Each cross-engine spec may authorize only its own spec artifact")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "CrossEngineSpec":
        return cls.model_validate(_load_yaml(_project_path(path)))


class HashedArtifact(BaseModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EngineMetadata(BaseModel):
    python_version: str
    symbolic_engine: Literal["sympy"] = "sympy"
    symbolic_engine_version: str
    numeric_engine: Literal["mpmath"] = "mpmath"
    numeric_engine_version: str
    numeric_method: Literal[
        "tanh_sinh_wall_gauss_legendre_radial_periodic_angular_quadrature"
    ] = (
        "tanh_sinh_wall_gauss_legendre_radial_periodic_angular_quadrature"
    )
    angular_nodes: int = Field(ge=16)
    precision_digits: list[int]
    absolute_tolerance: str
    relative_tolerance: str


class NumericPrecisionPoint(BaseModel):
    precision_digits: int
    estimates: list[str]
    references: list[str]
    maximum_absolute_error: str
    maximum_successive_delta: str | None
    within_tolerance: bool


class NumericConvergence(BaseModel):
    sample_id: str
    observables: list[str] = Field(min_length=1)
    points: list[NumericPrecisionPoint] = Field(min_length=3)
    converged_at_final_precision: bool


class CrossEngineCheckResult(BaseModel):
    check_id: str
    category: str
    method: CheckMethod
    required: bool
    status: CheckStatus
    symbolic_result: str | None = None
    convergence: list[NumericConvergence] = Field(default_factory=list)
    detail: str

    @model_validator(mode="after")
    def validate_status(self) -> "CrossEngineCheckResult":
        if self.method == "not_applicable":
            if self.status != "not_applicable" or self.required:
                raise ValueError("N/A check results must remain non-required and not_applicable")
        elif self.status == "not_applicable":
            raise ValueError("Executable cross-engine checks cannot become not_applicable")
        if self.method == "sympy_plus_mpmath" and not self.convergence:
            raise ValueError("Hybrid checks require numerical convergence evidence")
        if self.method == "sympy_exact" and self.convergence:
            raise ValueError("Exact symbolic checks cannot carry numerical convergence evidence")
        return self


class CrossEngineRouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[CROSS_ENGINE_SCHEMA_VERSION] = CROSS_ENGINE_SCHEMA_VERSION
    spec_id: str
    case_id: str
    route_id: str
    claim_scope: str
    execution_status: Literal["passed", "failed"]
    passed: bool
    executed_at: str
    engine: EngineMetadata
    input_artifacts: list[HashedArtifact]
    prohibited_input_artifacts: list[str]
    runner_artifact: HashedArtifact
    checks: list[CrossEngineCheckResult]
    passed_check_count: int
    failed_check_count: int
    not_applicable_check_count: int
    result_path: str
    summary_path: str

    @model_validator(mode="after")
    def validate_counts(self) -> "CrossEngineRouteResult":
        passed = sum(check.status == "passed" for check in self.checks)
        failed = sum(check.status == "failed" for check in self.checks)
        not_applicable = sum(check.status == "not_applicable" for check in self.checks)
        if (passed, failed, not_applicable) != (
            self.passed_check_count,
            self.failed_check_count,
            self.not_applicable_check_count,
        ):
            raise ValueError("Cross-engine check counts are inconsistent")
        required_passed = all(
            check.status == "passed" for check in self.checks if check.required
        )
        expected_pass = failed == 0 and required_passed
        if self.passed != expected_pass or self.execution_status != (
            "passed" if expected_pass else "failed"
        ):
            raise ValueError("Cross-engine route status is inconsistent with required checks")
        return self


class CrossEngineSuiteResult(BaseModel):
    schema_version: Literal[CROSS_ENGINE_SCHEMA_VERSION] = CROSS_ENGINE_SCHEMA_VERSION
    suite_id: Literal["core3_cross_engine_v1"] = "core3_cross_engine_v1"
    execution_status: Literal["passed", "failed"]
    passed: bool
    route_count: int
    passed_route_count: int
    failed_route_count: int
    passed_check_count: int
    failed_check_count: int
    not_applicable_check_count: int
    routes: list[CrossEngineRouteResult]
    result_path: str
    summary_path: str


class CrossEngineVerification(BaseModel):
    route_id: str
    eligible_for_cross_engine_pass: bool
    passed_check_count: int
    not_applicable_check_count: int
    issues: list[str]


def _artifact(path: Path) -> HashedArtifact:
    return HashedArtifact(path=_stored_path(path), sha256=_sha256(path))


def load_cross_engine_specs(path: str | Path = DEFAULT_CORE3_SPECS) -> list[tuple[Path, CrossEngineSpec]]:
    resolved = _project_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Cross-engine spec path does not exist: {resolved}")
    paths = [resolved] if resolved.is_file() else sorted(resolved.glob("*.yaml"))
    if not paths:
        raise ValueError(f"No cross-engine specs found under {resolved}")
    specs = [(item, CrossEngineSpec.from_yaml(item)) for item in paths]
    route_ids = [spec.route_id for _, spec in specs]
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("Cross-engine spec routes must be unique")
    return specs


def _dot(left: list[Any], right: list[Any]) -> Any:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _cross(left: list[Any], right: list[Any]) -> list[Any]:
    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


def _mp_text(mp: Any, value: Any, digits: int) -> str:
    return mp.nstr(value, min(digits, 60), strip_zeros=False)


def _sympy_values(sp: Any, expressions: list[Any], substitutions: dict[Any, Any], digits: int) -> list[str]:
    return [str(sp.N(expression.subs(substitutions), digits)) for expression in expressions]


def _convergence(
    *,
    spec: CrossEngineSpec,
    sample: CrossEngineSample,
    observables: list[str],
    numeric: Any,
    references: Any,
    mp: Any,
) -> NumericConvergence:
    absolute_tolerance = mp.mpf(spec.absolute_tolerance)
    relative_tolerance = mp.mpf(spec.relative_tolerance)
    points: list[NumericPrecisionPoint] = []
    previous: list[Any] | None = None
    for digits in spec.precision_digits:
        with mp.workdps(digits):
            estimates = [mp.mpf(value) for value in numeric(digits)]
            expected = [mp.mpf(value) for value in references(digits)]
            if len(estimates) != len(expected) or len(estimates) != len(observables):
                raise ValueError("Numeric observable dimensions do not match")
            errors = [abs(actual - target) for actual, target in zip(estimates, expected, strict=True)]
            thresholds = [
                max(absolute_tolerance, relative_tolerance * max(mp.mpf(1), abs(target)))
                for target in expected
            ]
            within = all(
                error <= threshold for error, threshold in zip(errors, thresholds, strict=True)
            )
            delta = None
            if previous is not None:
                delta = max(
                    abs(actual - old) for actual, old in zip(estimates, previous, strict=True)
                )
            points.append(
                NumericPrecisionPoint(
                    precision_digits=digits,
                    estimates=[_mp_text(mp, value, digits) for value in estimates],
                    references=[_mp_text(mp, value, digits) for value in expected],
                    maximum_absolute_error=_mp_text(mp, max(errors), digits),
                    maximum_successive_delta=(
                        None if delta is None else _mp_text(mp, delta, digits)
                    ),
                    within_tolerance=within,
                )
            )
            previous = estimates
    final = points[-1]
    penultimate = points[-2]
    final_delta = mp.mpf(final.maximum_successive_delta or "inf")
    reference_scale = max(mp.mpf(1), *(abs(mp.mpf(item)) for item in final.references))
    final_threshold = max(absolute_tolerance, relative_tolerance * reference_scale)
    converged = final.within_tolerance and penultimate.within_tolerance and final_delta <= final_threshold
    return NumericConvergence(
        sample_id=sample.sample_id,
        observables=observables,
        points=points,
        converged_at_final_precision=bool(converged),
    )


def _check_result(
    check: CrossEngineCheckSpec,
    *,
    passed: bool,
    symbolic_result: str,
    detail: str,
    convergence: list[NumericConvergence] | None = None,
) -> CrossEngineCheckResult:
    return CrossEngineCheckResult(
        check_id=check.check_id,
        category=check.category,
        method=check.method,
        required=check.required,
        status="passed" if passed else "failed",
        symbolic_result=symbolic_result,
        convergence=convergence or [],
        detail=detail,
    )


def _not_applicable(check: CrossEngineCheckSpec) -> CrossEngineCheckResult:
    return CrossEngineCheckResult(
        check_id=check.check_id,
        category=check.category,
        method=check.method,
        required=False,
        status="not_applicable",
        detail=check.not_applicable_reason or "Outside the registered cross-engine scope.",
    )


def _a4_symbolic(sp: Any) -> dict[str, Any]:
    xi = sp.symbols("xi", real=True)
    delta = sp.symbols("Delta", positive=True, real=True)
    phase = sp.symbols("Phi", real=True)
    polarity = sp.symbols("polarity", real=True)
    px, py, pz = sp.symbols("px py pz", real=True)
    tau_dl, tau_fl = sp.symbols("tau_dl tau_fl", real=True)
    sech = sp.sech(xi)
    field = sp.Matrix(
        [sech * sp.cos(phase), sech * sp.sin(phase), -polarity * sp.tanh(xi)]
    )
    tangent_x = -field.diff(xi) / delta
    tangent_phase = field.diff(phase)
    tangents = (tangent_x, tangent_phase)
    metric_integrand = sp.Matrix(
        2,
        2,
        lambda i, j: sp.simplify(delta * tangents[i].dot(tangents[j])),
    )
    polarization = sp.Matrix([px, py, pz])
    density = tau_dl * field.cross(field.cross(polarization)) + tau_fl * field.cross(
        polarization
    )
    force_integrand = sp.Matrix(
        [sp.simplify(delta * density.dot(tangent)) for tangent in tangents]
    )

    def integrate_symmetric(item: Any) -> Any:
        normalized = (
            sp.trigsimp(item, method="fu")
            .subs(polarity**2, 1)
            .subs(sp.tanh(xi) ** 2, 1 - sp.sech(xi) ** 2)
            .rewrite(sp.cosh)
            .subs(sp.cosh(2 * xi), 2 * sp.cosh(xi) ** 2 - 1)
            .subs(sp.sinh(2 * xi), 2 * sp.sinh(xi) * sp.cosh(xi))
        )
        normalized = sp.expand(sp.cancel(normalized))
        bases = (
            (1 / sp.cosh(xi), sp.integrate(1 / sp.cosh(xi), (xi, -sp.oo, sp.oo))),
            (
                1 / sp.cosh(xi) ** 2,
                sp.integrate(1 / sp.cosh(xi) ** 2, (xi, -sp.oo, sp.oo)),
            ),
            (
                1 / sp.cosh(xi) ** 3,
                sp.integrate(1 / sp.cosh(xi) ** 3, (xi, -sp.oo, sp.oo)),
            ),
        )
        values = []
        for term in sp.Add.make_args(normalized):
            if sp.simplify(term.subs(xi, -xi) + term) == 0:
                values.append(sp.Integer(0))
                continue
            matched = False
            for basis, integral in bases:
                coefficient = sp.simplify(term / basis)
                if not coefficient.has(xi):
                    values.append(coefficient * integral)
                    matched = True
                    break
            if not matched:
                raise ValueError(f"Unsupported wall-integration basis term: {term}")
        return sp.trigsimp(sum(values))

    metric = metric_integrand.applyfunc(integrate_symmetric)
    force = force_integrand.applyfunc(integrate_symmetric)
    coordinates = sp.symbols("u1:5", real=True)
    stiffness = sp.symbols("k", positive=True, real=True)
    energy = stiffness / 2 * sum(
        (coordinates[(index + 1) % 4] - coordinates[index]) ** 2 for index in range(4)
    )
    hessian = sp.hessian(energy, coordinates)
    metric_limits = [
        sp.simplify(sp.limit(item, xi, direction))
        for item in metric_integrand
        for direction in (-sp.oo, sp.oo)
    ]
    force_limits = [
        sp.simplify(sp.limit(item, xi, direction))
        for item in force_integrand
        for direction in (-sp.oo, sp.oo)
    ]
    return {
        "symbols": {
            "xi": xi,
            "Delta": delta,
            "Phi": phase,
            "polarity": polarity,
            "px": px,
            "py": py,
            "pz": pz,
            "tau_dl": tau_dl,
            "tau_fl": tau_fl,
        },
        "field": field,
        "metric": metric,
        "metric_integrand": metric_integrand,
        "force": force,
        "force_integrand": force_integrand,
        "hessian": hessian,
        "stiffness": stiffness,
        "metric_limits": metric_limits,
        "force_limits": force_limits,
    }


def _a4_numeric(sample: CrossEngineSample, mp: Any, *, tail_only: bool = False) -> list[Any]:
    values = sample.values
    delta = mp.mpf(str(values["Delta"]))
    phase = mp.mpf(str(values["Phi"]))
    polarity = mp.mpf(str(values["polarity"]))
    polarization = [
        mp.mpf(str(values["px"])),
        mp.mpf(str(values["py"])),
        mp.mpf(str(values["pz"])),
    ]
    tau_dl = mp.mpf(str(values["tau_dl"]))
    tau_fl = mp.mpf(str(values["tau_fl"]))

    def integrands(xi: Any) -> tuple[list[Any], list[Any]]:
        sech = 1 / mp.cosh(xi)
        tanh = mp.tanh(xi)
        field = [sech * mp.cos(phase), sech * mp.sin(phase), -polarity * tanh]
        derivative = [
            -sech * tanh * mp.cos(phase),
            -sech * tanh * mp.sin(phase),
            -polarity * sech**2,
        ]
        tangent_x = [-item / delta for item in derivative]
        tangent_phase = [-sech * mp.sin(phase), sech * mp.cos(phase), mp.mpf(0)]
        tangents = [tangent_x, tangent_phase]
        metric = [delta * _dot(left, right) for left in tangents for right in tangents]
        density_dl = _cross(field, _cross(field, polarization))
        density_fl = _cross(field, polarization)
        density = [
            tau_dl * left + tau_fl * right
            for left, right in zip(density_dl, density_fl, strict=True)
        ]
        force = [delta * _dot(density, tangent) for tangent in tangents]
        return metric, force

    if tail_only:
        output: list[Any] = []
        for location in (mp.mpf(-80), mp.mpf(80)):
            metric, force = integrands(location)
            output.extend(metric)
            output.extend(force)
        return output
    cache: dict[Any, tuple[list[Any], list[Any]]] = {}

    def cached_integrands(x: Any) -> tuple[list[Any], list[Any]]:
        if x not in cache:
            cache[x] = integrands(x)
        return cache[x]

    return [
        mp.quad(
            lambda x, index=index: cached_integrands(x)[0][index],
            [-mp.inf, 0, mp.inf],
        )
        for index in range(4)
    ] + [
        mp.quad(
            lambda x, index=index: cached_integrands(x)[1][index],
            [-mp.inf, 0, mp.inf],
        )
        for index in range(2)
    ]


@lru_cache(maxsize=1)
def _radial_symbolic() -> dict[str, Any]:
    sp, _ = _load_engines()
    r, phi = sp.symbols("r phi", positive=True, real=True)
    radius = sp.symbols("R", positive=True, real=True)
    helicity = sp.symbols("helicity", real=True)
    px, py, torque = sp.symbols("px py torque", real=True)
    sin_theta = 2 * radius**2 * r**2 / (r**4 + radius**4)
    cos_theta = (r**4 - radius**4) / (r**4 + radius**4)

    def texture(polarity: int) -> Any:
        return sp.Matrix(
            [
                sin_theta * sp.cos(phi + helicity),
                sin_theta * sp.sin(phi + helicity),
                polarity * cos_theta,
            ]
        )

    field = texture(1)
    radial = field.diff(r)
    angular = field.diff(phi)
    tangent_x = -(sp.cos(phi) * radial - sp.sin(phi) * angular / r)
    tangent_y = -(sp.sin(phi) * radial + sp.cos(phi) * angular / r)
    metric_angular = sp.Matrix(
        2,
        2,
        lambda i, j: sp.trigsimp(
            sp.integrate(
                r * (tangent_x, tangent_y)[i].dot((tangent_x, tangent_y)[j]),
                (phi, 0, 2 * sp.pi),
            )
        ),
    )
    metric = metric_angular.applyfunc(
        lambda item: sp.trigsimp(sp.integrate(item, (r, 0, sp.oo)))
    )
    topology_by_polarity: dict[int, Any] = {}
    force_by_polarity: dict[int, Any] = {}
    vector_identity_by_polarity: dict[int, bool] = {}
    polarization = sp.Matrix([px, py, 0])
    for polarity in (1, -1):
        candidate = texture(polarity)
        radial_candidate = candidate.diff(r)
        angular_candidate = candidate.diff(phi)
        candidate_tangent_x = -(
            sp.cos(phi) * radial_candidate - sp.sin(phi) * angular_candidate / r
        )
        candidate_tangent_y = -(
            sp.sin(phi) * radial_candidate + sp.cos(phi) * angular_candidate / r
        )
        topology_density = candidate.dot(radial_candidate.cross(angular_candidate))
        topology_by_polarity[polarity] = sp.simplify(
            sp.integrate(topology_density, (phi, 0, 2 * sp.pi), (r, 0, sp.oo))
            / (4 * sp.pi)
        )
        field_like = torque * candidate.cross(polarization)
        damping_like = torque * candidate.cross(candidate.cross(polarization))
        unit_constraint = sp.trigsimp(sp.cancel(candidate.dot(candidate) - 1)) == 0
        vector_identity_by_polarity[polarity] = unit_constraint and all(
            sp.trigsimp(
                sp.cancel(
                    damping_like.dot(candidate.cross(tangent))
                    - field_like.dot(tangent)
                )
            )
            == 0
            for tangent in (candidate_tangent_x, candidate_tangent_y)
        )
        force_components = []
        for tangent in (candidate_tangent_x, candidate_tangent_y):
            angular_density = sp.trigsimp(
                sp.integrate(r * field_like.dot(tangent), (phi, 0, 2 * sp.pi))
            )
            force_components.append(
                sp.trigsimp(sp.integrate(angular_density, (r, 0, sp.oo)))
            )
        force_by_polarity[polarity] = sp.Matrix(force_components)
    boundary_zero = (
        sp.limit(r * sin_theta, r, 0) == 0
        and sp.limit(r * sin_theta, r, sp.oo) == 0
    )
    return {
        "symbols": {
            "r": r,
            "phi": phi,
            "R": radius,
            "helicity": helicity,
            "px": px,
            "py": py,
            "torque": torque,
        },
        "metric": metric,
        "topology": topology_by_polarity,
        "force": force_by_polarity,
        "vector_identity": vector_identity_by_polarity,
        "boundary_zero": boundary_zero,
    }


def _periodic_angular_integral(mp: Any, function: Any, nodes: int = 32) -> Any:
    two_pi = 2 * mp.pi
    return two_pi / nodes * mp.fsum(
        function(two_pi * index / nodes) for index in range(nodes)
    )


def _radial_numeric_observables(
    sample: CrossEngineSample,
    mp: Any,
    *,
    force_kind: Literal["fm_damping_like", "afm_field_like"],
) -> list[Any]:
    values = sample.values
    radius = mp.mpf(str(values["R"]))
    helicity = mp.mpf(str(values["helicity"]))
    polarity = mp.mpf(str(values["polarity"]))
    px = mp.mpf(str(values["px"]))
    py = mp.mpf(str(values["py"]))
    torque_strength = mp.mpf(str(values["torque"]))
    polarization = [px, py, mp.mpf(0)]

    def geometry(r: Any, phi: Any) -> tuple[list[Any], list[Any], list[Any], list[Any], list[Any]]:
        if r == 0:
            r = mp.mpf("1e-100") * radius
        denominator = r**4 + radius**4
        sin_theta = 2 * radius**2 * r**2 / denominator
        cos_theta = (r**4 - radius**4) / denominator
        derivative_sin = 4 * radius**2 * r * (radius**4 - r**4) / denominator**2
        derivative_cos = 8 * radius**4 * r**3 / denominator**2
        angle = phi + helicity
        field = [
            sin_theta * mp.cos(angle),
            sin_theta * mp.sin(angle),
            polarity * cos_theta,
        ]
        radial = [
            derivative_sin * mp.cos(angle),
            derivative_sin * mp.sin(angle),
            polarity * derivative_cos,
        ]
        angular = [-sin_theta * mp.sin(angle), sin_theta * mp.cos(angle), mp.mpf(0)]
        tangent_x = [
            -(mp.cos(phi) * dr - mp.sin(phi) * da / r)
            for dr, da in zip(radial, angular, strict=True)
        ]
        tangent_y = [
            -(mp.sin(phi) * dr + mp.cos(phi) * da / r)
            for dr, da in zip(radial, angular, strict=True)
        ]
        return field, radial, angular, tangent_x, tangent_y

    angular_cache: dict[Any, list[Any]] = {}

    def angular_components(r: Any) -> list[Any]:
        if r in angular_cache:
            return angular_cache[r]

        def at(phi: Any) -> list[Any]:
            field, radial, angular, tangent_x, tangent_y = geometry(r, phi)
            metric = [
                r * _dot(tangent_x, tangent_x),
                r * _dot(tangent_x, tangent_y),
                r * _dot(tangent_y, tangent_y),
            ]
            topology = _dot(field, _cross(radial, angular)) / (4 * mp.pi)
            if force_kind == "fm_damping_like":
                density = [
                    torque_strength * item
                    for item in _cross(field, _cross(field, polarization))
                ]
                force = [
                    r * _dot(density, _cross(field, tangent_x)),
                    r * _dot(density, _cross(field, tangent_y)),
                ]
            else:
                density = [torque_strength * item for item in _cross(field, polarization)]
                force = [r * _dot(density, tangent_x), r * _dot(density, tangent_y)]
            return [topology, *metric, *force]

        two_pi = 2 * mp.pi
        angular_values = [at(two_pi * index / 32) for index in range(32)]
        result = [
            two_pi / 32 * mp.fsum(values[index] for values in angular_values)
            for index in range(6)
        ]
        angular_cache[r] = result
        return result

    radial_cache: dict[Any, list[Any]] = {}

    def finite_interval_components(t: Any) -> list[Any]:
        if t in radial_cache:
            return radial_cache[t]
        if t == 0 or t == 1:
            result = [mp.mpf(0)] * 6
        else:
            r = radius * t / (1 - t)
            jacobian = radius / (1 - t) ** 2
            result = [jacobian * item for item in angular_components(r)]
        radial_cache[t] = result
        return result

    return [
        mp.quadgl(
            lambda t, index=index: finite_interval_components(t)[index],
            [0, mp.mpf("0.5"), 1],
        )
        for index in range(6)
    ]


def _radial_references(
    sample: CrossEngineSample,
    digits: int,
    sp: Any,
    symbolic: dict[str, Any],
) -> list[str]:
    values = sample.values
    polarity = int(values["polarity"])
    symbols = symbolic["symbols"]
    substitutions = {
        symbols["R"]: sp.Float(str(values["R"]), digits),
        symbols["helicity"]: sp.Float(str(values["helicity"]), digits),
        symbols["px"]: sp.Float(str(values["px"]), digits),
        symbols["py"]: sp.Float(str(values["py"]), digits),
        symbols["torque"]: sp.Float(str(values["torque"]), digits),
    }
    expressions = [
        symbolic["topology"][polarity],
        symbolic["metric"][0, 0],
        symbolic["metric"][0, 1],
        symbolic["metric"][1, 1],
        symbolic["force"][polarity][0],
        symbolic["force"][polarity][1],
    ]
    return _sympy_values(sp, expressions, substitutions, digits)


def _radial_convergence(
    spec: CrossEngineSpec,
    sample: CrossEngineSample,
    sp: Any,
    mp: Any,
    symbolic: dict[str, Any],
    force_kind: Literal["fm_damping_like", "afm_field_like"],
) -> NumericConvergence:
    cache: dict[int, list[Any]] = {}

    def numeric(digits: int) -> list[Any]:
        if digits not in cache:
            cache[digits] = _radial_numeric_observables(sample, mp, force_kind=force_kind)
        return cache[digits]

    return _convergence(
        spec=spec,
        sample=sample,
        observables=["Q", "D_xx", "D_xy", "D_yy", "F_x", "F_y"],
        numeric=numeric,
        references=lambda digits: _radial_references(sample, digits, sp, symbolic),
        mp=mp,
    )


def _select_convergence(
    source: NumericConvergence,
    indices: list[int],
    observables: list[str],
) -> NumericConvergence:
    return NumericConvergence(
        sample_id=source.sample_id,
        observables=observables,
        points=[
            NumericPrecisionPoint(
                precision_digits=point.precision_digits,
                estimates=[point.estimates[index] for index in indices],
                references=[point.references[index] for index in indices],
                maximum_absolute_error=max(
                    (
                        str(
                            max(
                                Decimal(point.estimates[index])
                                - Decimal(point.references[index]),
                                Decimal(point.references[index])
                                - Decimal(point.estimates[index]),
                            )
                        )
                        for index in indices
                    ),
                    key=Decimal,
                ),
                maximum_successive_delta=point.maximum_successive_delta,
                within_tolerance=point.within_tolerance,
            )
            for point in source.points
        ],
        converged_at_final_precision=source.converged_at_final_precision,
    )


def _run_a4(spec: CrossEngineSpec, sp: Any, mp: Any) -> list[CrossEngineCheckResult]:
    symbolic = _a4_symbolic(sp)
    checks = {check.check_id: check for check in spec.checks}
    field = symbolic["field"]
    polarity = symbolic["symbols"]["polarity"]
    unit_passed = all(
        sp.trigsimp(field.dot(field).subs(polarity, sign)) == 1 for sign in (1, -1)
    )
    results = [
        _check_result(
            checks["a4_sympy_unit_constraint"],
            passed=unit_passed,
            symbolic_result=str(sp.trigsimp(field.dot(field).subs(polarity**2, 1))),
            detail="SymPy independently simplified the wall norm for both polarities.",
        )
    ]
    symbols = symbolic["symbols"]

    metric_convergence: list[NumericConvergence] = []
    force_convergence: list[NumericConvergence] = []
    limit_convergence: list[NumericConvergence] = []
    for sample in spec.samples:
        substitutions = {
            symbols[name]: sp.Float(str(sample.values[name]), spec.precision_digits[-1])
            for name in (
                "Delta",
                "Phi",
                "polarity",
                "px",
                "py",
                "pz",
                "tau_dl",
                "tau_fl",
            )
        }
        full = _convergence(
            spec=spec,
            sample=sample,
            observables=["g_xx", "g_xPhi", "g_PhiX", "g_PhiPhi", "F_x", "F_Phi"],
            numeric=lambda digits, sample=sample: _a4_numeric(sample, mp),
            references=lambda digits, substitutions=substitutions: _sympy_values(
                sp,
                [*symbolic["metric"], *symbolic["force"]],
                substitutions,
                digits,
            ),
            mp=mp,
        )
        metric_convergence.append(_select_convergence(full, [0, 1, 2, 3], full.observables[:4]))
        force_convergence.append(_select_convergence(full, [4, 5], full.observables[4:]))
        tail_observables = [
            "g_xx(-80)",
            "g_xPhi(-80)",
            "g_PhiX(-80)",
            "g_PhiPhi(-80)",
            "F_x(-80)",
            "F_Phi(-80)",
            "g_xx(+80)",
            "g_xPhi(+80)",
            "g_PhiX(+80)",
            "g_PhiPhi(+80)",
            "F_x(+80)",
            "F_Phi(+80)",
        ]
        limit_convergence.append(
            _convergence(
                spec=spec,
                sample=sample,
                observables=tail_observables,
                numeric=lambda digits, sample=sample: _a4_numeric(sample, mp, tail_only=True),
                references=lambda digits: ["0"] * len(tail_observables),
                mp=mp,
            )
        )
    metric_passed = not symbolic["metric"].has(sp.Integral) and all(
        item.converged_at_final_precision for item in metric_convergence
    )
    force_passed = not symbolic["force"].has(sp.Integral) and all(
        item.converged_at_final_precision for item in force_convergence
    )
    results.extend(
        [
            _check_result(
                checks["a4_wall_metric_coefficients"],
                passed=metric_passed,
                symbolic_result=str(symbolic["metric"]),
                convergence=metric_convergence,
                detail="Direct mpmath wall integrals converge to the SymPy-derived metric.",
            ),
            _check_result(
                checks["a4_sot_projection_coefficients"],
                passed=force_passed,
                symbolic_result=str(symbolic["force"]),
                convergence=force_convergence,
                detail="Direct torque-density quadrature converges to the independent SymPy projection.",
            ),
        ]
    )
    hessian = symbolic["hessian"]
    stiffness = symbolic["stiffness"]
    eigenvalues = hessian.eigenvals()
    hessian_passed = (
        hessian == hessian.T
        and hessian * sp.ones(4, 1) == sp.zeros(4, 1)
        and eigenvalues == {sp.Integer(0): 1, 2 * stiffness: 2, 4 * stiffness: 1}
    )
    results.append(
        _check_result(
            checks["a4_periodic_hessian_coefficients"],
            passed=hessian_passed,
            symbolic_result=str(hessian),
            detail="The independently differentiated periodic energy has one translation zero mode.",
        )
    )
    limit_passed = all(value == 0 for value in symbolic["metric_limits"] + symbolic["force_limits"]) and all(
        item.converged_at_final_precision for item in limit_convergence
    )
    results.append(
        _check_result(
            checks["a4_localization_limits"],
            passed=limit_passed,
            symbolic_result="all metric and SOT integrand limits are zero",
            convergence=limit_convergence,
            detail="Exact limits and high-precision finite-tail evaluations both vanish.",
        )
    )
    results.append(_not_applicable(checks["a4_terminal_equation_equivalence"]))
    return results


def _run_b1(spec: CrossEngineSpec, sp: Any, mp: Any) -> list[CrossEngineCheckResult]:
    symbolic = _radial_symbolic()
    checks = {check.check_id: check for check in spec.checks}
    convergence = [
        _radial_convergence(spec, sample, sp, mp, symbolic, "fm_damping_like")
        for sample in spec.samples
    ]
    topology = [_select_convergence(item, [0], ["Q"]) for item in convergence]
    metric = [
        _select_convergence(item, [1, 2, 3], ["D_xx", "D_xy", "D_yy"])
        for item in convergence
    ]
    force = [_select_convergence(item, [4, 5], ["F_x", "F_y"]) for item in convergence]
    topology_passed = symbolic["topology"] == {1: -1, -1: 1} and all(
        item.converged_at_final_precision for item in topology
    )
    metric_passed = symbolic["metric"] == 5 * sp.pi * sp.eye(2) and all(
        item.converged_at_final_precision for item in metric
    )
    results = [
        _check_result(
            checks["b1_topological_charge"],
            passed=topology_passed,
            symbolic_result=str(symbolic["topology"]),
            convergence=topology,
            detail="Direct polar quadrature reproduces Q=-polarity for the frozen localized profile.",
        ),
        _check_result(
            checks["b1_metric_coefficient"],
            passed=metric_passed,
            symbolic_result=str(symbolic["metric"]),
            convergence=metric,
            detail="The translational metric is isotropic with coefficient 5*pi.",
        ),
    ]
    spin = sp.symbols("s", positive=True, real=True)
    geometric_plus = 4 * sp.pi * symbolic["topology"][1]
    equation_plus = -spin * geometric_plus
    gyro_passed = geometric_plus == -4 * sp.pi and equation_plus == 4 * sp.pi * spin
    results.append(
        _check_result(
            checks["b1_gyrotropic_sign_bridge"],
            passed=gyro_passed,
            symbolic_result=(
                f"Ggeom_xy(p=+1)={geometric_plus}; Geq_xy=-s*Ggeom_xy={equation_plus}"
            ),
            detail="The equation tensor carries the declared minus sign relative to geometry.",
        )
    )
    force_passed = all(symbolic["vector_identity"].values()) and all(
        item.converged_at_final_precision for item in force
    )
    results.append(
        _check_result(
            checks["b1_damping_like_sot_projection"],
            passed=force_passed,
            symbolic_result=str(symbolic["force"]),
            convergence=force,
            detail="Vector-identity reduction and direct 2D quadrature agree for the LLG projection.",
        )
    )
    boundary_convergence = [
        _boundary_convergence(spec, sample, mp) for sample in spec.samples
    ]
    boundary_passed = symbolic["boundary_zero"] and all(
        item.converged_at_final_precision for item in boundary_convergence
    )
    results.append(
        _check_result(
            checks["b1_localized_field_like_boundary"],
            passed=boundary_passed,
            symbolic_result="limit r*sin(theta)=0 at r=0 and r=infinity",
            convergence=boundary_convergence,
            detail="The selected k=2 profile removes the translational field-like boundary term.",
        )
    )
    results.append(_not_applicable(checks["b1_full_thiele_equation_equivalence"]))
    return results


def _boundary_convergence(
    spec: CrossEngineSpec,
    sample: CrossEngineSample,
    mp: Any,
) -> NumericConvergence:
    radius_text = str(sample.values["R"])

    def numeric(digits: int) -> list[Any]:
        radius = mp.mpf(radius_text)
        small = radius * mp.power(10, -digits // 2)
        large = radius * mp.power(10, digits // 2)

        def radial_boundary(r: Any) -> Any:
            sin_theta = 2 * radius**2 * r**2 / (r**4 + radius**4)
            return r * sin_theta

        return [radial_boundary(small), radial_boundary(large)]

    return _convergence(
        spec=spec,
        sample=sample,
        observables=["r*sin(theta) near zero", "r*sin(theta) near infinity"],
        numeric=numeric,
        references=lambda digits: ["0", "0"],
        mp=mp,
    )


def _mass_convergence(
    spec: CrossEngineSpec,
    sample: CrossEngineSample,
    source: NumericConvergence,
    mp: Any,
) -> NumericConvergence:
    chi = mp.mpf(str(sample.values["chi"]))
    alpha = mp.mpf(str(sample.values["alpha"]))
    spin_density = mp.mpf(str(sample.values["spin_density"]))
    points: list[NumericPrecisionPoint] = []
    for point in source.points:
        metric_estimate = mp.mpf(point.estimates[1])
        metric_reference = mp.mpf(point.references[1])
        estimates = [chi * metric_estimate, alpha * spin_density * metric_estimate]
        references = [chi * metric_reference, alpha * spin_density * metric_reference]
        errors = [abs(a - b) for a, b in zip(estimates, references, strict=True)]
        points.append(
            NumericPrecisionPoint(
                precision_digits=point.precision_digits,
                estimates=[_mp_text(mp, item, point.precision_digits) for item in estimates],
                references=[_mp_text(mp, item, point.precision_digits) for item in references],
                maximum_absolute_error=_mp_text(mp, max(errors), point.precision_digits),
                maximum_successive_delta=point.maximum_successive_delta,
                within_tolerance=point.within_tolerance,
            )
        )
    return NumericConvergence(
        sample_id=sample.sample_id,
        observables=["M_xx=chi*D_xx", "Gamma_xx=alpha*s*D_xx"],
        points=points,
        converged_at_final_precision=source.converged_at_final_precision,
    )


def _run_b2(spec: CrossEngineSpec, sp: Any, mp: Any) -> list[CrossEngineCheckResult]:
    symbolic = _radial_symbolic()
    checks = {check.check_id: check for check in spec.checks}
    convergence = [
        _radial_convergence(spec, sample, sp, mp, symbolic, "afm_field_like")
        for sample in spec.samples
    ]
    topology = [_select_convergence(item, [0], ["Q[n]"]) for item in convergence]
    metric = [_mass_convergence(spec, sample, item, mp) for sample, item in zip(spec.samples, convergence, strict=True)]
    force = [_select_convergence(item, [4, 5], ["F_x", "F_y"]) for item in convergence]
    results = [
        _check_result(
            checks["b2_neel_topological_charge"],
            passed=symbolic["topology"] == {1: -1, -1: 1}
            and all(item.converged_at_final_precision for item in topology),
            symbolic_result=str(symbolic["topology"]),
            convergence=topology,
            detail="The Neel field, rather than total magnetization, carries Q=-polarity.",
        ),
        _check_result(
            checks["b2_metric_mass_damping_coefficients"],
            passed=symbolic["metric"] == 5 * sp.pi * sp.eye(2)
            and all(item.converged_at_final_precision for item in metric),
            symbolic_result="D=5*pi*I; M=chi*D; Gamma=alpha*s*D",
            convergence=metric,
            detail="Independent metric quadrature fixes the registered mass and damping scaling.",
        ),
        _check_result(
            checks["b2_field_like_sot_projection"],
            passed=all(item.converged_at_final_precision for item in force),
            symbolic_result=str(symbolic["force"]),
            convergence=force,
            detail="Direct sigma-model force-density quadrature agrees with SymPy projection.",
        ),
    ]
    boundary_convergence = [
        _boundary_convergence(spec, sample, mp) for sample in spec.samples
    ]
    results.append(
        _check_result(
            checks["b2_localized_damping_like_boundary"],
            passed=symbolic["boundary_zero"]
            and all(item.converged_at_final_precision for item in boundary_convergence),
            symbolic_result="limit r*sin(theta)=0 at r=0 and r=infinity",
            convergence=boundary_convergence,
            detail="The localized profile removes the total-derivative damping-like channel.",
        )
    )
    spin_a, spin_b = sp.symbols("s_A s_B", positive=True, real=True)
    gyro_a = 4 * sp.pi * symbolic["topology"][1]
    gyro_b = -gyro_a
    cancellation = sp.simplify((spin_a * gyro_a + spin_b * gyro_b).subs(spin_b, spin_a))
    results.append(
        _check_result(
            checks["b2_compensated_gyro_cancellation"],
            passed=cancellation == 0 and gyro_a == -gyro_b,
            symbolic_result=f"G_A={gyro_a}; G_B={gyro_b}; equal-spin sum={cancellation}",
            detail="Opposite sublattice tensors cancel only after the equal-spin substitution.",
        )
    )
    positive_mass = all(
        sample.values["chi"] > 0
        and all(Decimal(point.estimates[0]) > 0 for point in item.points)
        for sample, item in zip(spec.samples, metric, strict=True)
    )
    results.append(
        _check_result(
            checks["b2_inertial_mass_positive"],
            passed=positive_mass and all(item.converged_at_final_precision for item in metric),
            symbolic_result="M_xx=5*pi*chi > 0 for chi > 0",
            convergence=metric,
            detail="All frozen positive-susceptibility samples yield a positive inertial mass.",
        )
    )
    results.append(_not_applicable(checks["b2_full_inertial_equation_equivalence"]))
    return results


def _render_route_summary(result: CrossEngineRouteResult) -> str:
    lines = [
        f"# Cross-engine result: {result.case_id}",
        "",
        f"- Route: `{result.route_id}`",
        f"- Status: `{result.execution_status}`",
        f"- SymPy: `{result.engine.symbolic_engine_version}`",
        f"- mpmath: `{result.engine.numeric_engine_version}`",
        f"- Precision digits: `{result.engine.precision_digits}`",
        f"- Absolute / relative tolerance: `{result.engine.absolute_tolerance}` / "
        f"`{result.engine.relative_tolerance}`",
        "",
        "## Checks",
        "",
        "| Check | Category | Method | Status | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in result.checks:
        lines.append(
            f"| `{check.check_id}` | `{check.category}` | `{check.method}` | "
            f"`{check.status}` | {check.detail} |"
        )
    lines.extend(
        [
            "",
            "## Independence boundary",
            "",
            "The executed input inventory contains only the frozen cross-engine spec. "
            "Generated and independent Wolfram artifacts are prohibited inputs.",
            "",
            "`not_applicable` checks are excluded from both pass and fail counts and do not "
            "support a terminal-equation equivalence claim.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_suite_summary(result: CrossEngineSuiteResult) -> str:
    lines = [
        "# Core-three cross-engine validation",
        "",
        f"- Status: `{'passed' if result.passed else 'failed'}`",
        f"- Routes: `{result.passed_route_count}/{result.route_count}` passed",
        f"- Checks: `{result.passed_check_count}` passed, `{result.failed_check_count}` failed, "
        f"`{result.not_applicable_check_count}` not applicable",
        "",
        "| Route | Status | Passed | Failed | N/A |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for route in result.routes:
        lines.append(
            f"| `{route.route_id}` | `{route.execution_status}` | "
            f"{route.passed_check_count} | {route.failed_check_count} | "
            f"{route.not_applicable_check_count} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _run_spec(
    spec_path: Path,
    spec: CrossEngineSpec,
    build_dir: Path,
    published_dir: Path,
    sp: Any,
    mp: Any,
) -> CrossEngineRouteResult:
    route_dir = build_dir / spec.case_id
    published_route_dir = published_dir / spec.case_id
    route_dir.mkdir(parents=True)
    dispatch = {
        "afm_stripe_sot_full": _run_a4,
        "fm_skyrmion_sot_full": _run_b1,
        "afm_skyrmion_sot_full": _run_b2,
    }
    checks = dispatch[spec.route_id](spec, sp, mp)
    if tuple(check.check_id for check in checks) != EXPECTED_CHECK_IDS[spec.route_id]:
        raise ValueError(f"Executed checks drift from the frozen contract for {spec.route_id}")
    passed_count = sum(check.status == "passed" for check in checks)
    failed_count = sum(check.status == "failed" for check in checks)
    not_applicable_count = sum(check.status == "not_applicable" for check in checks)
    passed = failed_count == 0 and all(
        check.status == "passed" for check in checks if check.required
    )
    result_path = route_dir / "cross_engine_result.json"
    summary_path = route_dir / "cross_engine_summary.md"
    result = CrossEngineRouteResult(
        spec_id=spec.spec_id,
        case_id=spec.case_id,
        route_id=spec.route_id,
        claim_scope=spec.claim_scope,
        execution_status="passed" if passed else "failed",
        passed=passed,
        executed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        engine=EngineMetadata(
            python_version=platform.python_version(),
            symbolic_engine_version=sp.__version__,
            numeric_engine_version=mp.__version__,
            angular_nodes=32,
            precision_digits=spec.precision_digits,
            absolute_tolerance=spec.absolute_tolerance,
            relative_tolerance=spec.relative_tolerance,
        ),
        input_artifacts=[_artifact(spec_path)],
        prohibited_input_artifacts=spec.independence.prohibited_input_artifacts,
        runner_artifact=_artifact(RUNNER_PATH),
        checks=checks,
        passed_check_count=passed_count,
        failed_check_count=failed_count,
        not_applicable_check_count=not_applicable_count,
        result_path=_stored_path(published_route_dir / result_path.name),
        summary_path=_stored_path(published_route_dir / summary_path.name),
    )
    result_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(_render_route_summary(result), encoding="utf-8")
    return result


def run_cross_engine_suite(
    specs_path: str | Path = DEFAULT_CORE3_SPECS,
    out_dir: str | Path = DEFAULT_CORE3_OUTPUT,
) -> CrossEngineSuiteResult:
    specs = load_cross_engine_specs(specs_path)
    if {spec.route_id for _, spec in specs} != set(EXPECTED_CHECK_IDS):
        raise ValueError("Core-three cross-engine suite requires exactly the three frozen routes")
    destination = _project_path(out_dir)
    if destination.exists():
        raise FileExistsError(
            f"Cross-engine output already exists: {destination}. Evidence runs are never overwritten."
        )
    sp, mp = _load_engines()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}.", dir=destination.parent) as temp:
        build_dir = Path(temp) / destination.name
        build_dir.mkdir()
        routes = [
            _run_spec(path, spec, build_dir, destination, sp, mp)
            for path, spec in specs
        ]
        passed_routes = sum(route.passed for route in routes)
        passed = passed_routes == len(routes)
        result_path = build_dir / "cross_engine_suite.json"
        summary_path = build_dir / "cross_engine_suite.md"
        suite = CrossEngineSuiteResult(
            execution_status="passed" if passed else "failed",
            passed=passed,
            route_count=len(routes),
            passed_route_count=passed_routes,
            failed_route_count=len(routes) - passed_routes,
            passed_check_count=sum(route.passed_check_count for route in routes),
            failed_check_count=sum(route.failed_check_count for route in routes),
            not_applicable_check_count=sum(
                route.not_applicable_check_count for route in routes
            ),
            routes=routes,
            result_path=_stored_path(destination / result_path.name),
            summary_path=_stored_path(destination / summary_path.name),
        )
        result_path.write_text(
            json.dumps(suite.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary_path.write_text(_render_suite_summary(suite), encoding="utf-8")
        if destination.exists():
            raise FileExistsError(f"Cross-engine output appeared during execution: {destination}")
        shutil.move(str(build_dir), str(destination))
    return CrossEngineSuiteResult.model_validate_json(
        (destination / "cross_engine_suite.json").read_text(encoding="utf-8")
    )


def verify_cross_engine_result(
    result_path: str | Path,
    *,
    expected_route_id: str | None = None,
) -> CrossEngineVerification:
    path = _project_path(result_path)
    if not path.is_file():
        raise FileNotFoundError(f"Cross-engine result does not exist: {path}")
    result = CrossEngineRouteResult.model_validate_json(path.read_text(encoding="utf-8"))
    issues: list[str] = []
    if result.result_path != _stored_path(path):
        issues.append("cross-engine result path does not match its published location")
    expected_summary_path = path.with_name("cross_engine_summary.md")
    if result.summary_path != _stored_path(expected_summary_path):
        issues.append("cross-engine summary path does not match its published location")
    elif not expected_summary_path.is_file():
        issues.append("cross-engine summary artifact is missing")
    if expected_route_id is not None and result.route_id != expected_route_id:
        issues.append("cross-engine route identity mismatch")
    if result.execution_status != "passed" or not result.passed:
        issues.append("cross-engine execution did not pass")
    if result.engine.symbolic_engine != "sympy" or result.engine.numeric_engine != "mpmath":
        issues.append("cross-engine result does not identify the registered engines")
    if len(result.input_artifacts) != 1:
        issues.append("cross-engine result must have exactly one executed input artifact")
        spec = None
    else:
        input_artifact = result.input_artifacts[0]
        input_path = _project_path(input_artifact.path)
        if not input_path.is_file() or _sha256(input_path) != input_artifact.sha256:
            issues.append("cross-engine spec artifact hash drift")
            spec = None
        else:
            try:
                spec = CrossEngineSpec.from_yaml(input_path)
            except ValueError as exc:
                issues.append(f"cross-engine spec is invalid: {exc}")
                spec = None
    runner_path = _project_path(result.runner_artifact.path)
    if not runner_path.is_file() or _sha256(runner_path) != result.runner_artifact.sha256:
        issues.append("cross-engine runner artifact hash drift")
    if spec is not None:
        if (
            spec.spec_id != result.spec_id
            or spec.case_id != result.case_id
            or spec.route_id != result.route_id
        ):
            issues.append("cross-engine result identity drifts from its spec")
        if result.input_artifacts[0].path not in spec.independence.allowed_input_artifacts:
            issues.append("executed input is not authorized by the independence contract")
        if result.prohibited_input_artifacts != spec.independence.prohibited_input_artifacts:
            issues.append("prohibited-input inventory drifts from the spec")
        if set(item.path for item in result.input_artifacts) & set(
            spec.independence.prohibited_input_artifacts
        ):
            issues.append("cross-engine execution consumed a prohibited artifact")
        if tuple(check.check_id for check in result.checks) != tuple(
            check.check_id for check in spec.checks
        ):
            issues.append("executed check inventory drifts from the spec")
    required = [check for check in result.checks if check.required]
    if not required or any(check.status != "passed" for check in required):
        issues.append("not all required cross-engine checks passed")
    if not any(check.method == "sympy_exact" for check in required):
        issues.append("cross-engine result lacks an exact symbolic check")
    hybrid = [check for check in required if check.method == "sympy_plus_mpmath"]
    if not hybrid:
        issues.append("cross-engine result lacks a high-precision numerical check")
    elif any(
        not convergence.converged_at_final_precision
        for check in hybrid
        for convergence in check.convergence
    ):
        issues.append("cross-engine result contains unconverged numerical evidence")
    if any(
        check.status == "not_applicable" and (check.required or check.method != "not_applicable")
        for check in result.checks
    ):
        issues.append("not_applicable check semantics are invalid")
    return CrossEngineVerification(
        route_id=result.route_id,
        eligible_for_cross_engine_pass=not issues,
        passed_check_count=result.passed_check_count,
        not_applicable_check_count=result.not_applicable_check_count,
        issues=issues,
    )
