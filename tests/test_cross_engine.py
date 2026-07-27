import json
from pathlib import Path

import pytest

from spintexture_agent.cli import build_parser
from spintexture_agent.cross_engine import (
    DEFAULT_CORE3_OUTPUT,
    DEFAULT_CORE3_SPECS,
    EXPECTED_CHECK_IDS,
    CrossEngineSpec,
    CrossEngineSuiteResult,
    load_cross_engine_specs,
    run_cross_engine_suite,
    verify_cross_engine_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_core3_specs_freeze_bounded_claims_without_expected_results():
    loaded = load_cross_engine_specs(DEFAULT_CORE3_SPECS)

    assert {spec.route_id for _, spec in loaded} == set(EXPECTED_CHECK_IDS)
    for path, spec in loaded:
        payload = json.loads(json.dumps(spec.model_dump(mode="json")))
        serialized = json.dumps(payload).lower()
        assert "expected_expression" not in serialized
        assert "wolfram_result" not in serialized
        assert spec.independence.allowed_input_artifacts == [
            str(path.relative_to(PROJECT_ROOT))
        ]
        assert any("mathematica/gold" in item for item in spec.independence.prohibited_input_artifacts)
        assert spec.precision_digits == [40, 60, 80]


def test_cross_engine_runner_has_no_wolfram_execution_path():
    source = (PROJECT_ROOT / "src/spintexture_agent/cross_engine.py").read_text(
        encoding="utf-8"
    )

    assert "execute_wolfram" not in source
    assert "WolframKernel" not in source
    assert "subprocess" not in source


def test_registered_core3_execution_has_convergence_and_honest_na_semantics():
    suite = CrossEngineSuiteResult.model_validate_json(
        (DEFAULT_CORE3_OUTPUT / "cross_engine_suite.json").read_text(encoding="utf-8")
    )

    assert suite.passed
    assert (suite.passed_route_count, suite.route_count) == (3, 3)
    assert (suite.passed_check_count, suite.failed_check_count) == (16, 0)
    assert suite.not_applicable_check_count == 3
    for route in suite.routes:
        assert route.passed
        assert route.not_applicable_check_count == 1
        assert route.passed_check_count + route.not_applicable_check_count == len(
            route.checks
        )
        for check in route.checks:
            if check.method == "sympy_plus_mpmath":
                assert check.convergence
                for convergence in check.convergence:
                    assert convergence.converged_at_final_precision
                    assert [point.precision_digits for point in convergence.points] == [
                        40,
                        60,
                        80,
                    ]
            elif check.method == "not_applicable":
                assert check.status == "not_applicable"
                assert not check.required


def test_registered_route_results_pass_integrity_verification():
    for result_path in sorted(DEFAULT_CORE3_OUTPUT.glob("*/cross_engine_result.json")):
        verification = verify_cross_engine_result(result_path)
        assert verification.eligible_for_cross_engine_pass
        assert verification.issues == []


def test_cross_engine_verifier_rejects_runner_hash_drift(tmp_path):
    source = next(DEFAULT_CORE3_OUTPUT.glob("*/cross_engine_result.json"))
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["runner_artifact"]["sha256"] = "0" * 64
    result_path = tmp_path / "cross_engine_result.json"
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    verification = verify_cross_engine_result(result_path)

    assert not verification.eligible_for_cross_engine_pass
    assert "cross-engine runner artifact hash drift" in verification.issues


def test_cross_engine_run_is_non_overwriting():
    with pytest.raises(FileExistsError, match="never overwritten"):
        run_cross_engine_suite(DEFAULT_CORE3_SPECS, DEFAULT_CORE3_OUTPUT)


def test_cross_engine_cli_contract():
    parser = build_parser()
    run_args = parser.parse_args(
        ["cross-engine", "run", "--specs", "specs", "--out", "results", "--require-pass"]
    )
    verify_args = parser.parse_args(
        [
            "cross-engine",
            "verify",
            "--result",
            "result.json",
            "--route",
            "fm_skyrmion_sot_full",
            "--require-eligible",
        ]
    )

    assert run_args.specs == "specs"
    assert run_args.out == "results"
    assert run_args.require_pass
    assert verify_args.route == "fm_skyrmion_sot_full"
    assert verify_args.require_eligible


def test_cross_engine_spec_rejects_required_not_applicable_check():
    path = DEFAULT_CORE3_SPECS / "A4_afm_stripe_sot.yaml"
    payload = CrossEngineSpec.from_yaml(path).model_dump(mode="json")
    payload["checks"][-1]["required"] = True

    with pytest.raises(ValueError, match="not_applicable checks cannot be required"):
        CrossEngineSpec.model_validate(payload)
