from spintexture_agent.nl_benchmark import evaluate_nl_benchmark_cases, evaluate_nl_case
from spintexture_agent.wolfram import WolframExecution


def _fake_wolfram_execution(wolfram_path, *args, **kwargs):
    name = wolfram_path.name
    wolfram_text = wolfram_path.read_text(encoding="utf-8")
    if "stripe" in name and "altermagnet" not in name:
        dmi_type = "unspecified" if 'dmiType = "unspecified"' in wolfram_text else "interfacial_dmi"
        result = {
            "dmi_density_type": dmi_type,
            "dmi_variational_regression": "Missing[NotApplicable]"
            if dmi_type == "unspecified"
            else "True",
            "domain_wall_ansatz": "{Sin[theta] Cos[Phi], Sin[theta] Sin[Phi], Cos[theta]}",
            "ansatz_constraint_regression": "True",
            "collective_metric_integrand": "{{Sech[(x-X)/Delta]^2/Delta^2,0},{0,Sech[(x-X)/Delta]^2}}",
            "metric_boundary_regression": "True",
            "sot_boundary_regression": "True",
            "collective_metric_matrix": "{{2/Delta,0},{0,2*Delta}}",
            "metric_matrix_regression": "True",
            "collective_mass_matrix_definition": "chi integral dq n dq n",
            "collective_mass_matrix": "{{2 chi/Delta,0},{0,2 chi Delta}}",
            "mass_matrix_regression": "True",
            "collective_damping_matrix_definition": "alpha s integral dq n dq n",
            "collective_damping_matrix": "{{2 alpha s/Delta,0},{0,2 alpha s Delta}}",
            "damping_matrix_regression": "True",
            "single_wall_sot_generalized_force": "{Pi tauFL, Pi Delta tauDL}",
            "sot_force_regression": "True",
            "literature_wall_source_residual": "{sourceX,sourcePhi}",
            "literature_wall_target_residual": "{targetX,targetPhi}",
            "literature_wall_transformed_residual": "{targetX,targetPhi}",
            "literature_wall_mass_bridge_regression": "True",
            "literature_wall_damping_bridge_regression": "True",
            "literature_wall_force_bridge_regression": "True",
            "literature_wall_exact_regression": "True",
            "chain_sot_force": "{tauDL Cos[Phi1],-tauDL Cos[Phi2],tauDL Cos[Phi3],-tauDL Cos[Phi4]}",
            "wall_chain_stability_matrix": "{{2 k,-k,0,-k},{-k,2 k,-k,0},{0,-k,2 k,-k},{-k,0,-k,2 k}}",
            "stability_matrix_regression": "True",
            "stripe_chain_equation": "{2 k u1[t]-k u2[t]-k u4[t]+alpha Derivative[1][u1][t]+chi Derivative[2][u1][t]==tauDL, Derivative[2][u4][t]==tauDL}",
            "chain_equation_regression": "True",
            "alpha_limit_regression": "True",
            "dimension_contract": '<|"basis"->{"energy","length","time"},"convention"->"one_dimensional_energy_per_transverse_area"|>',
            "energy_density_dimension_regression": "True",
            "translation_dimension_regression": "True",
            "angle_dimension_regression": "True",
        }
    elif name.startswith("afm_skyrmion"):
        result = {
            "dmi_density_type": "interfacial_dmi",
            "dmi_variational_regression": "True",
            "topological_density": "TopologicalDensity2D[nVec,x,y]",
            "collective_mass_matrix": "{{Msk,0},{0,Msk}}",
            "collective_damping_matrix": "{{GammaSk,0},{0,GammaSk}}",
            "gyrotropic_cancellation": "G_A + G_B == 0 in the compensated AFM limit",
            "inertial_equation": "M Rddot + Gamma Rdot == F_SOT",
        }
    elif name.startswith("fm_skyrmion"):
        result = {
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
            "alpha_limit_regression": "True",
            "dimension_contract": "two_dimensional_energy_functional",
            "fm_energy_density_dimension_regression": "True",
            "thiele_dimension_regression": "True",
        }
        if "Derived Thiele equation" not in wolfram_text:
            result = {
                "dmi_density_type": "interfacial_dmi",
                "dmi_variational_regression": "True",
                "topological_density": "TopologicalDensity2D[mVec,x,y]",
                "gyrotropic_tensor": "{{0,-4 Pi Qsk s},{4 Pi Qsk s,0}}",
                "damping_tensor": "{{alpha s Dsk,0},{0,alpha s Dsk}}",
                "thiele_equation": "G cross Rdot + alpha D Rdot == F_SOT",
            }
    elif name == "fm_meron.wl":
        result = {
            "topological_density": "TopologicalDensity2D[mVec,x,y]",
            "topology_note": "Boundary conditions set the single meron half charge.",
        }
    else:
        result = {}

    return WolframExecution(
        status="passed",
        command=["fake-wolfram"],
        exit_code=0,
        result=result,
    )


def test_evaluate_nl_case_parses_and_generates_core_route(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.nl_benchmark.execute_wolfram_script", _fake_wolfram_execution)
    case = evaluate_nl_case(
        "nl_benchmark_cases/NL_B2_en_afm_skyrmion_sot.yaml",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
    )

    dimensions = {dimension.name: dimension for dimension in case.dimensions}
    assert case.passed
    assert dimensions["prompt_parse"].passed
    assert dimensions["parsed_material"].passed
    assert dimensions["equation_type"].passed
    assert dimensions["wolfram_result_content"].passed
    assert case.parsed_config is not None


def test_evaluate_nl_benchmark_cases(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.nl_benchmark.execute_wolfram_script", _fake_wolfram_execution)
    run = evaluate_nl_benchmark_cases(
        results_dir=tmp_path / "results",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
        archive_dir=tmp_path / "archive",
    )

    assert len(run.cases) == 4
    assert run.passed_cases == 4
    assert run.total_score == run.max_score
    assert run.csv_path.exists()
    assert run.json_path.exists()
    assert run.notes_path.exists()
    assert run.archive_paths["csv"].exists()
    assert run.archive_paths["json"].exists()
    assert run.archive_paths["notes"].exists()


def test_evaluate_negative_nl_benchmark_cases(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.nl_benchmark.execute_wolfram_script", _fake_wolfram_execution)
    run = evaluate_nl_benchmark_cases(
        cases_dir="nl_benchmark_case_sets/negative_3",
        results_dir=tmp_path / "results",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
    )

    assert len(run.cases) == 3
    assert run.passed_cases == 3
    assert run.total_score == run.max_score

    e1 = next(case for case in run.cases if case.case_id == "NL_E1_afm_skyrmion_reject_fm_thiele")
    dimensions = {dimension.name: dimension for dimension in e1.dimensions}
    assert dimensions["equation_type"].passed
    assert dimensions["forbidden_wolfram_symbols"].passed
    assert dimensions["validation_ids"].passed


def test_evaluate_uncertainty_nl_benchmark_cases(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.nl_benchmark.execute_wolfram_script", _fake_wolfram_execution)
    run = evaluate_nl_benchmark_cases(
        cases_dir="nl_benchmark_case_sets/uncertainty_2",
        results_dir=tmp_path / "results",
        bundle_out=tmp_path / "bundles",
        execute_wolfram=True,
    )

    assert len(run.cases) == 2
    assert run.passed_cases == 2
    assert run.total_score == run.max_score

    noncollinear = next(
        case for case in run.cases if case.case_id == "NL_G2_zh_noncollinear_afm_skyrmion_sot_review"
    )
    dimensions = {dimension.name: dimension for dimension in noncollinear.dimensions}
    assert dimensions["parsed_material"].passed
    assert dimensions["topology_field"].passed
    assert dimensions["confidence_topology_definition_max"].passed
    assert dimensions["validation_ids"].passed
