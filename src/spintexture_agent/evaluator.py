from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .checker import check_task
from .generator import PROJECT_ROOT, generate_task_bundle
from .ir import build_physics_ir
from .kb import KnowledgeBase
from .schema import PhysicsIR, TheoryTask
from .selector import select_template
from .wolfram import execute_wolfram_script, update_wolfram_execution_record


DEFAULT_CASES_DIR = PROJECT_ROOT / "benchmark_cases"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"
DEFAULT_BUNDLE_DIR = PROJECT_ROOT / "outputs" / "benchmark_runs"
DEFAULT_GOLD_DIR = PROJECT_ROOT / "gold_answers"


@dataclass(frozen=True)
class DimensionScore:
    name: str
    passed: bool
    detail: str
    status: str | None = None

    def __post_init__(self) -> None:
        status = self.status or ("pass" if self.passed else "fail")
        if status not in {"pass", "fail", "skipped", "not_applicable"}:
            raise ValueError(f"Unsupported dimension status: {status}")
        object.__setattr__(self, "status", status)

    @property
    def applicable(self) -> bool:
        return self.status in {"pass", "fail"}

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "passed": self.passed if self.applicable else None,
            "detail": self.detail,
        }


def summarize_dimensions(dimensions: list[DimensionScore]) -> tuple[int, int]:
    applicable = [dimension for dimension in dimensions if dimension.applicable]
    return sum(1 for dimension in applicable if dimension.passed), len(applicable)


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    description: str
    config: str
    score: int
    max_score: int
    support_level: str
    dimensions: list[DimensionScore]
    bundle_paths: dict[str, str]
    duration_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status not in {"failed", "incomplete"}

    @property
    def status(self) -> str:
        if any(dimension.status == "fail" for dimension in self.dimensions):
            return "failed"
        if any(dimension.status == "skipped" for dimension in self.dimensions):
            return "incomplete"
        if self.support_level == "review_only":
            return "review_only_passed"
        if self.support_level == "scaffold":
            return "scaffold_passed"
        if self.support_level == "unsupported":
            return "unsupported_routing_passed"
        return "full_derivation_passed"

    def to_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "description": self.description,
            "config": self.config,
            "score": self.score,
            "max_score": self.max_score,
            "support_level": self.support_level,
            "passed": self.passed,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "dimensions": [dimension.to_record() for dimension in self.dimensions],
            "bundle_paths": self.bundle_paths,
        }


@dataclass(frozen=True)
class BenchmarkRun:
    cases: list[CaseScore]
    csv_path: Path
    json_path: Path
    archive_dir: Path | None = None
    archive_paths: dict[str, Path] = field(default_factory=dict)

    @property
    def passed_cases(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    @property
    def total_score(self) -> int:
        return sum(case.score for case in self.cases)

    @property
    def max_score(self) -> int:
        return sum(case.max_score for case in self.cases)

    def to_record(self) -> dict[str, Any]:
        return {
            "summary": {
                "case_count": len(self.cases),
                "passed_cases": self.passed_cases,
                "total_score": self.total_score,
                "max_score": self.max_score,
                "support_level_counts": {
                    support_level: sum(
                        1 for case in self.cases if case.support_level == support_level
                    )
                    for support_level in [
                        "full_derivation",
                        "scaffold",
                        "review_only",
                        "unsupported",
                    ]
                },
            },
            "archive": {
                "archive_dir": str(self.archive_dir) if self.archive_dir else None,
                "paths": {name: str(path) for name, path in self.archive_paths.items()},
            },
            "cases": [case.to_record() for case in self.cases],
        }


def _project_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Benchmark case must be a mapping: {path}")
    return data


def _score_exact(name: str, actual: Any, expected: Any) -> DimensionScore:
    passed = actual == expected
    detail = f"expected={expected!r}, actual={actual!r}"
    return DimensionScore(name=name, passed=passed, detail=detail)


def _score_contains_all(name: str, actual_items: list[str], expected_items: list[str]) -> DimensionScore:
    missing = [item for item in expected_items if item not in actual_items]
    passed = not missing
    detail = "all expected items found" if passed else f"missing={missing!r}"
    return DimensionScore(name=name, passed=passed, detail=detail)


def _score_confidence_thresholds(
    physics_ir: PhysicsIR,
    expected_confidence: dict[str, Any],
) -> list[DimensionScore]:
    confidence = physics_ir.confidence
    values = {
        "model_selection": confidence.model_selection,
        "ansatz_validity": confidence.ansatz_validity,
        "topology_definition": confidence.topology_definition,
    }
    dimensions: list[DimensionScore] = []
    for name, actual in values.items():
        min_key = f"{name}_min"
        max_key = f"{name}_max"
        if min_key in expected_confidence:
            expected = float(expected_confidence[min_key])
            passed = actual >= expected
            dimensions.append(
                DimensionScore(
                    name=f"confidence_{name}_min",
                    passed=passed,
                    detail=f"expected>={expected:.3f}, actual={actual:.3f}",
                )
            )
        if max_key in expected_confidence:
            expected = float(expected_confidence[max_key])
            passed = actual <= expected
            dimensions.append(
                DimensionScore(
                    name=f"confidence_{name}_max",
                    passed=passed,
                    detail=f"expected<={expected:.3f}, actual={actual:.3f}",
                )
            )
    return dimensions


def _score_required_symbols(wolfram_text: str, required: list[str]) -> DimensionScore:
    missing = [symbol for symbol in required if symbol not in wolfram_text]
    passed = not missing
    detail = "all required symbols found" if passed else f"missing={missing!r}"
    return DimensionScore(name="required_wolfram_symbols", passed=passed, detail=detail)


def _score_forbidden_symbols(wolfram_text: str, forbidden: list[str]) -> DimensionScore:
    present = [symbol for symbol in forbidden if symbol in wolfram_text]
    passed = not present
    detail = "no forbidden symbols found" if passed else f"present={present!r}"
    return DimensionScore(name="forbidden_wolfram_symbols", passed=passed, detail=detail)


def _score_validation_ids(validation_items: list[dict[str, Any]], expected_ids: list[str]) -> DimensionScore:
    actual_ids = [str(item.get("id")) for item in validation_items]
    return _score_contains_all("validation_ids", actual_ids, expected_ids)


def _score_wolfram_execution(execution: dict[str, Any]) -> DimensionScore:
    status = execution.get("status")
    detail = f"status={status!r}"
    if execution.get("reason"):
        detail += f", reason={execution['reason']!r}"
    if status == "skipped":
        return DimensionScore(
            name="wolfram_execution",
            passed=False,
            detail=detail,
            status="skipped",
        )
    return DimensionScore(name="wolfram_execution", passed=status == "passed", detail=detail)


def _score_wolfram_result_keys(record: dict[str, Any]) -> DimensionScore:
    execution_status = record.get("wolfram_execution", {}).get("status")
    wolfram_results = record.get("wolfram_results", {})
    expected_keys = wolfram_results.get("expected_keys", [])
    if execution_status == "skipped":
        return DimensionScore(
            name="wolfram_result_keys",
            passed=False,
            detail="execution skipped; result-key check not applicable",
            status="skipped",
        )
    if not expected_keys:
        return DimensionScore(
            name="wolfram_result_keys",
            passed=False,
            detail="no Wolfram result keys declared for this support level",
            status="not_applicable",
        )
    results = wolfram_results.get("results")
    if not isinstance(results, dict):
        return DimensionScore(
            name="wolfram_result_keys",
            passed=False,
            detail="no structured Wolfram results found",
        )
    missing = [key for key in expected_keys if key not in results]
    passed = not missing
    detail = "all expected result keys found" if passed else f"missing={missing!r}"
    return DimensionScore(name="wolfram_result_keys", passed=passed, detail=detail)


def _score_wolfram_result_content(
    record: dict[str, Any],
    equation_type: str,
    support_level: str = "full_derivation",
) -> DimensionScore:
    execution_status = record.get("wolfram_execution", {}).get("status")
    if execution_status == "skipped":
        return DimensionScore(
            name="wolfram_result_content",
            passed=False,
            detail="execution skipped; content check not applicable",
            status="skipped",
        )
    if support_level in {"review_only", "unsupported"}:
        return DimensionScore(
            name="wolfram_result_content",
            passed=False,
            detail=f"support_level={support_level!r}; symbolic content is not claimed",
            status="not_applicable",
        )

    results = record.get("wolfram_results", {}).get("results")
    if not isinstance(results, dict):
        return DimensionScore(
            name="wolfram_result_content",
            passed=False,
            detail="no structured Wolfram results found",
        )

    checks: list[tuple[str, bool]] = []
    if equation_type == "coupled_wall_chain":
        metric = str(results.get("collective_metric_matrix", ""))
        mass = str(results.get("collective_mass_matrix", ""))
        damping = str(results.get("collective_damping_matrix", ""))
        force = str(results.get("single_wall_sot_generalized_force", ""))
        chain_force = str(results.get("chain_sot_force", ""))
        stability = str(results.get("wall_chain_stability_matrix", ""))
        equation = str(results.get("stripe_chain_equation", ""))
        dimension_contract = str(results.get("dimension_contract", ""))
        checks = [
            ("ansatz_constraint_proved", results.get("ansatz_constraint_regression") == "True"),
            ("metric_is_integrated", "2/Delta" in metric and "2*Delta" in metric),
            ("metric_regression_passed", results.get("metric_matrix_regression") == "True"),
            ("mass_contains_chi", "chi" in mass),
            ("mass_regression_passed", results.get("mass_matrix_regression") == "True"),
            ("damping_contains_alpha_s", "alpha" in damping and "s" in damping),
            ("damping_regression_passed", results.get("damping_matrix_regression") == "True"),
            (
                "sot_force_is_projected",
                "tauDL" in force and "tauFL" in force and "Pi" in force,
            ),
            ("sot_force_regression_passed", results.get("sot_force_regression") == "True"),
            (
                "alternating_chain_force_present",
                "Phi1" in chain_force and "Phi4" in chain_force and "tauDL" in chain_force,
            ),
            ("stability_contains_k_coupling", "k" in stability and "-k" in stability),
            (
                "stability_regression_passed",
                results.get("stability_matrix_regression") == "True",
            ),
            (
                "equation_is_derived_wall_chain",
                "Derivative[2]" in equation
                and "Derivative[1]" in equation
                and "u1[t]" in equation
                and "u4[t]" in equation,
            ),
            ("chain_equation_regression_passed", results.get("chain_equation_regression") == "True"),
            ("alpha_limit_passed", results.get("alpha_limit_regression") == "True"),
            (
                "dimension_contract_declared",
                "one_dimensional_energy_per_transverse_area" in dimension_contract
                and "energy" in dimension_contract
                and "length" in dimension_contract
                and "time" in dimension_contract,
            ),
            (
                "energy_density_dimensions_passed",
                results.get("energy_density_dimension_regression") == "True",
            ),
            (
                "translation_dimensions_passed",
                results.get("translation_dimension_regression") == "True",
            ),
            (
                "internal_angle_dimensions_passed",
                results.get("angle_dimension_regression") == "True",
            ),
        ]
    elif equation_type == "thiele_equation":
        gyro = str(results.get("gyrotropic_tensor", ""))
        damping = str(results.get("damping_tensor", ""))
        equation = str(results.get("thiele_equation", ""))
        if support_level == "full_derivation" and "anisotropic_metric_regression" in results:
            topology = str(results.get("topological_charge", ""))
            metric = str(results.get("anisotropic_metric_radial_integrand", ""))
            sot_force = str(results.get("sot_generalized_force", ""))
            dmi_projection = str(results.get("anisotropic_dmi_angular_density", ""))
            dimension_contract = str(results.get("dimension_contract", ""))
            checks = [
                ("ansatz_constraint_proved", results.get("ansatz_constraint_regression") == "True"),
                ("antiskyrmion_charge_uses_polarity", "polarity" in topology),
                (
                    "topological_charge_regression_passed",
                    results.get("topological_charge_regression") == "True",
                ),
                (
                    "gyrotropic_density_regression_passed",
                    results.get("gyrotropic_density_regression") == "True",
                ),
                (
                    "gyrotropic_tensor_regression_passed",
                    results.get("gyrotropic_tensor_regression") == "True",
                ),
                (
                    "elliptic_metric_contains_both_scales",
                    "lambdaX" in metric and "lambdaY" in metric,
                ),
                (
                    "anisotropic_metric_regression_passed",
                    results.get("anisotropic_metric_regression") == "True",
                ),
                (
                    "metric_ratio_regression_passed",
                    results.get("metric_anisotropy_ratio_regression") == "True",
                ),
                (
                    "isotropic_limit_regression_passed",
                    results.get("isotropic_metric_limit_regression") == "True",
                ),
                (
                    "anisotropic_damping_present",
                    "lambdaX" in damping and "lambdaY" in damping and "alpha" in damping,
                ),
                (
                    "damping_tensor_regression_passed",
                    results.get("damping_tensor_regression") == "True",
                ),
                (
                    "anisotropic_sot_force_projected",
                    "lambdaX" in sot_force
                    and "lambdaY" in sot_force
                    and "tauDL" in sot_force,
                ),
                (
                    "sot_force_density_regression_passed",
                    results.get("sot_force_density_regression") == "True",
                ),
                (
                    "field_like_boundary_regression_passed",
                    results.get("field_like_boundary_regression") == "True",
                ),
                (
                    "anisotropic_dmi_is_projected",
                    "Dmi" in dmi_projection
                    and "lambdaX" in dmi_projection
                    and "lambdaY" in dmi_projection
                    and "Cos[helicity]" in dmi_projection,
                ),
                (
                    "anisotropic_dmi_projection_regression_passed",
                    results.get("anisotropic_dmi_projection_regression") == "True",
                ),
                (
                    "dmi_helicity_stationarity_passed",
                    results.get("dmi_helicity_stationarity_regression") == "True",
                ),
                (
                    "equation_is_derived_anisotropic_thiele",
                    "Derivative[1]" in equation
                    and "Derivative[2]" not in equation
                    and "lambdaX" in equation
                    and "lambdaY" in equation,
                ),
                (
                    "thiele_equation_regression_passed",
                    results.get("thiele_equation_regression") == "True",
                ),
                ("alpha_limit_passed", results.get("alpha_limit_regression") == "True"),
                (
                    "dimension_contract_declared",
                    "two_dimensional_elliptic_antiskyrmion" in dimension_contract,
                ),
                (
                    "energy_density_dimensions_passed",
                    results.get("anti_energy_density_dimension_regression") == "True",
                ),
                (
                    "thiele_dimensions_passed",
                    results.get("anti_thiele_dimension_regression") == "True",
                ),
            ]
        elif support_level == "full_derivation":
            topology = str(results.get("topological_charge", ""))
            gyro_density = str(results.get("gyrotropic_angular_density", ""))
            metric_density = str(results.get("dissipative_radial_integrand", ""))
            sot_force = str(results.get("sot_generalized_force", ""))
            dimension_contract = str(results.get("dimension_contract", ""))
            checks = [
                ("topological_charge_uses_boundary_conditions", "polarity" in topology),
                (
                    "topological_charge_regression_passed",
                    results.get("topological_charge_regression") == "True",
                ),
                (
                    "gyrotropic_density_is_projected",
                    "Sin[thetaProfile[r]]" in gyro_density
                    and "Derivative[1][thetaProfile][r]" in gyro_density,
                ),
                (
                    "gyrotropic_density_regression_passed",
                    results.get("gyrotropic_density_regression") == "True",
                ),
                (
                    "dissipative_density_is_projected",
                    "Sin[thetaProfile[r]]" in metric_density
                    and "Derivative[1][thetaProfile][r]" in metric_density,
                ),
                (
                    "dissipative_density_regression_passed",
                    results.get("dissipative_density_regression") == "True",
                ),
                (
                    "sot_force_is_projected",
                    "tauDL" in sot_force and "Isot" in sot_force and "Pi" in sot_force,
                ),
                (
                    "sot_force_density_regression_passed",
                    results.get("sot_force_density_regression") == "True",
                ),
                (
                    "field_like_boundary_regression_passed",
                    results.get("field_like_boundary_regression") == "True",
                ),
                ("gyro_is_antisymmetric", "-4" in gyro and "4" in gyro and "Pi" in gyro),
                (
                    "gyrotropic_tensor_regression_passed",
                    results.get("gyrotropic_tensor_regression") == "True",
                ),
                ("damping_contains_alpha_s", "alpha" in damping and "s" in damping),
                (
                    "damping_tensor_regression_passed",
                    results.get("damping_tensor_regression") == "True",
                ),
                (
                    "equation_is_derived_first_order_thiele",
                    "Derivative[1]" in equation
                    and "Derivative[2]" not in equation
                    and "tauDL" in equation,
                ),
                (
                    "thiele_equation_regression_passed",
                    results.get("thiele_equation_regression") == "True",
                ),
                ("alpha_limit_passed", results.get("alpha_limit_regression") == "True"),
                (
                    "dimension_contract_declared",
                    "two_dimensional_energy_functional" in dimension_contract,
                ),
                (
                    "energy_density_dimensions_passed",
                    results.get("fm_energy_density_dimension_regression") == "True",
                ),
                (
                    "thiele_dimensions_passed",
                    results.get("thiele_dimension_regression") == "True",
                ),
            ]
        else:
            checks = [
                ("gyro_is_antisymmetric", "-4" in gyro and "4" in gyro and "Pi" in gyro),
                ("gyro_depends_on_topological_charge", "Q" in gyro),
                ("damping_contains_alpha", "alpha" in damping),
                (
                    "equation_is_first_order_thiele",
                    "G cross Rdot" in equation and "Rddot" not in equation,
                ),
            ]
    elif equation_type == "inertial_collective_coordinate":
        mass = str(results.get("collective_mass_matrix", ""))
        damping = str(results.get("collective_damping_matrix", ""))
        cancellation = str(results.get("gyrotropic_cancellation", ""))
        equation = str(results.get("inertial_equation", ""))
        if support_level == "full_derivation":
            topology = str(results.get("topological_charge", ""))
            metric = str(results.get("collective_metric_radial_integrand", ""))
            sot_force = str(results.get("sot_generalized_force", ""))
            gyro_a = str(results.get("sublattice_gyro_density_a", ""))
            gyro_b = str(results.get("sublattice_gyro_density_b", ""))
            dimension_contract = str(results.get("dimension_contract", ""))
            checks = [
                ("topological_charge_uses_neel_boundary", "polarity" in topology),
                (
                    "topological_charge_regression_passed",
                    results.get("topological_charge_regression") == "True",
                ),
                (
                    "metric_is_projected",
                    "Sin[thetaProfile[r]]" in metric
                    and "Derivative[1][thetaProfile][r]" in metric,
                ),
                (
                    "metric_density_regression_passed",
                    results.get("metric_density_regression") == "True",
                ),
                ("mass_contains_chi", "chi" in mass and "Dsk" in mass),
                ("mass_regression_passed", results.get("mass_matrix_regression") == "True"),
                (
                    "damping_contains_alpha_s",
                    "alpha" in damping and "s" in damping and "Dsk" in damping,
                ),
                (
                    "damping_regression_passed",
                    results.get("damping_matrix_regression") == "True",
                ),
                (
                    "sigma_model_sot_force_is_projected",
                    "tauFL" in sot_force and "IsotAFM" in sot_force and "Pi" in sot_force,
                ),
                (
                    "damping_like_boundary_regression_passed",
                    results.get("damping_like_boundary_regression") == "True",
                ),
                (
                    "field_like_force_regression_passed",
                    results.get("field_like_force_density_regression") == "True",
                ),
                (
                    "opposite_sublattice_gyro_densities_present",
                    "thetaProfile" in gyro_a and "thetaProfile" in gyro_b,
                ),
                (
                    "sublattice_gyro_density_regression_passed",
                    results.get("sublattice_gyro_density_regression") == "True",
                ),
                ("gyro_cancellation_is_zero_tensor", cancellation == "{{0, 0}, {0, 0}}"),
                (
                    "gyro_cancellation_regression_passed",
                    results.get("gyrotropic_cancellation_regression") == "True",
                ),
                (
                    "equation_is_derived_inertial",
                    "Derivative[2]" in equation
                    and "Derivative[1]" in equation
                    and "tauFL" in equation
                    and "G cross Rdot" not in equation,
                ),
                (
                    "inertial_equation_regression_passed",
                    results.get("inertial_equation_regression") == "True",
                ),
                ("alpha_limit_passed", results.get("alpha_limit_regression") == "True"),
                (
                    "dimension_contract_declared",
                    "two_dimensional_afm_sigma_model" in dimension_contract,
                ),
                (
                    "energy_density_dimensions_passed",
                    results.get("afm_energy_density_dimension_regression") == "True",
                ),
                (
                    "inertial_dimensions_passed",
                    results.get("inertial_dimension_regression") == "True",
                ),
            ]
        else:
            checks = [
                ("mass_matrix_present", "Msk" in mass or "chi" in mass),
                ("damping_matrix_present", "GammaSk" in damping or "alpha" in damping),
                (
                    "gyro_cancellation_present",
                    "G_A" in cancellation and "G_B" in cancellation and "0" in cancellation,
                ),
                (
                    "equation_is_inertial",
                    "Rddot" in equation and "G cross Rdot" not in equation,
                ),
            ]
    elif equation_type == "topology_only":
        note = str(results.get("topology_note", ""))
        if support_level == "full_derivation" and "charge_additivity_regression" in results:
            constituent_charges = str(results.get("constituent_charges", ""))
            composite_charge = str(results.get("general_composite_charge", ""))
            bimeron_charge = str(results.get("bimeron_topological_charge", ""))
            pairing_rules = str(results.get("pairing_rules", ""))
            dimension_contract = str(results.get("dimension_contract", ""))
            checks = [
                (
                    "constituent_half_charges_are_symbolic",
                    all(symbol in constituent_charges for symbol in ("p1", "p2", "w1", "w2", "/2")),
                ),
                (
                    "general_composite_charge_is_additive",
                    all(symbol in composite_charge for symbol in ("p1", "p2", "w1", "w2", "/2")),
                ),
                (
                    "nontrivial_pairing_rules_declared",
                    all(symbol in pairing_rules for symbol in ("p1", "p2", "w1", "w2", "-")),
                ),
                (
                    "integer_bimeron_charge_is_symbolic",
                    "p1" in bimeron_charge and "w1" in bimeron_charge,
                ),
                (
                    "constituent_half_charge_regression_passed",
                    results.get("constituent_half_charge_regression") == "True",
                ),
                (
                    "charge_additivity_regression_passed",
                    results.get("charge_additivity_regression") == "True",
                ),
                (
                    "nontrivial_pairing_regression_passed",
                    results.get("nontrivial_pairing_regression") == "True",
                ),
                (
                    "integer_charge_magnitude_passed",
                    results.get("integer_charge_magnitude_regression") == "True",
                ),
                (
                    "trivial_pair_control_is_zero",
                    str(results.get("trivial_pair_control_charge", "")) == "0"
                    and results.get("trivial_pair_control_regression") == "True",
                ),
                (
                    "dimension_contract_declared",
                    "dimensionless_topological_invariant" in dimension_contract,
                ),
                (
                    "topology_dimension_passed",
                    results.get("topology_dimension_regression") == "True",
                ),
                (
                    "topology_note_limits_additivity",
                    "additive" in note.lower() and "arbitrary" in note.lower(),
                ),
            ]
        elif support_level == "full_derivation" and "boundary_charge_regression" in results:
            density = str(results.get("topological_density", ""))
            boundary = str(results.get("boundary_conditions", ""))
            charge = str(results.get("topological_charge", ""))
            dimension_contract = str(results.get("dimension_contract", ""))
            checks = [
                (
                    "meron_density_uses_radial_order_parameter",
                    "thetaProfile" in density and "winding" in density and "polarity" in density,
                ),
                (
                    "meron_boundaries_declared",
                    "theta_core" in boundary and "theta_far" in boundary and "Pi/2" in boundary,
                ),
                (
                    "half_charge_is_symbolic",
                    "polarity" in charge and "winding" in charge and "/2" in charge,
                ),
                (
                    "boundary_charge_regression_passed",
                    results.get("boundary_charge_regression") == "True",
                ),
                (
                    "half_charge_magnitude_passed",
                    results.get("half_charge_magnitude_regression") == "True",
                ),
                (
                    "ansatz_constraint_passed",
                    results.get("ansatz_constraint_regression") == "True",
                ),
                (
                    "dimension_contract_declared",
                    "dimensionless_topological_invariant" in dimension_contract,
                ),
                (
                    "topology_dimension_passed",
                    results.get("topology_dimension_regression") == "True",
                ),
                ("topology_note_mentions_boundary_conditions", "boundary" in note.lower()),
            ]
        elif support_level == "full_derivation" and "winding_regression" in results:
            phase = str(results.get("boundary_phase", ""))
            winding = str(results.get("winding_number", ""))
            q_like = str(results.get("core_polarity_dependent_charge", ""))
            dimension_contract = str(results.get("dimension_contract", ""))
            checks = [
                ("boundary_phase_contains_vorticity", "vorticity" in phase),
                ("winding_equals_vorticity", "vorticity" in winding),
                ("winding_regression_passed", results.get("winding_regression") == "True"),
                (
                    "unit_winding_magnitude_passed",
                    results.get("unit_winding_magnitude_regression") == "True",
                ),
                (
                    "single_valued_boundary_passed",
                    results.get("single_valued_boundary_regression") == "True",
                ),
                (
                    "q_like_charge_uses_core_polarity",
                    "polarity" in q_like and "vorticity" in q_like,
                ),
                (
                    "winding_charge_distinction_passed",
                    results.get("winding_charge_distinction_regression") == "True",
                ),
                (
                    "dimension_contract_declared",
                    "dimensionless_topological_invariant" in dimension_contract,
                ),
                (
                    "topology_dimension_passed",
                    results.get("topology_dimension_regression") == "True",
                ),
                (
                    "topology_note_distinguishes_winding_and_charge",
                    "distinct" in note.lower() and "core" in note.lower(),
                ),
            ]
        else:
            density = str(results.get("topological_density", ""))
            checks = [
                ("topology_density_uses_order_parameter", "TopologicalDensity2D" in density),
                ("topology_note_mentions_boundary_conditions", "boundary" in note.lower()),
            ]
    else:
        return DimensionScore(
            name="wolfram_result_content",
            passed=False,
            detail=f"no content rule for equation_type={equation_type!r}",
            status="not_applicable",
        )

    failed = [name for name, passed in checks if not passed]
    passed = not failed
    detail = (
        f"passed {len(checks)}/{len(checks)} executable content checks"
        if passed
        else f"failed={failed!r}"
    )
    return DimensionScore(name="wolfram_result_content", passed=passed, detail=detail)


def _score_dmi_variational_content(
    record: dict[str, Any], energy_terms: list[str], support_level: str
) -> DimensionScore:
    execution_status = record.get("wolfram_execution", {}).get("status")
    if execution_status == "skipped":
        return DimensionScore(
            name="dmi_variational_regression",
            passed=False,
            detail="execution skipped; DMI regression not evaluated",
            status="skipped",
        )
    if support_level in {"review_only", "unsupported"}:
        return DimensionScore(
            name="dmi_variational_regression",
            passed=False,
            detail=f"support_level={support_level!r}; DMI derivation is not claimed",
            status="not_applicable",
        )
    expected_keys = record.get("wolfram_results", {}).get("expected_keys", [])
    if "dmi_variational_regression" not in expected_keys:
        return DimensionScore(
            name="dmi_variational_regression",
            passed=False,
            detail="this generated script does not claim a DMI variational result",
            status="not_applicable",
        )

    dmi_terms = [
        term
        for term in energy_terms
        if term in {"interfacial_dmi", "bulk_dmi", "anisotropic_dmi", "dmi_unspecified"}
    ]
    if not dmi_terms:
        return DimensionScore(
            name="dmi_variational_regression",
            passed=False,
            detail="task has no DMI term",
            status="not_applicable",
        )
    if dmi_terms == ["dmi_unspecified"]:
        return DimensionScore(
            name="dmi_variational_regression",
            passed=False,
            detail="DMI symmetry unspecified; derivation intentionally requires review",
            status="not_applicable",
        )

    results = record.get("wolfram_results", {}).get("results")
    if not isinstance(results, dict):
        return DimensionScore(
            name="dmi_variational_regression",
            passed=False,
            detail="no structured Wolfram results found",
        )

    expected_type = dmi_terms[0]
    actual_type = str(results.get("dmi_density_type", ""))
    regression = str(results.get("dmi_variational_regression", ""))
    passed = actual_type == expected_type and regression == "True"
    return DimensionScore(
        name="dmi_variational_regression",
        passed=passed,
        detail=(
            f"expected_type={expected_type!r}, actual_type={actual_type!r}, "
            f"symbolic_regression={regression!r}"
        ),
    )


def _gold_answer_path(case_id: str, gold_dir: str | Path = DEFAULT_GOLD_DIR) -> Path:
    return _project_path(gold_dir) / f"{case_id}.yaml"


def _score_gold_answer_link(
    *,
    case_id: str,
    gold_answer: dict[str, Any],
    task: TheoryTask,
    equation_type: str,
    topology_field: str | None,
    support_level: str | None = None,
) -> DimensionScore:
    checks: list[tuple[str, bool]] = []
    checks.append(("case_id", gold_answer.get("case_id") == case_id))

    canonical = gold_answer.get("canonical_result", {})
    checks.append(("equation_type", canonical.get("equation_type") == equation_type))
    if canonical.get("support_level") is not None and support_level is not None:
        checks.append(("support_level", canonical.get("support_level") == support_level))

    topology = gold_answer.get("topology", {})
    if topology.get("field") is not None:
        checks.append(("topology_field", topology.get("field") == topology_field))

    required_assumptions = gold_answer.get("required_assumptions", [])
    if required_assumptions:
        missing_assumptions = [
            assumption for assumption in required_assumptions if assumption not in task.assumptions
        ]
        checks.append(("required_assumptions", not missing_assumptions))
    else:
        missing_assumptions = []

    full_derivation_assumptions = gold_answer.get("full_derivation_assumptions", [])
    if support_level == "full_derivation" and full_derivation_assumptions:
        missing_full_derivation_assumptions = [
            assumption
            for assumption in full_derivation_assumptions
            if assumption not in task.assumptions
        ]
        checks.append(
            ("full_derivation_assumptions", not missing_full_derivation_assumptions)
        )
    else:
        missing_full_derivation_assumptions = []

    gold_limit_checks = gold_answer.get("limit_checks", [])
    checks.append(("limit_checks_declared", isinstance(gold_limit_checks, list)))

    failed = [name for name, passed in checks if not passed]
    passed = not failed
    detail = "linked" if passed else f"failed={failed!r}"
    if missing_assumptions:
        detail += f", missing_assumptions={missing_assumptions!r}"
    if missing_full_derivation_assumptions:
        detail += (
            ", missing_full_derivation_assumptions="
            f"{missing_full_derivation_assumptions!r}"
        )
    return DimensionScore(name="gold_answer_linked", passed=passed, detail=detail)


def _review_item_covered(item: str, validation_text: str) -> bool:
    item_lower = item.lower()
    rules = [
        (("dmi", "symmetry"), ("dmi", "symmetry")),
        (("boundary",), ("boundary",)),
        (("stiffness",), ("stiffness", " k ")),
        (("sign", "g", "q"), ("sign", "gyrotropic", "topological charge")),
        (("sot", "polarization"), ("sot", "polarization")),
        (("topology", "n"), ("topology", " n", "neel")),
        (("compensation", "sublattice"), ("compensation", "sublattice", "sign")),
        (("single meron",), ("single meron", "half-integer", "boundary")),
        (("core polarity", "helicity"), ("core polarity", "helicity")),
        (("winding number", "skyrmion charge"), ("winding number", "skyrmion charge")),
        (("core polarity", "q-like"), ("core polarity", "q-like", "charge")),
    ]
    for triggers, required_terms in rules:
        if all(trigger in item_lower for trigger in triggers):
            return all(term in validation_text for term in required_terms)

    keywords = [
        token.strip(".,;:()[]`'\"").lower()
        for token in item_lower.replace("/", " ").split()
        if len(token.strip(".,;:()[]`'\"")) >= 4
    ]
    if not keywords:
        return True
    matched = sum(1 for keyword in keywords if keyword in validation_text)
    return matched >= max(1, min(2, len(keywords)))


def _score_gold_review_coverage(
    *,
    gold_answer: dict[str, Any],
    validation_items: list[dict[str, Any]],
) -> DimensionScore:
    human_review = gold_answer.get("human_review", {})
    if not isinstance(human_review, dict) or not human_review.get("required", False):
        return DimensionScore(
            name="gold_review_coverage",
            passed=True,
            detail="human review not required by gold answer",
        )

    checklist = human_review.get("checklist", [])
    if not isinstance(checklist, list) or not checklist:
        return DimensionScore(
            name="gold_review_coverage",
            passed=False,
            detail="gold answer requires human review but has no checklist",
        )

    validation_text = " ".join(
        " ".join(
            str(item.get(key, ""))
            for key in ["id", "message", "evidence", "recommendation"]
        )
        for item in validation_items
    ).lower()
    missing = [
        str(item)
        for item in checklist
        if not _review_item_covered(str(item), validation_text)
    ]
    passed = not missing
    detail = "all gold review checklist items covered" if passed else f"missing={missing!r}"
    return DimensionScore(name="gold_review_coverage", passed=passed, detail=detail)


def evaluate_case(
    case_path: str | Path,
    bundle_out: str | Path = DEFAULT_BUNDLE_DIR,
    *,
    execute_wolfram: bool = False,
    wolfram_timeout: int = 120,
) -> CaseScore:
    started = time.perf_counter()
    case_path = _project_path(case_path)
    bundle_out = _project_path(bundle_out)
    case = _load_yaml(case_path)
    case_id = str(case["case_id"])
    config = str(case["config"])
    expected = case.get("expected", {})
    if not isinstance(expected, dict):
        raise ValueError(f"expected must be a mapping in {case_path}")

    task = TheoryTask.from_yaml(_project_path(config))
    kb = KnowledgeBase()
    template = select_template(task, kb)
    physics_ir = build_physics_ir(task, template, kb)
    report = check_task(task, template, kb, physics_ir)
    paths = generate_task_bundle(
        task,
        template,
        report,
        bundle_out / case_id,
        physics_ir=physics_ir,
    )
    if execute_wolfram:
        execution = execute_wolfram_script(
            paths["wolfram"],
            bundle_out / case_id / "wolfram_logs",
            timeout_seconds=wolfram_timeout,
        )
        update_wolfram_execution_record(paths["record"], execution)

    wolfram_text = paths["wolfram"].read_text(encoding="utf-8")
    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    validation_items = record["validation"]["items"]

    dimensions: list[DimensionScore] = [
        _score_exact("material_class", physics_ir.material_class, expected.get("material_class")),
        _score_exact(
            "order_parameter",
            physics_ir.order_parameter.primary,
            expected.get("primary_order_parameter"),
        ),
        _score_exact("dynamics_type", physics_ir.dynamics.type, expected.get("dynamics_type")),
        _score_exact(
            "equation_type",
            physics_ir.dynamics.expected_equation_type,
            expected.get("equation_type"),
        ),
        _score_exact(
            "topology_field",
            physics_ir.order_parameter.topology_field,
            expected.get("topology_field"),
        ),
        _score_required_symbols(wolfram_text, case.get("required_wolfram_symbols", [])),
        _score_forbidden_symbols(wolfram_text, case.get("forbidden_wolfram_symbols", [])),
        DimensionScore(
            name="record_exists",
            passed=paths["record"].exists(),
            detail=str(paths["record"]),
        ),
    ]

    if "support_level" in expected:
        dimensions.append(
            _score_exact("support_level", physics_ir.support_level, expected["support_level"])
        )

    if expected.get("limit_checks"):
        dimensions.append(
            _score_contains_all("limit_checks", physics_ir.limit_checks, expected["limit_checks"])
        )
    if expected.get("energy_terms"):
        dimensions.append(
            _score_contains_all("energy_terms", physics_ir.energy_terms, expected["energy_terms"])
        )
    if "gyrotropic_term" in expected:
        dimensions.append(
            _score_exact(
                "gyrotropic_term",
                physics_ir.dynamics.gyrotropic_term,
                expected["gyrotropic_term"],
            )
        )
    if "requires_human_review" in expected:
        dimensions.append(
            _score_exact(
                "requires_human_review",
                physics_ir.confidence.requires_human_review,
                expected["requires_human_review"],
            )
        )
    if isinstance(expected.get("confidence"), dict):
        dimensions.extend(_score_confidence_thresholds(physics_ir, expected["confidence"]))
    if expected.get("validation_ids"):
        dimensions.append(_score_validation_ids(validation_items, expected["validation_ids"]))
    if execute_wolfram:
        dimensions.append(_score_wolfram_execution(record["wolfram_execution"]))
        dimensions.append(_score_wolfram_result_keys(record))
        dimensions.append(
            _score_wolfram_result_content(
                record,
                physics_ir.dynamics.expected_equation_type,
                physics_ir.support_level,
            )
        )
        dimensions.append(
            _score_dmi_variational_content(
                record,
                physics_ir.energy_terms,
                physics_ir.support_level,
            )
        )
    gold_path = _gold_answer_path(case_id)
    if gold_path.exists():
        gold_answer = _load_yaml(gold_path)
        dimensions.append(
            _score_gold_answer_link(
                case_id=case_id,
                gold_answer=gold_answer,
                task=task,
                equation_type=physics_ir.dynamics.expected_equation_type,
                topology_field=physics_ir.order_parameter.topology_field,
                support_level=physics_ir.support_level,
            )
        )
        dimensions.append(
            _score_gold_review_coverage(
                gold_answer=gold_answer,
                validation_items=validation_items,
            )
        )

    score, max_score = summarize_dimensions(dimensions)
    bundle_paths = {name: str(path) for name, path in paths.items()}
    return CaseScore(
        case_id=case_id,
        description=str(case.get("description", "")),
        config=config,
        score=score,
        max_score=max_score,
        support_level=physics_ir.support_level,
        dimensions=dimensions,
        bundle_paths=bundle_paths,
        duration_seconds=time.perf_counter() - started,
    )


def _case_paths(cases_dir: str | Path) -> list[Path]:
    cases_dir = _project_path(cases_dir)
    return sorted(cases_dir.glob("*.yaml"))


def _write_csv(path: Path, cases: list[CaseScore]) -> None:
    dimension_names = sorted(
        {dimension.name for case in cases for dimension in case.dimensions}
    )
    fieldnames = [
        "case_id",
        "support_level",
        "status",
        "passed",
        "score",
        "max_score",
        "duration_seconds",
        *dimension_names,
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for case in cases:
            dimension_map = {
                dimension.name: int(dimension.passed) if dimension.applicable else ""
                for dimension in case.dimensions
            }
            row = {
                "case_id": case.case_id,
                "support_level": case.support_level,
                "status": case.status,
                "passed": int(case.passed),
                "score": case.score,
                "max_score": case.max_score,
                "duration_seconds": f"{case.duration_seconds:.6f}",
            }
            row.update({name: dimension_map.get(name, "") for name in dimension_names})
            writer.writerow(row)


def _write_notes(path: Path, run: BenchmarkRun) -> None:
    support_counts = {
        support_level: sum(1 for case in run.cases if case.support_level == support_level)
        for support_level in ["full_derivation", "scaffold", "review_only", "unsupported"]
    }
    lines = [
        "# Benchmark Run",
        "",
        "Rule-based benchmark snapshot for plotting and paper analysis.",
        "",
        f"- Cases: {len(run.cases)}",
        f"- Cases satisfying criteria for their declared support level: {run.passed_cases}",
        f"- Total score: {run.total_score}/{run.max_score}",
        "- Support levels: "
        + ", ".join(f"{name}={count}" for name, count in support_counts.items()),
        "- A passing case is not automatically a full derivation; inspect `support_level` and N/A dimensions.",
        f"- Mean case duration: {sum(case.duration_seconds for case in run.cases) / len(run.cases):.3f} s"
        if run.cases
        else "- Mean case duration: n/a",
        "",
        "## Files",
        "",
        "- `benchmark_scores.csv`: flat table for plotting.",
        "- `benchmark_scores.json`: full case and dimension-level record.",
        "",
        "## Case Summary",
        "",
        "| Case | Support level | Score | Status |",
        "| --- | --- | ---: | :---: |",
    ]
    for case in run.cases:
        lines.append(
            f"| `{case.case_id}` | `{case.support_level}` | "
            f"{case.score}/{case.max_score} | {case.status} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_benchmark_cases(
    cases_dir: str | Path = DEFAULT_CASES_DIR,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    bundle_out: str | Path = DEFAULT_BUNDLE_DIR,
    archive_dir: str | Path | None = None,
    *,
    execute_wolfram: bool = False,
    wolfram_timeout: int = 120,
) -> BenchmarkRun:
    results_dir = _project_path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    case_scores = [
        evaluate_case(
            path,
            bundle_out,
            execute_wolfram=execute_wolfram,
            wolfram_timeout=wolfram_timeout,
        )
        for path in _case_paths(cases_dir)
    ]

    csv_path = results_dir / "benchmark_scores.csv"
    json_path = results_dir / "benchmark_scores.json"
    archive_path = _project_path(archive_dir) if archive_dir else None
    archive_paths: dict[str, Path] = {}
    if archive_path:
        archive_path.mkdir(parents=True, exist_ok=True)
        archive_paths = {
            "csv": archive_path / "benchmark_scores.csv",
            "json": archive_path / "benchmark_scores.json",
            "notes": archive_path / "notes.md",
        }
    run = BenchmarkRun(
        cases=case_scores,
        csv_path=csv_path,
        json_path=json_path,
        archive_dir=archive_path,
        archive_paths=archive_paths,
    )

    _write_csv(csv_path, case_scores)
    json_path.write_text(json.dumps(run.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")
    if archive_path:
        _write_csv(archive_paths["csv"], case_scores)
        archive_paths["json"].write_text(
            json.dumps(run.to_record(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_notes(archive_paths["notes"], run)
    return run
