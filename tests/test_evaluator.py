import json
from pathlib import Path

from spintexture_agent.evaluator import evaluate_benchmark_cases, evaluate_case
from spintexture_agent.wolfram import WolframExecution


def _full_fm_skyrmion_result() -> dict[str, str]:
    return {
        "dmi_density_type": "interfacial_dmi",
        "dmi_variational_regression": "True",
        "skyrmion_ansatz": "axisymmetric unit m",
        "topological_density": "polarity Sin[thetaProfile[r]] thetaPrime/(4 Pi r)",
        "topological_charge": "-polarity",
        "topological_charge_regression": "True",
        "gyrotropic_angular_density": "{{0,2 Pi polarity Sin[thetaProfile[r]] Derivative[1][thetaProfile][r]},{-2 Pi polarity Sin[thetaProfile[r]] Derivative[1][thetaProfile][r],0}}",
        "gyrotropic_angular_density_expected": "same projected density",
        "gyrotropic_density_difference": "{{0,0},{0,0}}",
        "gyrotropic_density_regression": "True",
        "dissipative_radial_integrand": "Pi Sin[thetaProfile[r]]^2/r + Pi r Derivative[1][thetaProfile][r]^2",
        "dissipative_density_regression": "True",
        "collective_dissipation_integral_definition": "Dsk == Pi Integrate[...]",
        "sot_force_angular_density": "Pi polarity tauDL projected_density",
        "sot_force_density_regression": "True",
        "sot_radial_integral_definition": "Isot == Integrate[...]",
        "field_like_translation_force": "{0,0}",
        "field_like_boundary_regression": "True",
        "sot_generalized_force": "Pi s polarity tauDL Isot {py,-px}",
        "gyrotropic_tensor": "{{0,4 Pi polarity s},{-4 Pi polarity s,0}}",
        "gyrotropic_tensor_regression": "True",
        "damping_tensor": "{{alpha s Dsk,0},{0,alpha s Dsk}}",
        "damping_tensor_regression": "True",
        "thiele_equation": "{Derivative[1][X][t] == tauDL, Derivative[1][Y][t] == tauDL}",
        "thiele_equation_regression": "True",
        "literature_thiele_source_residual": "{sourceX,sourceY}",
        "literature_thiele_target_residual": "{targetX,targetY}",
        "literature_thiele_transformed_residual": "{targetX,targetY}",
        "literature_thiele_gyro_bridge_regression": "True",
        "literature_thiele_damping_bridge_regression": "True",
        "literature_thiele_force_bridge_regression": "True",
        "literature_thiele_exact_regression": "True",
        "alpha_limit_regression": "True",
        "dimension_contract": "two_dimensional_energy_functional",
        "fm_energy_density_dimension_regression": "True",
        "thiele_dimension_regression": "True",
    }


def test_evaluate_benchmark_cases(tmp_path):
    run = evaluate_benchmark_cases(
        results_dir=tmp_path / "results",
        bundle_out=tmp_path / "bundles",
        archive_dir=tmp_path / "archive",
    )

    assert len(run.cases) == 11
    assert run.passed_cases == 11
    assert run.csv_path.exists()
    assert run.json_path.exists()
    assert run.archive_paths["csv"].exists()
    assert run.archive_paths["json"].exists()
    assert run.archive_paths["notes"].exists()

    payload = json.loads(run.json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["case_count"] == 11
    assert payload["summary"]["total_score"] == payload["summary"]["max_score"]
    assert payload["archive"]["archive_dir"] is not None
    linked = [
        case
        for case in payload["cases"]
        if any(dimension["name"] == "gold_answer_linked" for dimension in case["dimensions"])
    ]
    assert len(linked) == 7


def test_negative_afm_skyrmion_case_blocks_fm_thiele(tmp_path):
    case = evaluate_case(
        "benchmark_cases/E1_afm_skyrmion_not_fm_thiele.yaml",
        bundle_out=tmp_path / "bundles",
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert case.passed
    assert dimensions["forbidden_wolfram_symbols"].passed
    assert dimensions["validation_ids"].passed


def test_topology_only_case_avoids_thiele_template(tmp_path):
    case = evaluate_case(
        "benchmark_cases/C2_fm_meron_topology.yaml",
        bundle_out=tmp_path / "bundles",
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert case.passed
    assert dimensions["equation_type"].passed
    assert dimensions["forbidden_wolfram_symbols"].passed
    assert dimensions["requires_human_review"].passed


def test_bimeron_case_executes_composition_checks(tmp_path):
    case = evaluate_case(
        "benchmark_cases/C3_fm_bimeron_topology.yaml",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert case.passed
    assert case.support_level == "full_derivation"
    assert dimensions["wolfram_execution"].passed
    assert dimensions["wolfram_result_keys"].passed
    assert dimensions["wolfram_result_content"].passed
    assert "12/12" in dimensions["wolfram_result_content"].detail


def test_evaluate_case_records_optional_wolfram_skip(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.wolfram.shutil.which", lambda _: None)
    monkeypatch.setattr("spintexture_agent.wolfram.KNOWN_WOLFRAM_KERNEL_PATHS", [])
    case = evaluate_case(
        "benchmark_cases/A4_afm_stripe_sot.yaml",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert not case.passed
    assert case.status == "incomplete"
    assert dimensions["wolfram_execution"].status == "skipped"
    assert not dimensions["wolfram_execution"].passed
    assert "skipped" in dimensions["wolfram_execution"].detail
    assert dimensions["wolfram_result_keys"].status == "skipped"
    assert dimensions["wolfram_result_content"].status == "skipped"


def test_evaluate_case_scores_wolfram_result_keys(monkeypatch, tmp_path):
    def fake_execute(*args, **kwargs):
        return WolframExecution(
            status="passed",
            command=["fake-wolfram"],
            exit_code=0,
            result=_full_fm_skyrmion_result(),
        )

    monkeypatch.setattr("spintexture_agent.evaluator.execute_wolfram_script", fake_execute)
    case = evaluate_case(
        "benchmark_cases/B1_fm_skyrmion_sot.yaml",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert case.passed
    assert dimensions["wolfram_execution"].passed
    assert dimensions["wolfram_result_keys"].passed
    assert dimensions["wolfram_result_content"].passed
    assert dimensions["dmi_variational_regression"].passed


def test_evaluate_case_flags_wrong_wolfram_result_content(monkeypatch, tmp_path):
    def fake_execute(*args, **kwargs):
        result = _full_fm_skyrmion_result()
        result["gyrotropic_tensor"] = "{{Msk,0},{0,Msk}}"
        result["thiele_equation"] = "M Rddot + Gamma Rdot == F_SOT"
        return WolframExecution(
            status="passed",
            command=["fake-wolfram"],
            exit_code=0,
            result=result,
        )

    monkeypatch.setattr("spintexture_agent.evaluator.execute_wolfram_script", fake_execute)
    case = evaluate_case(
        "benchmark_cases/B1_fm_skyrmion_sot.yaml",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert not case.passed
    assert dimensions["wolfram_result_keys"].passed
    assert not dimensions["wolfram_result_content"].passed


def test_core_case_links_gold_answer(tmp_path):
    case = evaluate_case(
        "benchmark_cases/B2_afm_skyrmion_sot.yaml",
        bundle_out=tmp_path / "bundles",
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert case.passed
    assert dimensions["gold_answer_linked"].passed
    assert dimensions["gold_review_coverage"].passed


def test_uncertainty_benchmark_flags_complex_material_review(tmp_path):
    run = evaluate_benchmark_cases(
        cases_dir="benchmark_case_sets/uncertainty_2",
        results_dir=tmp_path / "results",
        bundle_out=tmp_path / "bundles",
    )

    assert len(run.cases) == 2
    assert run.passed_cases == 2

    altermagnet = next(case for case in run.cases if case.case_id.startswith("G1_"))
    dimensions = {dimension.name: dimension for dimension in altermagnet.dimensions}
    assert dimensions["requires_human_review"].passed
    assert dimensions["confidence_model_selection_max"].passed
    assert dimensions["confidence_ansatz_validity_max"].passed
    assert dimensions["validation_ids"].passed


def test_review_only_case_does_not_claim_symbolic_content(monkeypatch, tmp_path):
    def fake_execute(*args, **kwargs):
        return WolframExecution(
            status="passed",
            command=["fake-wolfram"],
            exit_code=0,
            result={},
        )

    monkeypatch.setattr("spintexture_agent.evaluator.execute_wolfram_script", fake_execute)
    case = evaluate_case(
        "benchmark_cases/F1_ferrimagnet_skyrmion_compensation.yaml",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert case.passed
    assert case.status == "review_only_passed"
    assert case.support_level == "review_only"
    assert dimensions["wolfram_result_keys"].status == "not_applicable"
    assert dimensions["wolfram_result_content"].status == "not_applicable"
    assert dimensions["dmi_variational_regression"].status == "not_applicable"


def test_gold_review_coverage_flags_missing_review_items(monkeypatch, tmp_path):
    def shallow_report(*args, **kwargs):
        from spintexture_agent.checker import CheckReport

        report = CheckReport()
        report.add(
            id="dynamics_type",
            status="pass",
            severity="info",
            message="Dynamics class selected.",
        )
        return report

    monkeypatch.setattr("spintexture_agent.evaluator.check_task", shallow_report)
    case = evaluate_case(
        "benchmark_cases/A4_afm_stripe_sot.yaml",
        bundle_out=tmp_path / "bundles",
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert not case.passed
    assert not dimensions["gold_review_coverage"].passed
    assert "boundary" in dimensions["gold_review_coverage"].detail


def test_core3_gold_derivation_docs_exist():
    for case_id in [
        "A4_afm_stripe_sot",
        "B1_fm_skyrmion_sot",
        "B2_afm_skyrmion_sot",
    ]:
        path = Path("gold_answers") / "derivations" / f"{case_id}.md"
        text = path.read_text(encoding="utf-8")
        assert "## Order Parameter" in text
        assert "## Energy Functional" in text
        assert "## Canonical Reduced Equation" in text
        assert "## Common Error Modes" in text
