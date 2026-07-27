import json
from pathlib import Path

from spintexture_agent.assertion_coverage import (
    AssertionCoverageRegistry,
    AssertionGap,
    AssertionAxes,
    AxisContract,
    ResultKeyClasses,
    RouteAssertionContract,
    evaluate_route_contract,
    run_assertion_coverage,
)
from spintexture_agent.cli import build_parser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _minimal_contract() -> RouteAssertionContract:
    return RouteAssertionContract(
        route_id="test_full_route",
        evidence_card="evidence_cards/test.yaml",
        result_keys=ResultKeyClasses(
            must_resolve=["closed_form", "dimension_regression"],
            symbolic_by_design=["held_definition"],
            metadata=["note"],
        ),
        assertions=AssertionAxes(
            dimension=AxisContract(keys=["dimension_regression"]),
            sign=AxisContract(),
            boundary=AxisContract(not_applicable_reason="no boundary claim"),
            limit=AxisContract(not_applicable_reason="no limit claim"),
        ),
        known_gaps=[
            AssertionGap(
                gap_id="test_sign_gap",
                axis="sign",
                description="sign assertion absent",
                next_action="add a sign regression",
            )
        ],
    )


def _record(results: dict[str, object]) -> dict[str, object]:
    return {
        "wolfram_results": {
            "status": "passed",
            "expected_keys": [
                "closed_form",
                "dimension_regression",
                "held_definition",
                "note",
            ],
            "results": results,
        }
    }


def test_registry_covers_all_full_routes_and_classifies_every_current_key():
    registry = AssertionCoverageRegistry()

    registry.validate_capability_coverage()
    assert len(registry.routes) == 7
    assert sum(len(route.result_keys.all_keys) for route in registry.routes) == 204
    assert all(route.evidence_card for route in registry.routes)


def test_current_evidence_has_complete_resolution_and_assertion_axes(tmp_path):
    run = run_assertion_coverage(out_dir=tmp_path)

    assert run.suite_status == "pass"
    assert run.routes_passed == 7
    assert run.routes_incomplete == 0
    assert run.routes_failed == 0
    assert run.key_status_counts == {
        "pass": 204,
        "fail": 0,
        "missing": 0,
        "not_applicable": 0,
    }
    assert run.axis_status_counts == {
        "pass": 25,
        "fail": 0,
        "missing": 0,
        "not_applicable": 3,
    }
    gaps = {
        gap.gap_id
        for route in run.routes
        for gap in route.known_gaps
    }
    assert gaps == set()
    payload = json.loads(Path(run.result_json).read_text(encoding="utf-8"))
    assert payload["suite_status"] == "pass"
    assert Path(run.report_markdown).exists()


def test_must_resolve_rejects_unresolved_head_but_symbolic_definition_is_allowed():
    contract = _minimal_contract()
    evidence = {"generated_execution_status": "passed", "passed": True}
    route = evaluate_route_contract(
        contract,
        evidence,
        _record(
            {
                "closed_form": "Integrate[f[x], {x, 0, 1}]",
                "dimension_regression": "True",
                "held_definition": "HoldForm[Integrate[g[r], {r, 0, Infinity}]]",
                "note": "symbolic test",
            }
        ),
    )

    checks = {check.key: check for check in route.result_key_checks}
    assert checks["closed_form"].status == "fail"
    assert checks["held_definition"].status == "pass"
    assert route.resolution_status == "fail"
    assert route.overall_status == "fail"


def test_fatal_wolfram_sentinel_fails_every_result_class():
    contract = _minimal_contract()
    evidence = {"generated_execution_status": "passed", "passed": True}
    route = evaluate_route_contract(
        contract,
        evidence,
        _record(
            {
                "closed_form": "x + 1",
                "dimension_regression": "True",
                "held_definition": "HoldForm[Integrate[g[r], {r, 0, Infinity}]]",
                "note": "Failure[\"bad\", <||>]",
            }
        ),
    )

    checks = {check.key: check for check in route.result_key_checks}
    assert checks["note"].status == "fail"
    assert route.overall_status == "fail"


def test_assertion_coverage_cli_defaults_to_both_evidence_suites():
    args = build_parser().parse_args(["assertion-coverage"])

    assert args.registry == "knowledge_base/assertion_coverage.yaml"
    assert args.evidence_runs == [
        "analysis/evidence_runs/core3_latest",
        "analysis/evidence_runs/extended_literature_01",
    ]
    assert args.require_complete is False
