from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .evaluator import (
    CaseScore,
    DimensionScore,
    _score_wolfram_result_content,
    _score_wolfram_result_keys,
    evaluate_benchmark_cases,
    summarize_dimensions,
)
from .generator import PROJECT_ROOT


DEFAULT_RECORDED_OUTPUTS_DIR = PROJECT_ROOT / "baseline_outputs"
DEFAULT_RECORDED_BASELINE_DIR = PROJECT_ROOT / "analysis" / "baseline_actual_runs"
DEFAULT_RECORDED_BASELINE_BUNDLE_DIR = PROJECT_ROOT / "outputs" / "baseline_actual_runs"
RECORDED_BASELINE_NOTE = (
    "Scores are computed from recorded baseline output YAML files. The evaluator does not "
    "call an LLM or external API; replace Codex-recorded or example records with independent "
    "baseline transcripts before using the numbers as final paper evidence."
)
INDEPENDENT_BASELINE_NOTE = (
    "Scores are computed from independent external baseline transcripts stored as recorded "
    "YAML outputs. The evaluator does not call an LLM or external API during scoring."
)
INDEPENDENT_WITH_AGENT_NOTE = (
    "Scores combine independent external baseline transcripts with a full "
    "SpinTextureTheoryAgent reference evaluated by the standard local benchmark runner. "
    "The evaluator does not call an LLM or external API during baseline scoring."
)


@dataclass(frozen=True)
class RecordedBaselineMethod:
    method_id: str
    source_type: str
    description: str
    cases: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class RecordedBaselineCaseScore:
    case_id: str
    score: int
    max_score: int
    passed: bool
    dimensions: list[DimensionScore]

    def to_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "score": self.score,
            "max_score": self.max_score,
            "passed": self.passed,
            "dimensions": [dimension.to_record() for dimension in self.dimensions],
        }


@dataclass(frozen=True)
class RecordedBaselineMethodScore:
    method: RecordedBaselineMethod
    cases: list[RecordedBaselineCaseScore]

    @property
    def passed_cases(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    @property
    def total_score(self) -> int:
        return sum(case.score for case in self.cases)

    @property
    def max_score(self) -> int:
        return sum(case.max_score for case in self.cases)

    @property
    def score_rate(self) -> float:
        return self.total_score / self.max_score if self.max_score else 0.0

    @property
    def case_pass_rate(self) -> float:
        return self.passed_cases / len(self.cases) if self.cases else 0.0

    def to_record(self) -> dict[str, Any]:
        return {
            "profile_id": self.method.method_id,
            "baseline_type": self.method.source_type,
            "description": self.method.description,
            "passed_cases": self.passed_cases,
            "case_count": len(self.cases),
            "total_score": self.total_score,
            "max_score": self.max_score,
            "score_rate": self.score_rate,
            "case_pass_rate": self.case_pass_rate,
            "cases": [case.to_record() for case in self.cases],
        }


@dataclass(frozen=True)
class RecordedBaselineRun:
    methods: list[RecordedBaselineMethodScore]
    csv_path: Path
    json_path: Path
    notes_path: Path

    @property
    def has_independent_outputs(self) -> bool:
        return any(method.method.source_type.startswith("independent_") for method in self.methods)

    @property
    def has_agent_reference(self) -> bool:
        return any(method.method.source_type == "implemented_agent" for method in self.methods)

    def to_record(self) -> dict[str, Any]:
        return {
            "baseline_run_type": "recorded_output_evaluation",
            "warning": (
                INDEPENDENT_WITH_AGENT_NOTE
                if self.has_independent_outputs and self.has_agent_reference
                else INDEPENDENT_BASELINE_NOTE
                if self.has_independent_outputs
                else RECORDED_BASELINE_NOTE
            ),
            "summary": {
                "profile_count": len(self.methods),
                "profiles": [
                    {
                        "profile_id": method.method.method_id,
                        "baseline_type": method.method.source_type,
                        "score_rate": method.score_rate,
                        "case_pass_rate": method.case_pass_rate,
                    }
                    for method in self.methods
                ],
            },
            "profiles": [method.to_record() for method in self.methods],
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
        raise ValueError(f"Recorded baseline YAML must be a mapping: {path}")
    return data


def _case_paths(cases_dir: str | Path) -> list[Path]:
    cases_dir = _project_path(cases_dir)
    return sorted(cases_dir.glob("*.yaml"))


def _score_exact(name: str, actual: Any, expected: Any) -> DimensionScore:
    passed = actual == expected
    detail = f"expected={expected!r}, actual={actual!r}"
    return DimensionScore(name=name, passed=passed, detail=detail)


def _score_contains_all(name: str, actual_items: list[str], expected_items: list[str]) -> DimensionScore:
    missing = [item for item in expected_items if item not in actual_items]
    passed = not missing
    detail = "all expected items found" if passed else f"missing={missing!r}"
    return DimensionScore(name=name, passed=passed, detail=detail)


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


def _expected_wolfram_result_keys(equation_type: str) -> list[str]:
    if equation_type == "coupled_wall_chain":
        return [
            "domain_wall_ansatz",
            "collective_metric_integrand",
            "collective_mass_matrix_definition",
            "collective_mass_matrix",
            "collective_damping_matrix_definition",
            "collective_damping_matrix",
            "wall_chain_stability_matrix",
            "stripe_chain_equation",
        ]
    if equation_type == "thiele_equation":
        return ["topological_density", "gyrotropic_tensor", "damping_tensor", "thiele_equation"]
    if equation_type == "inertial_collective_coordinate":
        return [
            "topological_density",
            "collective_mass_matrix",
            "collective_damping_matrix",
            "gyrotropic_cancellation",
            "inertial_equation",
        ]
    if equation_type == "topology_only":
        return ["topological_density", "topology_note"]
    return []


def _recorded_wolfram_record(response: dict[str, Any], equation_type: str) -> dict[str, Any]:
    execution = response.get("wolfram_execution", {})
    if isinstance(execution, str):
        execution = {"status": execution}
    if not isinstance(execution, dict):
        execution = {}

    wolfram_results = response.get("wolfram_results", {})
    if not isinstance(wolfram_results, dict):
        wolfram_results = {}

    result_payload = wolfram_results.get("results", response.get("wolfram_result"))
    if result_payload is None:
        result_payload = response.get("wolfram_results_payload")

    expected_keys = wolfram_results.get("expected_keys")
    if not isinstance(expected_keys, list):
        expected_keys = _expected_wolfram_result_keys(equation_type)

    return {
        "wolfram_execution": execution,
        "wolfram_results": {
            "expected_keys": [str(key) for key in expected_keys],
            "results": result_payload if isinstance(result_payload, dict) else None,
        },
    }


def _score_recorded_wolfram_execution(response: dict[str, Any]) -> DimensionScore:
    execution = response.get("wolfram_execution", {})
    if isinstance(execution, str):
        status = execution
    elif isinstance(execution, dict):
        status = execution.get("status")
    else:
        status = None
    passed = status == "passed"
    detail = f"status={status!r}" if status is not None else "missing Wolfram execution record"
    return DimensionScore(name="wolfram_execution", passed=passed, detail=detail)


def _response_for_case(method: RecordedBaselineMethod, case_id: str) -> dict[str, Any]:
    case_record = method.cases.get(case_id, {})
    if not isinstance(case_record, dict):
        return {}
    response = case_record.get("response", case_record)
    return response if isinstance(response, dict) else {}


def _list_value(response: dict[str, Any], key: str) -> list[str]:
    value = response.get(key, [])
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None:
        return []
    return [str(value)]


def _wolfram_text(response: dict[str, Any]) -> str:
    parts = [str(response.get("wolfram_text", ""))]
    parts.extend(_list_value(response, "wolfram_symbols"))
    return "\n".join(part for part in parts if part)


def _primary_order_parameter(response: dict[str, Any]) -> Any:
    return response.get("primary_order_parameter", response.get("order_parameter"))


def _score_gold_consistency(
    *,
    case_id: str,
    gold_answer: dict[str, Any],
    response: dict[str, Any],
) -> DimensionScore:
    canonical = gold_answer.get("canonical_result", {})
    topology = gold_answer.get("topology", {})
    checks: list[tuple[str, bool]] = [
        ("case_id", gold_answer.get("case_id") == case_id),
        ("equation_type", canonical.get("equation_type") == response.get("equation_type")),
    ]
    if topology.get("field") is not None:
        checks.append(("topology_field", topology.get("field") == response.get("topology_field")))

    required_assumptions = [str(item) for item in gold_answer.get("required_assumptions", [])]
    actual_assumptions = _list_value(response, "assumptions")
    missing_assumptions = [
        assumption for assumption in required_assumptions if assumption not in actual_assumptions
    ]
    if required_assumptions:
        checks.append(("required_assumptions", not missing_assumptions))

    failed = [name for name, passed in checks if not passed]
    passed = not failed
    detail = "consistent" if passed else f"failed={failed!r}"
    if missing_assumptions:
        detail += f", missing_assumptions={missing_assumptions!r}"
    return DimensionScore(name="gold_answer_consistency", passed=passed, detail=detail)


def load_recorded_baseline_methods(
    outputs_dir: str | Path = DEFAULT_RECORDED_OUTPUTS_DIR,
) -> list[RecordedBaselineMethod]:
    methods: list[RecordedBaselineMethod] = []
    for path in sorted(_project_path(outputs_dir).glob("*.yaml")):
        data = _load_yaml(path)
        cases = data.get("cases", {})
        if not isinstance(cases, dict):
            raise ValueError(f"cases must be a mapping in {path}")
        methods.append(
            RecordedBaselineMethod(
                method_id=str(data["method_id"]),
                source_type=str(data.get("source_type", "recorded_output")),
                description=str(data.get("description", "")),
                cases={str(case_id): case for case_id, case in cases.items() if isinstance(case, dict)},
            )
        )
    preferred = {
        "llm_only": 0,
        "prompted_llm": 1,
        "template_only": 2,
        "naive_llm_wolfram": 3,
        "full_agent": 4,
    }
    return sorted(methods, key=lambda method: preferred.get(method.method_id, 100))


def _score_recorded_case(
    method: RecordedBaselineMethod,
    case_path: Path,
    *,
    gold_dir: str | Path = "gold_answers",
) -> RecordedBaselineCaseScore:
    case = _load_yaml(case_path)
    case_id = str(case["case_id"])
    expected = case.get("expected", {})
    if not isinstance(expected, dict):
        raise ValueError(f"expected must be a mapping in {case_path}")
    response = _response_for_case(method, case_id)
    present = bool(response)

    dimensions: list[DimensionScore] = [
        DimensionScore(
            name="response_exists",
            passed=present,
            detail="recorded response found" if present else "missing recorded response",
        ),
        _score_exact("material_class", response.get("material_class"), expected.get("material_class")),
        _score_exact(
            "order_parameter",
            _primary_order_parameter(response),
            expected.get("primary_order_parameter"),
        ),
        _score_exact("dynamics_type", response.get("dynamics_type"), expected.get("dynamics_type")),
        _score_exact("equation_type", response.get("equation_type"), expected.get("equation_type")),
        _score_exact("topology_field", response.get("topology_field"), expected.get("topology_field")),
        _score_required_symbols(_wolfram_text(response), case.get("required_wolfram_symbols", [])),
        _score_forbidden_symbols(_wolfram_text(response), case.get("forbidden_wolfram_symbols", [])),
    ]

    if expected.get("limit_checks"):
        dimensions.append(
            _score_contains_all("limit_checks", _list_value(response, "limit_checks"), expected["limit_checks"])
        )
    if expected.get("energy_terms"):
        dimensions.append(
            _score_contains_all("energy_terms", _list_value(response, "energy_terms"), expected["energy_terms"])
        )
    if "gyrotropic_term" in expected:
        dimensions.append(
            _score_exact("gyrotropic_term", response.get("gyrotropic_term"), expected["gyrotropic_term"])
        )
    if "requires_human_review" in expected:
        dimensions.append(
            _score_exact(
                "requires_human_review",
                response.get("requires_human_review"),
                expected["requires_human_review"],
            )
        )
    if expected.get("validation_ids"):
        dimensions.append(
            _score_contains_all(
                "validation_ids",
                _list_value(response, "validation_ids"),
                expected["validation_ids"],
            )
        )

    wolfram_record = _recorded_wolfram_record(response, str(expected.get("equation_type", "")))
    dimensions.extend(
        [
            _score_recorded_wolfram_execution(response),
            _score_wolfram_result_keys(wolfram_record),
            _score_wolfram_result_content(
                wolfram_record,
                str(expected.get("equation_type", "")),
                str(expected.get("support_level", "full_derivation")),
            ),
        ]
    )

    gold_path = _project_path(gold_dir) / f"{case_id}.yaml"
    if gold_path.exists():
        dimensions.append(
            _score_gold_consistency(
                case_id=case_id,
                gold_answer=_load_yaml(gold_path),
                response=response,
            )
        )

    score, max_score = summarize_dimensions(dimensions)
    return RecordedBaselineCaseScore(
        case_id=case_id,
        score=score,
        max_score=max_score,
        passed=score == max_score,
        dimensions=dimensions,
    )


def _score_method(
    method: RecordedBaselineMethod,
    case_paths: list[Path],
    *,
    gold_dir: str | Path = "gold_answers",
) -> RecordedBaselineMethodScore:
    return RecordedBaselineMethodScore(
        method=method,
        cases=[_score_recorded_case(method, path, gold_dir=gold_dir) for path in case_paths],
    )


def _case_from_agent_score(case: CaseScore) -> RecordedBaselineCaseScore:
    dimensions = [
        DimensionScore(name="response_exists", passed=True, detail="generated by full agent"),
        *case.dimensions,
    ]
    score, max_score = summarize_dimensions(dimensions)
    return RecordedBaselineCaseScore(
        case_id=case.case_id,
        score=score,
        max_score=max_score,
        passed=score == max_score,
        dimensions=dimensions,
    )


def _full_agent_method_score(
    *,
    cases_dir: str | Path,
    out_dir: Path,
    bundle_out: str | Path,
) -> RecordedBaselineMethodScore:
    benchmark = evaluate_benchmark_cases(
        cases_dir=cases_dir,
        results_dir=out_dir / "_full_agent_reference",
        bundle_out=bundle_out,
        execute_wolfram=True,
    )
    method = RecordedBaselineMethod(
        method_id="full_agent",
        source_type="implemented_agent",
        description="Full SpinTextureTheoryAgent evaluated with the standard benchmark runner.",
        cases={},
    )
    return RecordedBaselineMethodScore(
        method=method,
        cases=[_case_from_agent_score(case) for case in benchmark.cases],
    )


def _write_csv(path: Path, methods: list[RecordedBaselineMethodScore]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "profile_id",
                "baseline_type",
                "passed_cases",
                "case_count",
                "case_pass_rate",
                "total_score",
                "max_score",
                "score_rate",
            ],
        )
        writer.writeheader()
        for method in methods:
            writer.writerow(
                {
                    "profile_id": method.method.method_id,
                    "baseline_type": method.method.source_type,
                    "passed_cases": method.passed_cases,
                    "case_count": len(method.cases),
                    "case_pass_rate": f"{method.case_pass_rate:.6f}",
                    "total_score": method.total_score,
                    "max_score": method.max_score,
                    "score_rate": f"{method.score_rate:.6f}",
                }
            )


def _write_notes(path: Path, methods: list[RecordedBaselineMethodScore]) -> None:
    has_independent_outputs = any(
        method.method.source_type.startswith("independent_") for method in methods
    )
    has_agent_reference = any(method.method.source_type == "implemented_agent" for method in methods)
    lines = [
        "# Independent Baselines vs Full Agent"
        if has_independent_outputs and has_agent_reference
        else "# Independent Baseline Run"
        if has_independent_outputs
        else "# Recorded Baseline Run",
        "",
        INDEPENDENT_WITH_AGENT_NOTE
        if has_independent_outputs and has_agent_reference
        else INDEPENDENT_BASELINE_NOTE
        if has_independent_outputs
        else RECORDED_BASELINE_NOTE,
        "",
        "| Baseline | Type | Case pass rate | Rule score rate |",
        "| --- | --- | ---: | ---: |",
    ]
    for method in methods:
        lines.append(
            f"| `{method.method.method_id}` | `{method.method.source_type}` | "
            f"{method.case_pass_rate:.2%} | {method.score_rate:.2%} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_recorded_baselines(
    outputs_dir: str | Path = DEFAULT_RECORDED_OUTPUTS_DIR,
    out_dir: str | Path = DEFAULT_RECORDED_BASELINE_DIR,
    *,
    cases_dir: str | Path = "benchmark_cases",
    bundle_out: str | Path = DEFAULT_RECORDED_BASELINE_BUNDLE_DIR,
    include_agent_reference: bool = True,
    gold_dir: str | Path = "gold_answers",
) -> RecordedBaselineRun:
    out_dir = _project_path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    case_paths = _case_paths(cases_dir)
    methods = [
        _score_method(method, case_paths, gold_dir=gold_dir)
        for method in load_recorded_baseline_methods(outputs_dir)
    ]
    if include_agent_reference:
        methods.append(
            _full_agent_method_score(
                cases_dir=cases_dir,
                out_dir=out_dir,
                bundle_out=bundle_out,
            )
        )

    csv_path = out_dir / "baseline_scores.csv"
    json_path = out_dir / "baseline_scores.json"
    notes_path = out_dir / "notes.md"
    run = RecordedBaselineRun(methods=methods, csv_path=csv_path, json_path=json_path, notes_path=notes_path)
    _write_csv(csv_path, methods)
    json_path.write_text(json.dumps(run.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")
    _write_notes(notes_path, methods)
    return run
