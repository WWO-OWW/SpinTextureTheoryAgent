from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .benchmark_authoring import (
    AuthoringCaseSubmission,
    AuthoringPacketManifest,
    verify_authoring_packet,
)
from .benchmark_manifest import (
    DEFAULT_BENCHMARK_MANIFEST,
    PRIMARY_PARTITIONS,
    BenchmarkManifestRegistry,
    RepetitionPolicy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTAKE_SCHEMA_VERSION = "1.0.0"

INTAKE_ATTESTATION = (
    "I reviewed the frozen public task, source provenance, split assignment, "
    "scorer policy, and custody record without opening sealed evaluation material."
)

CaseIntakeStatus = Literal["incomplete", "pending", "accepted", "rejected"]
StageStatus = Literal["incomplete", "pending", "decided"]


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


def _model_sha256(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def _write_yaml(path: Path, model: BaseModel | dict[str, object]) -> None:
    payload = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
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


class FrozenIntakeArtifact(BaseModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class StagedSealedArtifact(FrozenIntakeArtifact):
    artifact_type: Literal["gold_answer", "readability_rubric"]
    protection: Literal["encrypted_archive", "custodian_access_control"]
    sealed_at: str


class StagedIntakeCase(BaseModel):
    case_id: str
    primary_partition: Literal["held_out_supported", "readability"]
    task_fingerprint: str
    claim_class: Literal["known_theory_derivation", "accessible_explanation"]
    scorer: str
    allowed_tools: list[str]
    repetition_policy: RepetitionPolicy
    public_brief: FrozenIntakeArtifact
    source_snapshot: FrozenIntakeArtifact
    source_type: Literal["primary_literature", "external_contribution"]
    source_citation: str
    source_locator: str
    equation_locators: list[str]
    sealed_artifacts: list[StagedSealedArtifact]
    packet_case_metadata_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    leakage_attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    custody_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_author_id: str
    gold_custodian_id: str
    review_path: str


class IntakeStagingManifest(BaseModel):
    schema_version: str
    stage_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    created_at: str
    benchmark_manifest: str
    benchmark_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    benchmark_partition_sha256: dict[str, str]
    benchmark_id: str
    benchmark_version: str
    scorer_registry_version: str
    packet_snapshot: str
    packet_manifest: FrozenIntakeArtifact
    authoring_verification: FrozenIntakeArtifact
    cases: list[StagedIntakeCase]

    @model_validator(mode="after")
    def validate_cases(self) -> "IntakeStagingManifest":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Intake staging case IDs must be unique")
        if not self.cases:
            raise ValueError("An intake stage requires at least one submitted case")
        if set(self.benchmark_partition_sha256) != set(PRIMARY_PARTITIONS):
            raise ValueError("Intake stage must bind exactly the five benchmark partitions")
        if any(
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
            for digest in self.benchmark_partition_sha256.values()
        ):
            raise ValueError("Benchmark partition SHA-256 values must be lowercase hex digests")
        return self


class IntakeReviewer(BaseModel):
    reviewer_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = ""
    affiliation: str = ""
    role: str = "benchmark_intake_reviewer"
    involved_in_case_authorship: bool = False
    has_plaintext_gold_access: bool = False
    conflict_declared: bool = False
    conflict_details: str = ""


class SourceEligibilityDecision(BaseModel):
    status: Literal["pending", "eligible", "ineligible"] = "pending"
    citation_resolves: bool | None = None
    equation_locators_verified: bool | None = None
    source_not_used_in_development: bool | None = None
    scientifically_relevant: bool | None = None
    gold_scope_supported_by_source: bool | None = None
    rationale: str = ""


class IntakeGateAssessment(BaseModel):
    partition_assignment_valid: bool | None = None
    public_task_contains_no_private_gold: bool | None = None
    task_fingerprint_clear: bool | None = None
    scorer_compatible: bool | None = None
    allowed_tools_locked: bool | None = None
    repetition_policy_locked: bool | None = None
    custody_intact: bool | None = None
    sealed_artifacts_unopened: bool | None = None


class IntakeReviewSignature(BaseModel):
    signed_by: str = ""
    signed_at: str | None = None
    attestation: str = INTAKE_ATTESTATION


class IntakeReviewRecord(BaseModel):
    schema_version: str
    review_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    stage_id: str
    stage_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str
    decision: Literal["pending", "accepted", "rejected"]
    reviewer: IntakeReviewer
    source_eligibility: SourceEligibilityDecision
    gates: IntakeGateAssessment
    decision_rationale: str = ""
    reviewed_at: str | None = None
    signature: IntakeReviewSignature


class IntakeCaseVerification(BaseModel):
    case_id: str
    primary_partition: Literal["held_out_supported", "readability"]
    decision: CaseIntakeStatus
    integrity_valid: bool
    reasons: list[str]
    review_path: str


class IntakeStageVerification(BaseModel):
    stage_id: str
    status: StageStatus
    integrity_valid: bool
    freeze_preview_ready: bool
    decision_counts: dict[str, int]
    cases: list[IntakeCaseVerification]
    issues: list[str]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


class IntakeStageResult(BaseModel):
    stage_dir: str
    stage_manifest: str
    guide_path: str
    review_forms: list[str]


class DraftPartitionEntry(BaseModel):
    case_id: str
    primary_partition: Literal["held_out_supported", "readability"]
    task_fingerprint: str
    claim_class: Literal["known_theory_derivation", "accessible_explanation"]
    registration_status: Literal["blinded_staged"] = "blinded_staged"
    public_brief: FrozenIntakeArtifact
    source_snapshot: FrozenIntakeArtifact
    source_citation: str
    source_locator: str
    equation_locators: list[str]
    gold_visibility: Literal["blinded"] = "blinded"
    leakage_status: Literal["held_out_blinded"] = "held_out_blinded"
    scorer: str
    allowed_tools: list[str]
    repetition_policy: RepetitionPolicy
    sealed_artifacts: list[StagedSealedArtifact]
    intake_review: FrozenIntakeArtifact
    direct_registration_blockers: list[str]


class PartitionEntryPreview(BaseModel):
    schema_version: str
    preview_only: Literal[True] = True
    do_not_register_directly: Literal[True] = True
    intake_stage: str
    benchmark_id: str
    benchmark_version: str
    primary_partition: Literal["held_out_supported", "readability"]
    entries: list[DraftPartitionEntry]


class FreezePreviewReport(BaseModel):
    schema_version: str
    stage_id: str
    status: Literal["blocked", "blind_split_ready"]
    blind_split_freeze_ready: bool
    direct_manifest_registration_ready: Literal[False] = False
    real_manifests_modified: Literal[False] = False
    accepted_case_ids: list[str]
    rejected_case_ids: list[str]
    blockers: list[str]
    direct_registration_blockers: list[str]
    partition_previews: dict[str, FrozenIntakeArtifact]
    report_json: str
    report_markdown: str


def _packet_manifest(packet_dir: Path) -> AuthoringPacketManifest:
    return AuthoringPacketManifest.model_validate(
        _load_yaml(packet_dir / "packet_manifest.yaml")
    )


def _snapshot_artifact(case_path: str, packet_dir: Path, stage_dir: Path) -> FrozenIntakeArtifact:
    source = (packet_dir / case_path).resolve()
    try:
        source.relative_to(packet_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Packet artifact escapes packet directory: {case_path}") from exc
    if not source.is_file():
        raise ValueError(f"Packet artifact is missing: {case_path}")
    staged = stage_dir / "packet_snapshot" / case_path
    return FrozenIntakeArtifact(
        path=str(staged.relative_to(stage_dir)),
        sha256=_sha256(staged),
    )


def _staged_case(
    case: AuthoringCaseSubmission,
    packet_dir: Path,
    stage_dir: Path,
) -> StagedIntakeCase:
    public = _snapshot_artifact(case.public_brief.path, packet_dir, stage_dir)
    source = _snapshot_artifact(
        case.source_provenance.snapshot.path,
        packet_dir,
        stage_dir,
    )
    sealed = []
    for artifact in case.sealed_artifacts:
        staged = _snapshot_artifact(artifact.path, packet_dir, stage_dir)
        sealed.append(
            StagedSealedArtifact(
                artifact_type=artifact.artifact_type,
                path=staged.path,
                sha256=staged.sha256,
                protection=artifact.protection,
                sealed_at=artifact.sealed_at,
            )
        )
    return StagedIntakeCase(
        case_id=case.case_id,
        primary_partition=case.primary_partition,
        task_fingerprint=case.task_fingerprint,
        claim_class=case.claim_class,
        scorer=case.scorer,
        allowed_tools=case.allowed_tools,
        repetition_policy=case.repetition_policy,
        public_brief=public,
        source_snapshot=source,
        source_type=case.source_provenance.source_type,
        source_citation=case.source_provenance.citation,
        source_locator=case.source_provenance.locator,
        equation_locators=case.source_provenance.equation_locators,
        sealed_artifacts=sealed,
        packet_case_metadata_sha256=_model_sha256(case),
        leakage_attestation_sha256=_model_sha256(case.leakage_attestation),
        custody_record_sha256=_model_sha256(case.custody),
        case_author_id=case.case_author.participant_id,
        gold_custodian_id=case.gold_custodian.participant_id,
        review_path=f"reviews/{case.case_id}_intake_review.yaml",
    )


def _pending_review(
    stage: IntakeStagingManifest,
    case: StagedIntakeCase,
    stage_sha256: str,
) -> IntakeReviewRecord:
    return IntakeReviewRecord(
        schema_version=INTAKE_SCHEMA_VERSION,
        review_id=f"{case.case_id}_intake_review_01",
        stage_id=stage.stage_id,
        stage_manifest_sha256=stage_sha256,
        case_id=case.case_id,
        decision="pending",
        reviewer=IntakeReviewer(reviewer_id="REPLACE_WITH_REVIEWER_ID"),
        source_eligibility=SourceEligibilityDecision(),
        gates=IntakeGateAssessment(),
        signature=IntakeReviewSignature(),
    )


def _intake_guide() -> str:
    return """# Benchmark v1 Intake And Freeze Guide

This stage is an immutable snapshot of an externally authored packet that passed the authoring
verifier. The snapshot includes public files, source files, and opaque sealed bytes. Do not decrypt
or open sealed evaluation material during intake.

## Intake reviewer

1. Resolve the source citation and verify every equation/page locator.
2. Confirm the source and task were not used to develop Project 1 routes, prompts, or scorers.
3. Review scientific relevance, partition assignment, public-task leakage, scorer compatibility,
   tool parity, repetition policy, and custody metadata.
4. Fill the case review under `reviews/` as `accepted` or `rejected`, add rationale and a
   timezone-aware signature. Do not mark a gate true without evidence.
5. Run `python -m spintexture_agent.cli benchmark-intake verify --stage <stage-dir>`.

An accepted intake is eligible only for a blinded split-freeze preview. It is not an executable
benchmark case: sealed gold must later be materialized by the evaluation custodian after the system
and scorer are frozen. Preview generation never modifies the real benchmark manifests.
"""


def stage_authoring_packet(
    packet_dir: str | Path,
    out_dir: str | Path,
) -> IntakeStageResult:
    source_packet = _project_path(packet_dir)
    verification = verify_authoring_packet(source_packet)
    if not verification.ready_for_intake:
        reasons = verification.packet_issues + [
            issue for case in verification.cases for issue in case.issues
        ]
        raise ValueError(
            "Authoring packet is not ready for intake: " + "; ".join(reasons)
        )
    stage_dir = _project_path(out_dir)
    if stage_dir.exists():
        raise FileExistsError(
            f"Benchmark intake stage already exists: {stage_dir}. "
            "Use a new path so packet evidence and decisions are never overwritten."
        )
    stage_dir.mkdir(parents=True)
    snapshot = stage_dir / "packet_snapshot"
    shutil.copytree(source_packet, snapshot)
    snapshot_verification = verify_authoring_packet(snapshot)
    if not snapshot_verification.ready_for_intake:
        raise ValueError("Copied authoring packet failed post-copy verification")
    authoring_manifest = _packet_manifest(snapshot)
    benchmark_path = _project_path(authoring_manifest.benchmark_manifest).resolve()
    if benchmark_path != DEFAULT_BENCHMARK_MANIFEST.resolve():
        raise ValueError(
            "Authoring packet does not target the Project 1 benchmark v1 manifest"
        )
    registry = BenchmarkManifestRegistry(benchmark_path)
    partition_hashes = {
        reference.primary_partition: _sha256(_project_path(reference.path))
        for reference in registry.suite.partitions
    }
    staged_cases = [
        _staged_case(case, snapshot, stage_dir) for case in authoring_manifest.cases
    ]
    packet_manifest_path = snapshot / "packet_manifest.yaml"
    authoring_verification_path = stage_dir / "authoring_verification.json"
    authoring_verification_path.write_text(
        snapshot_verification.to_json(),
        encoding="utf-8",
    )
    stage = IntakeStagingManifest(
        schema_version=INTAKE_SCHEMA_VERSION,
        stage_id=f"{authoring_manifest.packet_id}_intake",
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        benchmark_manifest=authoring_manifest.benchmark_manifest,
        benchmark_manifest_sha256=_sha256(benchmark_path),
        benchmark_partition_sha256=partition_hashes,
        benchmark_id=registry.suite.benchmark_id,
        benchmark_version=registry.suite.benchmark_version,
        scorer_registry_version=registry.suite.scorer_registry_version,
        packet_snapshot="packet_snapshot",
        packet_manifest=FrozenIntakeArtifact(
            path=str(packet_manifest_path.relative_to(stage_dir)),
            sha256=_sha256(packet_manifest_path),
        ),
        authoring_verification=FrozenIntakeArtifact(
            path=str(authoring_verification_path.relative_to(stage_dir)),
            sha256=_sha256(authoring_verification_path),
        ),
        cases=staged_cases,
    )
    stage_manifest_path = stage_dir / "intake_manifest.yaml"
    _write_yaml(stage_manifest_path, stage)
    stage_sha256 = _sha256(stage_manifest_path)
    reviews_dir = stage_dir / "reviews"
    reviews_dir.mkdir()
    review_forms = []
    for case in stage.cases:
        review_path = stage_dir / case.review_path
        _write_yaml(review_path, _pending_review(stage, case, stage_sha256))
        review_forms.append(str(review_path))
    guide_path = stage_dir / "INTAKE_GUIDE.md"
    guide_path.write_text(_intake_guide(), encoding="utf-8")
    return IntakeStageResult(
        stage_dir=str(stage_dir),
        stage_manifest=str(stage_manifest_path),
        guide_path=str(guide_path),
        review_forms=review_forms,
    )


def _resolve_stage_artifact(stage_dir: Path, artifact: FrozenIntakeArtifact) -> Path:
    locator = Path(artifact.path)
    if locator.is_absolute():
        raise ValueError(f"Intake artifact path must be relative: {artifact.path}")
    resolved = (stage_dir / locator).resolve()
    try:
        resolved.relative_to(stage_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Intake artifact escapes stage directory: {artifact.path}") from exc
    if not resolved.is_file():
        raise ValueError(f"Intake artifact is missing: {artifact.path}")
    if _sha256(resolved) != artifact.sha256:
        raise ValueError(f"Intake artifact SHA-256 mismatch: {artifact.path}")
    return resolved


def _resolve_stage_path(stage_dir: Path, locator: str, *, directory: bool) -> Path:
    path = Path(locator)
    if path.is_absolute():
        raise ValueError(f"Intake path must be relative: {locator}")
    resolved = (stage_dir / path).resolve()
    try:
        resolved.relative_to(stage_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Intake path escapes stage directory: {locator}") from exc
    exists = resolved.is_dir() if directory else resolved.is_file()
    if not exists:
        kind = "directory" if directory else "file"
        raise ValueError(f"Intake {kind} is missing: {locator}")
    return resolved


def _review_decision(
    review: IntakeReviewRecord,
    stage: IntakeStagingManifest,
    stage_sha256: str,
    case: StagedIntakeCase,
) -> tuple[CaseIntakeStatus, list[str]]:
    reasons: list[str] = []
    if review.schema_version != INTAKE_SCHEMA_VERSION:
        reasons.append("intake review schema version mismatch")
    if review.stage_id != stage.stage_id or review.stage_manifest_sha256 != stage_sha256:
        reasons.append("review is not bound to the frozen intake manifest")
    if review.case_id != case.case_id:
        reasons.append("review case ID does not match the intake case")
    if review.decision == "pending":
        return ("incomplete" if reasons else "pending"), reasons

    reviewer = review.reviewer
    if not reviewer.name.strip() or not reviewer.affiliation.strip():
        reasons.append("reviewer name and affiliation are required")
    if reviewer.reviewer_id in {case.case_author_id, case.gold_custodian_id}:
        reasons.append("intake reviewer cannot be the case author or gold custodian")
    if reviewer.involved_in_case_authorship:
        reasons.append("intake reviewer was involved in case authorship")
    if reviewer.has_plaintext_gold_access:
        reasons.append("intake reviewer accessed plaintext gold")
    if reviewer.conflict_declared:
        reasons.append("intake reviewer declared a conflict")
    if not review.decision_rationale.strip():
        reasons.append("intake decision rationale is required")
    if not _timestamp_is_valid(review.reviewed_at):
        reasons.append("intake review timestamp must be timezone-aware ISO-8601")
    if review.signature.signed_by.strip() != reviewer.reviewer_id.strip():
        reasons.append("intake signature does not match reviewer ID")
    if not _timestamp_is_valid(review.signature.signed_at):
        reasons.append("intake signature timestamp must be timezone-aware ISO-8601")
    if review.signature.attestation != INTAKE_ATTESTATION:
        reasons.append("intake attestation text was changed")

    source = review.source_eligibility
    source_checks = (
        source.citation_resolves,
        source.equation_locators_verified,
        source.source_not_used_in_development,
        source.scientifically_relevant,
        source.gold_scope_supported_by_source,
    )
    gate_values = tuple(review.gates.model_dump().values())
    if source.status == "pending":
        reasons.append("decided case lacks a source-eligibility decision")
    if any(value is None for value in source_checks):
        reasons.append("decided case has incomplete source-eligibility checks")
    if not source.rationale.strip():
        reasons.append("decided source eligibility requires a rationale")
    if any(value is None for value in gate_values):
        reasons.append("decided case has incomplete intake gates")

    if review.decision == "accepted":
        if source.status != "eligible":
            reasons.append("accepted case lacks an eligible source decision")
        if not all(value is True for value in source_checks):
            reasons.append("accepted case has incomplete source-eligibility checks")
        if not all(value is True for value in gate_values):
            reasons.append("accepted case has incomplete intake gates")
    elif not (
        source.status == "ineligible"
        or any(value is False for value in source_checks)
        or any(value is False for value in gate_values)
    ):
        reasons.append("rejected case must record at least one failed source or intake gate")

    if reasons:
        return "incomplete", reasons
    return review.decision, []


def verify_intake_stage(stage_dir: str | Path) -> IntakeStageVerification:
    resolved_stage = _project_path(stage_dir)
    stage_manifest_path = resolved_stage / "intake_manifest.yaml"
    stage = IntakeStagingManifest.model_validate(_load_yaml(stage_manifest_path))
    if stage.schema_version != INTAKE_SCHEMA_VERSION:
        raise ValueError("Unsupported benchmark intake schema version")
    stage_sha256 = _sha256(stage_manifest_path)
    stage_issues: list[str] = []
    if not _timestamp_is_valid(stage.created_at):
        stage_issues.append("intake stage timestamp must be timezone-aware ISO-8601")

    try:
        packet_manifest_path = _resolve_stage_artifact(
            resolved_stage,
            stage.packet_manifest,
        )
        _resolve_stage_artifact(resolved_stage, stage.authoring_verification)
        snapshot_dir = _resolve_stage_path(
            resolved_stage,
            stage.packet_snapshot,
            directory=True,
        )
        snapshot_verification = verify_authoring_packet(snapshot_dir)
        if not snapshot_verification.ready_for_intake:
            stage_issues.append("staged authoring packet no longer passes verification")
        verification_hash = hashlib.sha256(
            snapshot_verification.to_json().encode("utf-8")
        ).hexdigest()
        if verification_hash != stage.authoring_verification.sha256:
            stage_issues.append("authoring verification digest mismatch")
        packet = AuthoringPacketManifest.model_validate(_load_yaml(packet_manifest_path))
    except (FileNotFoundError, ValueError) as exc:
        stage_issues.append(str(exc))
        packet = None

    benchmark_path = _project_path(stage.benchmark_manifest).resolve()
    if benchmark_path != DEFAULT_BENCHMARK_MANIFEST.resolve():
        stage_issues.append("staged benchmark manifest is not the Project 1 v1 manifest")
        benchmark_path = DEFAULT_BENCHMARK_MANIFEST.resolve()
    if not benchmark_path.is_file():
        stage_issues.append("staged benchmark manifest is missing")
    elif _sha256(benchmark_path) != stage.benchmark_manifest_sha256:
        stage_issues.append("staged benchmark manifest SHA-256 drift")
    registry = BenchmarkManifestRegistry(benchmark_path)
    if (
        stage.benchmark_id != registry.suite.benchmark_id
        or stage.benchmark_version != registry.suite.benchmark_version
    ):
        stage_issues.append("staged benchmark identity/version drift")
    if stage.scorer_registry_version != registry.suite.scorer_registry_version:
        stage_issues.append("staged scorer registry version drift")
    current_partition_hashes = {
        reference.primary_partition: _sha256(_project_path(reference.path))
        for reference in registry.suite.partitions
    }
    if current_partition_hashes != stage.benchmark_partition_sha256:
        stage_issues.append("staged benchmark partition SHA-256 drift")

    packet_cases = {case.case_id: case for case in packet.cases} if packet else {}
    case_results: list[IntakeCaseVerification] = []
    for case in stage.cases:
        reasons = list(stage_issues)
        packet_case = packet_cases.get(case.case_id)
        if packet_case is None:
            reasons.append("case is missing from the staged authoring packet")
        else:
            if _model_sha256(packet_case) != case.packet_case_metadata_sha256:
                reasons.append("packet case metadata digest mismatch")
            if (
                _model_sha256(packet_case.leakage_attestation)
                != case.leakage_attestation_sha256
            ):
                reasons.append("leakage attestation digest mismatch")
            if _model_sha256(packet_case.custody) != case.custody_record_sha256:
                reasons.append("custody record digest mismatch")
            if case.scorer != stage.scorer_registry_version:
                reasons.append("case scorer differs from the staged scorer registry")
        for artifact in (
            [case.public_brief, case.source_snapshot]
            + list(case.sealed_artifacts)
        ):
            try:
                _resolve_stage_artifact(resolved_stage, artifact)
            except ValueError as exc:
                reasons.append(str(exc))

        try:
            review_path = _resolve_stage_path(
                resolved_stage,
                case.review_path,
                directory=False,
            )
        except ValueError as exc:
            review_path = resolved_stage / "reviews" / "__invalid_review_path__.yaml"
            decision: CaseIntakeStatus = "incomplete"
            reasons.append(str(exc))
        else:
            try:
                review = IntakeReviewRecord.model_validate(_load_yaml(review_path))
            except ValueError as exc:
                decision = "incomplete"
                reasons.append(f"intake review schema invalid: {exc}")
            else:
                review_decision, review_reasons = _review_decision(
                    review,
                    stage,
                    stage_sha256,
                    case,
                )
                reasons.extend(review_reasons)
                decision = "incomplete" if reasons else review_decision
        case_results.append(
            IntakeCaseVerification(
                case_id=case.case_id,
                primary_partition=case.primary_partition,
                decision=decision,
                integrity_valid=not reasons,
                reasons=reasons,
                review_path=str(review_path),
            )
        )

    decision_counts = {
        status: sum(case.decision == status for case in case_results)
        for status in ("incomplete", "pending", "accepted", "rejected")
    }
    integrity_valid = not stage_issues and all(case.integrity_valid for case in case_results)
    if decision_counts["incomplete"]:
        status: StageStatus = "incomplete"
    elif decision_counts["pending"]:
        status = "pending"
    else:
        status = "decided"
    freeze_ready = (
        integrity_valid
        and status == "decided"
        and decision_counts["accepted"] > 0
    )
    return IntakeStageVerification(
        stage_id=stage.stage_id,
        status=status,
        integrity_valid=integrity_valid,
        freeze_preview_ready=freeze_ready,
        decision_counts=decision_counts,
        cases=case_results,
        issues=stage_issues,
    )


def _render_freeze_report(report: FreezePreviewReport) -> str:
    lines = [
        "# Benchmark v1 release-candidate freeze preview",
        "",
        f"- Stage: `{report.stage_id}`",
        f"- Status: `{report.status}`",
        f"- Blind split freeze ready: `{report.blind_split_freeze_ready}`",
        f"- Direct manifest registration ready: `{report.direct_manifest_registration_ready}`",
        f"- Real manifests modified: `{report.real_manifests_modified}`",
        f"- Accepted cases: {len(report.accepted_case_ids)}",
        f"- Rejected cases: {len(report.rejected_case_ids)}",
        "",
        "## Blockers",
        "",
        *([f"- {item}" for item in report.blockers] or ["- None for blind split staging."]),
        "",
        "## Direct registration blockers",
        "",
        *[f"- {item}" for item in report.direct_registration_blockers],
        "",
        "This preview never edits `benchmark_manifests/v1`. Direct registration remains blocked until the evaluation custodian materializes executable scorer/gold artifacts after system freeze.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def generate_freeze_preview(
    stage_dir: str | Path,
    out_dir: str | Path,
) -> FreezePreviewReport:
    resolved_stage = _project_path(stage_dir)
    output_dir = _project_path(out_dir)
    if output_dir.exists():
        raise FileExistsError(
            f"Freeze preview directory already exists: {output_dir}. Use a new path."
        )
    output_dir.mkdir(parents=True)
    verification = verify_intake_stage(resolved_stage)
    stage = IntakeStagingManifest.model_validate(
        _load_yaml(resolved_stage / "intake_manifest.yaml")
    )
    accepted_ids = [
        case.case_id for case in verification.cases if case.decision == "accepted"
    ]
    rejected_ids = [
        case.case_id for case in verification.cases if case.decision == "rejected"
    ]
    blockers: list[str] = []
    preview_artifacts: dict[str, FrozenIntakeArtifact] = {}
    if not verification.freeze_preview_ready:
        blockers.append(
            "intake stage has incomplete/pending gates or no accepted cases"
        )
    else:
        accepted = {case_id for case_id in accepted_ids}
        reviews = {case.case_id: case for case in verification.cases}
        for partition in ("held_out_supported", "readability"):
            entries = []
            for case in stage.cases:
                if case.case_id not in accepted or case.primary_partition != partition:
                    continue
                review_path = Path(reviews[case.case_id].review_path)
                entries.append(
                    DraftPartitionEntry(
                        case_id=case.case_id,
                        primary_partition=case.primary_partition,
                        task_fingerprint=case.task_fingerprint,
                        claim_class=case.claim_class,
                        public_brief=case.public_brief,
                        source_snapshot=case.source_snapshot,
                        source_citation=case.source_citation,
                        source_locator=case.source_locator,
                        equation_locators=case.equation_locators,
                        scorer=case.scorer,
                        allowed_tools=case.allowed_tools,
                        repetition_policy=case.repetition_policy,
                        sealed_artifacts=case.sealed_artifacts,
                        intake_review=FrozenIntakeArtifact(
                            path=_stored_project_path(review_path),
                            sha256=_sha256(review_path),
                        ),
                        direct_registration_blockers=[
                            "authorized gold/scorer materialization after system freeze",
                            "conversion to executable benchmark-case schema",
                            "final partition-manifest hash and release approval",
                        ],
                    )
                )
            preview = PartitionEntryPreview(
                schema_version=INTAKE_SCHEMA_VERSION,
                intake_stage=_stored_project_path(resolved_stage),
                benchmark_id=stage.benchmark_id,
                benchmark_version=stage.benchmark_version,
                primary_partition=partition,
                entries=entries,
            )
            preview_path = output_dir / f"{partition}_preview.yaml"
            _write_yaml(preview_path, preview)
            preview_artifacts[partition] = FrozenIntakeArtifact(
                path=_stored_project_path(preview_path),
                sha256=_sha256(preview_path),
            )

    json_path = output_dir / "freeze_preview.json"
    markdown_path = output_dir / "freeze_preview.md"
    report = FreezePreviewReport(
        schema_version=INTAKE_SCHEMA_VERSION,
        stage_id=stage.stage_id,
        status=(
            "blind_split_ready" if verification.freeze_preview_ready else "blocked"
        ),
        blind_split_freeze_ready=verification.freeze_preview_ready,
        accepted_case_ids=accepted_ids,
        rejected_case_ids=rejected_ids,
        blockers=blockers,
        direct_registration_blockers=[
            "system, scorer, tool, repetition, and split freeze approval",
            "custodian-only gold/scorer materialization and unseal audit",
            "executable-case validation and final manifest SHA-256",
        ],
        partition_previews=preview_artifacts,
        report_json=_stored_project_path(json_path),
        report_markdown=_stored_project_path(markdown_path),
    )
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_freeze_report(report), encoding="utf-8")
    return report
