from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .checker import CheckReport
from .consistency import assert_generated_bundle_consistent
from .resources import resource_dir, resource_file
from .schema import PhysicsIR, TheoryTask
from .selector import SelectedTemplate
from .wolfram import not_run_execution


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = resource_dir("templates")


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _record_id(
    task: TheoryTask,
    template: SelectedTemplate,
    physics_ir: PhysicsIR | None,
) -> str:
    payload = {
        "task": task.model_dump(),
        "template": template.__dict__,
        "physics_ir": physics_ir.model_dump() if physics_ir else None,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"stta-{digest}"


def _wolfram_result_keys(task: TheoryTask, physics_ir: PhysicsIR | None) -> list[str]:
    if physics_ir is None:
        return []
    if (
        physics_ir.dynamics.expected_equation_type == "topology_only"
        and physics_ir.support_level == "full_derivation"
        and task.texture == "meron"
    ):
        return [
            "meron_ansatz",
            "ansatz_constraint_regression",
            "topological_density",
            "boundary_conditions",
            "topological_charge",
            "literature_meron_source_charge",
            "literature_meron_transformed_charge",
            "literature_meron_target_charge",
            "literature_meron_exact_regression",
            "boundary_charge_regression",
            "half_charge_magnitude_regression",
            "winding_sign_regression",
            "polarity_sign_regression",
            "non_meron_boundary_control_charge",
            "non_meron_boundary_control_regression",
            "dimension_contract",
            "topology_dimension_regression",
            "topology_note",
        ]
    if (
        physics_ir.dynamics.expected_equation_type == "topology_only"
        and physics_ir.support_level == "full_derivation"
        and task.texture == "bimeron"
    ):
        return [
            "constituent_charges",
            "general_composite_charge",
            "literature_bimeron_source_charge",
            "literature_bimeron_transformed_charge",
            "literature_bimeron_target_charge",
            "literature_bimeron_exact_regression",
            "pairing_rules",
            "bimeron_topological_charge",
            "constituent_half_charge_regression",
            "charge_additivity_regression",
            "nontrivial_pairing_regression",
            "integer_charge_magnitude_regression",
            "trivial_pair_control_charge",
            "trivial_pair_control_regression",
            "dimension_contract",
            "topology_dimension_regression",
            "topology_note",
        ]
    if (
        physics_ir.dynamics.expected_equation_type == "topology_only"
        and physics_ir.support_level == "full_derivation"
        and task.texture == "vortex"
    ):
        return [
            "boundary_phase",
            "in_plane_boundary_field",
            "winding_number",
            "literature_vortex_source_winding",
            "literature_vortex_transformed_winding",
            "literature_vortex_target_winding",
            "literature_vortex_winding_exact_regression",
            "winding_regression",
            "unit_winding_magnitude_regression",
            "single_valued_boundary_regression",
            "core_polarity_dependent_charge",
            "literature_vortex_source_core_charge",
            "literature_vortex_transformed_core_charge",
            "literature_vortex_target_core_charge",
            "literature_vortex_core_charge_exact_regression",
            "winding_charge_distinction_regression",
            "vorticity_flip_regression",
            "core_polarity_flip_regression",
            "dimension_contract",
            "topology_dimension_regression",
            "topology_note",
        ]
    if physics_ir.dynamics.expected_equation_type == "topology_only":
        return ["topological_density", "topology_note"]
    if task.material == "collinear_antiferromagnet" and task.texture == "stripe_domain":
        return [
            "dmi_density_type",
            "dmi_variational_regression",
            "domain_wall_ansatz",
            "ansatz_constraint_regression",
            "collective_metric_integrand",
            "metric_boundary_regression",
            "sot_boundary_regression",
            "collective_metric_matrix",
            "metric_matrix_regression",
            "collective_mass_matrix_definition",
            "collective_mass_matrix",
            "mass_matrix_regression",
            "collective_damping_matrix_definition",
            "collective_damping_matrix",
            "damping_matrix_regression",
            "single_wall_sot_generalized_force",
            "sot_force_regression",
            "literature_wall_source_residual",
            "literature_wall_target_residual",
            "literature_wall_transformed_residual",
            "literature_wall_mass_bridge_regression",
            "literature_wall_damping_bridge_regression",
            "literature_wall_force_bridge_regression",
            "literature_wall_exact_regression",
            "chain_sot_force",
            "wall_chain_stability_matrix",
            "stability_matrix_regression",
            "stripe_chain_equation",
            "chain_equation_regression",
            "alpha_limit_regression",
            "dimension_contract",
            "energy_density_dimension_regression",
            "translation_dimension_regression",
            "angle_dimension_regression",
        ]
    if (
        task.material == "collinear_antiferromagnet"
        and task.texture == "skyrmion"
        and physics_ir.support_level == "full_derivation"
    ):
        return [
            "dmi_density_type",
            "dmi_variational_regression",
            "skyrmion_ansatz",
            "topological_density",
            "topological_charge",
            "topological_charge_regression",
            "collective_metric_radial_integrand",
            "metric_density_regression",
            "collective_metric_integral_definition",
            "collective_mass_matrix",
            "mass_matrix_regression",
            "collective_damping_matrix",
            "damping_matrix_regression",
            "damping_like_force_angular_density",
            "damping_like_translation_force",
            "damping_like_boundary_regression",
            "field_like_force_angular_density",
            "field_like_force_density_regression",
            "sot_radial_integral_definition",
            "sot_generalized_force",
            "sublattice_gyro_density_a",
            "sublattice_gyro_density_b",
            "sublattice_gyro_density_regression",
            "gyrotropic_cancellation",
            "gyrotropic_cancellation_regression",
            "inertial_equation",
            "inertial_equation_regression",
            "literature_afm_source_residual",
            "literature_afm_target_residual",
            "literature_afm_transformed_residual",
            "literature_afm_mass_bridge_regression",
            "literature_afm_damping_bridge_regression",
            "literature_afm_gyro_bridge_regression",
            "literature_afm_force_bridge_regression",
            "literature_afm_exact_regression",
            "alpha_limit_regression",
            "dimension_contract",
            "afm_energy_density_dimension_regression",
            "inertial_dimension_regression",
        ]
    if task.material == "collinear_antiferromagnet" and task.texture == "skyrmion":
        return [
            "dmi_density_type",
            "dmi_variational_regression",
            "topological_density",
            "collective_mass_matrix",
            "collective_damping_matrix",
            "gyrotropic_cancellation",
            "inertial_equation",
        ]
    if (
        task.material == "ferromagnet"
        and task.texture == "skyrmion"
        and physics_ir.support_level == "full_derivation"
    ):
        return [
            "dmi_density_type",
            "dmi_variational_regression",
            "skyrmion_ansatz",
            "topological_density",
            "topological_charge",
            "topological_charge_regression",
            "gyrotropic_angular_density",
            "gyrotropic_angular_density_expected",
            "gyrotropic_density_difference",
            "gyrotropic_density_regression",
            "dissipative_radial_integrand",
            "dissipative_density_regression",
            "collective_dissipation_integral_definition",
            "sot_force_angular_density",
            "sot_force_density_regression",
            "sot_radial_integral_definition",
            "field_like_translation_force",
            "field_like_boundary_regression",
            "sot_generalized_force",
            "gyrotropic_tensor",
            "gyrotropic_tensor_regression",
            "damping_tensor",
            "damping_tensor_regression",
            "thiele_equation",
            "thiele_equation_regression",
            "literature_thiele_source_residual",
            "literature_thiele_target_residual",
            "literature_thiele_transformed_residual",
            "literature_thiele_gyro_bridge_regression",
            "literature_thiele_damping_bridge_regression",
            "literature_thiele_force_bridge_regression",
            "literature_thiele_exact_regression",
            "alpha_limit_regression",
            "dimension_contract",
            "fm_energy_density_dimension_regression",
            "thiele_dimension_regression",
        ]
    if (
        task.material == "ferromagnet"
        and task.texture == "antiskyrmion"
        and physics_ir.support_level == "full_derivation"
    ):
        return [
            "dmi_density_type",
            "dmi_variational_regression",
            "antiskyrmion_ansatz",
            "ansatz_constraint_regression",
            "topological_density",
            "topological_charge",
            "topological_charge_regression",
            "gyrotropic_angular_density",
            "gyrotropic_density_regression",
            "gyrotropic_tensor",
            "gyrotropic_tensor_regression",
            "anisotropic_metric_radial_integrand",
            "anisotropic_metric_regression",
            "metric_anisotropy_ratio_regression",
            "isotropic_metric_limit_regression",
            "collective_dissipation_integral_definition",
            "damping_tensor",
            "damping_tensor_regression",
            "sot_force_angular_density",
            "sot_force_density_regression",
            "field_like_translation_force",
            "field_like_boundary_regression",
            "sot_radial_integral_definition",
            "sot_generalized_force",
            "anisotropic_dmi_angular_density",
            "anisotropic_dmi_projection_regression",
            "dmi_energy_projection",
            "dmi_helicity_derivative",
            "dmi_helicity_stationarity_regression",
            "thiele_equation",
            "thiele_equation_regression",
            "literature_antiskyrmion_source_residual",
            "literature_antiskyrmion_transformed_residual",
            "literature_antiskyrmion_target_residual",
            "literature_antiskyrmion_exact_regression",
            "alpha_limit_regression",
            "dimension_contract",
            "anti_energy_density_dimension_regression",
            "anti_thiele_dimension_regression",
        ]
    if task.material == "ferromagnet":
        return [
            "dmi_density_type",
            "dmi_variational_regression",
            "topological_density",
            "gyrotropic_tensor",
            "damping_tensor",
            "thiele_equation",
        ]
    return []


def generate_task_bundle(
    task: TheoryTask,
    template: SelectedTemplate,
    check_report: CheckReport,
    out_dir: str | Path = PROJECT_ROOT / "outputs",
    physics_ir: PhysicsIR | None = None,
) -> dict[str, Path]:
    out_dir = Path(out_dir)
    notebook_dir = out_dir / "notebooks"
    summary_dir = out_dir / "summaries"
    record_dir = out_dir / "records"
    notebook_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)
    record_dir.mkdir(parents=True, exist_ok=True)

    env = _env()
    wl_template = env.get_template("derivation.wl.j2")
    md_template = env.get_template("summary.md.j2")
    record_id = _record_id(task, template, physics_ir)

    context = {
        "task": task,
        "template": template,
        "physics_ir": physics_ir,
        "checks": check_report.checks,
        "warnings": check_report.warnings,
        "validation_items": check_report.items,
        "project_root": PROJECT_ROOT,
        "wolfram_library_path": resource_file(
            "mathematica", "SpinTextureTheory.wl"
        ),
        "wolfram_result_keys": _wolfram_result_keys(task, physics_ir),
        "record_id": record_id,
    }

    wl_path = notebook_dir / f"{task.task_name}.wl"
    md_path = summary_dir / f"{task.task_name}_summary.md"
    json_path = record_dir / f"{task.task_name}_record.json"

    wl_path.write_text(wl_template.render(**context), encoding="utf-8")
    md_path.write_text(md_template.render(**context), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "record_id": record_id,
                "record_schema_version": "1.1.0",
                "task": task.model_dump(),
                "physics_ir": physics_ir.model_dump() if physics_ir else None,
                "selected_template": template.__dict__,
                "validation": {
                    "ok": check_report.ok,
                    "items": check_report.to_record(),
                },
                "wolfram_execution": not_run_execution().to_record(),
                "wolfram_results": {
                    "status": "pending_execution",
                    "expected_keys": _wolfram_result_keys(task, physics_ir),
                    "results": None,
                },
                "artifact_contract": {
                    "human_report": str(md_path),
                    "wolfram_script": str(wl_path),
                    "machine_record": str(json_path),
                    "authoritative_source": "machine_record",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert_generated_bundle_consistent(json_path, md_path, wl_path)

    return {"wolfram": wl_path, "summary": md_path, "record": json_path}
