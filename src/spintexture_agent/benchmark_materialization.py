from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .benchmark_authoring import PublicCaseBrief, ReadabilityRubricTemplate
from .benchmark_intake import (
    FreezePreviewReport,
    IntakeStageVerification,
    IntakeStagingManifest,
    PartitionEntryPreview,
    StagedIntakeCase,
    verify_intake_stage,
)
from .benchmark_manifest import (
    BENCHMARK_MANIFEST_SCHEMA_VERSION,
    DEFAULT_BENCHMARK_MANIFEST,
    PRIMARY_PARTITIONS,
    BenchmarkManifestCase,
    BenchmarkManifestRegistry,
    BenchmarkPartitionManifest,
    RepetitionPolicy,
    SourceProvenance,
)
from .schema import TheoryTask


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATERIALIZATION_SCHEMA_VERSION = "1.0.0"
DEFAULT_SCORER_REGISTRY = PROJECT_ROOT / "knowledge_base" / "benchmark_scorers.yaml"

SYSTEM_FREEZE_ATTESTATION = (
    "I froze the declared release candidate, scorer, split, tools, and repetition "
    "policies before private evaluation material was opened."
)
CUSTODIAN_MATERIALIZATION_ATTESTATION = (
    "I materialized the declared sealed artifacts only after the bound system freeze, "
    "inside the isolated evaluation workspace, without developer access or post-unseal tuning."
)

EquivalenceKind = Literal[
    "exact",
    "contains_all",
    "symbolic_regression_flag",
    "numeric_tolerance",
]
EvaluationPartition = Literal["held_out_supported", "readability"]


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


def _write_yaml(path: Path, payload: BaseModel | dict[str, object]) -> None:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return parsed


def _safe_path(root: Path, locator: str, *, directory: bool = False) -> Path:
    path = Path(locator)
    if path.is_absolute():
        raise ValueError(f"Package path must be relative: {locator}")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Package path escapes its root: {locator}") from exc
    exists = resolved.is_dir() if directory else resolved.is_file()
    if not exists:
        kind = "directory" if directory else "file"
        raise ValueError(f"Package {kind} is missing: {locator}")
    return resolved


class FrozenMaterializationArtifact(BaseModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _artifact(root: Path, path: Path) -> FrozenMaterializationArtifact:
    return FrozenMaterializationArtifact(
        path=str(path.resolve().relative_to(root.resolve())),
        sha256=_sha256(path),
    )


def _resolve_artifact(root: Path, artifact: FrozenMaterializationArtifact) -> Path:
    path = _safe_path(root, artifact.path)
    if _sha256(path) != artifact.sha256:
        raise ValueError(f"Artifact SHA-256 mismatch: {artifact.path}")
    return path


class ScorerDefinition(BaseModel):
    scorer_id: str = Field(min_length=1)
    implementation_artifacts: list[str] = Field(min_length=1)
    supported_case_schema_version: str
    supported_gold_schema_version: str
    supported_equivalence_kinds: list[EquivalenceKind] = Field(min_length=1)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capabilities(self) -> "ScorerDefinition":
        if len(self.implementation_artifacts) != len(set(self.implementation_artifacts)):
            raise ValueError("Scorer implementation artifacts must be unique")
        if len(self.supported_equivalence_kinds) != len(
            set(self.supported_equivalence_kinds)
        ):
            raise ValueError("Scorer equivalence kinds must be unique")
        return self


class ScorerRegistryFile(BaseModel):
    schema_version: str
    scorers: list[ScorerDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scorers(self) -> "ScorerRegistryFile":
        scorer_ids = [scorer.scorer_id for scorer in self.scorers]
        if len(scorer_ids) != len(set(scorer_ids)):
            raise ValueError("Scorer registry IDs must be unique")
        return self

    def get(self, scorer_id: str) -> ScorerDefinition:
        for scorer in self.scorers:
            if scorer.scorer_id == scorer_id:
                return scorer
        raise ValueError(f"Scorer is not registered: {scorer_id}")


def load_scorer_registry(
    path: str | Path = DEFAULT_SCORER_REGISTRY,
) -> ScorerRegistryFile:
    registry = ScorerRegistryFile.model_validate(_load_yaml(_project_path(path)))
    if registry.schema_version != MATERIALIZATION_SCHEMA_VERSION:
        raise ValueError("Unsupported scorer registry schema version")
    return registry


class ReleaseManagerApproval(BaseModel):
    manager_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1)
    affiliation: str = Field(min_length=1)
    involved_in_case_authorship: bool = False
    is_gold_custodian: bool = False
    has_plaintext_gold_access: bool = False
    signed_at: str
    attestation: str = SYSTEM_FREEZE_ATTESTATION


class FrozenCasePolicy(BaseModel):
    case_id: str
    primary_partition: EvaluationPartition
    task_fingerprint: str
    scorer: str
    allowed_tools: list[str] = Field(min_length=1)
    repetition_policy: RepetitionPolicy
    sealed_artifact_sha256s: list[str] = Field(min_length=1)


class SystemFreezeRecord(BaseModel):
    schema_version: str
    freeze_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    status: Literal["frozen"] = "frozen"
    frozen_at: str
    benchmark_id: str
    benchmark_version: str
    scorer_registry_version: str
    intake_stage_id: str
    intake_stage_snapshot: str
    freeze_preview_snapshot: str
    intake_manifest: FrozenMaterializationArtifact
    intake_verification: FrozenMaterializationArtifact
    freeze_preview_report: FrozenMaterializationArtifact
    partition_previews: dict[str, FrozenMaterializationArtifact]
    system_release_artifact: FrozenMaterializationArtifact
    scorer_registry: FrozenMaterializationArtifact
    scorer_implementation_artifacts: list[FrozenMaterializationArtifact]
    benchmark_manifest: FrozenMaterializationArtifact
    benchmark_partitions: dict[str, FrozenMaterializationArtifact]
    case_policies: list[FrozenCasePolicy]
    post_freeze_system_changes_allowed: Literal[False] = False
    post_freeze_scorer_changes_allowed: Literal[False] = False
    post_freeze_split_changes_allowed: Literal[False] = False
    post_freeze_policy_changes_allowed: Literal[False] = False
    approval: ReleaseManagerApproval

    @model_validator(mode="after")
    def validate_freeze_contract(self) -> "SystemFreezeRecord":
        case_ids = [policy.case_id for policy in self.case_policies]
        fingerprints = [policy.task_fingerprint for policy in self.case_policies]
        if not case_ids or len(case_ids) != len(set(case_ids)):
            raise ValueError("Frozen case IDs must be nonempty and unique")
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("Frozen task fingerprints must be unique")
        if set(self.partition_previews) != {"held_out_supported", "readability"}:
            raise ValueError("Freeze record must bind both evaluation partition previews")
        if set(self.benchmark_partitions) != set(PRIMARY_PARTITIONS):
            raise ValueError("Freeze record must bind all five benchmark partitions")
        return self


class SystemFreezeVerification(BaseModel):
    freeze_id: str
    ready_for_custodian_handoff: bool
    accepted_case_ids: list[str]
    issues: list[str]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


class SystemFreezePackageResult(BaseModel):
    freeze_dir: str
    freeze_record: str
    verification_report: str


def _load_preview(
    preview_dir: Path,
    stage: IntakeStagingManifest,
    stage_verification: IntakeStageVerification,
) -> tuple[FreezePreviewReport, dict[str, PartitionEntryPreview], list[str]]:
    issues: list[str] = []
    report_path = preview_dir / "freeze_preview.json"
    report = FreezePreviewReport.model_validate(
        json.loads(report_path.read_text(encoding="utf-8"))
    )
    accepted_ids = sorted(
        case.case_id
        for case in stage_verification.cases
        if case.decision == "accepted"
    )
    if report.stage_id != stage.stage_id:
        issues.append("freeze preview stage ID does not match intake stage")
    if not report.blind_split_freeze_ready or report.status != "blind_split_ready":
        issues.append("freeze preview is not blind-split ready")
    if sorted(report.accepted_case_ids) != accepted_ids:
        issues.append("freeze preview accepted cases drifted from intake decisions")
    if report.direct_manifest_registration_ready or report.real_manifests_modified:
        issues.append("freeze preview illegally claims direct registration or manifest edits")

    previews: dict[str, PartitionEntryPreview] = {}
    preview_ids: set[str] = set()
    for partition in ("held_out_supported", "readability"):
        preview_path = preview_dir / f"{partition}_preview.yaml"
        preview = PartitionEntryPreview.model_validate(_load_yaml(preview_path))
        previews[partition] = preview
        recorded = report.partition_previews.get(partition)
        if recorded is None or _sha256(preview_path) != recorded.sha256:
            issues.append(f"freeze preview hash mismatch for {partition}")
        if preview.benchmark_id != stage.benchmark_id:
            issues.append(f"freeze preview benchmark ID mismatch for {partition}")
        if preview.benchmark_version != stage.benchmark_version:
            issues.append(f"freeze preview benchmark version mismatch for {partition}")
        for entry in preview.entries:
            preview_ids.add(entry.case_id)
            matching = next((case for case in stage.cases if case.case_id == entry.case_id), None)
            if matching is None or matching.primary_partition != partition:
                issues.append(f"freeze preview contains an unknown or mispartitioned case: {entry.case_id}")
            elif (
                entry.task_fingerprint != matching.task_fingerprint
                or entry.scorer != matching.scorer
                or entry.allowed_tools != matching.allowed_tools
                or entry.repetition_policy != matching.repetition_policy
            ):
                issues.append(f"freeze preview policy drift for {entry.case_id}")
    if preview_ids != set(accepted_ids):
        issues.append("partition previews do not contain exactly the accepted intake cases")
    return report, previews, issues


def create_system_freeze_package(
    intake_stage: str | Path,
    freeze_preview: str | Path,
    system_artifact: str | Path,
    out_dir: str | Path,
    approval: ReleaseManagerApproval,
    *,
    scorer_registry_path: str | Path = DEFAULT_SCORER_REGISTRY,
) -> SystemFreezePackageResult:
    stage_dir = _project_path(intake_stage)
    preview_dir = _project_path(freeze_preview)
    release_path = _project_path(system_artifact)
    output_dir = _project_path(out_dir)
    if output_dir.exists():
        raise FileExistsError(
            f"System-freeze package already exists: {output_dir}. Use a new path."
        )
    if not release_path.is_file():
        raise ValueError(f"System release artifact is missing: {release_path}")
    _parse_timestamp(approval.signed_at)
    if approval.attestation != SYSTEM_FREEZE_ATTESTATION:
        raise ValueError("System-freeze attestation text was changed")
    if (
        approval.involved_in_case_authorship
        or approval.is_gold_custodian
        or approval.has_plaintext_gold_access
    ):
        raise ValueError("Release manager is not eligible to approve the pre-unseal freeze")

    stage_verification = verify_intake_stage(stage_dir)
    if not stage_verification.freeze_preview_ready:
        raise ValueError("Intake stage is not ready for a system freeze")
    stage = IntakeStagingManifest.model_validate(_load_yaml(stage_dir / "intake_manifest.yaml"))
    _, previews, preview_issues = _load_preview(preview_dir, stage, stage_verification)
    if preview_issues:
        raise ValueError("Freeze preview failed verification: " + "; ".join(preview_issues))
    accepted = {
        case.case_id for case in stage_verification.cases if case.decision == "accepted"
    }
    accepted_cases = [case for case in stage.cases if case.case_id in accepted]
    disallowed_manager_ids = {
        identity
        for case in accepted_cases
        for identity in (case.case_author_id, case.gold_custodian_id)
    }
    if approval.manager_id in disallowed_manager_ids:
        raise ValueError("Release manager cannot be a case author or gold custodian")

    scorer_registry_source = _project_path(scorer_registry_path)
    scorer_registry = load_scorer_registry(scorer_registry_source)
    scorer = scorer_registry.get(stage.scorer_registry_version)
    implementation_sources = [_project_path(path) for path in scorer.implementation_artifacts]
    if any(not path.is_file() for path in implementation_sources):
        raise ValueError("One or more scorer implementation artifacts are missing")

    output_dir.mkdir(parents=True)
    stage_snapshot = output_dir / "snapshots" / "intake_stage"
    preview_snapshot = output_dir / "snapshots" / "freeze_preview"
    shutil.copytree(stage_dir, stage_snapshot)
    shutil.copytree(preview_dir, preview_snapshot)

    system_copy = output_dir / "system" / release_path.name
    system_copy.parent.mkdir(parents=True)
    shutil.copy2(release_path, system_copy)
    scorer_registry_copy = output_dir / "scorer" / "benchmark_scorers.yaml"
    scorer_registry_copy.parent.mkdir(parents=True)
    shutil.copy2(scorer_registry_source, scorer_registry_copy)
    scorer_copies = []
    for source in implementation_sources:
        destination = output_dir / "scorer" / "implementation" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        scorer_copies.append(destination)

    benchmark_dir = output_dir / "contracts" / "benchmark_manifests"
    benchmark_dir.mkdir(parents=True)
    benchmark_copy = benchmark_dir / "manifest.yaml"
    shutil.copy2(DEFAULT_BENCHMARK_MANIFEST, benchmark_copy)
    registry = BenchmarkManifestRegistry(DEFAULT_BENCHMARK_MANIFEST)
    partition_copies: dict[str, Path] = {}
    for reference in registry.suite.partitions:
        source = _project_path(reference.path)
        destination = benchmark_dir / f"{reference.primary_partition}.yaml"
        shutil.copy2(source, destination)
        partition_copies[reference.primary_partition] = destination

    intake_verification_path = output_dir / "snapshots" / "intake_verification.json"
    intake_verification_path.write_text(stage_verification.to_json(), encoding="utf-8")
    frozen_at = datetime.now().astimezone().isoformat(timespec="seconds")
    if _parse_timestamp(approval.signed_at) > _parse_timestamp(frozen_at):
        raise ValueError("System-freeze approval cannot be signed after the freeze record")
    record = SystemFreezeRecord(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        freeze_id=f"{stage.stage_id}_system_freeze",
        frozen_at=frozen_at,
        benchmark_id=stage.benchmark_id,
        benchmark_version=stage.benchmark_version,
        scorer_registry_version=stage.scorer_registry_version,
        intake_stage_id=stage.stage_id,
        intake_stage_snapshot=str(stage_snapshot.relative_to(output_dir)),
        freeze_preview_snapshot=str(preview_snapshot.relative_to(output_dir)),
        intake_manifest=_artifact(output_dir, stage_snapshot / "intake_manifest.yaml"),
        intake_verification=_artifact(output_dir, intake_verification_path),
        freeze_preview_report=_artifact(output_dir, preview_snapshot / "freeze_preview.json"),
        partition_previews={
            partition: _artifact(
                output_dir,
                preview_snapshot / f"{partition}_preview.yaml",
            )
            for partition in previews
        },
        system_release_artifact=_artifact(output_dir, system_copy),
        scorer_registry=_artifact(output_dir, scorer_registry_copy),
        scorer_implementation_artifacts=[
            _artifact(output_dir, path) for path in scorer_copies
        ],
        benchmark_manifest=_artifact(output_dir, benchmark_copy),
        benchmark_partitions={
            partition: _artifact(output_dir, path)
            for partition, path in partition_copies.items()
        },
        case_policies=[
            FrozenCasePolicy(
                case_id=case.case_id,
                primary_partition=case.primary_partition,
                task_fingerprint=case.task_fingerprint,
                scorer=case.scorer,
                allowed_tools=case.allowed_tools,
                repetition_policy=case.repetition_policy,
                sealed_artifact_sha256s=sorted(
                    artifact.sha256 for artifact in case.sealed_artifacts
                ),
            )
            for case in accepted_cases
        ],
        approval=approval,
    )
    record_path = output_dir / "system_freeze_record.yaml"
    _write_yaml(record_path, record)
    verification = verify_system_freeze_package(output_dir)
    if not verification.ready_for_custodian_handoff:
        raise ValueError("Created system-freeze package failed verification")
    verification_path = output_dir / "system_freeze_verification.json"
    verification_path.write_text(verification.to_json(), encoding="utf-8")
    return SystemFreezePackageResult(
        freeze_dir=str(output_dir),
        freeze_record=str(record_path),
        verification_report=str(verification_path),
    )


def verify_system_freeze_package(freeze_dir: str | Path) -> SystemFreezeVerification:
    root = _project_path(freeze_dir)
    record_path = root / "system_freeze_record.yaml"
    record = SystemFreezeRecord.model_validate(_load_yaml(record_path))
    issues: list[str] = []
    if record.schema_version != MATERIALIZATION_SCHEMA_VERSION:
        issues.append("unsupported system-freeze schema version")
    try:
        frozen_at = _parse_timestamp(record.frozen_at)
        signed_at = _parse_timestamp(record.approval.signed_at)
        if signed_at > frozen_at:
            issues.append("system-freeze approval was signed after the freeze time")
    except ValueError as exc:
        issues.append(str(exc))
    if record.approval.attestation != SYSTEM_FREEZE_ATTESTATION:
        issues.append("system-freeze attestation text was changed")
    if (
        record.approval.involved_in_case_authorship
        or record.approval.is_gold_custodian
        or record.approval.has_plaintext_gold_access
    ):
        issues.append("release manager eligibility declarations failed")

    artifacts = [
        record.intake_manifest,
        record.intake_verification,
        record.freeze_preview_report,
        record.system_release_artifact,
        record.scorer_registry,
        record.benchmark_manifest,
        *record.partition_previews.values(),
        *record.benchmark_partitions.values(),
        *record.scorer_implementation_artifacts,
    ]
    for artifact in artifacts:
        try:
            _resolve_artifact(root, artifact)
        except ValueError as exc:
            issues.append(str(exc))

    try:
        stage_snapshot = _safe_path(root, record.intake_stage_snapshot, directory=True)
        _safe_path(root, record.freeze_preview_snapshot, directory=True)
        stage = IntakeStagingManifest.model_validate(
            _load_yaml(stage_snapshot / "intake_manifest.yaml")
        )
        intake_verification_path = _resolve_artifact(root, record.intake_verification)
        intake_verification = IntakeStageVerification.model_validate(
            json.loads(intake_verification_path.read_text(encoding="utf-8"))
        )
        preview_path = _resolve_artifact(root, record.freeze_preview_report)
        preview = FreezePreviewReport.model_validate(
            json.loads(preview_path.read_text(encoding="utf-8"))
        )
    except (ValueError, json.JSONDecodeError) as exc:
        issues.append(f"frozen contract schema invalid: {exc}")
        stage = None
        intake_verification = None
        preview = None

    accepted_ids = sorted(policy.case_id for policy in record.case_policies)
    stage_cases: dict[str, StagedIntakeCase] = {}
    if stage is not None:
        if stage.stage_id != record.intake_stage_id:
            issues.append("frozen intake stage ID mismatch")
        if stage.benchmark_id != record.benchmark_id:
            issues.append("frozen benchmark ID mismatch")
        if stage.benchmark_version != record.benchmark_version:
            issues.append("frozen benchmark version mismatch")
        if stage.scorer_registry_version != record.scorer_registry_version:
            issues.append("frozen scorer version mismatch")
        if stage.benchmark_manifest_sha256 != record.benchmark_manifest.sha256:
            issues.append("frozen benchmark manifest digest mismatch")
        if {
            partition: artifact.sha256
            for partition, artifact in record.benchmark_partitions.items()
        } != stage.benchmark_partition_sha256:
            issues.append("frozen partition digests do not match intake split")
        stage_cases = {case.case_id: case for case in stage.cases}
        for policy in record.case_policies:
            case = stage_cases.get(policy.case_id)
            if case is None:
                issues.append(f"frozen policy case is absent from intake stage: {policy.case_id}")
            elif (
                policy.primary_partition != case.primary_partition
                or policy.task_fingerprint != case.task_fingerprint
                or policy.scorer != case.scorer
                or policy.allowed_tools != case.allowed_tools
                or policy.repetition_policy != case.repetition_policy
                or policy.sealed_artifact_sha256s
                != sorted(artifact.sha256 for artifact in case.sealed_artifacts)
            ):
                issues.append(f"frozen case policy drift for {policy.case_id}")
        disallowed_manager_ids = {
            identity
            for case in stage.cases
            if case.case_id in accepted_ids
            for identity in (case.case_author_id, case.gold_custodian_id)
        }
        if record.approval.manager_id in disallowed_manager_ids:
            issues.append("release manager is a case author or gold custodian")

    if intake_verification is not None:
        if not intake_verification.freeze_preview_ready:
            issues.append("frozen intake verification was not preview-ready")
        frozen_accepted = sorted(
            case.case_id
            for case in intake_verification.cases
            if case.decision == "accepted"
        )
        if frozen_accepted != accepted_ids:
            issues.append("frozen accepted cases differ from frozen policies")
    if preview is not None:
        if not preview.blind_split_freeze_ready:
            issues.append("frozen preview was not blind-split ready")
        if sorted(preview.accepted_case_ids) != accepted_ids:
            issues.append("frozen preview cases differ from frozen policies")
        frozen_preview_ids: set[str] = set()
        policies = {policy.case_id: policy for policy in record.case_policies}
        for partition, artifact in record.partition_previews.items():
            try:
                partition_path = _resolve_artifact(root, artifact)
                partition_preview = PartitionEntryPreview.model_validate(
                    _load_yaml(partition_path)
                )
            except ValueError as exc:
                issues.append(f"frozen partition preview invalid for {partition}: {exc}")
                continue
            reported = preview.partition_previews.get(partition)
            if reported is None or reported.sha256 != artifact.sha256:
                issues.append(f"freeze report/record preview hash mismatch for {partition}")
            if partition_preview.primary_partition != partition:
                issues.append(f"frozen partition preview identity mismatch for {partition}")
            if (
                partition_preview.benchmark_id != record.benchmark_id
                or partition_preview.benchmark_version != record.benchmark_version
            ):
                issues.append(f"frozen partition preview benchmark drift for {partition}")
            for entry in partition_preview.entries:
                frozen_preview_ids.add(entry.case_id)
                policy = policies.get(entry.case_id)
                stage_case = stage_cases.get(entry.case_id)
                if policy is None or stage_case is None:
                    issues.append(f"frozen partition preview has unknown case: {entry.case_id}")
                elif (
                    policy.primary_partition != partition
                    or entry.task_fingerprint != policy.task_fingerprint
                    or entry.scorer != policy.scorer
                    or entry.allowed_tools != policy.allowed_tools
                    or entry.repetition_policy != policy.repetition_policy
                ):
                    issues.append(f"frozen partition preview policy drift for {entry.case_id}")
        if frozen_preview_ids != set(accepted_ids):
            issues.append("frozen partition previews differ from accepted case policies")

    try:
        scorer_registry_path = _resolve_artifact(root, record.scorer_registry)
        scorer_registry = ScorerRegistryFile.model_validate(_load_yaml(scorer_registry_path))
        scorer = scorer_registry.get(record.scorer_registry_version)
        if len(scorer.implementation_artifacts) != len(
            record.scorer_implementation_artifacts
        ):
            issues.append("frozen scorer implementation artifact count mismatch")
        expected_names = sorted(Path(path).name for path in scorer.implementation_artifacts)
        frozen_names = sorted(
            Path(artifact.path).name
            for artifact in record.scorer_implementation_artifacts
        )
        if expected_names != frozen_names:
            issues.append("frozen scorer implementation artifact identity mismatch")
    except ValueError as exc:
        issues.append(f"frozen scorer registry invalid: {exc}")

    return SystemFreezeVerification(
        freeze_id=record.freeze_id,
        ready_for_custodian_handoff=not issues,
        accepted_case_ids=accepted_ids,
        issues=issues,
    )


class ExpectedScoringContract(BaseModel):
    material_class: str
    primary_order_parameter: str
    dynamics_type: str
    equation_type: str
    support_level: str
    topology_field: str | None = None
    limit_checks: list[str] = Field(default_factory=list)
    energy_terms: list[str] = Field(default_factory=list)
    gyrotropic_term: str | None = None
    requires_human_review: bool | None = None
    validation_ids: list[str] = Field(default_factory=list)


class ExecutableBenchmarkCasePayload(BaseModel):
    schema_version: str
    case_id: str
    description: str = Field(min_length=1)
    task: TheoryTask
    expected: ExpectedScoringContract
    required_wolfram_symbols: list[str] = Field(default_factory=list)
    forbidden_wolfram_symbols: list[str] = Field(default_factory=list)


class CanonicalGoldResult(BaseModel):
    equation_type: str
    support_level: str
    equation: str = Field(min_length=1)
    dynamics_class: str = Field(min_length=1)


class EquivalentFormRule(BaseModel):
    target: str = Field(min_length=1)
    comparison: EquivalenceKind
    accepted_forms: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class MaterializedGoldAnswer(BaseModel):
    schema_version: str
    case_id: str
    derivation_scope: str = Field(min_length=1)
    canonical_result: CanonicalGoldResult
    required_assumptions: list[str] = Field(min_length=1)
    full_derivation_assumptions: list[str] = Field(default_factory=list)
    validity_limits: list[str] = Field(default_factory=list)
    source_symbol_mapping: dict[str, str]
    required_physics: list[str] = Field(min_length=1)
    allowed_equivalent_forms: list[EquivalentFormRule] = Field(min_length=1)
    failure_conditions: list[str] = Field(min_length=1)
    limit_checks: list[str] = Field(default_factory=list)


class UnsealEvent(BaseModel):
    event_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    case_id: str
    freeze_id: str
    custodian_id: str
    occurred_at: str
    prior_unseal_event_count: int = Field(ge=0)
    sealed_artifact_sha256s: list[str] = Field(min_length=1)
    authorization: Literal["post_freeze_materialization"]


class PlaintextAccessEvent(BaseModel):
    event_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    actor_id: str
    actor_role: Literal["gold_custodian"]
    accessed_at: str
    purpose: Literal["authorized_materialization"]


class CustodianSignature(BaseModel):
    signed_by: str
    signed_at: str
    attestation: str = CUSTODIAN_MATERIALIZATION_ATTESTATION


class CustodianCaseHandoff(BaseModel):
    case_id: str
    custodian_id: str
    executable_case: FrozenMaterializationArtifact
    gold_answer: FrozenMaterializationArtifact
    readability_rubric: FrozenMaterializationArtifact | None = None
    unseal_events: list[UnsealEvent] = Field(min_length=1)
    access_events: list[PlaintextAccessEvent] = Field(min_length=1)
    development_team_plaintext_access: bool
    post_unseal_system_tuning: bool
    system_changed_after_freeze: bool
    scorer_changed_after_freeze: bool
    custody_complete: bool
    signature: CustodianSignature


class CustodianHandoffManifest(BaseModel):
    schema_version: str
    handoff_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    status: Literal["template", "submitted"]
    created_at: str
    workspace_class: Literal["isolated_evaluation"]
    system_freeze_id: str
    system_freeze_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[CustodianCaseHandoff] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_ids(self) -> "CustodianHandoffManifest":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Custodian handoff case IDs must be unique")
        return self


class HandoffCaseVerification(BaseModel):
    case_id: str
    passed: bool
    issues: list[str]


class CustodianHandoffVerification(BaseModel):
    handoff_id: str
    ready_for_registration_candidate: bool
    cases: list[HandoffCaseVerification]
    issues: list[str]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


class CustodianHandoffTemplateResult(BaseModel):
    handoff_dir: str
    handoff_manifest: str
    guide_path: str


def _contains_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return "REPLACE_WITH" in value
    if isinstance(value, dict):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(item) for item in value)
    return False


def _handoff_guide() -> str:
    return """# Custodian materialization handoff

This template contains no plaintext gold. Use it only in the isolated evaluation workspace after
the bound system-freeze package passes verification. The Project 1 development team must not receive
the completed plaintext handoff.

1. Decrypt or access each frozen sealed artifact exactly once after the recorded freeze time.
2. Replace every `REPLACE_WITH_...` value in the materialized case, gold, and optional rubric.
3. Keep the public task unchanged. Declare only equivalence kinds supported by the frozen scorer.
4. Recompute every artifact SHA-256 in `handoff_manifest.yaml`.
5. Record the actual unseal and plaintext-access events, set `custody_complete: true`, sign the fixed
   attestation, and change the manifest status from `template` to `submitted`.
6. Run `benchmark-materialization verify-handoff` inside the isolated evaluation workspace.

Do not send decrypted gold, a completed handoff, or evaluator outputs back to system developers.
"""


def generate_custodian_handoff_template(
    freeze_dir: str | Path,
    out_dir: str | Path,
) -> CustodianHandoffTemplateResult:
    freeze_root = _project_path(freeze_dir)
    output_dir = _project_path(out_dir)
    if output_dir.exists():
        raise FileExistsError(
            f"Custodian handoff template already exists: {output_dir}. Use a new path."
        )
    freeze_verification = verify_system_freeze_package(freeze_root)
    if not freeze_verification.ready_for_custodian_handoff:
        raise ValueError("System-freeze package is not ready for a custodian handoff")
    record_path = freeze_root / "system_freeze_record.yaml"
    record = SystemFreezeRecord.model_validate(_load_yaml(record_path))
    stage_root = _safe_path(freeze_root, record.intake_stage_snapshot, directory=True)
    stage = IntakeStagingManifest.model_validate(_load_yaml(stage_root / "intake_manifest.yaml"))
    stage_cases = {case.case_id: case for case in stage.cases}
    output_dir.mkdir(parents=True)
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    handoff_cases: list[CustodianCaseHandoff] = []
    for policy in record.case_policies:
        stage_case = stage_cases[policy.case_id]
        public = PublicCaseBrief.model_validate(
            _load_yaml(_safe_path(stage_root, stage_case.public_brief.path))
        )
        structured = public.structured_input or {}
        executable = ExecutableBenchmarkCasePayload(
            schema_version=MATERIALIZATION_SCHEMA_VERSION,
            case_id=policy.case_id,
            description="REPLACE_WITH_SCORER_FACING_CASE_DESCRIPTION",
            task=TheoryTask(
                task_name=policy.case_id,
                material=str(structured.get("material", "REPLACE_WITH_MATERIAL")),
                texture=str(structured.get("texture", "REPLACE_WITH_TEXTURE")),
                drive=(
                    str(structured["drive"])
                    if structured.get("drive") is not None
                    else None
                ),
                geometry=(
                    str(structured["geometry"])
                    if structured.get("geometry") is not None
                    else None
                ),
                goals=["REPLACE_WITH_SCORER_TARGET_GOAL"],
                assumptions=["REPLACE_WITH_REQUIRED_ASSUMPTION"],
            ),
            expected=ExpectedScoringContract(
                material_class="REPLACE_WITH_MATERIAL_CLASS",
                primary_order_parameter="REPLACE_WITH_PRIMARY_ORDER_PARAMETER",
                dynamics_type="REPLACE_WITH_DYNAMICS_TYPE",
                equation_type="REPLACE_WITH_EQUATION_TYPE",
                support_level="REPLACE_WITH_SUPPORT_LEVEL",
            ),
            required_wolfram_symbols=["REPLACE_WITH_REQUIRED_WOLFRAM_SYMBOL"],
        )
        gold = MaterializedGoldAnswer(
            schema_version=MATERIALIZATION_SCHEMA_VERSION,
            case_id=policy.case_id,
            derivation_scope="REPLACE_WITH_DERIVATION_SCOPE",
            canonical_result=CanonicalGoldResult(
                equation_type="REPLACE_WITH_EQUATION_TYPE",
                support_level="REPLACE_WITH_SUPPORT_LEVEL",
                equation="REPLACE_WITH_CANONICAL_EQUATION",
                dynamics_class="REPLACE_WITH_DYNAMICS_CLASS",
            ),
            required_assumptions=["REPLACE_WITH_REQUIRED_ASSUMPTION"],
            source_symbol_mapping={"REPLACE_WITH_SOURCE_SYMBOL": "REPLACE_WITH_AGENT_SYMBOL"},
            required_physics=["REPLACE_WITH_REQUIRED_PHYSICS_ITEM"],
            allowed_equivalent_forms=[
                EquivalentFormRule(
                    target="REPLACE_WITH_SCORING_TARGET",
                    comparison="exact",
                    accepted_forms=["REPLACE_WITH_ACCEPTED_EQUIVALENT_FORM"],
                    rationale="REPLACE_WITH_EQUIVALENCE_RATIONALE",
                )
            ],
            failure_conditions=["REPLACE_WITH_FAILURE_CONDITION"],
        )
        executable_path = output_dir / "materialized" / "cases" / f"{policy.case_id}.yaml"
        gold_path = output_dir / "materialized" / "gold" / f"{policy.case_id}.yaml"
        _write_yaml(executable_path, executable)
        _write_yaml(gold_path, gold)
        rubric_artifact = None
        if policy.primary_partition == "readability":
            rubric = ReadabilityRubricTemplate(
                schema_version=MATERIALIZATION_SCHEMA_VERSION,
                case_id=policy.case_id,
                audience=public.audience or "REPLACE_WITH_AUDIENCE",
                scale="1-5",
                criteria=[
                    {
                        "criterion_id": "REPLACE_WITH_CRITERION_ID",
                        "prompt": "REPLACE_WITH_RATING_PROMPT",
                        "critical": True,
                        "minimum_score": 4,
                    }
                ],
            )
            rubric_path = output_dir / "materialized" / "rubrics" / f"{policy.case_id}.yaml"
            _write_yaml(rubric_path, rubric)
            rubric_artifact = _artifact(output_dir, rubric_path)
        event = UnsealEvent(
            event_id=f"{policy.case_id}_REPLACE_WITH_UNSEAL_EVENT_ID",
            case_id=policy.case_id,
            freeze_id=record.freeze_id,
            custodian_id=stage_case.gold_custodian_id,
            occurred_at=created_at,
            prior_unseal_event_count=0,
            sealed_artifact_sha256s=policy.sealed_artifact_sha256s,
            authorization="post_freeze_materialization",
        )
        handoff_cases.append(
            CustodianCaseHandoff(
                case_id=policy.case_id,
                custodian_id=stage_case.gold_custodian_id,
                executable_case=_artifact(output_dir, executable_path),
                gold_answer=_artifact(output_dir, gold_path),
                readability_rubric=rubric_artifact,
                unseal_events=[event],
                access_events=[
                    PlaintextAccessEvent(
                        event_id=f"{policy.case_id}_REPLACE_WITH_ACCESS_EVENT_ID",
                        actor_id=stage_case.gold_custodian_id,
                        actor_role="gold_custodian",
                        accessed_at=created_at,
                        purpose="authorized_materialization",
                    )
                ],
                development_team_plaintext_access=False,
                post_unseal_system_tuning=False,
                system_changed_after_freeze=False,
                scorer_changed_after_freeze=False,
                custody_complete=False,
                signature=CustodianSignature(
                    signed_by=stage_case.gold_custodian_id,
                    signed_at=created_at,
                ),
            )
        )
    manifest = CustodianHandoffManifest(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        handoff_id=f"{record.freeze_id}_handoff_template",
        status="template",
        created_at=created_at,
        workspace_class="isolated_evaluation",
        system_freeze_id=record.freeze_id,
        system_freeze_record_sha256=_sha256(record_path),
        cases=handoff_cases,
    )
    manifest_path = output_dir / "handoff_manifest.yaml"
    _write_yaml(manifest_path, manifest)
    guide_path = output_dir / "CUSTODIAN_GUIDE.md"
    guide_path.write_text(_handoff_guide(), encoding="utf-8")
    return CustodianHandoffTemplateResult(
        handoff_dir=str(output_dir),
        handoff_manifest=str(manifest_path),
        guide_path=str(guide_path),
    )


def _current_benchmark_hash_issues(record: SystemFreezeRecord) -> list[str]:
    issues: list[str] = []
    if _sha256(DEFAULT_BENCHMARK_MANIFEST) != record.benchmark_manifest.sha256:
        issues.append("benchmark manifest changed after system freeze")
    registry = BenchmarkManifestRegistry(DEFAULT_BENCHMARK_MANIFEST)
    current_partitions = {
        reference.primary_partition: _sha256(_project_path(reference.path))
        for reference in registry.suite.partitions
    }
    frozen_partitions = {
        partition: artifact.sha256
        for partition, artifact in record.benchmark_partitions.items()
    }
    if current_partitions != frozen_partitions:
        issues.append("benchmark split changed after system freeze")
    return issues


def verify_custodian_handoff(
    freeze_dir: str | Path,
    handoff_dir: str | Path,
) -> CustodianHandoffVerification:
    freeze_root = _project_path(freeze_dir)
    handoff_root = _project_path(handoff_dir)
    freeze_verification = verify_system_freeze_package(freeze_root)
    record_path = freeze_root / "system_freeze_record.yaml"
    record = SystemFreezeRecord.model_validate(_load_yaml(record_path))
    handoff = CustodianHandoffManifest.model_validate(
        _load_yaml(handoff_root / "handoff_manifest.yaml")
    )
    issues = list(freeze_verification.issues)
    if handoff.schema_version != MATERIALIZATION_SCHEMA_VERSION:
        issues.append("unsupported custodian handoff schema version")
    if handoff.status != "submitted":
        issues.append("custodian handoff remains a template")
    try:
        _parse_timestamp(handoff.created_at)
    except ValueError as exc:
        issues.append(str(exc))
    if handoff.system_freeze_id != record.freeze_id:
        issues.append("handoff references the wrong system-freeze ID")
    if handoff.system_freeze_record_sha256 != _sha256(record_path):
        issues.append("handoff system-freeze record SHA-256 mismatch")
    issues.extend(_current_benchmark_hash_issues(record))

    stage_root = _safe_path(freeze_root, record.intake_stage_snapshot, directory=True)
    stage = IntakeStagingManifest.model_validate(_load_yaml(stage_root / "intake_manifest.yaml"))
    stage_cases = {case.case_id: case for case in stage.cases}
    policies = {policy.case_id: policy for policy in record.case_policies}
    scorer_registry_path = _resolve_artifact(freeze_root, record.scorer_registry)
    scorer_registry = ScorerRegistryFile.model_validate(_load_yaml(scorer_registry_path))
    scorer = scorer_registry.get(record.scorer_registry_version)
    registered = BenchmarkManifestRegistry(DEFAULT_BENCHMARK_MANIFEST)
    registered_ids = {case.case_id for case in registered.cases}
    registered_fingerprints = {case.task_fingerprint for case in registered.cases}

    handoff_ids = {case.case_id for case in handoff.cases}
    if handoff_ids != set(policies):
        issues.append("handoff must contain exactly the frozen accepted cases")

    case_results: list[HandoffCaseVerification] = []
    frozen_at = _parse_timestamp(record.frozen_at)
    for submitted in handoff.cases:
        case_issues: list[str] = []
        policy = policies.get(submitted.case_id)
        stage_case = stage_cases.get(submitted.case_id)
        if policy is None or stage_case is None:
            case_issues.append("case is not an accepted frozen intake case")
            case_results.append(
                HandoffCaseVerification(
                    case_id=submitted.case_id,
                    passed=False,
                    issues=case_issues,
                )
            )
            continue
        if submitted.case_id in registered_ids:
            case_issues.append("case ID already exists in the benchmark")
        if policy.task_fingerprint in registered_fingerprints:
            case_issues.append("task fingerprint overlaps the registered benchmark")
        if submitted.custodian_id != stage_case.gold_custodian_id:
            case_issues.append("handoff custodian does not match frozen custody")
        if submitted.development_team_plaintext_access:
            case_issues.append("development team had plaintext gold access")
        if submitted.post_unseal_system_tuning:
            case_issues.append("post-unseal system tuning was declared")
        if submitted.system_changed_after_freeze:
            case_issues.append("system changed after freeze")
        if submitted.scorer_changed_after_freeze:
            case_issues.append("scorer changed after freeze")
        if not submitted.custody_complete:
            case_issues.append("custody handoff is incomplete")
        if len(submitted.unseal_events) != 1:
            case_issues.append("exactly one unseal/materialization event is required")
        else:
            event = submitted.unseal_events[0]
            if (
                event.case_id != submitted.case_id
                or event.freeze_id != record.freeze_id
                or event.custodian_id != submitted.custodian_id
            ):
                case_issues.append("unseal event identity or freeze binding mismatch")
            if event.prior_unseal_event_count != 0:
                case_issues.append("sealed material was opened before the authorized event")
            if sorted(event.sealed_artifact_sha256s) != sorted(
                policy.sealed_artifact_sha256s
            ):
                case_issues.append("unseal event sealed-artifact hashes do not match the freeze")
            try:
                if _parse_timestamp(event.occurred_at) < frozen_at:
                    case_issues.append("private material was unsealed before system freeze")
            except ValueError as exc:
                case_issues.append(str(exc))

        if not submitted.access_events:
            case_issues.append("plaintext access ledger is empty")
        for event in submitted.access_events:
            if event.actor_id != submitted.custodian_id:
                case_issues.append("plaintext access ledger contains a non-custodian actor")
            try:
                if _parse_timestamp(event.accessed_at) < frozen_at:
                    case_issues.append("plaintext access occurred before system freeze")
            except ValueError as exc:
                case_issues.append(str(exc))
        if submitted.signature.signed_by != submitted.custodian_id:
            case_issues.append("custodian signature identity mismatch")
        if submitted.signature.attestation != CUSTODIAN_MATERIALIZATION_ATTESTATION:
            case_issues.append("custodian materialization attestation text was changed")
        try:
            _parse_timestamp(submitted.signature.signed_at)
        except ValueError as exc:
            case_issues.append(str(exc))

        try:
            executable_path = _resolve_artifact(handoff_root, submitted.executable_case)
            gold_path = _resolve_artifact(handoff_root, submitted.gold_answer)
            executable = ExecutableBenchmarkCasePayload.model_validate(
                _load_yaml(executable_path)
            )
            gold = MaterializedGoldAnswer.model_validate(_load_yaml(gold_path))
        except ValueError as exc:
            case_issues.append(f"materialized case/gold schema invalid: {exc}")
            executable = None
            gold = None

        if executable is not None and gold is not None:
            if _contains_placeholder(executable.model_dump(mode="json")) or _contains_placeholder(
                gold.model_dump(mode="json")
            ):
                case_issues.append("materialized case/gold still contains template placeholders")
            if executable.schema_version != scorer.supported_case_schema_version:
                case_issues.append("materialized case schema is unsupported by the scorer")
            if gold.schema_version != scorer.supported_gold_schema_version:
                case_issues.append("materialized gold schema is unsupported by the scorer")
            if executable.case_id != submitted.case_id or gold.case_id != submitted.case_id:
                case_issues.append("materialized case/gold ID mismatch")
            if executable.task.task_name != submitted.case_id:
                case_issues.append("materialized task name must equal the case ID")
            if (
                executable.expected.equation_type != gold.canonical_result.equation_type
                or executable.expected.support_level != gold.canonical_result.support_level
            ):
                case_issues.append("case expected contract differs from canonical gold")
            unsupported_equivalences = sorted(
                {
                    rule.comparison
                    for rule in gold.allowed_equivalent_forms
                    if rule.comparison not in scorer.supported_equivalence_kinds
                }
            )
            if unsupported_equivalences:
                case_issues.append(
                    "scorer does not support equivalence kinds: "
                    + ", ".join(unsupported_equivalences)
                )
            public_path = _safe_path(stage_root, stage_case.public_brief.path)
            public = PublicCaseBrief.model_validate(_load_yaml(public_path))
            if public.case_id != submitted.case_id:
                case_issues.append("public brief case ID mismatch")
            structured = public.structured_input or {}
            task_values = {
                "material": executable.task.material,
                "texture": executable.task.texture,
                "drive": executable.task.drive,
                "geometry": executable.task.geometry,
            }
            for key, value in task_values.items():
                if key in structured and structured[key] != value:
                    case_issues.append(f"materialized task changed public structured input: {key}")

        if policy.primary_partition == "readability":
            if submitted.readability_rubric is None:
                case_issues.append("readability case lacks a materialized rubric")
            else:
                try:
                    rubric_path = _resolve_artifact(
                        handoff_root,
                        submitted.readability_rubric,
                    )
                    rubric = ReadabilityRubricTemplate.model_validate(_load_yaml(rubric_path))
                    if rubric.case_id != submitted.case_id:
                        case_issues.append("readability rubric case ID mismatch")
                except ValueError as exc:
                    case_issues.append(f"materialized readability rubric invalid: {exc}")
        elif submitted.readability_rubric is not None:
            case_issues.append("held-out derivation case must not include a readability rubric")

        case_results.append(
            HandoffCaseVerification(
                case_id=submitted.case_id,
                passed=not case_issues,
                issues=case_issues,
            )
        )

    ready = (
        freeze_verification.ready_for_custodian_handoff
        and not issues
        and bool(case_results)
        and all(case.passed for case in case_results)
    )
    return CustodianHandoffVerification(
        handoff_id=handoff.handoff_id,
        ready_for_registration_candidate=ready,
        cases=case_results,
        issues=issues,
    )


class CandidateCaseArtifacts(BaseModel):
    case_id: str
    primary_partition: EvaluationPartition
    public_brief: FrozenMaterializationArtifact
    source_snapshot: FrozenMaterializationArtifact
    task_config: FrozenMaterializationArtifact
    executable_case: FrozenMaterializationArtifact
    gold_answer: FrozenMaterializationArtifact
    readability_rubric: FrozenMaterializationArtifact | None = None
    gold_bundle: FrozenMaterializationArtifact | None = None


class RegistrationCandidateIndex(BaseModel):
    schema_version: str
    candidate_id: str
    status: Literal["registration_candidate"] = "registration_candidate"
    automatic_registration_allowed: Literal[False] = False
    real_manifests_modified: Literal[False] = False
    system_freeze_record: FrozenMaterializationArtifact
    custodian_handoff_manifest: FrozenMaterializationArtifact
    case_artifacts: list[CandidateCaseArtifacts]
    partition_candidates: dict[str, FrozenMaterializationArtifact]
    access_event_sha256: dict[str, list[str]]
    final_registration_blockers: list[str]


class RegistrationCandidateResult(BaseModel):
    candidate_dir: str
    candidate_index: str
    report_json: str
    report_markdown: str
    checksums: str
    case_ids: list[str]
    real_manifests_modified: Literal[False] = False


def _copy_from_stage(
    stage_root: Path,
    locator: str,
    destination: Path,
) -> Path:
    source = _safe_path(stage_root, locator)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _manifest_hashes() -> dict[Path, str]:
    return {
        path: _sha256(path)
        for path in sorted((PROJECT_ROOT / "benchmark_manifests" / "v1").glob("*.yaml"))
    }


def generate_registration_candidate(
    freeze_dir: str | Path,
    handoff_dir: str | Path,
    out_dir: str | Path,
) -> RegistrationCandidateResult:
    freeze_root = _project_path(freeze_dir)
    handoff_root = _project_path(handoff_dir)
    output_dir = _project_path(out_dir)
    if output_dir.exists():
        raise FileExistsError(
            f"Registration-candidate directory already exists: {output_dir}. Use a new path."
        )
    verification = verify_custodian_handoff(freeze_root, handoff_root)
    if not verification.ready_for_registration_candidate:
        details = verification.issues + [
            issue for case in verification.cases for issue in case.issues
        ]
        raise ValueError("Custodian handoff is not registration-ready: " + "; ".join(details))

    before = _manifest_hashes()
    record_path = freeze_root / "system_freeze_record.yaml"
    record = SystemFreezeRecord.model_validate(_load_yaml(record_path))
    handoff_path = handoff_root / "handoff_manifest.yaml"
    handoff = CustodianHandoffManifest.model_validate(_load_yaml(handoff_path))
    stage_root = _safe_path(freeze_root, record.intake_stage_snapshot, directory=True)
    stage = IntakeStagingManifest.model_validate(_load_yaml(stage_root / "intake_manifest.yaml"))
    stage_cases: dict[str, StagedIntakeCase] = {case.case_id: case for case in stage.cases}
    policies = {policy.case_id: policy for policy in record.case_policies}

    output_dir.mkdir(parents=True)
    provenance_dir = output_dir / "provenance"
    provenance_dir.mkdir()
    freeze_copy = provenance_dir / "system_freeze_record.yaml"
    handoff_copy = provenance_dir / "handoff_manifest.yaml"
    shutil.copy2(record_path, freeze_copy)
    shutil.copy2(handoff_path, handoff_copy)

    entries: dict[str, list[BenchmarkManifestCase]] = {
        "held_out_supported": [],
        "readability": [],
    }
    case_artifacts: list[CandidateCaseArtifacts] = []
    access_hashes: dict[str, list[str]] = {}
    for submitted in handoff.cases:
        policy = policies[submitted.case_id]
        stage_case = stage_cases[submitted.case_id]
        executable_source = _resolve_artifact(handoff_root, submitted.executable_case)
        gold_source = _resolve_artifact(handoff_root, submitted.gold_answer)
        executable = ExecutableBenchmarkCasePayload.model_validate(_load_yaml(executable_source))
        MaterializedGoldAnswer.model_validate(_load_yaml(gold_source))

        config_path = output_dir / "configs" / f"{submitted.case_id}.yaml"
        _write_yaml(config_path, executable.task)
        case_path = output_dir / "cases" / f"{submitted.case_id}.yaml"
        case_payload: dict[str, object] = {
            "case_id": submitted.case_id,
            "description": executable.description,
            "config": _stored_project_path(config_path),
            "expected": executable.expected.model_dump(
                mode="json",
                exclude_none=True,
            ),
            "required_wolfram_symbols": executable.required_wolfram_symbols,
            "forbidden_wolfram_symbols": executable.forbidden_wolfram_symbols,
        }
        _write_yaml(case_path, case_payload)
        gold_path = output_dir / "gold" / f"{submitted.case_id}.yaml"
        gold_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(gold_source, gold_path)
        public_path = _copy_from_stage(
            stage_root,
            stage_case.public_brief.path,
            output_dir / "public" / f"{submitted.case_id}.yaml",
        )
        source_suffix = Path(stage_case.source_snapshot.path).suffix or ".dat"
        source_path = _copy_from_stage(
            stage_root,
            stage_case.source_snapshot.path,
            output_dir / "sources" / f"{submitted.case_id}{source_suffix}",
        )

        rubric_path: Path | None = None
        bundle_path: Path | None = None
        gold_artifact_path = gold_path
        if submitted.readability_rubric is not None:
            rubric_source = _resolve_artifact(handoff_root, submitted.readability_rubric)
            rubric_path = output_dir / "rubrics" / f"{submitted.case_id}.yaml"
            rubric_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(rubric_source, rubric_path)
            bundle_path = output_dir / "gold_bundles" / f"{submitted.case_id}.yaml"
            _write_yaml(
                bundle_path,
                {
                    "schema_version": MATERIALIZATION_SCHEMA_VERSION,
                    "case_id": submitted.case_id,
                    "gold_answer": _artifact(output_dir, gold_path).model_dump(mode="json"),
                    "readability_rubric": _artifact(output_dir, rubric_path).model_dump(
                        mode="json"
                    ),
                },
            )
            gold_artifact_path = bundle_path

        manifest_case = BenchmarkManifestCase(
            case_id=submitted.case_id,
            task_fingerprint=policy.task_fingerprint,
            case_path=_stored_project_path(case_path),
            source_provenance=SourceProvenance(
                source_type=stage_case.source_type,
                locator=_stored_project_path(source_path),
                citation=stage_case.source_citation,
                sha256=_sha256(source_path),
            ),
            claim_class=stage_case.claim_class,
            gold_visibility="blinded",
            leakage_status="held_out_blinded",
            scorer=policy.scorer,
            allowed_tools=policy.allowed_tools,
            repetition_policy=policy.repetition_policy,
            gold_artifact=_stored_project_path(gold_artifact_path),
            gold_mutable=False,
            gold_sha256=_sha256(gold_artifact_path),
        )
        entries[policy.primary_partition].append(manifest_case)
        case_artifacts.append(
            CandidateCaseArtifacts(
                case_id=submitted.case_id,
                primary_partition=policy.primary_partition,
                public_brief=_artifact(output_dir, public_path),
                source_snapshot=_artifact(output_dir, source_path),
                task_config=_artifact(output_dir, config_path),
                executable_case=_artifact(output_dir, case_path),
                gold_answer=_artifact(output_dir, gold_path),
                readability_rubric=(
                    _artifact(output_dir, rubric_path) if rubric_path else None
                ),
                gold_bundle=_artifact(output_dir, bundle_path) if bundle_path else None,
            )
        )
        access_hashes[submitted.case_id] = [
            _model_sha256(event) for event in submitted.access_events
        ]

    partition_artifacts: dict[str, FrozenMaterializationArtifact] = {}
    for partition in ("held_out_supported", "readability"):
        candidate = BenchmarkPartitionManifest(
            schema_version=BENCHMARK_MANIFEST_SCHEMA_VERSION,
            benchmark_id=record.benchmark_id,
            benchmark_version=record.benchmark_version,
            primary_partition=partition,
            freeze_status="frozen",
            cases=entries[partition],
        )
        path = output_dir / "partition_candidates" / f"{partition}.yaml"
        _write_yaml(path, candidate)
        partition_artifacts[partition] = _artifact(output_dir, path)

    index = RegistrationCandidateIndex(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        candidate_id=f"{handoff.handoff_id}_registration_candidate",
        system_freeze_record=_artifact(output_dir, freeze_copy),
        custodian_handoff_manifest=_artifact(output_dir, handoff_copy),
        case_artifacts=case_artifacts,
        partition_candidates=partition_artifacts,
        access_event_sha256=access_hashes,
        final_registration_blockers=[
            "independent release-manager review of candidate hashes",
            "authorized merge into real partition manifests",
            "final suite freeze and release hash approval",
        ],
    )
    index_path = output_dir / "registration_candidate.yaml"
    _write_yaml(index_path, index)
    report_json = output_dir / "registration_candidate_report.json"
    report_markdown = output_dir / "registration_candidate_report.md"
    result_payload = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "candidate_id": index.candidate_id,
        "status": index.status,
        "automatic_registration_allowed": False,
        "real_manifests_modified": False,
        "case_ids": [case.case_id for case in case_artifacts],
        "partition_candidate_count": len(partition_artifacts),
        "final_registration_blockers": index.final_registration_blockers,
    }
    report_json.write_text(
        json.dumps(result_payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    report_markdown.write_text(
        "\n".join(
            [
                "# Benchmark registration candidate",
                "",
                f"- Candidate: `{index.candidate_id}`",
                "- Status: `registration_candidate`",
                "- Automatic registration allowed: `false`",
                "- Real manifests modified: `false`",
                f"- Cases: {len(case_artifacts)}",
                "",
                "## Final registration blockers",
                "",
                *[f"- {blocker}" for blocker in index.final_registration_blockers],
                "",
            ]
        ),
        encoding="utf-8",
    )
    checksum_path = output_dir / "checksums.sha256"
    checksum_lines = [
        f"{_sha256(path)}  {path.relative_to(output_dir)}"
        for path in sorted(output_dir.rglob("*"))
        if path.is_file() and path != checksum_path
    ]
    checksum_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    after = _manifest_hashes()
    if before != after:
        raise RuntimeError("Registration-candidate generation modified real manifests")
    return RegistrationCandidateResult(
        candidate_dir=str(output_dir),
        candidate_index=str(index_path),
        report_json=str(report_json),
        report_markdown=str(report_markdown),
        checksums=str(checksum_path),
        case_ids=[case.case_id for case in case_artifacts],
    )
