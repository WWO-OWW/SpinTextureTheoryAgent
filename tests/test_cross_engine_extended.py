import json
from pathlib import Path

import pytest

from spintexture_agent.cli import build_parser
from spintexture_agent.cross_engine_extended import (
    DEFAULT_OUTPUT,
    DEFAULT_SPECS,
    EXPECTED_CHECK_IDS,
    ExtendedCrossEngineSpec,
    ExtendedSuiteResult,
    load_extended_specs,
    run_extended_cross_engine_suite,
    verify_extended_cross_engine_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_extended_specs_are_frozen_and_contain_no_expected_results():
    loaded = load_extended_specs()

    assert {spec.route_id for _, spec in loaded} == set(EXPECTED_CHECK_IDS)
    assert sum(len(spec.checks) for _, spec in loaded) == 28
    for path, spec in loaded:
        serialized = json.dumps(spec.model_dump(mode="json")).lower()
        assert "expected_expression" not in serialized
        assert "wolfram_result" not in serialized
        assert spec.independence.allowed_input_artifacts == [
            str(path.relative_to(PROJECT_ROOT))
        ]
        assert any(
            "mathematica/gold" in item
            for item in spec.independence.prohibited_input_artifacts
        )
        assert spec.precision_digits == [40, 60, 80]


def test_extended_runner_has_no_wolfram_execution_path():
    source = (
        PROJECT_ROOT / "src/spintexture_agent/cross_engine_extended.py"
    ).read_text(encoding="utf-8")

    assert "execute_wolfram" not in source
    assert "WolframKernel" not in source
    assert "subprocess" not in source


def test_registered_extended_execution_has_convergence_and_honest_na():
    result = ExtendedSuiteResult.model_validate_json(
        (DEFAULT_OUTPUT / "cross_engine_suite.json").read_text(encoding="utf-8")
    )

    assert result.passed
    assert (result.passed_route_count, result.route_count) == (4, 4)
    assert (result.passed_check_count, result.failed_check_count) == (24, 0)
    assert result.not_applicable_check_count == 4
    for route in result.routes:
        assert route.passed
        assert route.not_applicable_check_count == 1
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


def test_registered_extended_results_pass_integrity_verification():
    for result_path in sorted(DEFAULT_OUTPUT.glob("*/cross_engine_result.json")):
        verification = verify_extended_cross_engine_result(result_path)
        assert verification.eligible_for_cross_engine_pass
        assert verification.issues == []


def test_extended_verifier_rejects_runner_hash_drift(tmp_path):
    source = next(DEFAULT_OUTPUT.glob("*/cross_engine_result.json"))
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["runner_artifact"]["sha256"] = "0" * 64
    result_path = tmp_path / "cross_engine_result.json"
    result_path.write_text(json.dumps(payload), encoding="utf-8")

    verification = verify_extended_cross_engine_result(result_path)

    assert not verification.eligible_for_cross_engine_pass
    assert "extended runner artifact hash drift" in verification.issues


def test_extended_run_is_non_overwriting():
    with pytest.raises(FileExistsError, match="never overwritten"):
        run_extended_cross_engine_suite(DEFAULT_SPECS, DEFAULT_OUTPUT)


def test_extended_cross_engine_cli_contract():
    parser = build_parser()
    run_args = parser.parse_args(
        [
            "cross-engine",
            "run",
            "--suite",
            "extended",
            "--specs",
            "specs",
            "--out",
            "results",
            "--require-pass",
        ]
    )
    verify_args = parser.parse_args(
        [
            "cross-engine",
            "verify",
            "--suite",
            "extended",
            "--result",
            "result.json",
            "--route",
            "fm_vortex_topology_full",
            "--require-eligible",
        ]
    )

    assert run_args.suite == "extended"
    assert run_args.require_pass
    assert verify_args.suite == "extended"
    assert verify_args.route == "fm_vortex_topology_full"


def test_extended_spec_rejects_required_not_applicable_check():
    path = DEFAULT_SPECS / "C4_fm_vortex_topology.yaml"
    payload = ExtendedCrossEngineSpec.from_yaml(path).model_dump(mode="json")
    payload["checks"][-1]["required"] = True

    with pytest.raises(ValueError, match="not_applicable checks cannot be required"):
        ExtendedCrossEngineSpec.model_validate(payload)
