from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .benchmark_manifest import (
    DEFAULT_BENCHMARK_MANIFEST,
    BenchmarkManifestRegistry,
    RepetitionPolicy,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTHORING_SCHEMA_VERSION = "1.0.0"
DEFAULT_AUTHORING_PACKET = PROJECT_ROOT / "benchmark_authoring_packets" / "v1_template"

AuthoringPartition = Literal["held_out_supported", "readability"]
AuthoringClaimClass = Literal["known_theory_derivation", "accessible_explanation"]
SealedArtifactType = Literal["gold_answer", "readability_rubric"]

LEAKAGE_ATTESTATION = (
    "I selected and authored this case independently of the Project 1 development "
    "cases, generated outputs, gold answers, and evaluator implementation."
)
CUSTODY_ATTESTATION = (
    "I received the private evaluation material, froze it under the recorded hash, "
    "and did not disclose it to the Project 1 development team."
)

FORBIDDEN_PUBLIC_KEYS = {
    "answer",
    "expected",
    "expected_answer",
    "expected_equation",
    "expected_model",
    "gold",
    "gold_answer",
    "reference_answer",
    "reference_solution",
    "required_answer",
    "scoring_rubric",
    "solution",
}


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


def _write_yaml(path: Path, payload: BaseModel | dict[str, object]) -> None:
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def _timestamp_is_valid(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


class HashedPacketArtifact(BaseModel):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ParticipantIdentity(BaseModel):
    participant_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field(min_length=1)
    affiliation: str = Field(min_length=1)
    contact: str = Field(min_length=1)
    independent_of_project_development: bool


class SourceAuthoringRecord(BaseModel):
    source_type: Literal["primary_literature", "external_contribution"]
    citation: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    equation_locators: list[str] = Field(min_length=1)
    snapshot: HashedPacketArtifact

    @model_validator(mode="after")
    def validate_equation_locators(self) -> "SourceAuthoringRecord":
        if any(not locator.strip() for locator in self.equation_locators):
            raise ValueError("Source equation locators cannot be blank")
        return self


class LeakageAttestation(BaseModel):
    independent_source_selection: bool
    inspected_development_cases: bool
    inspected_agent_outputs: bool
    inspected_gold_answers: bool
    inspected_evaluator_implementation: bool
    consulted_project_artifacts: list[str] = Field(default_factory=list)
    attestation: str
    signed_by: str = Field(min_length=1)
    signed_at: str = Field(min_length=1)


class SealedEvaluationArtifact(HashedPacketArtifact):
    artifact_type: SealedArtifactType
    protection: Literal["encrypted_archive", "custodian_access_control"]
    seal_state: Literal["unsealed", "sealed", "opened"]
    mutable: bool
    opened_before_evaluation: bool
    sealed_at: str = Field(min_length=1)


class GoldCustodyRecord(BaseModel):
    custodian_id: str = Field(min_length=1)
    author_handoff_complete: bool
    author_retained_plaintext_copy: bool
    development_team_has_gold_access: bool
    disclosure_events: list[str] = Field(default_factory=list)
    attestation: str
    signed_by: str = Field(min_length=1)
    signed_at: str = Field(min_length=1)


class PublicCaseBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    primary_partition: AuthoringPartition
    task_fingerprint: str = Field(pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=10)
    structured_input: dict[str, object] | None = None
    target_outputs: list[str] = Field(min_length=1)
    audience: str | None = None
    allowed_tools: list[str] = Field(min_length=1)
    repetition_policy: RepetitionPolicy

    @model_validator(mode="after")
    def validate_readability_audience(self) -> "PublicCaseBrief":
        if self.primary_partition == "readability" and not (
            self.audience and self.audience.strip()
        ):
            raise ValueError("Readability public briefs require an audience")
        return self


class AuthoringCaseSubmission(BaseModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    primary_partition: AuthoringPartition
    task_fingerprint: str = Field(pattern=r"^[a-z0-9_]+$")
    claim_class: AuthoringClaimClass
    gold_visibility: Literal["blinded"] = "blinded"
    leakage_status: Literal["held_out_blinded"] = "held_out_blinded"
    scorer: str = Field(min_length=1)
    allowed_tools: list[str] = Field(min_length=1)
    repetition_policy: RepetitionPolicy
    public_brief: HashedPacketArtifact
    source_provenance: SourceAuthoringRecord
    case_author: ParticipantIdentity
    gold_custodian: ParticipantIdentity
    leakage_attestation: LeakageAttestation
    sealed_artifacts: list[SealedEvaluationArtifact] = Field(min_length=1)
    custody: GoldCustodyRecord

    @model_validator(mode="after")
    def validate_partition_contract(self) -> "AuthoringCaseSubmission":
        expected_claim = {
            "held_out_supported": "known_theory_derivation",
            "readability": "accessible_explanation",
        }[self.primary_partition]
        if self.claim_class != expected_claim:
            raise ValueError(
                f"{self.primary_partition} requires claim_class={expected_claim}"
            )
        artifact_types = [artifact.artifact_type for artifact in self.sealed_artifacts]
        if len(artifact_types) != len(set(artifact_types)):
            raise ValueError("Sealed artifact types must be unique per case")
        required_types = {"gold_answer"}
        if self.primary_partition == "readability":
            required_types.add("readability_rubric")
        missing_types = sorted(required_types - set(artifact_types))
        if missing_types:
            raise ValueError(
                "Missing sealed artifact types: " + ", ".join(missing_types)
            )
        if self.case_author.participant_id == self.gold_custodian.participant_id:
            raise ValueError("Case author and gold custodian must be different participants")
        if self.custody.custodian_id != self.gold_custodian.participant_id:
            raise ValueError("Custody record does not identify the declared gold custodian")
        if len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise ValueError("Allowed tools must be unique")
        return self


class AuthoringPacketManifest(BaseModel):
    schema_version: str
    packet_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    packet_status: Literal["template", "submitted"]
    created_at: str
    benchmark_manifest: str = Field(min_length=1)
    cases: list[AuthoringCaseSubmission] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case_identity(self) -> "AuthoringPacketManifest":
        case_ids = [case.case_id for case in self.cases]
        fingerprints = [case.task_fingerprint for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Authoring packet case IDs must be unique")
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("Authoring packet task fingerprints must be unique")
        return self


class GoldAnswerTemplate(BaseModel):
    schema_version: str
    case_id: str
    derivation_scope: str
    assumptions: list[str]
    source_symbol_mapping: dict[str, str]
    required_physics: list[str]
    allowed_equivalent_forms: list[str]
    failure_conditions: list[str]


class ReadabilityCriterionTemplate(BaseModel):
    criterion_id: str
    prompt: str
    critical: bool
    minimum_score: int = Field(ge=1, le=5)


class ReadabilityRubricTemplate(BaseModel):
    schema_version: str
    case_id: str
    audience: str
    scale: str
    criteria: list[ReadabilityCriterionTemplate]


class AuthoringCaseVerification(BaseModel):
    case_id: str
    primary_partition: AuthoringPartition
    passed: bool
    issues: list[str]


class AuthoringPacketVerification(BaseModel):
    packet_id: str
    packet_status: Literal["template", "submitted"]
    ready_for_intake: bool
    case_count: int
    passed_cases: int
    cases: list[AuthoringCaseVerification]
    packet_issues: list[str]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


class AuthoringPacketResult(BaseModel):
    packet_dir: str
    manifest_path: str
    guide_path: str
    template_paths: list[str]


def _placeholder_identity(participant_id: str, role: str) -> ParticipantIdentity:
    return ParticipantIdentity(
        participant_id=participant_id,
        name=f"REPLACE_WITH_{role.upper()}_NAME",
        affiliation="REPLACE_WITH_AFFILIATION",
        contact="REPLACE_WITH_CONTACT",
        independent_of_project_development=True,
    )


def _public_case_template(partition: AuthoringPartition) -> PublicCaseBrief:
    readability = partition == "readability"
    return PublicCaseBrief(
        schema_version=AUTHORING_SCHEMA_VERSION,
        case_id="TEMPLATE_not_for_submission",
        primary_partition=partition,
        task_fingerprint=f"replace_with_unique_{partition}_fingerprint",
        title="REPLACE_WITH_CASE_TITLE",
        prompt="REPLACE_WITH_COMPLETE_PUBLIC_TASK_PROMPT",
        structured_input=None,
        target_outputs=(
            ["accessible_explanation"]
            if readability
            else ["physics_ir", "wolfram_derivation", "validation_report"]
        ),
        audience="REPLACE_WITH_TARGET_AUDIENCE" if readability else None,
        allowed_tools=["python_orchestrator", "wolfram_kernel"],
        repetition_policy=RepetitionPolicy(
            deterministic_runs=1,
            stochastic_runs=3,
            aggregation="mean_and_confidence_interval",
        ),
    )


def _case_registration_template(
    partition: AuthoringPartition,
) -> AuthoringCaseSubmission:
    public = _public_case_template(partition)
    author = _placeholder_identity("replace_case_author_id", "case_author")
    custodian = _placeholder_identity("replace_gold_custodian_id", "gold_custodian")
    artifacts = [
        SealedEvaluationArtifact(
            artifact_type="gold_answer",
            path="returned/sealed_gold/CASE_ID_gold.enc",
            sha256="0" * 64,
            protection="encrypted_archive",
            seal_state="sealed",
            mutable=False,
            opened_before_evaluation=False,
            sealed_at="2000-01-01T00:00:00Z",
        )
    ]
    if partition == "readability":
        artifacts.append(
            SealedEvaluationArtifact(
                artifact_type="readability_rubric",
                path="returned/sealed_gold/CASE_ID_readability_rubric.enc",
                sha256="0" * 64,
                protection="encrypted_archive",
                seal_state="sealed",
                mutable=False,
                opened_before_evaluation=False,
                sealed_at="2000-01-01T00:00:00Z",
            )
        )
    return AuthoringCaseSubmission(
        case_id=public.case_id,
        primary_partition=partition,
        task_fingerprint=public.task_fingerprint,
        claim_class=(
            "accessible_explanation"
            if partition == "readability"
            else "known_theory_derivation"
        ),
        scorer="structured_rule_scorer_v1",
        allowed_tools=public.allowed_tools,
        repetition_policy=public.repetition_policy,
        public_brief=HashedPacketArtifact(
            path=f"returned/public_cases/{partition}_CASE_ID.yaml",
            sha256="0" * 64,
        ),
        source_provenance=SourceAuthoringRecord(
            source_type="primary_literature",
            citation="REPLACE_WITH_FULL_PRIMARY_CITATION",
            locator="REPLACE_WITH_DOI_OR_STABLE_URL",
            equation_locators=["REPLACE_WITH_EQUATION_OR_PAGE_LOCATOR"],
            snapshot=HashedPacketArtifact(
                path="returned/source_snapshots/CASE_ID_source_snapshot.pdf",
                sha256="0" * 64,
            ),
        ),
        case_author=author,
        gold_custodian=custodian,
        leakage_attestation=LeakageAttestation(
            independent_source_selection=True,
            inspected_development_cases=False,
            inspected_agent_outputs=False,
            inspected_gold_answers=False,
            inspected_evaluator_implementation=False,
            consulted_project_artifacts=[],
            attestation=LEAKAGE_ATTESTATION,
            signed_by=author.name,
            signed_at="2000-01-01T00:00:00Z",
        ),
        sealed_artifacts=artifacts,
        custody=GoldCustodyRecord(
            custodian_id=custodian.participant_id,
            author_handoff_complete=True,
            author_retained_plaintext_copy=False,
            development_team_has_gold_access=False,
            disclosure_events=[],
            attestation=CUSTODY_ATTESTATION,
            signed_by=custodian.name,
            signed_at="2000-01-01T00:00:00Z",
        ),
    )


def _operator_guide() -> str:
    return """# Benchmark v1 External Case Authoring Packet

This packet collects independently sourced `held_out_supported` and `readability` cases. It does
not contain a real benchmark case and must not be registered directly.

## Role separation

1. The case author selects a source not used for Project 1 development, writes only the public
   task brief, records exact source/equation locators, and signs the leakage attestation.
2. The gold custodian is a different person. The custodian receives the private gold material,
   seals it as an encrypted or institutionally access-controlled opaque artifact, records its
   SHA-256, and signs the custody attestation.
3. The Project 1 development team receives the public brief, source snapshot, sealed bytes, and
   metadata. It must not receive the password or plaintext gold before the frozen evaluation.

Typed-name attestations and hashes make the process auditable; they do not cryptographically prove
identity or prove that a person never viewed a file. Disclose any deviation instead of claiming a
blind split.

## Case-author workflow

1. Copy the matching file from `case_author/` into `returned/public_cases/` and replace every
   placeholder. Do not include expected equations, answers, reference solutions, or rubric fields.
2. Put a stable source snapshot in `returned/source_snapshots/`.
3. Copy the matching case-registration template into a working file, fill source citation and exact
   equation/page locators, identity, tool policy, repetition policy, and leakage attestation.
4. Send the private gold template and registration file to the gold custodian without sending any
   Project 1 output or evaluator implementation.

## Gold-custodian workflow

1. Check that the case author and custodian are different participants.
2. Complete the private gold. For readability, also complete the private rubric.
3. Seal each private file into an encrypted or access-controlled opaque artifact under
   `returned/sealed_gold/`. Keep the key outside this packet.
4. Compute SHA-256 for the public brief, source snapshot, and every sealed artifact; enter the
   hashes in the case registration.
5. Confirm `mutable: false`, `seal_state: sealed`, `opened_before_evaluation: false`, an empty
   disclosure log, and all custody attestations.
6. Add the completed case registration under `cases` in `packet_manifest.yaml`, set
   `packet_status: submitted`, and return the whole packet without the decryption key.

## Verification

```bash
python -m spintexture_agent.cli benchmark-authoring verify --packet <returned-packet>
```

The verifier hashes but does not parse sealed artifacts. A passing packet is eligible for an intake
review only; it is not automatically inserted into the held-out manifest and is not a benchmark
pass. Gold may be unsealed only by the declared evaluation custodian after methods and scorer are
frozen.
"""


def generate_authoring_packet(
    out_dir: str | Path = DEFAULT_AUTHORING_PACKET,
    benchmark_manifest: str | Path = DEFAULT_BENCHMARK_MANIFEST,
) -> AuthoringPacketResult:
    packet_dir = _project_path(out_dir)
    if packet_dir.exists():
        raise FileExistsError(
            f"Authoring packet directory already exists: {packet_dir}. "
            "Use a new path so returned submissions are never overwritten."
        )
    (packet_dir / "case_author").mkdir(parents=True)
    (packet_dir / "gold_custodian").mkdir()
    for relative in (
        "returned/public_cases",
        "returned/source_snapshots",
        "returned/sealed_gold",
    ):
        returned_dir = packet_dir / relative
        returned_dir.mkdir(parents=True)
        (returned_dir / ".gitkeep").write_text("", encoding="utf-8")

    benchmark_path = _project_path(benchmark_manifest)
    BenchmarkManifestRegistry(benchmark_path)
    manifest = AuthoringPacketManifest(
        schema_version=AUTHORING_SCHEMA_VERSION,
        packet_id="spintexture_benchmark_v1_external_authoring",
        packet_status="template",
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        benchmark_manifest=_stored_project_path(benchmark_path),
        cases=[],
    )
    manifest_path = packet_dir / "packet_manifest.yaml"
    _write_yaml(manifest_path, manifest)

    templates: list[Path] = []
    for partition in ("held_out_supported", "readability"):
        public_path = packet_dir / "case_author" / f"{partition}_public_case_template.yaml"
        registration_path = (
            packet_dir / "case_author" / f"{partition}_registration_template.yaml"
        )
        _write_yaml(public_path, _public_case_template(partition))
        _write_yaml(registration_path, _case_registration_template(partition))
        templates.extend([public_path, registration_path])

    gold_template = GoldAnswerTemplate(
        schema_version=AUTHORING_SCHEMA_VERSION,
        case_id="TEMPLATE_not_for_submission",
        derivation_scope="REPLACE_WITH_BOUNDED_GOLD_SCOPE",
        assumptions=["REPLACE_WITH_EXPLICIT_ASSUMPTION"],
        source_symbol_mapping={"source_symbol": "agent_symbol"},
        required_physics=["REPLACE_WITH_REQUIRED_PHYSICS_RESULT"],
        allowed_equivalent_forms=["REPLACE_WITH_ALLOWED_EQUIVALENT_FORM"],
        failure_conditions=["REPLACE_WITH_CRITICAL_FAILURE_CONDITION"],
    )
    gold_path = packet_dir / "gold_custodian" / "gold_answer_template.yaml"
    _write_yaml(gold_path, gold_template)
    templates.append(gold_path)

    rubric = ReadabilityRubricTemplate(
        schema_version=AUTHORING_SCHEMA_VERSION,
        case_id="TEMPLATE_not_for_submission",
        audience="REPLACE_WITH_TARGET_AUDIENCE",
        scale="1=incorrect_or_missing; 3=adequate; 5=complete_and_faithful",
        criteria=[
            ReadabilityCriterionTemplate(
                criterion_id="formula_fidelity",
                prompt="The accessible view preserves the formal equations and conventions.",
                critical=True,
                minimum_score=4,
            ),
            ReadabilityCriterionTemplate(
                criterion_id="assumptions_and_validity",
                prompt="Assumptions and validity limits remain explicit.",
                critical=True,
                minimum_score=4,
            ),
            ReadabilityCriterionTemplate(
                criterion_id="warning_and_certainty_preservation",
                prompt="Warnings, review requirements, and certainty are not softened.",
                critical=True,
                minimum_score=4,
            ),
            ReadabilityCriterionTemplate(
                criterion_id="symbol_clarity",
                prompt="Symbols and physical terms are understandable to the target audience.",
                critical=False,
                minimum_score=3,
            ),
            ReadabilityCriterionTemplate(
                criterion_id="task_comprehension",
                prompt="The target reader can identify what was derived, what it means, and when it applies.",
                critical=False,
                minimum_score=3,
            ),
        ],
    )
    rubric_path = packet_dir / "gold_custodian" / "readability_rubric_template.yaml"
    _write_yaml(rubric_path, rubric)
    templates.append(rubric_path)

    guide_path = packet_dir / "OPERATOR_GUIDE.md"
    guide_path.write_text(_operator_guide(), encoding="utf-8")
    return AuthoringPacketResult(
        packet_dir=str(packet_dir),
        manifest_path=str(manifest_path),
        guide_path=str(guide_path),
        template_paths=[str(path) for path in templates],
    )


def _resolve_packet_artifact(packet_dir: Path, locator: str) -> tuple[Path | None, str | None]:
    candidate = Path(locator)
    if candidate.is_absolute():
        return None, f"packet artifact path must be relative: {locator}"
    resolved = (packet_dir / candidate).resolve()
    try:
        resolved.relative_to(packet_dir.resolve())
    except ValueError:
        return None, f"packet artifact escapes packet directory: {locator}"
    if not resolved.is_file():
        return None, f"packet artifact is missing: {locator}"
    return resolved, None


def _artifact_issue(
    packet_dir: Path,
    artifact: HashedPacketArtifact,
    label: str,
) -> str | None:
    path, issue = _resolve_packet_artifact(packet_dir, artifact.path)
    if issue:
        return issue
    if path is not None and _sha256(path) != artifact.sha256:
        return f"{label} SHA-256 mismatch: {artifact.path}"
    return None


def _find_forbidden_public_keys(value: object, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            location = f"{prefix}.{key_text}" if prefix else key_text
            normalized = key_text.lower()
            if normalized in FORBIDDEN_PUBLIC_KEYS or normalized.startswith("expected_"):
                findings.append(location)
            findings.extend(_find_forbidden_public_keys(nested, location))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            findings.extend(_find_forbidden_public_keys(nested, f"{prefix}[{index}]"))
    return findings


def _verify_case(
    packet_dir: Path,
    case: AuthoringCaseSubmission,
    registry: BenchmarkManifestRegistry,
) -> AuthoringCaseVerification:
    issues: list[str] = []
    existing_ids = {registered.case_id for registered in registry.cases}
    development_fingerprints = {
        registered.task_fingerprint
        for registered in registry.cases
        if registered.leakage_status == "development_exposed"
    }
    if case.case_id in existing_ids:
        issues.append("case ID already exists in the benchmark registry")
    if case.task_fingerprint in development_fingerprints:
        issues.append("task fingerprint overlaps development-exposed data")
    if case.scorer != registry.suite.scorer_registry_version:
        issues.append("case scorer does not match the benchmark scorer registry")

    public_issue = _artifact_issue(packet_dir, case.public_brief, "public brief")
    if public_issue:
        issues.append(public_issue)
    else:
        public_path, _ = _resolve_packet_artifact(packet_dir, case.public_brief.path)
        assert public_path is not None
        public_payload = _load_yaml(public_path)
        forbidden = _find_forbidden_public_keys(public_payload)
        if forbidden:
            issues.append("public brief leaks private evaluation keys: " + ", ".join(forbidden))
        else:
            try:
                public = PublicCaseBrief.model_validate(public_payload)
            except ValueError as exc:
                issues.append(f"public brief schema invalid: {exc}")
            else:
                if (
                    public.case_id != case.case_id
                    or public.primary_partition != case.primary_partition
                    or public.task_fingerprint != case.task_fingerprint
                ):
                    issues.append("public brief identity does not match case registration")
                if public.allowed_tools != case.allowed_tools:
                    issues.append("public brief allowed tools do not match registration")
                if public.repetition_policy != case.repetition_policy:
                    issues.append("public brief repetition policy does not match registration")

    source_issue = _artifact_issue(
        packet_dir,
        case.source_provenance.snapshot,
        "source snapshot",
    )
    if source_issue:
        issues.append(source_issue)

    if not case.case_author.independent_of_project_development:
        issues.append("case author is not independent of Project 1 development")
    if not case.gold_custodian.independent_of_project_development:
        issues.append("gold custodian is not independent of Project 1 development")

    leakage = case.leakage_attestation
    if not leakage.independent_source_selection:
        issues.append("source selection is not attested independent")
    if any(
        (
            leakage.inspected_development_cases,
            leakage.inspected_agent_outputs,
            leakage.inspected_gold_answers,
            leakage.inspected_evaluator_implementation,
        )
    ):
        issues.append("leakage attestation records access to development evidence")
    if leakage.consulted_project_artifacts:
        issues.append("leakage attestation lists consulted Project 1 artifacts")
    if leakage.attestation != LEAKAGE_ATTESTATION:
        issues.append("leakage attestation text was changed")
    if leakage.signed_by.strip() != case.case_author.name.strip():
        issues.append("leakage attestation signer does not match case author")
    if not _timestamp_is_valid(leakage.signed_at):
        issues.append("leakage attestation timestamp must be timezone-aware ISO-8601")

    for artifact in case.sealed_artifacts:
        artifact_issue = _artifact_issue(
            packet_dir,
            artifact,
            f"sealed {artifact.artifact_type}",
        )
        if artifact_issue:
            issues.append(artifact_issue)
        if artifact.seal_state != "sealed":
            issues.append(f"sealed {artifact.artifact_type} is not in sealed state")
        if artifact.mutable:
            issues.append(f"sealed {artifact.artifact_type} is marked mutable")
        if artifact.opened_before_evaluation:
            issues.append(f"sealed {artifact.artifact_type} was opened before evaluation")
        if not _timestamp_is_valid(artifact.sealed_at):
            issues.append(
                f"sealed {artifact.artifact_type} timestamp must be timezone-aware ISO-8601"
            )

    custody = case.custody
    if not custody.author_handoff_complete:
        issues.append("gold custody handoff is incomplete")
    if custody.author_retained_plaintext_copy:
        issues.append("case author retained a plaintext gold copy")
    if custody.development_team_has_gold_access:
        issues.append("Project 1 development team has gold access")
    if custody.disclosure_events:
        issues.append("gold custody record contains disclosure events")
    if custody.attestation != CUSTODY_ATTESTATION:
        issues.append("gold custody attestation text was changed")
    if custody.signed_by.strip() != case.gold_custodian.name.strip():
        issues.append("gold custody signer does not match custodian")
    if not _timestamp_is_valid(custody.signed_at):
        issues.append("gold custody timestamp must be timezone-aware ISO-8601")

    return AuthoringCaseVerification(
        case_id=case.case_id,
        primary_partition=case.primary_partition,
        passed=not issues,
        issues=issues,
    )


def verify_authoring_packet(
    packet_dir: str | Path,
    benchmark_manifest: str | Path | None = None,
) -> AuthoringPacketVerification:
    resolved_packet = _project_path(packet_dir)
    manifest_path = resolved_packet / "packet_manifest.yaml"
    manifest = AuthoringPacketManifest.model_validate(_load_yaml(manifest_path))
    if manifest.schema_version != AUTHORING_SCHEMA_VERSION:
        raise ValueError("Unsupported benchmark authoring schema version")
    registry = BenchmarkManifestRegistry(benchmark_manifest or manifest.benchmark_manifest)
    cases = [_verify_case(resolved_packet, case, registry) for case in manifest.cases]
    packet_issues: list[str] = []
    if manifest.packet_status != "submitted":
        packet_issues.append("packet status is template, not submitted")
    if not manifest.cases:
        packet_issues.append("packet contains no submitted cases")
    if not _timestamp_is_valid(manifest.created_at):
        packet_issues.append("packet creation timestamp must be timezone-aware ISO-8601")
    passed_cases = sum(case.passed for case in cases)
    return AuthoringPacketVerification(
        packet_id=manifest.packet_id,
        packet_status=manifest.packet_status,
        ready_for_intake=not packet_issues and passed_cases == len(cases),
        case_count=len(cases),
        passed_cases=passed_cases,
        cases=cases,
        packet_issues=packet_issues,
    )


def render_authoring_verification(result: AuthoringPacketVerification) -> str:
    lines = [
        "# Benchmark authoring packet verification",
        "",
        f"- Packet: `{result.packet_id}`",
        f"- Status: `{result.packet_status}`",
        f"- Ready for intake: `{'yes' if result.ready_for_intake else 'no'}`",
        f"- Cases passed: {result.passed_cases}/{result.case_count}",
        "",
    ]
    if result.packet_issues:
        lines.extend(["Packet issues:", "", *[f"- {item}" for item in result.packet_issues], ""])
    lines.extend(
        [
            "| Case | Partition | Result | Issues |",
            "| --- | --- | --- | --- |",
        ]
    )
    for case in result.cases:
        issues = "; ".join(case.issues) or "None"
        lines.append(
            f"| `{case.case_id}` | `{case.primary_partition}` | "
            f"`{'pass' if case.passed else 'fail'}` | {issues} |"
        )
    return "\n".join(lines).rstrip() + "\n"
