from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .checker import check_task
from .evaluator import (
    DimensionScore,
    _gold_answer_path,
    _load_yaml,
    _project_path,
    _score_contains_all,
    _score_confidence_thresholds,
    _score_dmi_variational_content,
    _score_exact,
    _score_forbidden_symbols,
    _score_gold_answer_link,
    _score_gold_review_coverage,
    _score_required_symbols,
    _score_validation_ids,
    _score_wolfram_execution,
    _score_wolfram_result_content,
    _score_wolfram_result_keys,
    summarize_dimensions,
)
from .generator import PROJECT_ROOT, generate_task_bundle
from .ir import build_physics_ir
from .kb import KnowledgeBase
from .nl import PromptParseError, parse_natural_language_task, task_to_yaml
from .selector import select_template
from .wolfram import execute_wolfram_script, update_wolfram_execution_record


DEFAULT_NL_CASES_DIR = PROJECT_ROOT / "nl_benchmark_cases"
DEFAULT_NL_RESULTS_DIR = PROJECT_ROOT / "analysis" / "nl_benchmark_runs" / "latest"
DEFAULT_NL_BUNDLE_DIR = PROJECT_ROOT / "outputs" / "nl_benchmark_runs"


@dataclass(frozen=True)
class NaturalLanguageCaseScore:
    case_id: str
    description: str
    prompt: str
    parsed_config: str | None
    score: int
    max_score: int
    support_level: str
    dimensions: list[DimensionScore]
    bundle_paths: dict[str, str]
    duration_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status not in {"failed", "incomplete"}

    @property
    def status(self) -> str:
        if any(dimension.status == "fail" for dimension in self.dimensions):
            return "failed"
        if any(dimension.status == "skipped" for dimension in self.dimensions):
            return "incomplete"
        if self.support_level == "review_only":
            return "review_only_passed"
        if self.support_level == "scaffold":
            return "scaffold_passed"
        if self.support_level == "unsupported":
            return "unsupported_routing_passed"
        return "full_derivation_passed"

    def to_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "description": self.description,
            "prompt": self.prompt,
            "parsed_config": self.parsed_config,
            "score": self.score,
            "max_score": self.max_score,
            "support_level": self.support_level,
            "passed": self.passed,
            "status": self.status,
            "duration_seconds": self.duration_seconds,
            "dimensions": [dimension.to_record() for dimension in self.dimensions],
            "bundle_paths": self.bundle_paths,
        }


@dataclass(frozen=True)
class NaturalLanguageBenchmarkRun:
    cases: list[NaturalLanguageCaseScore]
    csv_path: Path
    json_path: Path
    notes_path: Path
    archive_dir: Path | None = None
    archive_paths: dict[str, Path] = field(default_factory=dict)

    @property
    def passed_cases(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    @property
    def total_score(self) -> int:
        return sum(case.score for case in self.cases)

    @property
    def max_score(self) -> int:
        return sum(case.max_score for case in self.cases)

    def to_record(self) -> dict[str, Any]:
        return {
            "benchmark_run_type": "natural_language_prompt_to_derivation",
            "summary": {
                "case_count": len(self.cases),
                "passed_cases": self.passed_cases,
                "total_score": self.total_score,
                "max_score": self.max_score,
                "support_level_counts": {
                    support_level: sum(
                        1 for case in self.cases if case.support_level == support_level
                    )
                    for support_level in [
                        "full_derivation",
                        "scaffold",
                        "review_only",
                        "unsupported",
                    ]
                },
            },
            "archive": {
                "archive_dir": str(self.archive_dir) if self.archive_dir else None,
                "paths": {name: str(path) for name, path in self.archive_paths.items()},
            },
            "cases": [case.to_record() for case in self.cases],
        }


def _case_paths(cases_dir: str | Path) -> list[Path]:
    return sorted(_project_path(cases_dir).glob("*.yaml"))


def _score_optional_exact(
    dimensions: list[DimensionScore],
    name: str,
    actual: Any,
    expected: dict[str, Any],
    key: str,
) -> None:
    if key in expected:
        dimensions.append(_score_exact(name, actual, expected[key]))


def evaluate_nl_case(
    case_path: str | Path,
    bundle_out: str | Path = DEFAULT_NL_BUNDLE_DIR,
    *,
    execute_wolfram: bool = False,
    wolfram_timeout: int = 120,
) -> NaturalLanguageCaseScore:
    started = time.perf_counter()
    case_path = _project_path(case_path)
    bundle_out = _project_path(bundle_out)
    case = _load_yaml(case_path)
    case_id = str(case["case_id"])
    prompt = str(case["prompt"])
    expected = case.get("expected", {})
    if not isinstance(expected, dict):
        raise ValueError(f"expected must be a mapping in {case_path}")

    case_bundle = bundle_out / case_id
    case_bundle.mkdir(parents=True, exist_ok=True)

    dimensions: list[DimensionScore] = []
    bundle_paths: dict[str, str] = {}
    parsed_config_path: Path | None = None

    try:
        parsed = parse_natural_language_task(prompt, task_name=case.get("task_name"))
    except PromptParseError as exc:
        dimensions.append(DimensionScore("prompt_parse", False, str(exc)))
        return NaturalLanguageCaseScore(
            case_id=case_id,
            description=str(case.get("description", "")),
            prompt=prompt,
            parsed_config=None,
            score=0,
            max_score=len(dimensions),
            support_level="unsupported",
            dimensions=dimensions,
            bundle_paths=bundle_paths,
            duration_seconds=time.perf_counter() - started,
        )

    task = parsed.task
    parsed_config_path = case_bundle / "parsed_task.yaml"
    parsed_config_path.write_text(task_to_yaml(task), encoding="utf-8")
    bundle_paths["parsed_config"] = str(parsed_config_path)
    dimensions.append(
        DimensionScore(
            "prompt_parse",
            True,
            f"matched_aliases={parsed.matched_aliases!r}, warnings={parsed.warnings!r}",
        )
    )

    _score_optional_exact(dimensions, "parsed_material", task.material, expected, "material")
    _score_optional_exact(dimensions, "parsed_texture", task.texture, expected, "texture")
    _score_optional_exact(dimensions, "parsed_drive", task.drive, expected, "drive")
    _score_optional_exact(dimensions, "parsed_geometry", task.geometry, expected, "geometry")
    if expected.get("goals"):
        dimensions.append(_score_contains_all("parsed_goals", task.goals, expected["goals"]))
    if expected.get("assumptions"):
        dimensions.append(
            _score_contains_all("parsed_assumptions", task.assumptions, expected["assumptions"])
        )

    kb = KnowledgeBase()
    template = select_template(task, kb)
    physics_ir = build_physics_ir(task, template, kb)
    report = check_task(task, template, kb, physics_ir)
    paths = generate_task_bundle(task, template, report, case_bundle, physics_ir=physics_ir)
    bundle_paths.update({name: str(path) for name, path in paths.items()})

    if execute_wolfram:
        execution = execute_wolfram_script(
            paths["wolfram"],
            case_bundle / "wolfram_logs",
            timeout_seconds=wolfram_timeout,
        )
        update_wolfram_execution_record(paths["record"], execution)

    wolfram_text = paths["wolfram"].read_text(encoding="utf-8")
    record = json.loads(paths["record"].read_text(encoding="utf-8"))
    validation_items = record["validation"]["items"]

    _score_optional_exact(
        dimensions,
        "material_class",
        physics_ir.material_class,
        expected,
        "material_class",
    )
    _score_optional_exact(
        dimensions,
        "order_parameter",
        physics_ir.order_parameter.primary,
        expected,
        "primary_order_parameter",
    )
    _score_optional_exact(
        dimensions,
        "dynamics_type",
        physics_ir.dynamics.type,
        expected,
        "dynamics_type",
    )
    _score_optional_exact(
        dimensions,
        "equation_type",
        physics_ir.dynamics.expected_equation_type,
        expected,
        "equation_type",
    )
    _score_optional_exact(
        dimensions,
        "topology_field",
        physics_ir.order_parameter.topology_field,
        expected,
        "topology_field",
    )
    _score_optional_exact(
        dimensions,
        "support_level",
        physics_ir.support_level,
        expected,
        "support_level",
    )
    if expected.get("limit_checks"):
        dimensions.append(
            _score_contains_all("limit_checks", physics_ir.limit_checks, expected["limit_checks"])
        )
    if expected.get("energy_terms"):
        dimensions.append(
            _score_contains_all("energy_terms", physics_ir.energy_terms, expected["energy_terms"])
        )
    if "gyrotropic_term" in expected:
        dimensions.append(
            _score_exact(
                "gyrotropic_term",
                physics_ir.dynamics.gyrotropic_term,
                expected["gyrotropic_term"],
            )
        )
    if "requires_human_review" in expected:
        dimensions.append(
            _score_exact(
                "requires_human_review",
                physics_ir.confidence.requires_human_review,
                expected["requires_human_review"],
            )
        )
    if isinstance(expected.get("confidence"), dict):
        dimensions.extend(_score_confidence_thresholds(physics_ir, expected["confidence"]))
    if expected.get("validation_ids"):
        dimensions.append(_score_validation_ids(validation_items, expected["validation_ids"]))

    dimensions.extend(
        [
            _score_required_symbols(wolfram_text, case.get("required_wolfram_symbols", [])),
            _score_forbidden_symbols(wolfram_text, case.get("forbidden_wolfram_symbols", [])),
            DimensionScore("record_exists", paths["record"].exists(), str(paths["record"])),
        ]
    )

    if execute_wolfram:
        dimensions.append(_score_wolfram_execution(record["wolfram_execution"]))
        dimensions.append(_score_wolfram_result_keys(record))
        dimensions.append(
            _score_wolfram_result_content(
                record,
                physics_ir.dynamics.expected_equation_type,
                physics_ir.support_level,
            )
        )
        dimensions.append(
            _score_dmi_variational_content(
                record,
                physics_ir.energy_terms,
                physics_ir.support_level,
            )
        )

    gold_case_id = str(case.get("gold_case_id", ""))
    if gold_case_id:
        gold_path = _gold_answer_path(gold_case_id)
        if gold_path.exists():
            gold_answer = _load_yaml(gold_path)
            dimensions.append(
                _score_gold_answer_link(
                    case_id=gold_case_id,
                    gold_answer=gold_answer,
                    task=task,
                    equation_type=physics_ir.dynamics.expected_equation_type,
                    topology_field=physics_ir.order_parameter.topology_field,
                )
            )
            dimensions.append(
                _score_gold_review_coverage(
                    gold_answer=gold_answer,
                    validation_items=validation_items,
                )
            )

    score, max_score = summarize_dimensions(dimensions)
    return NaturalLanguageCaseScore(
        case_id=case_id,
        description=str(case.get("description", "")),
        prompt=prompt,
        parsed_config=str(parsed_config_path),
        score=score,
        max_score=max_score,
        support_level=physics_ir.support_level,
        dimensions=dimensions,
        bundle_paths=bundle_paths,
        duration_seconds=time.perf_counter() - started,
    )


def _write_csv(path: Path, cases: list[NaturalLanguageCaseScore]) -> None:
    dimension_names = sorted({dimension.name for case in cases for dimension in case.dimensions})
    fieldnames = [
        "case_id",
        "support_level",
        "status",
        "passed",
        "score",
        "max_score",
        "duration_seconds",
        *dimension_names,
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for case in cases:
            dimension_map = {
                dimension.name: int(dimension.passed) if dimension.applicable else ""
                for dimension in case.dimensions
            }
            row = {
                "case_id": case.case_id,
                "support_level": case.support_level,
                "status": case.status,
                "passed": int(case.passed),
                "score": case.score,
                "max_score": case.max_score,
                "duration_seconds": f"{case.duration_seconds:.6f}",
            }
            row.update({name: dimension_map.get(name, "") for name in dimension_names})
            writer.writerow(row)


def _write_notes(path: Path, run: NaturalLanguageBenchmarkRun) -> None:
    mean_duration = (
        sum(case.duration_seconds for case in run.cases) / len(run.cases)
        if run.cases
        else 0.0
    )
    support_counts = {
        support_level: sum(1 for case in run.cases if case.support_level == support_level)
        for support_level in ["full_derivation", "scaffold", "review_only", "unsupported"]
    }
    lines = [
        "# Natural-Language Benchmark Run",
        "",
        "Prompt-to-derivation benchmark for the controlled natural-language parser.",
        "",
        f"- Cases: {len(run.cases)}",
        f"- Cases satisfying criteria for their declared support level: {run.passed_cases}",
        f"- Total score: {run.total_score}/{run.max_score}",
        "- Support levels: "
        + ", ".join(f"{name}={count}" for name, count in support_counts.items()),
        "- A passing case is not automatically a full derivation; inspect `support_level` and N/A dimensions.",
        f"- Mean case duration: {mean_duration:.3f} s",
        "",
        "## Case Summary",
        "",
        "| Case | Support level | Score | Status |",
        "| --- | --- | ---: | :---: |",
    ]
    for case in run.cases:
        lines.append(
            f"| `{case.case_id}` | `{case.support_level}` | "
            f"{case.score}/{case.max_score} | {case.status} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_nl_benchmark_cases(
    cases_dir: str | Path = DEFAULT_NL_CASES_DIR,
    results_dir: str | Path = DEFAULT_NL_RESULTS_DIR,
    bundle_out: str | Path = DEFAULT_NL_BUNDLE_DIR,
    archive_dir: str | Path | None = None,
    *,
    execute_wolfram: bool = False,
    wolfram_timeout: int = 120,
) -> NaturalLanguageBenchmarkRun:
    results_dir = _project_path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    cases = [
        evaluate_nl_case(
            path,
            bundle_out=bundle_out,
            execute_wolfram=execute_wolfram,
            wolfram_timeout=wolfram_timeout,
        )
        for path in _case_paths(cases_dir)
    ]

    csv_path = results_dir / "nl_benchmark_scores.csv"
    json_path = results_dir / "nl_benchmark_scores.json"
    notes_path = results_dir / "notes.md"
    archive_path = _project_path(archive_dir) if archive_dir else None
    archive_paths: dict[str, Path] = {}
    if archive_path:
        archive_path.mkdir(parents=True, exist_ok=True)
        archive_paths = {
            "csv": archive_path / "nl_benchmark_scores.csv",
            "json": archive_path / "nl_benchmark_scores.json",
            "notes": archive_path / "notes.md",
        }

    run = NaturalLanguageBenchmarkRun(
        cases=cases,
        csv_path=csv_path,
        json_path=json_path,
        notes_path=notes_path,
        archive_dir=archive_path,
        archive_paths=archive_paths,
    )
    _write_csv(csv_path, cases)
    json_path.write_text(json.dumps(run.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")
    _write_notes(notes_path, run)
    if archive_path:
        _write_csv(archive_paths["csv"], cases)
        archive_paths["json"].write_text(
            json.dumps(run.to_record(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _write_notes(archive_paths["notes"], run)
    return run
