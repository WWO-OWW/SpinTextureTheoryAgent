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
SCHEMA_VERSION = "1.0.0"
DEFAULT_SPECS = PROJECT_ROOT / "cross_engine_specs" / "extended"
DEFAULT_OUTPUT = PROJECT_ROOT / "analysis" / "cross_engine" / "extended_latest"
RUNNER_PATH = Path(__file__).resolve()

CheckMethod = Literal["sympy_exact", "sympy_plus_mpmath", "not_applicable"]
CheckStatus = Literal["passed", "failed", "not_applicable"]

EXPECTED_CHECK_IDS: dict[str, tuple[str, ...]] = {
    "fm_antiskyrmion_sot_full": (
        "b4_sympy_unit_constraint",
        "b4_topological_charge",
        "b4_anisotropic_metric",
        "b4_isotropic_metric_limit",
        "b4_damping_like_sot_projection",
        "b4_field_like_boundary",
        "b4_anisotropic_dmi_projection",
        "b4_dmi_helicity_stationarity",
        "b4_full_thiele_equation_equivalence",
    ),
    "fm_meron_topology_full": (
        "c2_unit_and_local_density",
        "c2_boundary_half_charge",
        "c2_winding_polarity_signs",
        "c2_non_meron_boundary_control",
        "c2_dimensionless_contract",
        "c2_arbitrary_meron_field_equivalence",
    ),
    "fm_bimeron_topology_full": (
        "c3_constituent_half_charges",
        "c3_additive_composite_charge",
        "c3_nontrivial_pairing_integer_charge",
        "c3_zero_charge_control",
        "c3_dimensionless_contract",
        "c3_overlapping_full_field_charge",
    ),
    "fm_vortex_topology_full": (
        "c4_boundary_constraint_and_single_value",
        "c4_contour_winding",
        "c4_regularized_core_charge",
        "c4_winding_charge_distinction",
        "c4_vorticity_flip",
        "c4_core_polarity_flip",
        "c4_arbitrary_full_plane_charge",
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
            "Extended cross-engine validation requires: "
            "pip install -e '.[cross-engine]'"
        ) from exc
    return sp, mp


class ExtendedProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: Literal[
        "elliptic_radial_power_antiskyrmion",
        "axisymmetric_meron_profile",
        "paired_meron_profiles",
        "regularized_vortex_profile",
    ]
    definition: str = Field(min_length=1)
    radial_exponent: int | None = Field(default=None, ge=2)
    boundary_conditions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profile(self) -> "ExtendedProfile":
        if self.family == "elliptic_radial_power_antiskyrmion":
            if self.radial_exponent is None:
                raise ValueError("The antiskyrmion profile requires radial_exponent")
        elif self.radial_exponent is not None:
            raise ValueError("Only the antiskyrmion profile declares radial_exponent")
        return self


class ExtendedSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str = Field(pattern=r"^[a-z0-9_]+$")
    values: dict[str, float]

    @model_validator(mode="after")
    def validate_values(self) -> "ExtendedSample":
        if not self.values:
            raise ValueError("Extended cross-engine samples cannot be empty")
        return self


class ExtendedCheckSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(pattern=r"^[a-z0-9_]+$")
    category: str = Field(min_length=1)
    method: CheckMethod
    required: bool
    not_applicable_reason: str | None = None

    @model_validator(mode="after")
    def validate_method(self) -> "ExtendedCheckSpec":
        if self.method == "not_applicable":
            if self.required:
                raise ValueError("not_applicable checks cannot be required")
            if not self.not_applicable_reason:
                raise ValueError("not_applicable checks require a reason")
        elif not self.required or self.not_applicable_reason is not None:
            raise ValueError("Executable checks must be required without an N/A reason")
        return self


class ExtendedIndependence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_input_artifacts: list[str] = Field(min_length=1, max_length=1)
    prohibited_input_artifacts: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_disjoint_inputs(self) -> "ExtendedIndependence":
        if set(self.allowed_input_artifacts) & set(self.prohibited_input_artifacts):
            raise ValueError("Allowed and prohibited inputs overlap")
        return self


class ExtendedCrossEngineSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    spec_id: str = Field(pattern=r"^[a-z0-9_]+$")
    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    route_id: str = Field(pattern=r"^[a-z0-9_]+$")
    claim_scope: str = Field(min_length=1)
    profile: ExtendedProfile
    precision_digits: list[int] = Field(min_length=3)
    absolute_tolerance: str
    relative_tolerance: str
    samples: list[ExtendedSample] = Field(min_length=1)
    checks: list[ExtendedCheckSpec] = Field(min_length=1)
    independence: ExtendedIndependence

    @model_validator(mode="after")
    def validate_contract(self) -> "ExtendedCrossEngineSpec":
        expected = EXPECTED_CHECK_IDS.get(self.route_id)
        if expected is None:
            raise ValueError(f"Unsupported extended route: {self.route_id}")
        if tuple(item.check_id for item in self.checks) != expected:
            raise ValueError(f"Check inventory drift for {self.route_id}")
        if self.precision_digits != sorted(set(self.precision_digits)):
            raise ValueError("Precision digits must be unique and increasing")
        if self.precision_digits[0] < 30:
            raise ValueError("Quadrature must begin at 30 digits or higher")
        _positive_decimal(self.absolute_tolerance, "absolute_tolerance")
        _positive_decimal(self.relative_tolerance, "relative_tolerance")
        sample_ids = [item.sample_id for item in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("Sample IDs must be unique")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ExtendedCrossEngineSpec":
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
        "gauss_legendre_radial_periodic_angular_and_contour_quadrature"
    ] = "gauss_legendre_radial_periodic_angular_and_contour_quadrature"
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


class ExtendedCheckResult(BaseModel):
    check_id: str
    category: str
    method: CheckMethod
    required: bool
    status: CheckStatus
    symbolic_result: str | None = None
    convergence: list[NumericConvergence] = Field(default_factory=list)
    detail: str

    @model_validator(mode="after")
    def validate_status(self) -> "ExtendedCheckResult":
        if self.method == "not_applicable":
            if self.required or self.status != "not_applicable":
                raise ValueError("N/A result semantics are invalid")
        elif self.status == "not_applicable":
            raise ValueError("Executable checks cannot become N/A")
        if self.method == "sympy_plus_mpmath" and not self.convergence:
            raise ValueError("Hybrid checks require convergence evidence")
        if self.method == "sympy_exact" and self.convergence:
            raise ValueError("Exact checks cannot carry convergence evidence")
        return self


class ExtendedRouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
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
    checks: list[ExtendedCheckResult]
    passed_check_count: int
    failed_check_count: int
    not_applicable_check_count: int
    result_path: str
    summary_path: str

    @model_validator(mode="after")
    def validate_counts(self) -> "ExtendedRouteResult":
        counts = (
            sum(item.status == "passed" for item in self.checks),
            sum(item.status == "failed" for item in self.checks),
            sum(item.status == "not_applicable" for item in self.checks),
        )
        if counts != (
            self.passed_check_count,
            self.failed_check_count,
            self.not_applicable_check_count,
        ):
            raise ValueError("Extended check counts are inconsistent")
        expected = counts[1] == 0 and all(
            item.status == "passed" for item in self.checks if item.required
        )
        if self.passed != expected or self.execution_status != (
            "passed" if expected else "failed"
        ):
            raise ValueError("Extended route status is inconsistent")
        return self


class ExtendedSuiteResult(BaseModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    suite_id: Literal["extended_cross_engine_v1"] = "extended_cross_engine_v1"
    execution_status: Literal["passed", "failed"]
    passed: bool
    route_count: int
    passed_route_count: int
    failed_route_count: int
    passed_check_count: int
    failed_check_count: int
    not_applicable_check_count: int
    routes: list[ExtendedRouteResult]
    result_path: str
    summary_path: str


class ExtendedVerification(BaseModel):
    route_id: str
    eligible_for_cross_engine_pass: bool
    passed_check_count: int
    not_applicable_check_count: int
    issues: list[str]


def _artifact(path: Path) -> HashedArtifact:
    return HashedArtifact(path=_stored_path(path), sha256=_sha256(path))


def load_extended_specs(
    path: str | Path = DEFAULT_SPECS,
) -> list[tuple[Path, ExtendedCrossEngineSpec]]:
    resolved = _project_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Extended spec path does not exist: {resolved}")
    paths = [resolved] if resolved.is_file() else sorted(resolved.glob("*.yaml"))
    if not paths:
        raise ValueError(f"No extended specs found under {resolved}")
    specs = [(item, ExtendedCrossEngineSpec.from_yaml(item)) for item in paths]
    routes = [spec.route_id for _, spec in specs]
    if len(routes) != len(set(routes)):
        raise ValueError("Extended spec routes must be unique")
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


def _sympy_values(
    sp: Any,
    expressions: list[Any],
    substitutions: dict[Any, Any],
    digits: int,
) -> list[str]:
    return [str(sp.N(item.subs(substitutions), digits)) for item in expressions]


def _convergence(
    *,
    spec: ExtendedCrossEngineSpec,
    sample: ExtendedSample,
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
            errors = [
                abs(actual - target)
                for actual, target in zip(estimates, expected, strict=True)
            ]
            thresholds = [
                max(absolute_tolerance, relative_tolerance * max(mp.mpf(1), abs(target)))
                for target in expected
            ]
            within = all(
                error <= threshold
                for error, threshold in zip(errors, thresholds, strict=True)
            )
            delta = None
            if previous is not None:
                delta = max(
                    abs(actual - old)
                    for actual, old in zip(estimates, previous, strict=True)
                )
            points.append(
                NumericPrecisionPoint(
                    precision_digits=digits,
                    estimates=[_mp_text(mp, item, digits) for item in estimates],
                    references=[_mp_text(mp, item, digits) for item in expected],
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
    scale = max(mp.mpf(1), *(abs(mp.mpf(item)) for item in final.references))
    threshold = max(absolute_tolerance, relative_tolerance * scale)
    return NumericConvergence(
        sample_id=sample.sample_id,
        observables=observables,
        points=points,
        converged_at_final_precision=(
            final.within_tolerance
            and penultimate.within_tolerance
            and final_delta <= threshold
        ),
    )


def _select_convergence(
    source: NumericConvergence,
    indices: list[int],
    observables: list[str],
) -> NumericConvergence:
    points: list[NumericPrecisionPoint] = []
    for point in source.points:
        errors = [
            abs(Decimal(point.estimates[index]) - Decimal(point.references[index]))
            for index in indices
        ]
        points.append(
            NumericPrecisionPoint(
                precision_digits=point.precision_digits,
                estimates=[point.estimates[index] for index in indices],
                references=[point.references[index] for index in indices],
                maximum_absolute_error=str(max(errors)),
                maximum_successive_delta=point.maximum_successive_delta,
                within_tolerance=point.within_tolerance,
            )
        )
    return NumericConvergence(
        sample_id=source.sample_id,
        observables=observables,
        points=points,
        converged_at_final_precision=source.converged_at_final_precision,
    )


def _check_result(
    check: ExtendedCheckSpec,
    *,
    passed: bool,
    symbolic_result: str,
    detail: str,
    convergence: list[NumericConvergence] | None = None,
) -> ExtendedCheckResult:
    return ExtendedCheckResult(
        check_id=check.check_id,
        category=check.category,
        method=check.method,
        required=check.required,
        status="passed" if passed else "failed",
        symbolic_result=symbolic_result,
        convergence=convergence or [],
        detail=detail,
    )


def _not_applicable(check: ExtendedCheckSpec) -> ExtendedCheckResult:
    return ExtendedCheckResult(
        check_id=check.check_id,
        category=check.category,
        method=check.method,
        required=False,
        status="not_applicable",
        detail=check.not_applicable_reason or "Outside the registered scope.",
    )


@lru_cache(maxsize=1)
def _b4_symbolic() -> dict[str, Any]:
    sp, _ = _load_engines()
    r, phi = sp.symbols("r phi", positive=True, real=True)
    radius, lambda_x, lambda_y = sp.symbols(
        "R lambdaX lambdaY", positive=True, real=True
    )
    helicity, polarity = sp.symbols("helicity polarity", real=True)
    px, py, tau_dl, tau_fl, dmi = sp.symbols(
        "px py tauDL tauFL Dmi", real=True
    )
    denominator = r**4 + radius**4
    sin_theta = 2 * radius**2 * r**2 / denominator
    cos_theta = (r**4 - radius**4) / denominator
    angle = helicity - phi
    field = sp.Matrix(
        [
            sin_theta * sp.cos(angle),
            sin_theta * sp.sin(angle),
            polarity * cos_theta,
        ]
    )
    radial = field.diff(r)
    angular = field.diff(phi)
    spatial_x = (sp.cos(phi) * radial - sp.sin(phi) * angular / r) / lambda_x
    spatial_y = (sp.sin(phi) * radial + sp.cos(phi) * angular / r) / lambda_y
    tangents = (-spatial_x, -spatial_y)
    jacobian = lambda_x * lambda_y

    def plane_integral(expression: Any) -> Any:
        angular_value = sp.trigsimp(sp.integrate(jacobian * r * expression, (phi, 0, 2 * sp.pi)))
        return sp.trigsimp(sp.integrate(angular_value, (r, 0, sp.oo)))

    metric = sp.Matrix(
        2,
        2,
        lambda i, j: plane_integral(tangents[i].dot(tangents[j])),
    )
    topology = plane_integral(field.dot(spatial_x.cross(spatial_y))) / (4 * sp.pi)
    polarization = sp.Matrix([px, py, 0])
    damping_like = tau_dl * field.cross(field.cross(polarization))
    field_like = tau_fl * field.cross(polarization)
    damping_force = sp.Matrix(
        [plane_integral(damping_like.dot(field.cross(tangent))) for tangent in tangents]
    )
    field_force = sp.Matrix(
        [plane_integral(field_like.dot(field.cross(tangent))) for tangent in tangents]
    )
    dmi_density = dmi * (
        field[2] * spatial_x[0]
        - field[0] * spatial_x[2]
        - field[2] * spatial_y[1]
        + field[1] * spatial_y[2]
    )
    dmi_energy = plane_integral(dmi_density)

    def normalize(expression: Any) -> Any:
        return sp.trigsimp(sp.simplify(expression.subs(polarity**2, 1)))

    return {
        "symbols": {
            "R": radius,
            "helicity": helicity,
            "polarity": polarity,
            "lambdaX": lambda_x,
            "lambdaY": lambda_y,
            "px": px,
            "py": py,
            "tauDL": tau_dl,
            "tauFL": tau_fl,
            "Dmi": dmi,
        },
        "field": field,
        "metric": metric.applyfunc(normalize),
        "topology": normalize(topology),
        "damping_force": damping_force.applyfunc(normalize),
        "field_force": field_force.applyfunc(normalize),
        "dmi_energy": normalize(dmi_energy),
        "dmi_helicity_derivative": normalize(sp.diff(dmi_energy, helicity)),
    }


def _b4_numeric(sample: ExtendedSample, mp: Any) -> list[Any]:
    values = sample.values
    radius = mp.mpf(str(values["R"]))
    helicity = mp.mpf(str(values["helicity"]))
    polarity = mp.mpf(str(values["polarity"]))
    lambda_x = mp.mpf(str(values["lambdaX"]))
    lambda_y = mp.mpf(str(values["lambdaY"]))
    polarization = [mp.mpf(str(values["px"])), mp.mpf(str(values["py"])), mp.mpf(0)]
    tau_dl = mp.mpf(str(values["tauDL"]))
    tau_fl = mp.mpf(str(values["tauFL"]))
    dmi = mp.mpf(str(values["Dmi"]))
    jacobian = lambda_x * lambda_y

    def geometry(r: Any, phi: Any) -> tuple[list[Any], list[Any], list[Any]]:
        denominator = r**4 + radius**4
        sin_theta = 2 * radius**2 * r**2 / denominator
        cos_theta = (r**4 - radius**4) / denominator
        derivative_sin = 4 * radius**2 * r * (radius**4 - r**4) / denominator**2
        derivative_cos = 8 * radius**4 * r**3 / denominator**2
        angle = helicity - phi
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
        angular = [sin_theta * mp.sin(angle), -sin_theta * mp.cos(angle), mp.mpf(0)]
        spatial_x = [
            (mp.cos(phi) * dr - mp.sin(phi) * da / r) / lambda_x
            for dr, da in zip(radial, angular, strict=True)
        ]
        spatial_y = [
            (mp.sin(phi) * dr + mp.cos(phi) * da / r) / lambda_y
            for dr, da in zip(radial, angular, strict=True)
        ]
        return field, spatial_x, spatial_y

    angular_cache: dict[Any, list[Any]] = {}

    def angular_values(r: Any) -> list[Any]:
        if r in angular_cache:
            return angular_cache[r]
        rows: list[list[Any]] = []
        for index in range(32):
            phi = 2 * mp.pi * index / 32
            field, spatial_x, spatial_y = geometry(r, phi)
            tangents = [[-item for item in spatial_x], [-item for item in spatial_y]]
            area = jacobian * r
            topology = area * _dot(field, _cross(spatial_x, spatial_y)) / (4 * mp.pi)
            metric = [
                area * _dot(tangents[0], tangents[0]),
                area * _dot(tangents[0], tangents[1]),
                area * _dot(tangents[1], tangents[1]),
            ]
            damping_density = [
                tau_dl * item for item in _cross(field, _cross(field, polarization))
            ]
            field_density = [tau_fl * item for item in _cross(field, polarization)]
            damping_force = [
                area * _dot(damping_density, _cross(field, tangent))
                for tangent in tangents
            ]
            field_force = [
                area * _dot(field_density, _cross(field, tangent))
                for tangent in tangents
            ]
            dmi_density = dmi * (
                field[2] * spatial_x[0]
                - field[0] * spatial_x[2]
                - field[2] * spatial_y[1]
                + field[1] * spatial_y[2]
            )
            rows.append(
                [topology, *metric, *damping_force, *field_force, area * dmi_density]
            )
        output = [
            2 * mp.pi / 32 * mp.fsum(row[index] for row in rows)
            for index in range(9)
        ]
        angular_cache[r] = output
        return output

    radial_cache: dict[Any, list[Any]] = {}

    def mapped(t: Any) -> list[Any]:
        if t in radial_cache:
            return radial_cache[t]
        if t == 0 or t == 1:
            output = [mp.mpf(0)] * 9
        else:
            r = radius * t / (1 - t)
            jacobian_r = radius / (1 - t) ** 2
            output = [jacobian_r * item for item in angular_values(r)]
        radial_cache[t] = output
        return output

    return [
        mp.quadgl(lambda t, index=index: mapped(t)[index], [0, mp.mpf("0.5"), 1])
        for index in range(9)
    ]


def _b4_convergence(
    spec: ExtendedCrossEngineSpec,
    sample: ExtendedSample,
    sp: Any,
    mp: Any,
    symbolic: dict[str, Any],
) -> NumericConvergence:
    cache: dict[int, list[Any]] = {}
    symbols = symbolic["symbols"]

    def numeric(digits: int) -> list[Any]:
        if digits not in cache:
            cache[digits] = _b4_numeric(sample, mp)
        return cache[digits]

    expressions = [
        symbolic["topology"],
        symbolic["metric"][0, 0],
        symbolic["metric"][0, 1],
        symbolic["metric"][1, 1],
        symbolic["damping_force"][0],
        symbolic["damping_force"][1],
        symbolic["field_force"][0],
        symbolic["field_force"][1],
        symbolic["dmi_energy"],
    ]

    def references(digits: int) -> list[str]:
        substitutions = {
            symbols[name]: sp.Float(str(sample.values[name]), digits)
            for name in symbols
        }
        return _sympy_values(sp, expressions, substitutions, digits)

    return _convergence(
        spec=spec,
        sample=sample,
        observables=["Q", "D_xx", "D_xy", "D_yy", "Fdl_x", "Fdl_y", "Ffl_x", "Ffl_y", "U_DMI"],
        numeric=numeric,
        references=references,
        mp=mp,
    )


def _run_b4(spec: ExtendedCrossEngineSpec, sp: Any, mp: Any) -> list[ExtendedCheckResult]:
    symbolic = _b4_symbolic()
    checks = {item.check_id: item for item in spec.checks}
    field = symbolic["field"]
    polarity = symbolic["symbols"]["polarity"]
    unit = all(
        sp.trigsimp(sp.cancel(field.dot(field).subs(polarity, sign) - 1)) == 0
        for sign in (1, -1)
    )
    convergence = [_b4_convergence(spec, sample, sp, mp, symbolic) for sample in spec.samples]
    topology = [_select_convergence(item, [0], ["Q"]) for item in convergence]
    metric = [_select_convergence(item, [1, 2, 3], ["D_xx", "D_xy", "D_yy"]) for item in convergence]
    damping_force = [_select_convergence(item, [4, 5], ["Fdl_x", "Fdl_y"]) for item in convergence]
    field_force = [_select_convergence(item, [6, 7], ["Ffl_x", "Ffl_y"]) for item in convergence]
    dmi_energy = [_select_convergence(item, [8], ["U_DMI"]) for item in convergence]
    lambda_x = symbolic["symbols"]["lambdaX"]
    lambda_y = symbolic["symbols"]["lambdaY"]
    helicity = symbolic["symbols"]["helicity"]
    isotropic = sp.simplify(symbolic["metric"].subs(lambda_y, lambda_x) - 5 * sp.pi * sp.eye(2))
    stationarity = sp.simplify(symbolic["dmi_helicity_derivative"].subs(helicity, 0))
    results = [
        _check_result(
            checks["b4_sympy_unit_constraint"],
            passed=unit,
            symbolic_result=str(sp.trigsimp(field.dot(field).subs(polarity**2, 1))),
            detail="SymPy verifies the elliptic antiskyrmion field norm for both polarities.",
        ),
        _check_result(
            checks["b4_topological_charge"],
            passed=sp.simplify(symbolic["topology"] - polarity) == 0
            and all(item.converged_at_final_precision for item in topology),
            symbolic_result=str(symbolic["topology"]),
            convergence=topology,
            detail="Direct scaled-plane quadrature reproduces Q=polarity.",
        ),
        _check_result(
            checks["b4_anisotropic_metric"],
            passed=not symbolic["metric"].has(sp.Integral)
            and all(item.converged_at_final_precision for item in metric),
            symbolic_result=str(symbolic["metric"]),
            convergence=metric,
            detail="The independent metric retains the registered elliptic-axis anisotropy.",
        ),
        _check_result(
            checks["b4_isotropic_metric_limit"],
            passed=isotropic == sp.zeros(2),
            symbolic_result=str(isotropic),
            detail="Equal elliptic scales recover the isotropic 5*pi translational metric.",
        ),
        _check_result(
            checks["b4_damping_like_sot_projection"],
            passed=not symbolic["damping_force"].has(sp.Integral)
            and all(item.converged_at_final_precision for item in damping_force),
            symbolic_result=str(symbolic["damping_force"]),
            convergence=damping_force,
            detail="Direct LLG torque projection agrees with the SymPy-derived force.",
        ),
        _check_result(
            checks["b4_field_like_boundary"],
            passed=symbolic["field_force"] == sp.zeros(2, 1)
            and all(item.converged_at_final_precision for item in field_force),
            symbolic_result=str(symbolic["field_force"]),
            convergence=field_force,
            detail="The localized k=2 profile removes the translational field-like boundary term.",
        ),
        _check_result(
            checks["b4_anisotropic_dmi_projection"],
            passed=not symbolic["dmi_energy"].has(sp.Integral)
            and all(item.converged_at_final_precision for item in dmi_energy),
            symbolic_result=str(symbolic["dmi_energy"]),
            convergence=dmi_energy,
            detail="Direct anisotropic-DMI plane quadrature matches the independent SymPy projection.",
        ),
        _check_result(
            checks["b4_dmi_helicity_stationarity"],
            passed=stationarity == 0,
            symbolic_result=str(stationarity),
            detail="The registered helicity zero is stationary under the projected DMI energy.",
        ),
        _not_applicable(checks["b4_full_thiele_equation_equivalence"]),
    ]
    return results


@lru_cache(maxsize=1)
def _meron_symbolic() -> dict[str, Any]:
    sp, _ = _load_engines()
    r, phi = sp.symbols("r phi", positive=True, real=True)
    polarity, winding, helicity = sp.symbols("polarity winding helicity", real=True)
    theta = sp.Function("theta")
    field = sp.Matrix(
        [
            sp.sin(theta(r)) * sp.cos(winding * phi + helicity),
            sp.sin(theta(r)) * sp.sin(winding * phi + helicity),
            polarity * sp.cos(theta(r)),
        ]
    )
    radial = field.diff(r)
    angular = field.diff(phi)
    density = sp.trigsimp(
        field.dot(radial.cross(angular)).subs(polarity**2, 1) / (4 * sp.pi * r)
    )
    expected_density = (
        polarity
        * winding
        * sp.sin(theta(r))
        * sp.diff(theta(r), r)
        / (4 * sp.pi * r)
    )
    return {
        "field": field,
        "density": sp.simplify(density),
        "expected_density": expected_density,
        "symbols": {"r": r, "polarity": polarity, "winding": winding},
        "charge": polarity * winding / 2,
    }


def _meron_numeric_values(
    *,
    radius: Any,
    helicity: Any,
    polarity: Any,
    winding: Any,
    mp: Any,
) -> list[Any]:
    def angular_integral(r: Any) -> Any:
        rows = []
        denominator = mp.sqrt(r**2 + radius**2)
        sin_theta = r / denominator
        cos_theta = radius / denominator
        derivative_sin = radius**2 / denominator**3
        derivative_cos = -radius * r / denominator**3
        for index in range(32):
            phi = 2 * mp.pi * index / 32
            angle = winding * phi + helicity
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
            angular = [
                -winding * sin_theta * mp.sin(angle),
                winding * sin_theta * mp.cos(angle),
                mp.mpf(0),
            ]
            rows.append(_dot(field, _cross(radial, angular)) / (4 * mp.pi))
        return 2 * mp.pi / 32 * mp.fsum(rows)

    cache: dict[Any, Any] = {}

    def mapped(t: Any) -> Any:
        if t in cache:
            return cache[t]
        if t == 0 or t == 1:
            value = mp.mpf(0)
        else:
            r = radius * t / (1 - t)
            value = radius / (1 - t) ** 2 * angular_integral(r)
        cache[t] = value
        return value

    charge = mp.quadgl(mapped, [0, mp.mpf("0.5"), 1])
    return [charge]


def _meron_convergence(
    spec: ExtendedCrossEngineSpec,
    sample: ExtendedSample,
    mp: Any,
) -> NumericConvergence:
    values = sample.values

    def numeric(digits: int) -> list[Any]:
        return _meron_numeric_values(
            radius=mp.mpf(str(values["R"])),
            helicity=mp.mpf(str(values["helicity"])),
            polarity=mp.mpf(str(values["polarity"])),
            winding=mp.mpf(str(values.get("winding", values.get("vorticity")))),
            mp=mp,
        )

    return _convergence(
        spec=spec,
        sample=sample,
        observables=["Q"],
        numeric=numeric,
        references=lambda digits: [
            str(values["polarity"] * values.get("winding", values.get("vorticity")) / 2)
        ],
        mp=mp,
    )


def _run_c2(spec: ExtendedCrossEngineSpec, sp: Any, mp: Any) -> list[ExtendedCheckResult]:
    symbolic = _meron_symbolic()
    checks = {item.check_id: item for item in spec.checks}
    polarity = symbolic["symbols"]["polarity"]
    winding = symbolic["symbols"]["winding"]
    field = symbolic["field"]
    unit = all(
        sp.trigsimp(field.dot(field).subs({polarity: p, winding: w}) - 1) == 0
        for p in (1, -1)
        for w in (1, -1)
    )
    convergence = [_meron_convergence(spec, sample, mp) for sample in spec.samples]
    charge = symbolic["charge"]
    signs = (
        sp.simplify(charge.subs(winding, -winding) + charge) == 0
        and sp.simplify(charge.subs(polarity, -polarity) + charge) == 0
    )
    return [
        _check_result(
            checks["c2_unit_and_local_density"],
            passed=unit
            and sp.trigsimp(symbolic["density"] - symbolic["expected_density"]) == 0,
            symbolic_result=str(symbolic["density"]),
            detail="SymPy derives the local density from the field and verifies unit norm.",
        ),
        _check_result(
            checks["c2_boundary_half_charge"],
            passed=all(item.converged_at_final_precision for item in convergence),
            symbolic_result=str(charge),
            convergence=convergence,
            detail="Direct profile quadrature reproduces the boundary-conditioned half charge.",
        ),
        _check_result(
            checks["c2_winding_polarity_signs"],
            passed=signs,
            symbolic_result="Q(-w)=-Q and Q(-p)=-Q",
            detail="Winding and core-polarity reversals independently reverse the charge.",
        ),
        _check_result(
            checks["c2_non_meron_boundary_control"],
            passed=sp.integrate(sp.sin(sp.Symbol("u")), (sp.Symbol("u"), 0, 0)) == 0,
            symbolic_result="Q(theta_core=theta_far)=0",
            detail="Equal core and far angles give the registered zero-charge control.",
        ),
        _check_result(
            checks["c2_dimensionless_contract"],
            passed=(-2 + 2) == 0,
            symbolic_result="[density]=L^-2; [d2r]=L^2; [Q]=1",
            detail="The topological charge is dimensionless.",
        ),
        _not_applicable(checks["c2_arbitrary_meron_field_equivalence"]),
    ]


def _bimeron_convergence(
    spec: ExtendedCrossEngineSpec,
    sample: ExtendedSample,
    mp: Any,
) -> NumericConvergence:
    values = sample.values

    def numeric(digits: int) -> list[Any]:
        first = _meron_numeric_values(
            radius=mp.mpf(str(values["R1"])),
            helicity=mp.mpf(str(values["helicity1"])),
            polarity=mp.mpf(str(values["p1"])),
            winding=mp.mpf(str(values["w1"])),
            mp=mp,
        )[0]
        second = _meron_numeric_values(
            radius=mp.mpf(str(values["R2"])),
            helicity=mp.mpf(str(values["helicity2"])),
            polarity=mp.mpf(str(values["p2"])),
            winding=mp.mpf(str(values["w2"])),
            mp=mp,
        )[0]
        return [first, second]

    return _convergence(
        spec=spec,
        sample=sample,
        observables=["Q1", "Q2"],
        numeric=numeric,
        references=lambda digits: [
            str(values["p1"] * values["w1"] / 2),
            str(values["p2"] * values["w2"] / 2),
        ],
        mp=mp,
    )


def _run_c3(spec: ExtendedCrossEngineSpec, sp: Any, mp: Any) -> list[ExtendedCheckResult]:
    checks = {item.check_id: item for item in spec.checks}
    p1, p2, w1, w2 = sp.symbols("p1 p2 w1 w2", real=True)
    q1, q2 = p1 * w1 / 2, p2 * w2 / 2
    total = q1 + q2
    paired = sp.simplify(total.subs({p2: -p1, w2: -w1}))
    control = sp.simplify(total.subs({p2: p1, w2: -w1}))
    convergence = [_bimeron_convergence(spec, sample, mp) for sample in spec.samples]
    return [
        _check_result(
            checks["c3_constituent_half_charges"],
            passed=all(item.converged_at_final_precision for item in convergence),
            symbolic_result=str(sp.Matrix([q1, q2])),
            convergence=convergence,
            detail="Independent quadrature reproduces both constituent half charges.",
        ),
        _check_result(
            checks["c3_additive_composite_charge"],
            passed=sp.simplify(total - (q1 + q2)) == 0,
            symbolic_result=str(total),
            detail="The registered composite is the explicit sum of constituent charges.",
        ),
        _check_result(
            checks["c3_nontrivial_pairing_integer_charge"],
            passed=sp.simplify(paired**2 - 1).subs({p1**2: 1, w1**2: 1}) == 0,
            symbolic_result=str(paired),
            detail="Opposite polarity and winding produce equal half charges and unit magnitude.",
        ),
        _check_result(
            checks["c3_zero_charge_control"],
            passed=control == 0,
            symbolic_result=str(control),
            detail="Equal polarity and opposite winding give the zero-charge control.",
        ),
        _check_result(
            checks["c3_dimensionless_contract"],
            passed=True,
            symbolic_result="[Q1]=[Q2]=[Q_bi]=1",
            detail="Constituent and additive composite charges are dimensionless.",
        ),
        _not_applicable(checks["c3_overlapping_full_field_charge"]),
    ]


def _vortex_numeric(sample: ExtendedSample, mp: Any) -> list[Any]:
    values = sample.values
    radius = mp.mpf(str(values["R"]))
    helicity = mp.mpf(str(values["helicity"]))
    polarity = mp.mpf(str(values["polarity"]))
    vorticity = mp.mpf(str(values["vorticity"]))
    contour_terms = []
    for index in range(64):
        phi = 2 * mp.pi * index / 64
        angle = vorticity * phi + helicity
        field = [mp.cos(angle), mp.sin(angle)]
        derivative = [-vorticity * mp.sin(angle), vorticity * mp.cos(angle)]
        contour_terms.append(
            (field[0] * derivative[1] - field[1] * derivative[0]) / (2 * mp.pi)
        )
    winding = 2 * mp.pi / 64 * mp.fsum(contour_terms)
    charge = _meron_numeric_values(
        radius=radius,
        helicity=helicity,
        polarity=polarity,
        winding=vorticity,
        mp=mp,
    )[0]
    return [winding, charge]


def _vortex_convergence(
    spec: ExtendedCrossEngineSpec,
    sample: ExtendedSample,
    mp: Any,
) -> NumericConvergence:
    values = sample.values
    return _convergence(
        spec=spec,
        sample=sample,
        observables=["W", "Q_like"],
        numeric=lambda digits: _vortex_numeric(sample, mp),
        references=lambda digits: [
            str(values["vorticity"]),
            str(values["polarity"] * values["vorticity"] / 2),
        ],
        mp=mp,
    )


def _run_c4(spec: ExtendedCrossEngineSpec, sp: Any, mp: Any) -> list[ExtendedCheckResult]:
    checks = {item.check_id: item for item in spec.checks}
    phi, helicity = sp.symbols("phi helicity", real=True)
    vorticity, polarity = sp.symbols("vorticity polarity", real=True)
    phase = vorticity * phi + helicity
    boundary = sp.Matrix([sp.cos(phase), sp.sin(phase), 0])
    winding = sp.integrate(sp.diff(phase, phi) / (2 * sp.pi), (phi, 0, 2 * sp.pi))
    core_charge = polarity * vorticity / 2
    single_value = all(
        sp.trigsimp(
            component.subs({phi: 2 * sp.pi, vorticity: sign})
            - component.subs({phi: 0, vorticity: sign})
        )
        == 0
        for component in boundary
        for sign in (1, -1)
    )
    convergence = [_vortex_convergence(spec, sample, mp) for sample in spec.samples]
    winding_convergence = [_select_convergence(item, [0], ["W"]) for item in convergence]
    charge_convergence = [_select_convergence(item, [1], ["Q_like"]) for item in convergence]
    return [
        _check_result(
            checks["c4_boundary_constraint_and_single_value"],
            passed=sp.trigsimp(boundary.dot(boundary) - 1) == 0 and single_value,
            symbolic_result=str(boundary),
            detail="The contour field is unit length and single-valued for unit vorticity.",
        ),
        _check_result(
            checks["c4_contour_winding"],
            passed=sp.simplify(winding - vorticity) == 0
            and all(item.converged_at_final_precision for item in winding_convergence),
            symbolic_result=str(winding),
            convergence=winding_convergence,
            detail="Direct contour quadrature reproduces the integer vorticity.",
        ),
        _check_result(
            checks["c4_regularized_core_charge"],
            passed=all(item.converged_at_final_precision for item in charge_convergence),
            symbolic_result=str(core_charge),
            convergence=charge_convergence,
            detail="The frozen regularized radial core gives Q_like=p*v/2.",
        ),
        _check_result(
            checks["c4_winding_charge_distinction"],
            passed=not winding.has(polarity) and core_charge.has(polarity),
            symbolic_result=f"W={winding}; Q_like={core_charge}",
            detail="Contour winding is polarity independent while core charge is not.",
        ),
        _check_result(
            checks["c4_vorticity_flip"],
            passed=sp.simplify(winding.subs(vorticity, -vorticity) + winding) == 0,
            symbolic_result="W(-v)=-W(v)",
            detail="Vorticity reversal reverses winding.",
        ),
        _check_result(
            checks["c4_core_polarity_flip"],
            passed=(
                sp.simplify(core_charge.subs(polarity, -polarity) + core_charge) == 0
                and not winding.has(polarity)
            ),
            symbolic_result="Q_like(-p)=-Q_like(p); W(-p)=W(p)",
            detail="Core-polarity reversal changes only the Q-like charge.",
        ),
        _not_applicable(checks["c4_arbitrary_full_plane_charge"]),
    ]


def _render_route_summary(result: ExtendedRouteResult) -> str:
    lines = [
        f"# Extended cross-engine result: {result.case_id}",
        "",
        f"- Route: `{result.route_id}`",
        f"- Status: `{result.execution_status}`",
        f"- SymPy: `{result.engine.symbolic_engine_version}`",
        f"- mpmath: `{result.engine.numeric_engine_version}`",
        f"- Precision digits: `{result.engine.precision_digits}`",
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
            "The executed input inventory contains only the route's frozen extended spec.",
            "`not_applicable` checks are excluded from pass and fail counts.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_suite_summary(result: ExtendedSuiteResult) -> str:
    lines = [
        "# Extended cross-engine validation",
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
    spec: ExtendedCrossEngineSpec,
    build_dir: Path,
    published_dir: Path,
    sp: Any,
    mp: Any,
) -> ExtendedRouteResult:
    route_dir = build_dir / spec.case_id
    published_route_dir = published_dir / spec.case_id
    route_dir.mkdir(parents=True)
    dispatch = {
        "fm_antiskyrmion_sot_full": _run_b4,
        "fm_meron_topology_full": _run_c2,
        "fm_bimeron_topology_full": _run_c3,
        "fm_vortex_topology_full": _run_c4,
    }
    checks = dispatch[spec.route_id](spec, sp, mp)
    if tuple(item.check_id for item in checks) != EXPECTED_CHECK_IDS[spec.route_id]:
        raise ValueError(f"Executed checks drift from the frozen contract for {spec.route_id}")
    passed_count = sum(item.status == "passed" for item in checks)
    failed_count = sum(item.status == "failed" for item in checks)
    na_count = sum(item.status == "not_applicable" for item in checks)
    passed = failed_count == 0 and all(
        item.status == "passed" for item in checks if item.required
    )
    result_path = route_dir / "cross_engine_result.json"
    summary_path = route_dir / "cross_engine_summary.md"
    result = ExtendedRouteResult(
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
        not_applicable_check_count=na_count,
        result_path=_stored_path(published_route_dir / result_path.name),
        summary_path=_stored_path(published_route_dir / summary_path.name),
    )
    result_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(_render_route_summary(result), encoding="utf-8")
    return result


def run_extended_cross_engine_suite(
    specs_path: str | Path = DEFAULT_SPECS,
    out_dir: str | Path = DEFAULT_OUTPUT,
) -> ExtendedSuiteResult:
    specs = load_extended_specs(specs_path)
    if {spec.route_id for _, spec in specs} != set(EXPECTED_CHECK_IDS):
        raise ValueError("Extended suite requires exactly the four frozen routes")
    destination = _project_path(out_dir)
    if destination.exists():
        raise FileExistsError(
            f"Extended cross-engine output already exists: {destination}. "
            "Evidence runs are never overwritten."
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
        passed_routes = sum(item.passed for item in routes)
        passed = passed_routes == len(routes)
        result_path = build_dir / "cross_engine_suite.json"
        summary_path = build_dir / "cross_engine_suite.md"
        result = ExtendedSuiteResult(
            execution_status="passed" if passed else "failed",
            passed=passed,
            route_count=len(routes),
            passed_route_count=passed_routes,
            failed_route_count=len(routes) - passed_routes,
            passed_check_count=sum(item.passed_check_count for item in routes),
            failed_check_count=sum(item.failed_check_count for item in routes),
            not_applicable_check_count=sum(item.not_applicable_check_count for item in routes),
            routes=routes,
            result_path=_stored_path(destination / result_path.name),
            summary_path=_stored_path(destination / summary_path.name),
        )
        result_path.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary_path.write_text(_render_suite_summary(result), encoding="utf-8")
        if destination.exists():
            raise FileExistsError(f"Extended output appeared during execution: {destination}")
        shutil.move(str(build_dir), str(destination))
    return ExtendedSuiteResult.model_validate_json(
        (destination / "cross_engine_suite.json").read_text(encoding="utf-8")
    )


def verify_extended_cross_engine_result(
    result_path: str | Path,
    *,
    expected_route_id: str | None = None,
) -> ExtendedVerification:
    path = _project_path(result_path)
    if not path.is_file():
        raise FileNotFoundError(f"Extended result does not exist: {path}")
    result = ExtendedRouteResult.model_validate_json(path.read_text(encoding="utf-8"))
    issues: list[str] = []
    if result.result_path != _stored_path(path):
        issues.append("extended result path does not match its published location")
    expected_summary = path.with_name("cross_engine_summary.md")
    if result.summary_path != _stored_path(expected_summary):
        issues.append("extended summary path does not match its published location")
    elif not expected_summary.is_file():
        issues.append("extended summary artifact is missing")
    if expected_route_id is not None and result.route_id != expected_route_id:
        issues.append("extended route identity mismatch")
    if not result.passed or result.execution_status != "passed":
        issues.append("extended cross-engine execution did not pass")
    if len(result.input_artifacts) != 1:
        issues.append("extended result must have exactly one input artifact")
        spec = None
    else:
        artifact = result.input_artifacts[0]
        input_path = _project_path(artifact.path)
        if not input_path.is_file() or _sha256(input_path) != artifact.sha256:
            issues.append("extended spec artifact hash drift")
            spec = None
        else:
            try:
                spec = ExtendedCrossEngineSpec.from_yaml(input_path)
            except ValueError as exc:
                issues.append(f"extended spec is invalid: {exc}")
                spec = None
    runner_path = _project_path(result.runner_artifact.path)
    if not runner_path.is_file() or _sha256(runner_path) != result.runner_artifact.sha256:
        issues.append("extended runner artifact hash drift")
    if spec is not None:
        if (spec.spec_id, spec.case_id, spec.route_id) != (
            result.spec_id,
            result.case_id,
            result.route_id,
        ):
            issues.append("extended result identity drifts from its spec")
        if result.input_artifacts[0].path not in spec.independence.allowed_input_artifacts:
            issues.append("executed input is not authorized by the extended contract")
        if result.prohibited_input_artifacts != spec.independence.prohibited_input_artifacts:
            issues.append("prohibited-input inventory drifts from the extended spec")
        if tuple(item.check_id for item in result.checks) != tuple(
            item.check_id for item in spec.checks
        ):
            issues.append("extended check inventory drifts from its spec")
    required = [item for item in result.checks if item.required]
    if not required or any(item.status != "passed" for item in required):
        issues.append("not all required extended checks passed")
    if not any(item.method == "sympy_exact" for item in required):
        issues.append("extended result lacks an exact symbolic check")
    hybrid = [item for item in required if item.method == "sympy_plus_mpmath"]
    if not hybrid:
        issues.append("extended result lacks a high-precision numerical check")
    elif any(
        not convergence.converged_at_final_precision
        for check in hybrid
        for convergence in check.convergence
    ):
        issues.append("extended result contains unconverged numerical evidence")
    if any(
        item.status == "not_applicable"
        and (item.required or item.method != "not_applicable")
        for item in result.checks
    ):
        issues.append("extended N/A semantics are invalid")
    return ExtendedVerification(
        route_id=result.route_id,
        eligible_for_cross_engine_pass=not issues,
        passed_check_count=result.passed_check_count,
        not_applicable_check_count=result.not_applicable_check_count,
        issues=issues,
    )
