from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
READABILITY_SCHEMA_VERSION = "1.0.0"
READABILITY_RUBRIC_VERSION = "readability_v1.0.0"
DEFAULT_READABILITY_STUDY = PROJECT_ROOT / "readability_studies" / "v1_template"

ReadabilityStatus = Literal[
    "missing",
    "incomplete",
    "needs_adjudication",
    "passed",
    "failed",
]
RecordStatus = Literal["pending", "complete"]

RATING_ATTESTATION = (
    "I rated only the blinded response and frozen reference supplied for this "
    "study, and the recorded scores and comments are my own."
)
ADJUDICATION_ATTESTATION = (
    "I reviewed the blinded response, frozen reference, and independent rating "
    "disagreement, and recorded the resolution without using method identity."
)

RUBRIC_DEFINITIONS: tuple[dict[str, object], ...] = (
    {
        "criterion_id": "formula_fidelity",
        "prompt": "Equations, signs, order parameters, and conventions match the formal reference.",
        "critical": True,
        "minimum_score": 4,
    },
    {
        "criterion_id": "assumptions_and_validity",
        "prompt": "Assumptions, boundary conditions, approximations, and validity limits remain visible.",
        "critical": True,
        "minimum_score": 4,
    },
    {
        "criterion_id": "warning_and_certainty_preservation",
        "prompt": "Warnings, support level, review requirements, and certainty are not softened.",
        "critical": True,
        "minimum_score": 4,
    },
    {
        "criterion_id": "symbol_clarity",
        "prompt": "Symbols and physical terms are understandable to the declared target audience.",
        "critical": False,
        "minimum_score": 3,
    },
    {
        "criterion_id": "task_comprehension",
        "prompt": "The target reader can identify what was derived, what it means, and when it applies.",
        "critical": False,
        "minimum_score": 3,
    },
)


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


def _stored_project_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def _write_yaml(path: Path, model: BaseModel) -> None:
    path.write_text(
        yaml.safe_dump(
            model.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=False,
            width=100,
        ),
        encoding="utf-8",
    )


def _timestamp_is_valid(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


class FrozenStudyArtifact(BaseModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RubricCriterion(BaseModel):
    criterion_id: str
    prompt: str
    critical: bool
    minimum_score: int = Field(ge=1, le=5)


class ReadabilityRubric(BaseModel):
    schema_version: str
    rubric_version: str
    score_scale: str
    minimum_independent_raters: int = Field(ge=2)
    disagreement_threshold: int = Field(ge=0, le=4)
    criteria: list[RubricCriterion]

    @model_validator(mode="after")
    def validate_criteria(self) -> "ReadabilityRubric":
        criterion_ids = [criterion.criterion_id for criterion in self.criteria]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("Readability rubric criterion IDs must be unique")
        return self


class BlindingProtocol(BaseModel):
    method_identity_hidden: bool
    case_order_randomized: bool
    raters_cannot_access_model_metadata: bool
    gold_used_only_as_frozen_reference: bool


class ReadabilityStudyCase(BaseModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    blind_response_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    audience: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    authoritative_record: FrozenStudyArtifact
    layered_report: FrozenStudyArtifact
    accessible_view: FrozenStudyArtifact
    formal_reference: FrozenStudyArtifact


class ReadabilityStudyManifest(BaseModel):
    schema_version: str
    study_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    study_status: Literal["template", "collecting", "frozen"]
    created_at: str
    rubric: FrozenStudyArtifact
    blinding: BlindingProtocol
    cases: list[ReadabilityStudyCase] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case_ids(self) -> "ReadabilityStudyManifest":
        case_ids = [case.case_id for case in self.cases]
        blind_ids = [case.blind_response_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Readability study case IDs must be unique")
        if len(blind_ids) != len(set(blind_ids)):
            raise ValueError("Readability blind response IDs must be unique")
        return self


class RaterProfile(BaseModel):
    rater_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    role: str = Field(min_length=1)
    affiliation: str = Field(min_length=1)
    target_audience_match: bool
    independent_of_system_development: bool
    involved_in_response_generation: bool
    method_identity_seen: bool
    conflict_declared: bool
    conflict_details: str = ""


class CriterionRating(BaseModel):
    criterion_id: str
    score: int | None = Field(default=None, ge=1, le=5)
    critical_omission: bool | None = None
    comment: str = ""


class RatingSignature(BaseModel):
    signed_by: str = ""
    signed_at: str | None = None
    attestation: str = RATING_ATTESTATION


class ReadabilityRatingRecord(BaseModel):
    schema_version: str
    rating_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    study_id: str
    study_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str
    blind_response_id: str
    status: RecordStatus
    rater: RaterProfile
    criteria: list[CriterionRating]
    completed_at: str | None = None
    signature: RatingSignature

    @model_validator(mode="after")
    def validate_rating(self) -> "ReadabilityRatingRecord":
        expected = {str(item["criterion_id"]) for item in RUBRIC_DEFINITIONS}
        actual = {criterion.criterion_id for criterion in self.criteria}
        if len(actual) != len(self.criteria) or actual != expected:
            raise ValueError("Rating record must contain exactly the frozen rubric criteria")
        critical_ids = {
            str(item["criterion_id"])
            for item in RUBRIC_DEFINITIONS
            if bool(item["critical"])
        }
        for criterion in self.criteria:
            if criterion.critical_omission and criterion.criterion_id not in critical_ids:
                raise ValueError(
                    f"Noncritical criterion cannot declare a critical omission: {criterion.criterion_id}"
                )
        if self.status == "complete":
            for criterion in self.criteria:
                if criterion.score is None or criterion.critical_omission is None:
                    raise ValueError("Complete ratings require every score and omission flag")
                if (criterion.score <= 2 or criterion.critical_omission) and not (
                    criterion.comment.strip()
                ):
                    raise ValueError(
                        f"Low scores and critical omissions require a comment: {criterion.criterion_id}"
                    )
        return self


class CriterionResolution(BaseModel):
    criterion_id: str
    final_score: int | None = Field(default=None, ge=1, le=5)
    critical_omission_confirmed: bool | None = None
    rationale: str = ""


class AdjudicationSignature(BaseModel):
    signed_by: str = ""
    signed_at: str | None = None
    attestation: str = ADJUDICATION_ATTESTATION


class ReadabilityAdjudicationRecord(BaseModel):
    schema_version: str
    adjudication_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    study_id: str
    study_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str
    blind_response_id: str
    status: RecordStatus
    adjudicator: RaterProfile
    resolutions: list[CriterionResolution]
    completed_at: str | None = None
    signature: AdjudicationSignature

    @model_validator(mode="after")
    def validate_resolutions(self) -> "ReadabilityAdjudicationRecord":
        expected = {str(item["criterion_id"]) for item in RUBRIC_DEFINITIONS}
        actual = {resolution.criterion_id for resolution in self.resolutions}
        if len(actual) != len(self.resolutions) or actual != expected:
            raise ValueError("Adjudication must resolve exactly the frozen rubric criteria")
        critical_ids = {
            str(item["criterion_id"])
            for item in RUBRIC_DEFINITIONS
            if bool(item["critical"])
        }
        for resolution in self.resolutions:
            if (
                resolution.critical_omission_confirmed
                and resolution.criterion_id not in critical_ids
            ):
                raise ValueError(
                    "Noncritical adjudication cannot confirm a critical omission: "
                    f"{resolution.criterion_id}"
                )
        if self.status == "complete":
            for resolution in self.resolutions:
                if (
                    resolution.final_score is None
                    or resolution.critical_omission_confirmed is None
                    or not resolution.rationale.strip()
                ):
                    raise ValueError(
                        "Complete adjudication requires scores, omission flags, and rationales"
                    )
        return self


class CriterionAggregate(BaseModel):
    criterion_id: str
    critical: bool
    minimum_score: int
    rating_count: int
    mean_score: float
    standard_deviation: float
    standard_error: float
    approximate_ci95_low: float
    approximate_ci95_high: float
    score_range: int
    critical_omission_votes: int
    disagreement: bool
    final_score: float | None
    final_critical_omission: bool | None
    passed: bool | None


class ReadabilityCaseResult(BaseModel):
    case_id: str
    blind_response_id: str
    status: ReadabilityStatus
    rating_record_count: int
    eligible_rater_count: int
    excluded_ratings: dict[str, list[str]]
    criteria: list[CriterionAggregate]
    adjudication_status: Literal["not_required", "missing", "pending", "complete"]
    issues: list[str]


class ReadabilityStudyResult(BaseModel):
    study_id: str
    rubric_version: str
    status: ReadabilityStatus
    case_count: int
    status_counts: dict[str, int]
    cases: list[ReadabilityCaseResult]
    issues: list[str]
    report_json: str | None = None
    report_markdown: str | None = None

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


class ReadabilityPacketResult(BaseModel):
    study_dir: str
    manifest_path: str
    rubric_path: str
    guide_path: str
    rating_template: str
    adjudication_template: str


def default_readability_rubric() -> ReadabilityRubric:
    return ReadabilityRubric(
        schema_version=READABILITY_SCHEMA_VERSION,
        rubric_version=READABILITY_RUBRIC_VERSION,
        score_scale="1=incorrect_or_missing; 2=major_problems; 3=adequate; 4=good; 5=complete_and_faithful",
        minimum_independent_raters=2,
        disagreement_threshold=1,
        criteria=[RubricCriterion.model_validate(item) for item in RUBRIC_DEFINITIONS],
    )


def _template_rater(rater_id: str) -> RaterProfile:
    return RaterProfile(
        rater_id=rater_id,
        role="REPLACE_WITH_RATER_ROLE",
        affiliation="REPLACE_WITH_AFFILIATION",
        target_audience_match=True,
        independent_of_system_development=True,
        involved_in_response_generation=False,
        method_identity_seen=False,
        conflict_declared=False,
        conflict_details="",
    )


def _rating_template() -> ReadabilityRatingRecord:
    return ReadabilityRatingRecord(
        schema_version=READABILITY_SCHEMA_VERSION,
        rating_id="REPLACE_WITH_UNIQUE_RATING_ID",
        study_id="REPLACE_WITH_STUDY_ID",
        study_manifest_sha256="0" * 64,
        case_id="REPLACE_WITH_CASE_ID",
        blind_response_id="REPLACE_WITH_BLIND_RESPONSE_ID",
        status="pending",
        rater=_template_rater("REPLACE_WITH_RATER_ID"),
        criteria=[
            CriterionRating(criterion_id=str(item["criterion_id"]))
            for item in RUBRIC_DEFINITIONS
        ],
        completed_at=None,
        signature=RatingSignature(),
    )


def _adjudication_template() -> ReadabilityAdjudicationRecord:
    return ReadabilityAdjudicationRecord(
        schema_version=READABILITY_SCHEMA_VERSION,
        adjudication_id="REPLACE_WITH_UNIQUE_ADJUDICATION_ID",
        study_id="REPLACE_WITH_STUDY_ID",
        study_manifest_sha256="0" * 64,
        case_id="REPLACE_WITH_CASE_ID",
        blind_response_id="REPLACE_WITH_BLIND_RESPONSE_ID",
        status="pending",
        adjudicator=_template_rater("REPLACE_WITH_ADJUDICATOR_ID"),
        resolutions=[
            CriterionResolution(criterion_id=str(item["criterion_id"]))
            for item in RUBRIC_DEFINITIONS
        ],
        completed_at=None,
        signature=AdjudicationSignature(),
    )


def _rater_guide() -> str:
    return """# Readability v1 Blinded Rater Guide

The accessible response and formal reference come from one authoritative Physics IR record. Rate
fidelity and comprehension, not whether you prefer the writing style.

## Blinding

- Do not seek the method identity, development history, other raters, or hidden gold.
- Declare any conflict, prior involvement, or accidental identity exposure.
- Use only the frozen accessible view, formal reference, and rubric supplied for the blind ID.

## Scoring

Score every criterion from 1 to 5 using `rubric.yaml`. A critical omission may be declared only for
formula fidelity, assumptions/validity, or warning/certainty preservation. Add a comment for every
score of 1 or 2 and every critical omission.

A fluent response cannot pass if it changes a formula, hides a necessary assumption, or softens a
warning/support boundary. Symbol clarity and task comprehension are evaluated separately and cannot
average away a critical physics failure.

At least two eligible independent raters are required per case. A criterion score range greater
than one point, or disagreement about a critical omission, requires blinded adjudication. The
reported uncertainty is based on the original independent ratings; adjudication supplies the final
decision rather than erasing disagreement.
"""


def generate_readability_packet(
    out_dir: str | Path = DEFAULT_READABILITY_STUDY,
) -> ReadabilityPacketResult:
    study_dir = _project_path(out_dir)
    if study_dir.exists():
        raise FileExistsError(
            f"Readability study directory already exists: {study_dir}. "
            "Use a new path so ratings are never overwritten."
        )
    for relative in ("ratings", "adjudications", "views"):
        target = study_dir / relative
        target.mkdir(parents=True)
        (target / ".gitkeep").write_text("", encoding="utf-8")
    forms_dir = study_dir / "forms"
    forms_dir.mkdir()

    rubric = default_readability_rubric()
    rubric_path = study_dir / "rubric.yaml"
    _write_yaml(rubric_path, rubric)
    manifest = ReadabilityStudyManifest(
        schema_version=READABILITY_SCHEMA_VERSION,
        study_id="spintexture_readability_v1",
        study_status="template",
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        rubric=FrozenStudyArtifact(path="rubric.yaml", sha256=_sha256(rubric_path)),
        blinding=BlindingProtocol(
            method_identity_hidden=True,
            case_order_randomized=True,
            raters_cannot_access_model_metadata=True,
            gold_used_only_as_frozen_reference=True,
        ),
        cases=[],
    )
    manifest_path = study_dir / "study_manifest.yaml"
    _write_yaml(manifest_path, manifest)
    rating_path = forms_dir / "rating_form_template.yaml"
    adjudication_path = forms_dir / "adjudication_form_template.yaml"
    _write_yaml(rating_path, _rating_template())
    _write_yaml(adjudication_path, _adjudication_template())
    guide_path = study_dir / "RATER_GUIDE.md"
    guide_path.write_text(_rater_guide(), encoding="utf-8")
    return ReadabilityPacketResult(
        study_dir=str(study_dir),
        manifest_path=str(manifest_path),
        rubric_path=str(rubric_path),
        guide_path=str(guide_path),
        rating_template=str(rating_path),
        adjudication_template=str(adjudication_path),
    )


def _resolve_study_artifact(study_dir: Path, artifact: FrozenStudyArtifact) -> Path:
    locator = Path(artifact.path)
    if locator.is_absolute():
        raise ValueError(f"Study artifact path must be relative: {artifact.path}")
    resolved = (study_dir / locator).resolve()
    try:
        resolved.relative_to(study_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Study artifact escapes study directory: {artifact.path}") from exc
    if not resolved.is_file():
        raise ValueError(f"Study artifact is missing: {artifact.path}")
    if _sha256(resolved) != artifact.sha256:
        raise ValueError(f"Study artifact SHA-256 mismatch: {artifact.path}")
    return resolved


def _extract_section(text: str, start: str, end: str | None = None) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise ValueError(f"Layered report is missing section: {start}")
    if end is None:
        return text[start_index:].rstrip() + "\n"
    end_index = text.find(end, start_index + len(start))
    if end_index < 0:
        raise ValueError(f"Layered report is missing section boundary: {end}")
    return text[start_index:end_index].rstrip() + "\n"


def _validate_case_artifacts(study_dir: Path, case: ReadabilityStudyCase) -> list[str]:
    issues: list[str] = []
    try:
        record_path = _resolve_study_artifact(study_dir, case.authoritative_record)
        report_path = _resolve_study_artifact(study_dir, case.layered_report)
        accessible_path = _resolve_study_artifact(study_dir, case.accessible_view)
        formal_path = _resolve_study_artifact(study_dir, case.formal_reference)
    except ValueError as exc:
        return [str(exc)]
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"Authoritative record cannot be parsed: {exc}"]
    if record.get("record_id") != case.record_id:
        issues.append("authoritative record ID does not match study case")
    report_text = report_path.read_text(encoding="utf-8")
    if f"`{case.record_id}`" not in report_text:
        issues.append("layered report does not contain the authoritative record ID")
    try:
        expected_accessible = _extract_section(
            report_text,
            "## Accessible view",
            "## Formal view",
        )
        expected_formal = _extract_section(report_text, "## Formal view")
    except ValueError as exc:
        issues.append(str(exc))
        return issues
    if accessible_path.read_text(encoding="utf-8") != expected_accessible:
        issues.append("accessible view is not an exact extraction of the layered report")
    if formal_path.read_text(encoding="utf-8") != expected_formal:
        issues.append("formal reference is not an exact extraction of the layered report")
    return issues


def _rater_exclusion_reasons(
    rating: ReadabilityRatingRecord,
    manifest: ReadabilityStudyManifest,
    manifest_sha256: str,
    case: ReadabilityStudyCase,
) -> list[str]:
    reasons: list[str] = []
    if rating.status != "complete":
        reasons.append("rating is pending")
    if rating.schema_version != READABILITY_SCHEMA_VERSION:
        reasons.append("rating schema version mismatch")
    if rating.study_id != manifest.study_id or rating.study_manifest_sha256 != manifest_sha256:
        reasons.append("rating is not bound to the frozen study manifest")
    if rating.case_id != case.case_id or rating.blind_response_id != case.blind_response_id:
        reasons.append("rating identity does not match the study case")
    rater = rating.rater
    if not rater.target_audience_match:
        reasons.append("rater does not match the target audience")
    if not rater.independent_of_system_development:
        reasons.append("rater is not independent of system development")
    if rater.involved_in_response_generation:
        reasons.append("rater was involved in response generation")
    if rater.method_identity_seen:
        reasons.append("rater saw the method identity")
    if rater.conflict_declared:
        reasons.append("rater declared a conflict")
    if not _timestamp_is_valid(rating.completed_at):
        reasons.append("rating completion timestamp is invalid")
    if rating.signature.signed_by.strip() != rater.rater_id.strip():
        reasons.append("rating signature does not match rater ID")
    if not _timestamp_is_valid(rating.signature.signed_at):
        reasons.append("rating signature timestamp is invalid")
    if rating.signature.attestation != RATING_ATTESTATION:
        reasons.append("rating attestation text was changed")
    return reasons


def _adjudication_reasons(
    adjudication: ReadabilityAdjudicationRecord,
    manifest: ReadabilityStudyManifest,
    manifest_sha256: str,
    case: ReadabilityStudyCase,
    rater_ids: set[str],
) -> list[str]:
    reasons: list[str] = []
    if adjudication.status != "complete":
        reasons.append("adjudication is pending")
    if (
        adjudication.study_id != manifest.study_id
        or adjudication.study_manifest_sha256 != manifest_sha256
    ):
        reasons.append("adjudication is not bound to the frozen study manifest")
    if (
        adjudication.case_id != case.case_id
        or adjudication.blind_response_id != case.blind_response_id
    ):
        reasons.append("adjudication identity does not match the study case")
    profile = adjudication.adjudicator
    if profile.rater_id in rater_ids:
        reasons.append("adjudicator must be independent of the original raters")
    if not profile.independent_of_system_development:
        reasons.append("adjudicator is not independent of system development")
    if profile.involved_in_response_generation:
        reasons.append("adjudicator was involved in response generation")
    if profile.method_identity_seen:
        reasons.append("adjudicator saw the method identity")
    if profile.conflict_declared:
        reasons.append("adjudicator declared a conflict")
    if not _timestamp_is_valid(adjudication.completed_at):
        reasons.append("adjudication completion timestamp is invalid")
    if adjudication.signature.signed_by.strip() != profile.rater_id.strip():
        reasons.append("adjudication signature does not match adjudicator ID")
    if not _timestamp_is_valid(adjudication.signature.signed_at):
        reasons.append("adjudication signature timestamp is invalid")
    if adjudication.signature.attestation != ADJUDICATION_ATTESTATION:
        reasons.append("adjudication attestation text was changed")
    return reasons


def _criterion_aggregate(
    rubric: RubricCriterion,
    ratings: list[ReadabilityRatingRecord],
    disagreement_threshold: int,
) -> CriterionAggregate:
    entries = [
        next(item for item in rating.criteria if item.criterion_id == rubric.criterion_id)
        for rating in ratings
    ]
    scores = [int(entry.score) for entry in entries if entry.score is not None]
    mean_score = statistics.mean(scores)
    stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0
    standard_error = stdev / math.sqrt(len(scores)) if scores else 0.0
    omission_votes = sum(bool(entry.critical_omission) for entry in entries)
    score_range = max(scores) - min(scores)
    omission_disagreement = 0 < omission_votes < len(entries)
    disagreement = score_range > disagreement_threshold or omission_disagreement
    return CriterionAggregate(
        criterion_id=rubric.criterion_id,
        critical=rubric.critical,
        minimum_score=rubric.minimum_score,
        rating_count=len(scores),
        mean_score=round(mean_score, 4),
        standard_deviation=round(stdev, 4),
        standard_error=round(standard_error, 4),
        approximate_ci95_low=round(max(1.0, mean_score - 1.96 * standard_error), 4),
        approximate_ci95_high=round(min(5.0, mean_score + 1.96 * standard_error), 4),
        score_range=score_range,
        critical_omission_votes=omission_votes,
        disagreement=disagreement,
        final_score=None,
        final_critical_omission=None,
        passed=None,
    )


def _finalize_criteria(
    aggregates: list[CriterionAggregate],
    adjudication: ReadabilityAdjudicationRecord | None,
) -> list[CriterionAggregate]:
    resolutions = (
        {item.criterion_id: item for item in adjudication.resolutions}
        if adjudication is not None
        else {}
    )
    finalized: list[CriterionAggregate] = []
    for aggregate in aggregates:
        resolution = resolutions.get(aggregate.criterion_id)
        if resolution is None:
            final_score = aggregate.mean_score
            final_omission = aggregate.critical_omission_votes > 0
        else:
            final_score = float(resolution.final_score)
            final_omission = bool(resolution.critical_omission_confirmed)
        passed = final_score >= aggregate.minimum_score and not (
            aggregate.critical and final_omission
        )
        finalized.append(
            aggregate.model_copy(
                update={
                    "final_score": final_score,
                    "final_critical_omission": final_omission,
                    "passed": passed,
                }
            )
        )
    return finalized


def _evaluate_case(
    study_dir: Path,
    manifest: ReadabilityStudyManifest,
    manifest_sha256: str,
    rubric: ReadabilityRubric,
    case: ReadabilityStudyCase,
    ratings: list[ReadabilityRatingRecord],
    adjudication: ReadabilityAdjudicationRecord | None,
) -> ReadabilityCaseResult:
    issues = _validate_case_artifacts(study_dir, case)
    excluded: dict[str, list[str]] = {}
    eligible: list[ReadabilityRatingRecord] = []
    seen_raters: set[str] = set()
    for rating in ratings:
        rater_id = rating.rater.rater_id
        if rater_id in seen_raters:
            raise ValueError(f"Duplicate readability rater for {case.case_id}: {rater_id}")
        seen_raters.add(rater_id)
        reasons = _rater_exclusion_reasons(
            rating,
            manifest,
            manifest_sha256,
            case,
        )
        if reasons:
            excluded[rating.rating_id] = reasons
        else:
            eligible.append(rating)

    if not ratings:
        return ReadabilityCaseResult(
            case_id=case.case_id,
            blind_response_id=case.blind_response_id,
            status="missing",
            rating_record_count=0,
            eligible_rater_count=0,
            excluded_ratings={},
            criteria=[],
            adjudication_status="not_required",
            issues=issues + ["no rating records were submitted"],
        )
    if manifest.study_status != "frozen":
        issues.append("study manifest is not frozen")
    if len(eligible) < rubric.minimum_independent_raters or issues:
        if len(eligible) < rubric.minimum_independent_raters:
            issues.append(
                f"requires at least {rubric.minimum_independent_raters} eligible independent raters"
            )
        return ReadabilityCaseResult(
            case_id=case.case_id,
            blind_response_id=case.blind_response_id,
            status="incomplete",
            rating_record_count=len(ratings),
            eligible_rater_count=len(eligible),
            excluded_ratings=excluded,
            criteria=[],
            adjudication_status="not_required",
            issues=issues,
        )

    aggregates = [
        _criterion_aggregate(criterion, eligible, rubric.disagreement_threshold)
        for criterion in rubric.criteria
    ]
    disagreement = any(item.disagreement for item in aggregates)
    adjudication_status: Literal["not_required", "missing", "pending", "complete"] = (
        "not_required"
    )
    valid_adjudication: ReadabilityAdjudicationRecord | None = None
    if disagreement:
        if adjudication is None:
            adjudication_status = "missing"
        else:
            adjudication_issues = _adjudication_reasons(
                adjudication,
                manifest,
                manifest_sha256,
                case,
                seen_raters,
            )
            if adjudication_issues:
                adjudication_status = "pending"
                issues.extend(adjudication_issues)
            else:
                adjudication_status = "complete"
                valid_adjudication = adjudication
        if valid_adjudication is None:
            return ReadabilityCaseResult(
                case_id=case.case_id,
                blind_response_id=case.blind_response_id,
                status="needs_adjudication",
                rating_record_count=len(ratings),
                eligible_rater_count=len(eligible),
                excluded_ratings=excluded,
                criteria=aggregates,
                adjudication_status=adjudication_status,
                issues=issues + ["independent ratings exceed the disagreement threshold"],
            )

    finalized = _finalize_criteria(aggregates, valid_adjudication)
    status: ReadabilityStatus = (
        "passed" if all(item.passed for item in finalized) else "failed"
    )
    return ReadabilityCaseResult(
        case_id=case.case_id,
        blind_response_id=case.blind_response_id,
        status=status,
        rating_record_count=len(ratings),
        eligible_rater_count=len(eligible),
        excluded_ratings=excluded,
        criteria=finalized,
        adjudication_status=adjudication_status,
        issues=issues,
    )


def evaluate_readability_study(study_dir: str | Path) -> ReadabilityStudyResult:
    resolved_study = _project_path(study_dir)
    manifest_path = resolved_study / "study_manifest.yaml"
    manifest = ReadabilityStudyManifest.model_validate(_load_yaml(manifest_path))
    if manifest.schema_version != READABILITY_SCHEMA_VERSION:
        raise ValueError("Unsupported readability study schema version")
    if not _timestamp_is_valid(manifest.created_at):
        raise ValueError("Readability study creation timestamp must be timezone-aware ISO-8601")
    rubric_path = _resolve_study_artifact(resolved_study, manifest.rubric)
    rubric = ReadabilityRubric.model_validate(_load_yaml(rubric_path))
    if rubric.model_dump() != default_readability_rubric().model_dump():
        raise ValueError("Readability rubric differs from the frozen v1 contract")
    if not all(manifest.blinding.model_dump().values()):
        raise ValueError("Readability study blinding protocol is incomplete")
    manifest_sha256 = _sha256(manifest_path)

    cases_by_id = {case.case_id: case for case in manifest.cases}
    ratings_by_case: dict[str, list[ReadabilityRatingRecord]] = {
        case_id: [] for case_id in cases_by_id
    }
    for rating_path in sorted((resolved_study / "ratings").glob("*.yaml")):
        rating = ReadabilityRatingRecord.model_validate(_load_yaml(rating_path))
        if rating.case_id not in cases_by_id:
            raise ValueError(f"Rating references an unknown case: {rating.case_id}")
        ratings_by_case[rating.case_id].append(rating)

    adjudications: dict[str, ReadabilityAdjudicationRecord] = {}
    for adjudication_path in sorted((resolved_study / "adjudications").glob("*.yaml")):
        adjudication = ReadabilityAdjudicationRecord.model_validate(
            _load_yaml(adjudication_path)
        )
        if adjudication.case_id not in cases_by_id:
            raise ValueError(
                f"Adjudication references an unknown case: {adjudication.case_id}"
            )
        if adjudication.case_id in adjudications:
            raise ValueError(f"Duplicate adjudication for case: {adjudication.case_id}")
        adjudications[adjudication.case_id] = adjudication

    case_results = [
        _evaluate_case(
            resolved_study,
            manifest,
            manifest_sha256,
            rubric,
            case,
            ratings_by_case[case.case_id],
            adjudications.get(case.case_id),
        )
        for case in manifest.cases
    ]
    status_counts = {
        status: sum(case.status == status for case in case_results)
        for status in (
            "missing",
            "incomplete",
            "needs_adjudication",
            "passed",
            "failed",
        )
    }
    issues: list[str] = []
    if not manifest.cases:
        status: ReadabilityStatus = "missing"
        issues.append("study contains no readability cases")
    elif status_counts["missing"] == len(case_results):
        status = "missing"
    elif status_counts["missing"] or status_counts["incomplete"]:
        status = "incomplete"
    elif status_counts["needs_adjudication"]:
        status = "needs_adjudication"
    elif status_counts["failed"]:
        status = "failed"
    else:
        status = "passed"
    return ReadabilityStudyResult(
        study_id=manifest.study_id,
        rubric_version=rubric.rubric_version,
        status=status,
        case_count=len(case_results),
        status_counts=status_counts,
        cases=case_results,
        issues=issues,
    )


def render_readability_result(result: ReadabilityStudyResult) -> str:
    lines = [
        "# Readability study result",
        "",
        f"- Study: `{result.study_id}`",
        f"- Rubric: `{result.rubric_version}`",
        f"- Status: `{result.status}`",
        f"- Cases: {result.case_count}",
        "",
        "| Case | Blind ID | Status | Eligible raters | Adjudication |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for case in result.cases:
        lines.append(
            f"| `{case.case_id}` | `{case.blind_response_id}` | `{case.status}` | "
            f"{case.eligible_rater_count} | `{case.adjudication_status}` |"
        )
    lines.extend(
        [
            "",
            "Critical formula, assumption, warning, or certainty failures are gating criteria and cannot be averaged away by symbol clarity or writing quality.",
            "Approximate 95% intervals summarize original independent scores; they are not physical uncertainty or model confidence.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_readability_study(
    study_dir: str | Path,
    out_dir: str | Path,
) -> ReadabilityStudyResult:
    result = evaluate_readability_study(study_dir)
    output_dir = _project_path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "readability_scores.json"
    markdown_path = output_dir / "readability_scores.md"
    result = result.model_copy(
        update={
            "report_json": _stored_project_path(json_path),
            "report_markdown": _stored_project_path(markdown_path),
        }
    )
    json_path.write_text(result.to_json() + "\n", encoding="utf-8")
    markdown_path.write_text(render_readability_result(result), encoding="utf-8")
    return result
