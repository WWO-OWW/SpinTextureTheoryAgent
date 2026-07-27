from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .checker import check_task
from .generator import generate_task_bundle
from .ir import build_physics_ir
from .kb import KnowledgeBase
from .schema import TheoryTask
from .selector import select_template
from .wolfram import execute_wolfram_script, update_wolfram_execution_record


PROJECT_ROOT = Path(__file__).resolve().parents[2]

Comparison = Literal["exact", "gold_true", "generated_true", "both_true"]
ExpertReviewStatus = Literal["pending", "approved", "rejected", "revision_required"]


class EvidenceIndependence(BaseModel):
    method: str
    prohibited_dependencies: list[str] = Field(default_factory=list)


class EvidenceCheck(BaseModel):
    check_id: str = Field(pattern=r"^[a-z0-9_]+$")
    category: str
    generated_key: str | None = None
    gold_key: str | None = None
    comparison: Comparison

    @model_validator(mode="after")
    def validate_keys(self) -> "EvidenceCheck":
        if self.comparison == "exact" and not (self.generated_key and self.gold_key):
            raise ValueError("Exact evidence checks require generated_key and gold_key.")
        if self.comparison == "gold_true" and not self.gold_key:
            raise ValueError("gold_true evidence checks require gold_key.")
        if self.comparison == "generated_true" and not self.generated_key:
            raise ValueError("generated_true evidence checks require generated_key.")
        if self.comparison == "both_true" and not (self.generated_key and self.gold_key):
            raise ValueError("both_true evidence checks require generated_key and gold_key.")
        return self


class EvidenceSource(BaseModel):
    source_id: str
    source_type: Literal["primary_literature", "internal_analytic_derivation"]
    citation: str
    doi: str | None = None
    url: str | None = None
    supports: list[str] = Field(default_factory=list)


class ExpertReview(BaseModel):
    status: ExpertReviewStatus
    required_expertise: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    reviewer: str | None = None
    reviewed_at: str | None = None


class EvidenceCard(BaseModel):
    schema_version: str
    card_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    case_id: str
    route_id: str
    claim_scope: str
    generated_config: str
    benchmark_case: str
    gold_derivation_doc: str
    independent_gold_script: str
    independence: EvidenceIndependence
    assumptions: list[str]
    conventions: dict[str, object]
    checks: list[EvidenceCheck]
    sources: list[EvidenceSource]
    expert_review: ExpertReview

    @model_validator(mode="after")
    def validate_card(self) -> "EvidenceCard":
        check_ids = [check.check_id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError(f"Evidence check IDs must be unique in {self.card_id}.")
        if not any(source.source_type == "primary_literature" for source in self.sources):
            raise ValueError(f"Evidence card {self.card_id} needs primary literature provenance.")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "EvidenceCard":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


class EvidenceCheckResult(BaseModel):
    check_id: str
    category: str
    comparison: Comparison
    passed: bool
    generated_key: str | None = None
    gold_key: str | None = None
    generated_value: str | None = None
    gold_value: str | None = None
    detail: str


class EvidenceRunResult(BaseModel):
    card_id: str
    case_id: str
    route_id: str
    passed: bool
    generated_execution_status: str
    gold_execution_status: str
    generated_record: str
    gold_result: str | None
    expert_review_status: ExpertReviewStatus
    checks: list[EvidenceCheckResult]
    result_path: str
    summary_path: str


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


def load_evidence_cards(path: str | Path) -> list[tuple[Path, EvidenceCard]]:
    resolved = _project_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Evidence card path does not exist: {resolved}")
    paths = [resolved] if resolved.is_file() else sorted(resolved.glob("*.yaml"))
    if not paths:
        raise ValueError(f"No evidence cards found under {resolved}")
    return [(card_path, EvidenceCard.from_yaml(card_path)) for card_path in paths]


def _normalize_wolfram(value: object | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", "", str(value))


def _is_true(value: object | None) -> bool:
    return value is True or str(value).strip() == "True"


def _evaluate_check(
    check: EvidenceCheck,
    generated: dict[str, object],
    gold: dict[str, object],
) -> EvidenceCheckResult:
    generated_value = generated.get(check.generated_key) if check.generated_key else None
    gold_value = gold.get(check.gold_key) if check.gold_key else None

    missing: list[str] = []
    if check.generated_key and check.generated_key not in generated:
        missing.append(f"generated:{check.generated_key}")
    if check.gold_key and check.gold_key not in gold:
        missing.append(f"gold:{check.gold_key}")

    if missing:
        passed = False
        detail = f"missing keys: {', '.join(missing)}"
    elif check.comparison == "exact":
        passed = _normalize_wolfram(generated_value) == _normalize_wolfram(gold_value)
        detail = "expressions match" if passed else "expressions differ"
    elif check.comparison == "gold_true":
        passed = _is_true(gold_value)
        detail = f"gold={gold_value!r}"
    elif check.comparison == "generated_true":
        passed = _is_true(generated_value)
        detail = f"generated={generated_value!r}"
    else:
        passed = _is_true(generated_value) and _is_true(gold_value)
        detail = f"generated={generated_value!r}, gold={gold_value!r}"

    return EvidenceCheckResult(
        check_id=check.check_id,
        category=check.category,
        comparison=check.comparison,
        passed=passed,
        generated_key=check.generated_key,
        gold_key=check.gold_key,
        generated_value=None if generated_value is None else str(generated_value),
        gold_value=None if gold_value is None else str(gold_value),
        detail=detail,
    )


def _valid_wolfram_result(status: str, result: dict[str, object] | None) -> bool:
    return status == "passed" and isinstance(result, dict) and "parse_error" not in result


def _render_summary(card: EvidenceCard, run: EvidenceRunResult) -> str:
    lines = [
        f"# Evidence run: {card.card_id}",
        "",
        f"- Route: `{card.route_id}`",
        f"- Case: `{card.case_id}`",
        f"- Overall: `{'passed' if run.passed else 'failed'}`",
        f"- Generated Wolfram: `{run.generated_execution_status}`",
        f"- Independent gold Wolfram: `{run.gold_execution_status}`",
        f"- Expert review: `{card.expert_review.status}`",
        "",
        "## Independence",
        "",
        card.independence.method,
        "",
        "Prohibited dependencies:",
        "",
        *[f"- `{item}`" for item in card.independence.prohibited_dependencies],
        "",
        "## Checks",
        "",
        "| Check | Category | Comparison | Status | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in run.checks:
        lines.append(
            f"| `{check.check_id}` | `{check.category}` | `{check.comparison}` | "
            f"`{'pass' if check.passed else 'fail'}` | {check.detail} |"
        )
    lines.extend(["", "## Sources", ""])
    for source in card.sources:
        suffix = f" DOI: `{source.doi}`." if source.doi else ""
        lines.append(f"- `{source.source_id}`: {source.citation}{suffix}")
    lines.extend(["", "## Expert review questions", ""])
    lines.extend(f"- {question}" for question in card.expert_review.open_questions)
    return "\n".join(lines).rstrip() + "\n"


def run_evidence_card(
    card_path: str | Path,
    out_dir: str | Path,
    *,
    wolfram_timeout: int = 180,
) -> EvidenceRunResult:
    card_path = _project_path(card_path)
    card = EvidenceCard.from_yaml(card_path)
    out_dir = _project_path(out_dir) / card.card_id
    out_dir.mkdir(parents=True, exist_ok=True)

    task = TheoryTask.from_yaml(_project_path(card.generated_config))
    kb = KnowledgeBase()
    template = select_template(task, kb)
    physics_ir = build_physics_ir(task, template, kb)
    if physics_ir.capability_route_id != card.route_id:
        raise ValueError(
            f"Evidence card route {card.route_id!r} does not match "
            f"Physics IR route {physics_ir.capability_route_id!r}."
        )
    report = check_task(task, template, kb, physics_ir)
    paths = generate_task_bundle(
        task,
        template,
        report,
        out_dir / "generated",
        physics_ir=physics_ir,
    )
    generated_execution = execute_wolfram_script(
        paths["wolfram"],
        out_dir / "generated_wolfram_logs",
        timeout_seconds=wolfram_timeout,
    )
    update_wolfram_execution_record(paths["record"], generated_execution)

    gold_script = _project_path(card.independent_gold_script)
    gold_text = gold_script.read_text(encoding="utf-8")
    if "Get[" in gold_text or "Needs[" in gold_text:
        raise ValueError(f"Independent gold script imports an external Wolfram package: {gold_script}")
    gold_execution = execute_wolfram_script(
        gold_script,
        out_dir / "gold_wolfram_logs",
        timeout_seconds=wolfram_timeout,
    )

    generated_results = generated_execution.result or {}
    gold_results = gold_execution.result or {}
    checks = [
        _evaluate_check(check, generated_results, gold_results)
        for check in card.checks
    ]
    generated_valid = _valid_wolfram_result(
        generated_execution.status, generated_execution.result
    )
    gold_valid = _valid_wolfram_result(gold_execution.status, gold_execution.result)
    passed = generated_valid and gold_valid and all(check.passed for check in checks)

    result_path = out_dir / "evidence_result.json"
    summary_path = out_dir / "evidence_summary.md"
    run = EvidenceRunResult(
        card_id=card.card_id,
        case_id=card.case_id,
        route_id=card.route_id,
        passed=passed,
        generated_execution_status=generated_execution.status,
        gold_execution_status=gold_execution.status,
        generated_record=str(paths["record"]),
        gold_result=gold_execution.result_path,
        expert_review_status=card.expert_review.status,
        checks=checks,
        result_path=str(result_path),
        summary_path=str(summary_path),
    )
    result_path.write_text(
        json.dumps(run.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary_path.write_text(_render_summary(card, run), encoding="utf-8")

    generated_record = json.loads(paths["record"].read_text(encoding="utf-8"))
    generated_record["independent_gold_validation"] = {
        "card_id": card.card_id,
        "status": "passed" if passed else "failed",
        "evidence_result": str(result_path),
        "expert_review_status": card.expert_review.status,
        "checks": [check.model_dump() for check in checks],
    }
    paths["record"].write_text(
        json.dumps(generated_record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run


def run_evidence_cards(
    cards_path: str | Path,
    out_dir: str | Path,
    *,
    wolfram_timeout: int = 180,
) -> list[EvidenceRunResult]:
    return [
        run_evidence_card(card_path, out_dir, wolfram_timeout=wolfram_timeout)
        for card_path, _ in load_evidence_cards(cards_path)
    ]
