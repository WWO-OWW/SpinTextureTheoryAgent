import hashlib
import json
from pathlib import Path

import yaml

from spintexture_agent.evidence import EvidenceCard
from spintexture_agent.literature import LiteratureReproductionRecord
from spintexture_agent.machine_audit import MachineAuditSpec, run_machine_audit_spec


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARD_PATH = PROJECT_ROOT / "evidence_cards/core3/A4_afm_stripe_sot.yaml"
SPEC_PATH = PROJECT_ROOT / "machine_audit_specs/core3/A4_afm_stripe_sot.yaml"
B4_SPEC_PATH = (
    PROJECT_ROOT / "machine_audit_specs/extended/B4_fm_antiskyrmion_sot.yaml"
)
C2_SPEC_PATH = (
    PROJECT_ROOT / "machine_audit_specs/extended/C2_fm_meron_topology.yaml"
)
C3_SPEC_PATH = (
    PROJECT_ROOT / "machine_audit_specs/extended/C3_fm_bimeron_topology.yaml"
)
C4_SPEC_PATH = (
    PROJECT_ROOT / "machine_audit_specs/extended/C4_fm_vortex_topology.yaml"
)


def test_extended_antiskyrmion_audit_preserves_material_review_boundary():
    spec = MachineAuditSpec.from_yaml(B4_SPEC_PATH)

    assert spec.route_id == "fm_antiskyrmion_sot_full"
    assert spec.literature_reproduction_record == (
        "literature_reproduction_records/extended/B4_fm_antiskyrmion_sot.yaml"
    )
    assert spec.material_symmetry_record is None
    material_checks = [
        check for check in spec.checks if check.scope == "material_applicability"
    ]
    assert material_checks
    assert all(check.on_missing == "incomplete" for check in material_checks)
    assert {
        "b4_add_inertia",
        "b4_use_neel_topology",
        "b4_mutate_dmi_family",
        "b4_break_dmi_projection",
        "b4_break_terminal_equation",
        "b4_break_literature_transform",
    }.issubset({mutation.mutation_id for mutation in spec.mutations})


def test_extended_meron_audit_requires_boundaries_and_sign_falsification():
    spec = MachineAuditSpec.from_yaml(C2_SPEC_PATH)

    assert spec.route_id == "fm_meron_topology_full"
    assert spec.literature_reproduction_record == (
        "literature_reproduction_records/extended/C2_fm_meron_topology.yaml"
    )
    assert spec.material_symmetry_record is None
    material_checks = [
        check for check in spec.checks if check.scope == "material_applicability"
    ]
    assert material_checks
    assert all(check.on_missing == "incomplete" for check in material_checks)
    assert {
        "c2_remove_registered_boundaries",
        "c2_break_boundary_charge",
        "c2_break_winding_sign",
        "c2_break_polarity_sign",
        "c2_accept_wrong_far_boundary",
        "c2_break_dimension_contract",
        "c2_break_literature_transform",
    }.issubset({mutation.mutation_id for mutation in spec.mutations})


def test_extended_bimeron_audit_requires_additive_separated_decomposition():
    spec = MachineAuditSpec.from_yaml(C3_SPEC_PATH)

    assert spec.route_id == "fm_bimeron_topology_full"
    assert spec.literature_reproduction_record == (
        "literature_reproduction_records/extended/C3_fm_bimeron_topology.yaml"
    )
    assert spec.material_symmetry_record is None
    material_checks = [
        check for check in spec.checks if check.scope == "material_applicability"
    ]
    assert material_checks
    assert all(check.on_missing == "incomplete" for check in material_checks)
    assert {
        "c3_remove_decomposition_assumptions",
        "c3_break_constituent_charges",
        "c3_break_additivity",
        "c3_break_pairing",
        "c3_break_integer_charge",
        "c3_accept_trivial_pair",
        "c3_break_dimension_contract",
        "c3_break_literature_transform",
    }.issubset({mutation.mutation_id for mutation in spec.mutations})


def test_extended_vortex_audit_separates_winding_from_core_charge():
    spec = MachineAuditSpec.from_yaml(C4_SPEC_PATH)

    assert spec.route_id == "fm_vortex_topology_full"
    assert spec.literature_reproduction_record == (
        "literature_reproduction_records/extended/C4_fm_vortex_topology.yaml"
    )
    assert spec.material_symmetry_record is None
    material_checks = [
        check for check in spec.checks if check.scope == "material_applicability"
    ]
    assert material_checks
    assert all(check.on_missing == "incomplete" for check in material_checks)
    assert {
        "c4_remove_boundary_core_assumptions",
        "c4_break_winding",
        "c4_break_unit_winding",
        "c4_break_single_valued_boundary",
        "c4_equate_winding_and_charge",
        "c4_break_vorticity_flip",
        "c4_break_core_polarity_flip",
        "c4_break_dimension_contract",
        "c4_break_literature_winding_transform",
        "c4_break_literature_core_transform",
    }.issubset({mutation.mutation_id for mutation in spec.mutations})


def _fake_a4_evidence(tmp_path: Path, *, dmi_type: str = "interfacial_dmi") -> Path:
    card = EvidenceCard.from_yaml(CARD_PATH)
    run_dir = tmp_path / "runs" / card.card_id
    run_dir.mkdir(parents=True)
    record_path = tmp_path / "record.json"
    record_path.write_text(
        json.dumps(
            {
                "physics_ir": {
                    "material_class": "collinear_antiferromagnet",
                    "energy_terms": ["exchange", "interfacial_dmi"],
                    "dynamics": {
                        "type": "sigma_model",
                        "inertial_term": True,
                        "gyrotropic_term": "cancelled_in_compensated_limit",
                    },
                    "order_parameter": {"topology_field": "n"},
                },
                "task": {
                    "material": "collinear_antiferromagnet",
                    "texture": "stripe_domain",
                    "parameters": {
                        "magnetic_space_group": "arbitrary text must not count",
                        "sot_response_tensor": "arbitrary text must not count",
                    },
                },
                "wolfram_results": {
                    "results": {
                        "dmi_density_type": dmi_type,
                        "collective_mass_matrix": "{{(2*chi)/Delta, 0}, {0, 2*chi*Delta}}",
                        "collective_damping_matrix": (
                            "{{(2*alpha*s)/Delta, 0}, {0, 2*alpha*Delta*s}}"
                        ),
                        "single_wall_sot_generalized_force": "{FX, FPhi}",
                        "literature_wall_mass_bridge_regression": "True",
                        "literature_wall_damping_bridge_regression": "True",
                        "literature_wall_force_bridge_regression": "True",
                        "literature_wall_exact_regression": "True",
                        "literature_wall_source_residual": "{sourceX,sourcePhi}",
                        "literature_wall_transformed_residual": "{targetX,targetPhi}",
                        "literature_wall_target_residual": "{targetX,targetPhi}",
                        "ansatz_constraint_regression": "True",
                        "dmi_variational_regression": "True",
                        "energy_density_dimension_regression": "True",
                        "translation_dimension_regression": "True",
                        "angle_dimension_regression": "True",
                        "alpha_limit_regression": "True",
                        "metric_boundary_regression": "True",
                        "sot_boundary_regression": "True",
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    evidence_path = run_dir / "evidence_result.json"
    evidence_path.write_text(
        json.dumps(
            {
                "card_id": card.card_id,
                "case_id": card.case_id,
                "route_id": card.route_id,
                "passed": True,
                "generated_execution_status": "passed",
                "gold_execution_status": "passed",
                "generated_record": str(record_path),
                "gold_result": None,
                "expert_review_status": "pending",
                "checks": [
                    {
                        "check_id": check.check_id,
                        "category": check.category,
                        "comparison": check.comparison,
                        "passed": True,
                        "generated_key": check.generated_key,
                        "gold_key": check.gold_key,
                        "generated_value": "True",
                        "gold_value": "True",
                        "detail": "test fixture",
                    }
                    for check in card.checks
                ],
                "result_path": str(evidence_path),
                "summary_path": str(run_dir / "evidence_summary.md"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return tmp_path / "runs"


def _spec_with_symmetry_record(tmp_path: Path, artifact_hash: str) -> Path:
    artifact = tmp_path / "symmetry_source.txt"
    artifact.write_text("independent magnetic symmetry output\n", encoding="utf-8")
    symmetry_record = tmp_path / "material_symmetry.yaml"
    symmetry_record.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "record_id": "test_material_symmetry",
                "material_name": "Test material",
                "structure_identifier": "test-structure-001",
                "magnetic_space_group": "P_test",
                "source_kind": "spglib",
                "source_version": "test-version",
                "source_reference": "test fixture",
                "source_artifact": str(artifact),
                "source_artifact_sha256": artifact_hash,
                "allowed_dmi_families": ["interfacial_dmi"],
                "allowed_sot_tensor_forms": ["in_plane_damping_like"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    spec_payload = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    spec_payload["material_symmetry_record"] = str(symmetry_record)
    spec_path = tmp_path / "audit_spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(spec_payload, sort_keys=False), encoding="utf-8"
    )
    return spec_path


def test_machine_audit_separates_formal_pass_from_material_incompleteness(tmp_path):
    evidence_root = _fake_a4_evidence(tmp_path)
    result = run_machine_audit_spec(SPEC_PATH, evidence_root, tmp_path / "audit")

    assert result.formal_route_status == "pass"
    assert result.material_applicability_status == "incomplete"
    assert result.overall_status == "conditional_pass"
    assert all(mutation.status == "pass" for mutation in result.mutations)
    badges = {badge.badge: badge.status for badge in result.verification_badges}
    assert badges["literature_alignment"] == "pass"
    assert badges["material_specific_symmetry"] == "incomplete"


def test_a4_machine_audit_mutates_generated_boundary_regressions():
    spec = MachineAuditSpec.from_yaml(SPEC_PATH)
    mutations = {mutation.mutation_id: mutation for mutation in spec.mutations}

    assert mutations["a4_break_metric_boundary"].must_fail_checks == [
        "a4_metric_boundary"
    ]
    assert mutations["a4_break_sot_boundary"].must_fail_checks == ["a4_sot_boundary"]


def test_machine_audit_rejects_wrong_executed_dmi_family(tmp_path):
    evidence_root = _fake_a4_evidence(tmp_path, dmi_type="bulk_dmi")
    result = run_machine_audit_spec(SPEC_PATH, evidence_root, tmp_path / "audit")

    assert result.formal_route_status == "fail"
    assert result.overall_status == "fail"
    failed = {check.check_id for check in result.checks if check.status == "fail"}
    assert failed == {"a4_sym_dmi_result"}


def test_hashed_material_symmetry_record_can_complete_material_scope(tmp_path):
    evidence_root = _fake_a4_evidence(tmp_path)
    artifact_text = b"independent magnetic symmetry output\n"
    spec_path = _spec_with_symmetry_record(
        tmp_path, hashlib.sha256(artifact_text).hexdigest()
    )
    result = run_machine_audit_spec(spec_path, evidence_root, tmp_path / "audit")

    assert result.formal_route_status == "pass"
    assert result.material_applicability_status == "pass"
    assert result.overall_status == "pass"
    assert "material_symmetry_record" in result.input_artifacts
    assert "material_symmetry_source" in result.input_artifacts


def test_tampered_material_symmetry_source_fails_material_scope(tmp_path):
    evidence_root = _fake_a4_evidence(tmp_path)
    spec_path = _spec_with_symmetry_record(tmp_path, "0" * 64)
    result = run_machine_audit_spec(spec_path, evidence_root, tmp_path / "audit")

    assert result.material_applicability_status == "fail"
    assert result.overall_status == "fail"
    failed = {check.check_id for check in result.checks if check.status == "fail"}
    assert failed == {"a4_material_symmetry_provenance"}


def test_literature_record_rejects_tampered_source_expression_hash(tmp_path):
    source = (
        PROJECT_ROOT
        / "literature_reproduction_records/core3/A4_afm_stripe_sot.yaml"
    )
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["locators"][0]["source_expression"] += " + tampered"
    tampered = tmp_path / "tampered_literature.yaml"
    tampered.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    try:
        LiteratureReproductionRecord.from_yaml(tampered)
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("Tampered source-expression hash was accepted.")


def test_literature_record_rejects_reused_blinded_token(tmp_path):
    source = (
        PROJECT_ROOT
        / "literature_reproduction_records/core3/A4_afm_stripe_sot.yaml"
    )
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    mappings = payload["claims"][0]["blinded_symbol_mappings"]
    mappings[1]["token"] = mappings[0]["token"]
    tampered = tmp_path / "reused_token.yaml"
    tampered.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    try:
        LiteratureReproductionRecord.from_yaml(tampered)
    except ValueError as exc:
        assert "Blinded tokens must be unique" in str(exc)
    else:
        raise AssertionError("Reused blinded symbol token was accepted.")


def test_exact_literature_claim_requires_executable_wolfram_assertion(tmp_path):
    source = (
        PROJECT_ROOT
        / "literature_reproduction_records/core3/B1_fm_skyrmion_sot.yaml"
    )
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    claim = payload["claims"][0]
    claim["assertions"] = [
        assertion
        for assertion in claim["assertions"]
        if assertion["path"] != claim["executable_regression_key"]
    ]
    invalid = tmp_path / "exact_without_regression.yaml"
    invalid.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    try:
        LiteratureReproductionRecord.from_yaml(invalid)
    except ValueError as exc:
        assert "must assert its Wolfram regression" in str(exc)
    else:
        raise AssertionError("Exact literature claim without regression was accepted.")
