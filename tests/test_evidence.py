import json
from pathlib import Path

from spintexture_agent.evidence import load_evidence_cards, run_evidence_card
from spintexture_agent.wolfram import WolframExecution


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _a4_generated_result() -> dict[str, str]:
    return {
        "collective_metric_matrix": "{{2/Delta, 0}, {0, 2*Delta}}",
        "collective_mass_matrix": "{{(2*chi)/Delta, 0}, {0, 2*chi*Delta}}",
        "collective_damping_matrix": "{{(2*alpha*s)/Delta, 0}, {0, 2*alpha*Delta*s}}",
        "single_wall_sot_generalized_force": "{wallPolarity*(-2*pz*tauDL + Pi*py*tauFL*Cos[Phic] - Pi*px*tauFL*Sin[Phic]), Delta*(-2*pz*tauFL - Pi*py*tauDL*Cos[Phic] + Pi*px*tauDL*Sin[Phic])}",
        "wall_chain_stability_matrix": "{{2*k, -k, 0, -k}, {-k, 2*k, -k, 0}, {0, -k, 2*k, -k}, {-k, 0, -k, 2*k}}",
        "chain_equation_regression": "True",
        "literature_wall_exact_regression": "True",
        "metric_boundary_regression": "True",
        "sot_boundary_regression": "True",
    }


def _a4_gold_result() -> dict[str, str]:
    return {
        "metric_matrix": "{{2/Delta,0},{0,2*Delta}}",
        "mass_matrix": "{{(2*chi)/Delta,0},{0,2*chi*Delta}}",
        "damping_matrix": "{{(2*alpha*s)/Delta,0},{0,2*alpha*Delta*s}}",
        "sot_generalized_force": "{wallPolarity*(-2*pz*tauDL+Pi*py*tauFL*Cos[Phic]-Pi*px*tauFL*Sin[Phic]),Delta*(-2*pz*tauFL-Pi*py*tauDL*Cos[Phic]+Pi*px*tauDL*Sin[Phic])}",
        "stability_matrix": "{{2*k,-k,0,-k},{-k,2*k,-k,0},{0,-k,2*k,-k},{-k,0,-k,2*k}}",
        "metric_boundary_vanish": "True",
        "sot_boundary_vanish": "True",
        "all_regressions": "True",
    }


def test_core3_evidence_cards_are_independent_and_sourced():
    cards = load_evidence_cards("evidence_cards/core3")

    assert {card.case_id for _, card in cards} == {
        "A4_afm_stripe_sot",
        "B1_fm_skyrmion_sot",
        "B2_afm_skyrmion_sot",
    }
    for _, card in cards:
        gold_path = PROJECT_ROOT / card.independent_gold_script
        gold_text = gold_path.read_text(encoding="utf-8")
        assert "Get[" not in gold_text
        assert "Needs[" not in gold_text
        assert card.expert_review.status == "pending"
        assert any(source.doi for source in card.sources if source.source_type == "primary_literature")
        assert {"analytic_gold", "boundary"}.issubset(
            {check.category for check in card.checks}
        )


def test_extended_antiskyrmion_evidence_is_independent_and_bounded():
    cards = load_evidence_cards("evidence_cards/extended")

    cards_by_case = {card.case_id: (path, card) for path, card in cards}
    assert {
        "B4_fm_antiskyrmion_sot",
        "C2_fm_meron_topology",
        "C3_fm_bimeron_topology",
        "C4_fm_vortex_topology",
    }.issubset(cards_by_case)
    _, card = cards_by_case["B4_fm_antiskyrmion_sot"]
    assert card.case_id == "B4_fm_antiskyrmion_sot"
    assert card.route_id == "fm_antiskyrmion_sot_full"
    assert card.expert_review.status == "pending"
    assert "aligned principal axes" in card.claim_scope
    assert {
        "analytic_gold",
        "topology",
        "mass_damping",
        "limit",
        "generalized_force",
        "dmi_symmetry",
        "boundary",
        "terminal_equation",
    }.issubset({check.category for check in card.checks})

    gold_path = PROJECT_ROOT / card.independent_gold_script
    gold_text = gold_path.read_text(encoding="utf-8")
    assert "Get[" not in gold_text
    assert "Needs[" not in gold_text
    assert "SpinTextureTheory" not in gold_text
    assert "ScaledPolarSpatialDerivatives" not in gold_text
    assert "AngularCollectiveMetricMatrix" not in gold_text
    assert "AngularLLGTorqueGeneralizedForce" not in gold_text


def test_extended_meron_evidence_is_independent_and_boundary_conditioned():
    cards = load_evidence_cards("evidence_cards/extended")
    cards_by_case = {card.case_id: (path, card) for path, card in cards}
    _, card = cards_by_case["C2_fm_meron_topology"]

    assert card.route_id == "fm_meron_topology_full"
    assert card.expert_review.status == "pending"
    assert "isolated axisymmetric FM meron" in card.claim_scope
    assert {
        "analytic_gold",
        "constraint",
        "topology",
        "boundary",
        "sign_control",
        "dimension",
    }.issubset({check.category for check in card.checks})

    gold_path = PROJECT_ROOT / card.independent_gold_script
    gold_text = gold_path.read_text(encoding="utf-8")
    assert "Get[" not in gold_text
    assert "Needs[" not in gold_text
    assert "SpinTextureTheory" not in gold_text
    assert "TopologicalDensity2D" not in gold_text
    assert "AxisymmetricTopologicalChargeFromBoundaries" not in gold_text


def test_extended_bimeron_evidence_is_independent_and_additivity_bounded():
    cards = load_evidence_cards("evidence_cards/extended")
    cards_by_case = {card.case_id: (path, card) for path, card in cards}
    _, card = cards_by_case["C3_fm_bimeron_topology"]

    assert card.route_id == "fm_bimeron_topology_full"
    assert card.expert_review.status == "pending"
    assert "well-separated two-meron" in card.claim_scope
    assert {
        "analytic_gold",
        "topology",
        "composition",
        "pairing",
        "boundary",
        "negative_control",
        "dimension",
    }.issubset({check.category for check in card.checks})

    gold_path = PROJECT_ROOT / card.independent_gold_script
    gold_text = gold_path.read_text(encoding="utf-8")
    assert "Get[" not in gold_text
    assert "Needs[" not in gold_text
    assert "SpinTextureTheory" not in gold_text
    assert "CompositeMeronTopologicalCharge" not in gold_text
    assert "AxisymmetricTopologicalChargeFromBoundaries" not in gold_text


def test_extended_vortex_evidence_is_independent_and_contour_bounded():
    cards = load_evidence_cards("evidence_cards/extended")
    cards_by_case = {card.case_id: (path, card) for path, card in cards}
    _, card = cards_by_case["C4_fm_vortex_topology"]

    assert card.route_id == "fm_vortex_topology_full"
    assert card.expert_review.status == "pending"
    assert "outside a finite regularized core" in card.claim_scope
    assert {
        "analytic_gold",
        "topology",
        "boundary",
        "core_boundary",
        "negative_control",
        "sign_control",
        "dimension",
    }.issubset({check.category for check in card.checks})

    gold_path = PROJECT_ROOT / card.independent_gold_script
    gold_text = gold_path.read_text(encoding="utf-8")
    assert "Get[" not in gold_text
    assert "Needs[" not in gold_text
    assert "SpinTextureTheory" not in gold_text
    assert "WindingNumberFromPhase" not in gold_text
    assert "TopologicalDensity2D" not in gold_text


def test_run_evidence_card_records_dual_path_success(monkeypatch, tmp_path):
    executions = iter(
        [
            WolframExecution(status="passed", result=_a4_generated_result()),
            WolframExecution(status="passed", result=_a4_gold_result()),
        ]
    )
    monkeypatch.setattr(
        "spintexture_agent.evidence.execute_wolfram_script",
        lambda *args, **kwargs: next(executions),
    )

    run = run_evidence_card(
        "evidence_cards/core3/A4_afm_stripe_sot.yaml",
        tmp_path,
    )

    assert run.passed
    assert all(check.passed for check in run.checks)
    checks = {check.check_id: check for check in run.checks}
    assert checks["a4_metric_boundary"].comparison == "both_true"
    assert checks["a4_sot_boundary"].comparison == "both_true"
    payload = json.loads(Path(run.generated_record).read_text(encoding="utf-8"))
    assert payload["independent_gold_validation"]["status"] == "passed"
    assert payload["independent_gold_validation"]["expert_review_status"] == "pending"
    assert Path(run.result_path).exists()
    assert Path(run.summary_path).exists()


def test_run_evidence_card_fails_on_cross_path_difference(monkeypatch, tmp_path):
    wrong_generated = _a4_generated_result()
    wrong_generated["collective_mass_matrix"] = "{{wrong,0},{0,wrong}}"
    executions = iter(
        [
            WolframExecution(status="passed", result=wrong_generated),
            WolframExecution(status="passed", result=_a4_gold_result()),
        ]
    )
    monkeypatch.setattr(
        "spintexture_agent.evidence.execute_wolfram_script",
        lambda *args, **kwargs: next(executions),
    )

    run = run_evidence_card(
        "evidence_cards/core3/A4_afm_stripe_sot.yaml",
        tmp_path,
    )

    assert not run.passed
    failed = {check.check_id for check in run.checks if not check.passed}
    assert failed == {"a4_mass_matrix"}
