import json
from pathlib import Path

from spintexture_agent.checker import check_task
from spintexture_agent.generator import generate_task_bundle
from spintexture_agent.ir import build_physics_ir
from spintexture_agent.kb import KnowledgeBase
from spintexture_agent.schema import TheoryTask
from spintexture_agent.selector import select_template


def _generate(config: str, tmp_path):
    task = TheoryTask.from_yaml(Path(config))
    kb = KnowledgeBase()
    template = select_template(task, kb)
    physics_ir = build_physics_ir(task, template, kb)
    report = check_task(task, template, kb, physics_ir)
    paths = generate_task_bundle(task, template, report, tmp_path, physics_ir=physics_ir)
    return task, template, physics_ir, report, paths


def test_generate_afm_stripe_bundle(tmp_path):
    _, _, physics_ir, _, paths = _generate("configs/afm_stripe_sot.yaml", tmp_path)
    assert paths["wolfram"].exists()
    assert paths["summary"].exists()
    assert paths["record"].exists()
    wolfram = paths["wolfram"].read_text(encoding="utf-8")
    assert "AFMSigmaEquation" in wolfram
    assert "CollectiveMassMatrix" in wolfram
    assert "LinearStabilityMatrix" in wolfram
    assert "Collective metric integrand" in wolfram
    assert "Mass matrix skeleton" not in wolfram
    assert "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN" in wolfram
    assert physics_ir.order_parameter.topology_field == "n"
    assert physics_ir.support_level == "full_derivation"
    assert physics_ir.knowledge_status == "cas_validated"
    assert physics_ir.capability_route_id == "afm_stripe_sot_full"
    assert physics_ir.dimension_contract is not None
    assert physics_ir.dimension_contract.convention == "one_dimensional_energy_per_transverse_area"
    assert physics_ir.dimension_contract.expected_equation_dimensions["translation_terms"] == "E L^-1"

    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    summary = paths["summary"].read_text(encoding="utf-8")
    assert record["record_id"].startswith("stta-")
    assert record["record_schema_version"] == "1.1.0"
    assert record["artifact_contract"]["authoritative_source"] == "machine_record"
    assert record["record_id"] in summary
    assert record["physics_ir"]["permitted_claim"] in summary
    assert record["physics_ir"]["evidence_status"]["benchmark"]["status"] == "registered"
    assert record["physics_ir"]["evidence_status"]["external_review"]["status"] == "pending"
    assert "### Independent evidence badges" in summary
    assert "`benchmark` | `registered`" in summary
    assert "## Accessible view" in summary
    assert "## Formal view" in summary
    assert "## Human review checklist" in summary
    assert f"Authoritative record ID: {record['record_id']}" in wolfram
    assert record["physics_ir"]["dynamics"]["expected_equation_type"] == "coupled_wall_chain"
    assert record["validation"]["ok"] is True
    assert "collective_mass_matrix" in record["wolfram_results"]["expected_keys"]
    assert "dmi_variational_regression" in record["wolfram_results"]["expected_keys"]
    assert "single_wall_sot_generalized_force" in record["wolfram_results"]["expected_keys"]
    assert "chain_equation_regression" in record["wolfram_results"]["expected_keys"]
    assert "literature_wall_exact_regression" in record["wolfram_results"]["expected_keys"]
    assert "metric_boundary_regression" in record["wolfram_results"]["expected_keys"]
    assert "sot_boundary_regression" in record["wolfram_results"]["expected_keys"]
    assert "literatureWallSourceResidual" in wolfram
    assert "literatureWallBridgeRules" in wolfram
    assert "dimension_contract" in record["wolfram_results"]["expected_keys"]
    assert "translation_dimension_regression" in record["wolfram_results"]["expected_keys"]
    assert any(item["id"] == "dimension_contract" for item in record["validation"]["items"])
    assert 'stripeChainEquation = "' not in wolfram


def test_generate_fm_skyrmion_bundle(tmp_path):
    _, _, physics_ir, _, paths = _generate("configs/fm_skyrmion_sot.yaml", tmp_path)
    wolfram = paths["wolfram"].read_text(encoding="utf-8")
    assert "AngularCollectiveGyrotropicTensor" in wolfram
    assert "AngularCollectiveMetricMatrix" in wolfram
    assert "AngularLLGTorqueGeneralizedForce" in wolfram
    assert "Derived Thiele equation" in wolfram
    assert 'AgentRecord["gyrotropic_tensor"' in wolfram
    assert 'AgentRecord["thiele_equation"' in wolfram
    assert physics_ir.order_parameter.topology_field == "m"
    assert physics_ir.support_level == "full_derivation"
    assert physics_ir.dimension_contract is not None
    assert physics_ir.dimension_contract.convention == "two_dimensional_energy_functional"

    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    assert "gyrotropic_tensor" in record["wolfram_results"]["expected_keys"]
    assert "thiele_equation" in record["wolfram_results"]["expected_keys"]
    assert "topological_charge_regression" in record["wolfram_results"]["expected_keys"]
    assert "sot_force_density_regression" in record["wolfram_results"]["expected_keys"]
    assert "thiele_dimension_regression" in record["wolfram_results"]["expected_keys"]
    assert "literature_thiele_exact_regression" in record["wolfram_results"]["expected_keys"]
    assert "literatureThieleSourceResidual" in wolfram
    assert "-4 Pi s literatureThieleSourceResidual" in wolfram
    assert "literatureAntiSourceResidual" not in wolfram
    assert 'thieleEquation = "' not in wolfram


def test_generate_afm_skyrmion_bundle(tmp_path):
    _, _, physics_ir, _, paths = _generate("configs/afm_skyrmion_inertia.yaml", tmp_path)
    wolfram = paths["wolfram"].read_text(encoding="utf-8")
    assert "AngularCollectiveMetricMatrix" in wolfram
    assert "AngularGeneralizedForceDensity" in wolfram
    assert "Derived AFM inertial equation" in wolfram
    assert "Sublattice gyrotropic cancellation" in wolfram
    assert "Thiele target equation" not in wolfram
    assert 'AgentRecord["collective_mass_matrix"' in wolfram
    assert 'AgentRecord["inertial_equation"' in wolfram
    assert physics_ir.dynamics.gyrotropic_term == "cancelled_in_compensated_limit"
    assert physics_ir.support_level == "full_derivation"
    assert physics_ir.dimension_contract is not None
    assert physics_ir.dimension_contract.convention == "two_dimensional_afm_sigma_model"

    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    assert "collective_mass_matrix" in record["wolfram_results"]["expected_keys"]
    assert "inertial_equation" in record["wolfram_results"]["expected_keys"]
    assert "gyrotropic_cancellation_regression" in record["wolfram_results"]["expected_keys"]
    assert "field_like_force_density_regression" in record["wolfram_results"]["expected_keys"]
    assert "inertial_dimension_regression" in record["wolfram_results"]["expected_keys"]
    assert "literature_afm_exact_regression" in record["wolfram_results"]["expected_keys"]
    assert "literatureAFMSourceResidual" in wolfram
    assert "literatureAFMBridgeRules" in wolfram
    assert 'inertialEquation = "' not in wolfram


def test_generate_antiskyrmion_routes_anisotropic_dmi(tmp_path):
    _, _, physics_ir, _, paths = _generate("configs/fm_antiskyrmion_sot.yaml", tmp_path)
    wolfram = paths["wolfram"].read_text(encoding="utf-8")

    assert physics_ir.support_level == "full_derivation"
    assert physics_ir.dimension_contract is not None
    assert physics_ir.dimension_contract.convention == "two_dimensional_elliptic_antiskyrmion"
    assert "anisotropic_dmi" in physics_ir.energy_terms
    assert 'dmiType = "anisotropic_dmi";' in wolfram
    assert "AnisotropicDMIDensity[field, coords2D, Dmi, 3]" in wolfram
    assert "ScaledPolarSpatialDerivatives" in wolfram
    assert "Derived anisotropic antiskyrmion Thiele equation" in wolfram
    assert "Elliptic dissipative tensor projection" in wolfram
    assert "literatureAntiSourceResidual" in wolfram
    assert "-4 Pi s literatureAntiSourceResidual" in wolfram

    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    assert "anisotropic_metric_regression" in record["wolfram_results"]["expected_keys"]
    assert "anisotropic_dmi_projection_regression" in record["wolfram_results"]["expected_keys"]
    assert "anti_thiele_dimension_regression" in record["wolfram_results"]["expected_keys"]
    assert (
        "literature_antiskyrmion_exact_regression"
        in record["wolfram_results"]["expected_keys"]
    )
    assert (
        "evidence_cards/extended/B4_fm_antiskyrmion_sot.yaml"
        in physics_ir.evidence_refs
    )
    assert 'thieleEquation = "' not in wolfram


def test_generate_bimeron_topology_bundle(tmp_path):
    _, _, physics_ir, _, paths = _generate("configs/fm_bimeron_topology.yaml", tmp_path)
    wolfram = paths["wolfram"].read_text(encoding="utf-8")

    assert physics_ir.support_level == "full_derivation"
    assert physics_ir.dynamics.expected_equation_type == "topology_only"
    assert physics_ir.order_parameter.topology_field == "m"
    assert physics_ir.limit_checks == []
    assert physics_ir.dimension_contract is not None
    assert physics_ir.dimension_contract.convention == "dimensionless_topological_invariant"
    assert "CompositeMeronTopologicalCharge" in wolfram
    assert "Derived bimeron charge" in wolfram
    assert "trivialPairControlRegression" in wolfram

    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    expected_keys = record["wolfram_results"]["expected_keys"]
    assert "general_composite_charge" in expected_keys
    assert "bimeron_topological_charge" in expected_keys
    assert "trivial_pair_control_regression" in expected_keys
    assert "literature_bimeron_exact_regression" in expected_keys
    assert (
        "evidence_cards/extended/C3_fm_bimeron_topology.yaml"
        in physics_ir.evidence_refs
    )


def test_generate_meron_topology_bundle_has_sign_and_boundary_controls(tmp_path):
    _, _, physics_ir, _, paths = _generate("configs/fm_meron_topology.yaml", tmp_path)
    wolfram = paths["wolfram"].read_text(encoding="utf-8")
    record = json.loads(paths["record"].read_text(encoding="utf-8"))

    assert physics_ir.capability_route_id == "fm_meron_topology_full"
    assert (
        "evidence_cards/extended/C2_fm_meron_topology.yaml"
        in physics_ir.evidence_refs
    )
    assert "windingSignRegression" in wolfram
    assert "polaritySignRegression" in wolfram
    assert "nonMeronBoundaryControlCharge" in wolfram
    expected_keys = record["wolfram_results"]["expected_keys"]
    assert "winding_sign_regression" in expected_keys
    assert "polarity_sign_regression" in expected_keys
    assert "non_meron_boundary_control_charge" in expected_keys
    assert "non_meron_boundary_control_regression" in expected_keys
    assert "literature_meron_exact_regression" in expected_keys


def test_generate_vortex_topology_bundle_references_independent_evidence(tmp_path):
    _, _, physics_ir, _, paths = _generate("configs/fm_vortex_topology.yaml", tmp_path)
    wolfram = paths["wolfram"].read_text(encoding="utf-8")
    record = json.loads(paths["record"].read_text(encoding="utf-8"))

    assert physics_ir.capability_route_id == "fm_vortex_topology_full"
    assert (
        "evidence_cards/extended/C4_fm_vortex_topology.yaml"
        in physics_ir.evidence_refs
    )
    assert "WindingNumberFromPhase" in wolfram
    assert "windingChargeDistinctionRegression" in wolfram
    assert "vorticityFlipRegression" in wolfram
    assert "corePolarityFlipRegression" in wolfram
    expected_keys = record["wolfram_results"]["expected_keys"]
    assert "winding_number" in expected_keys
    assert "single_valued_boundary_regression" in expected_keys
    assert "winding_charge_distinction_regression" in expected_keys
    assert "vorticity_flip_regression" in expected_keys
    assert "core_polarity_flip_regression" in expected_keys
    assert "literature_vortex_winding_exact_regression" in expected_keys
    assert "literature_vortex_core_charge_exact_regression" in expected_keys
