from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .benchmark_authoring import (
    AUTHORING_SCHEMA_VERSION,
    AuthoringPacketManifest,
    generate_authoring_packet,
)
from .benchmark_manifest import (
    DEFAULT_BENCHMARK_MANIFEST,
    PRIMARY_PARTITIONS,
    BenchmarkManifestRegistry,
    BenchmarkPartitionManifest,
    BenchmarkSuiteManifest,
)
from .capabilities import CapabilityRegistry, DEFAULT_REGISTRY_PATH


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COLLECTION_SCHEMA_VERSION = "1.0.0"
DEFAULT_SCORER_REGISTRY = PROJECT_ROOT / "knowledge_base" / "benchmark_scorers.yaml"
DEFAULT_COLLECTION_RELEASE = (
    PROJECT_ROOT / "benchmark_collection_releases" / "v1" / "round_01"
)
COLLECTION_ID = "spintexture_benchmark_v1_external_collection_round_01"
ARCHIVE_ROOT = "spintexture_benchmark_v1_external_collection_round_01"
ARCHIVE_NAME = f"{ARCHIVE_ROOT}.zip"
RELEASE_PAYLOAD_DIR = "release_payload"
CHECKSUM_FILE = "CHECKSUMS.sha256"
RELEASE_INDEX_FILE = "release_index.yaml"
RELEASE_INDEX_DIGEST_FILE = "release_index.sha256"

LedgerState = Literal["invited", "accepted", "declined", "returned", "withdrawn"]
CollectionPartition = Literal["held_out_supported", "readability"]

LEDGER_STATES: tuple[str, ...] = (
    "invited",
    "accepted",
    "declined",
    "returned",
    "withdrawn",
)


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


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


def _write_yaml(path: Path, value: BaseModel | dict[str, object]) -> None:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid timezone-aware ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value}")
    return parsed


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"Release artifact path must be safe and relative: {value}")
    return path


class FrozenCollectionArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_path(self) -> "FrozenCollectionArtifact":
        _safe_relative_path(self.path)
        return self


class CollectionTargetQuota(BaseModel):
    primary_partition: CollectionPartition
    target_cases: int = Field(ge=1)


class SupportedRouteFamily(BaseModel):
    route_id: str = Field(pattern=r"^[a-z0-9_]+$")
    material: str = Field(min_length=1)
    texture: str = Field(min_length=1)
    drive: str | None
    geometry: str = Field(min_length=1)
    support_level: Literal["full_derivation"] = "full_derivation"
    held_out_target_cases: int = Field(ge=1)


class SemanticFingerprintExclusion(BaseModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    primary_partition: str = Field(min_length=1)
    task_fingerprint: str = Field(pattern=r"^[a-z0-9_]+$")
    reason: Literal["already_registered_or_development_exposed"] = (
        "already_registered_or_development_exposed"
    )


class RoleSeparationPolicy(BaseModel):
    project_developers_may_author_independent_cases: Literal[False] = False
    case_author_must_be_independent_of_project_development: Literal[True] = True
    gold_custodian_must_be_independent_of_project_development: Literal[True] = True
    case_author_and_gold_custodian_must_differ: Literal[True] = True
    development_team_may_access_plaintext_gold_before_evaluation: Literal[False] = False
    identities_must_be_blank_at_launch: Literal[True] = True


class SourceEligibilityPolicy(BaseModel):
    allowed_source_types: list[Literal["primary_literature", "external_contribution"]]
    stable_source_snapshot_required: Literal[True] = True
    citation_must_resolve: Literal[True] = True
    exact_equation_or_page_locators_required: Literal[True] = True
    source_must_not_have_been_used_in_project_development: Literal[True] = True
    source_must_support_declared_gold_scope: Literal[True] = True
    scientific_relevance_review_required: Literal[True] = True
    unverifiable_or_retracted_sources_eligible: Literal[False] = False

    @model_validator(mode="after")
    def validate_source_types(self) -> "SourceEligibilityPolicy":
        if set(self.allowed_source_types) != {
            "primary_literature",
            "external_contribution",
        }:
            raise ValueError("Collection source policy must preserve both eligible source types")
        return self


class ReadabilityAudienceQuota(BaseModel):
    audience_id: str = Field(pattern=r"^[a-z0-9_]+$")
    audience_description: str = Field(min_length=1)
    target_cases: int = Field(ge=1)
    minimum_independent_raters_per_case: int = Field(ge=2)


class CollectionDeadlines(BaseModel):
    invitations_open: str
    acceptance_due: str
    sealed_submission_due: str
    custody_confirmation_due: str
    intake_review_close: str

    @model_validator(mode="after")
    def validate_order(self) -> "CollectionDeadlines":
        values = [
            _timestamp(self.invitations_open),
            _timestamp(self.acceptance_due),
            _timestamp(self.sealed_submission_due),
            _timestamp(self.custody_confirmation_due),
            _timestamp(self.intake_review_close),
        ]
        if values != sorted(values) or len(set(values)) != len(values):
            raise ValueError("Collection deadlines must be strictly increasing")
        return self


class ExternalCollectionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[COLLECTION_SCHEMA_VERSION] = COLLECTION_SCHEMA_VERSION
    collection_id: Literal[COLLECTION_ID] = COLLECTION_ID
    plan_status: Literal["frozen"] = "frozen"
    frozen_at: str
    benchmark_id: str
    benchmark_version: str
    scorer_registry_version: str
    authoring_schema_version: Literal[AUTHORING_SCHEMA_VERSION] = AUTHORING_SCHEMA_VERSION
    target_quotas: list[CollectionTargetQuota]
    allowed_supported_route_families: list[SupportedRouteFamily]
    semantic_fingerprint_exclusions: list[SemanticFingerprintExclusion]
    role_separation: RoleSeparationPolicy
    source_eligibility: SourceEligibilityPolicy
    readability_audience_coverage: list[ReadabilityAudienceQuota]
    deadlines: CollectionDeadlines
    source_contracts: list[FrozenCollectionArtifact]
    invited_participant_identities: list[dict[str, object]] = Field(default_factory=list)
    submitted_case_ids: list[str] = Field(default_factory=list)
    real_manifest_registration_allowed: Literal[False] = False

    @model_validator(mode="after")
    def validate_frozen_plan(self) -> "ExternalCollectionPlan":
        _timestamp(self.frozen_at)
        quotas = {quota.primary_partition: quota.target_cases for quota in self.target_quotas}
        if set(quotas) != {"held_out_supported", "readability"}:
            raise ValueError("Collection plan must define held-out and readability quotas")
        route_ids = [route.route_id for route in self.allowed_supported_route_families]
        if len(route_ids) != len(set(route_ids)) or not route_ids:
            raise ValueError("Allowed route families must be non-empty and unique")
        held_out_total = sum(
            route.held_out_target_cases for route in self.allowed_supported_route_families
        )
        if held_out_total != quotas["held_out_supported"]:
            raise ValueError("Held-out route-family quotas do not sum to the partition target")
        audiences = [item.audience_id for item in self.readability_audience_coverage]
        if len(audiences) != len(set(audiences)) or not audiences:
            raise ValueError("Readability audience coverage must be non-empty and unique")
        if sum(item.target_cases for item in self.readability_audience_coverage) != quotas[
            "readability"
        ]:
            raise ValueError("Readability audience quotas do not sum to the partition target")
        fingerprints = [item.task_fingerprint for item in self.semantic_fingerprint_exclusions]
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("Semantic-fingerprint exclusions must be unique")
        if self.invited_participant_identities or self.submitted_case_ids:
            raise ValueError("The launch plan must contain blank identities and no submitted cases")
        return self


class CollectionLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    contributor_id: str = Field(min_length=1)
    custodian_id: str | None = None
    state: LedgerState
    invited_at: str
    accepted_at: str | None = None
    declined_at: str | None = None
    returned_at: str | None = None
    withdrawn_at: str | None = None
    returned_packet: FrozenCollectionArtifact | None = None
    submitted_case_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state_fields(self) -> "CollectionLedgerEntry":
        _timestamp(self.invited_at)
        required_timestamp = {
            "accepted": self.accepted_at,
            "declined": self.declined_at,
            "returned": self.returned_at,
            "withdrawn": self.withdrawn_at,
        }.get(self.state)
        if self.state != "invited" and not required_timestamp:
            raise ValueError(f"Ledger state {self.state} requires its transition timestamp")
        for value in (
            self.accepted_at,
            self.declined_at,
            self.returned_at,
            self.withdrawn_at,
        ):
            if value:
                _timestamp(value)
        if self.state == "returned":
            if not self.accepted_at or not self.custodian_id:
                raise ValueError("Returned entries require acceptance and a named custodian")
            if not self.returned_packet or not self.submitted_case_ids:
                raise ValueError("Returned entries require a packet and submitted case IDs")
        elif self.returned_packet or self.submitted_case_ids:
            raise ValueError("Only returned ledger entries may identify packets or cases")
        return self


class InvitationReturnLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[COLLECTION_SCHEMA_VERSION] = COLLECTION_SCHEMA_VERSION
    collection_id: Literal[COLLECTION_ID] = COLLECTION_ID
    ledger_status: Literal["launch_empty"] = "launch_empty"
    allowed_states: list[LedgerState]
    participant_identities: list[dict[str, object]] = Field(default_factory=list)
    submitted_case_ids: list[str] = Field(default_factory=list)
    entries: list[CollectionLedgerEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_launch_ledger(self) -> "InvitationReturnLedger":
        if tuple(self.allowed_states) != LEDGER_STATES:
            raise ValueError("Invitation ledger must preserve all five workflow states")
        if self.participant_identities or self.submitted_case_ids or self.entries:
            raise ValueError("Round-01 launch ledger must contain no identities, cases, or entries")
        return self


class CollectionReleaseIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[COLLECTION_SCHEMA_VERSION] = COLLECTION_SCHEMA_VERSION
    collection_id: Literal[COLLECTION_ID] = COLLECTION_ID
    release_status: Literal["distribution_ready"] = "distribution_ready"
    generated_at: str
    archive_root: Literal[ARCHIVE_ROOT] = ARCHIVE_ROOT
    archive: FrozenCollectionArtifact
    payload_root: Literal[RELEASE_PAYLOAD_DIR] = RELEASE_PAYLOAD_DIR
    checksum_index: FrozenCollectionArtifact
    payload_artifacts: list[FrozenCollectionArtifact]
    authoring_packet_case_count: Literal[0] = 0
    participant_identity_count: Literal[0] = 0
    submitted_case_count: Literal[0] = 0
    real_manifests_modified: Literal[False] = False
    external_hash_publication_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_index(self) -> "CollectionReleaseIndex":
        _timestamp(self.generated_at)
        paths = [artifact.path for artifact in self.payload_artifacts]
        if len(paths) != len(set(paths)) or not paths:
            raise ValueError("Release payload artifacts must be non-empty and unique")
        return self


class CollectionLaunchResult(BaseModel):
    release_dir: str
    plan_path: str
    ledger_path: str
    release_index_path: str
    release_index_sha256: str
    archive_path: str
    archive_sha256: str
    payload_file_count: int


class CollectionReleaseVerification(BaseModel):
    collection_id: str
    ready_for_distribution: bool
    byte_for_byte_reconstruction: bool
    payload_file_count: int
    invited_identity_count: int
    submitted_case_count: int
    issues: list[str]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


def _artifact(payload_dir: Path, path: Path) -> FrozenCollectionArtifact:
    return FrozenCollectionArtifact(
        path=path.relative_to(payload_dir).as_posix(),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
    )


def _copy_contract(source: Path, payload_dir: Path, relative: str) -> FrozenCollectionArtifact:
    destination = payload_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return _artifact(payload_dir, destination)


def _registered_exclusions(registry: BenchmarkManifestRegistry) -> list[SemanticFingerprintExclusion]:
    exclusions: list[SemanticFingerprintExclusion] = []
    for partition in PRIMARY_PARTITIONS:
        for case in registry.partitions[partition].cases:
            exclusions.append(
                SemanticFingerprintExclusion(
                    case_id=case.case_id,
                    primary_partition=partition,
                    task_fingerprint=case.task_fingerprint,
                )
            )
    return sorted(exclusions, key=lambda item: (item.primary_partition, item.case_id))


def _snapshot_exclusions(
    suite: BenchmarkSuiteManifest,
    partitions: dict[str, BenchmarkPartitionManifest],
) -> list[SemanticFingerprintExclusion]:
    exclusions: list[SemanticFingerprintExclusion] = []
    for partition_id in PRIMARY_PARTITIONS:
        partition = partitions[partition_id]
        if (
            partition.benchmark_id != suite.benchmark_id
            or partition.benchmark_version != suite.benchmark_version
            or partition.primary_partition != partition_id
        ):
            raise ValueError(f"Frozen partition identity mismatch: {partition_id}")
        for case in partition.cases:
            exclusions.append(
                SemanticFingerprintExclusion(
                    case_id=case.case_id,
                    primary_partition=partition_id,
                    task_fingerprint=case.task_fingerprint,
                )
            )
    return sorted(exclusions, key=lambda item: (item.primary_partition, item.case_id))


def _supported_routes(registry: CapabilityRegistry) -> list[SupportedRouteFamily]:
    routes = [route for route in registry.routes if route.support_level == "full_derivation"]
    return [
        SupportedRouteFamily(
            route_id=route.route_id,
            material=route.material,
            texture=route.texture,
            drive=route.drive,
            geometry=route.geometry or "unspecified",
            held_out_target_cases=1,
        )
        for route in sorted(routes, key=lambda item: item.route_id)
    ]


def _operator_instructions() -> str:
    return """# SpinTextureDynamicsBench v1 External Collection Round 01

This is a distribution-only launch packet. It contains no contributor identity, invitation,
submitted case, or private gold. Do not add a case directly to the real benchmark manifests.

## Collection objective

- Collect one independently authored held-out case for each allowed full-derivation route.
- Collect accessible-explanation cases across all audiences frozen in `collection_plan.yaml`.
- Exclude every semantic fingerprint listed in the frozen plan, including paraphrases that test
  the same material-texture-drive-equation combination.

## Role boundary

1. A Project 1 operator may invite and coordinate external participants, but must not author a
   purportedly independent case or inspect plaintext gold.
2. The external case author independently selects an eligible source and completes the public
   brief and provenance record.
3. A different external gold custodian completes and seals private gold. The custodian retains the
   key outside the returned packet.
4. Identities and invitation states belong only in a working copy of the ledger outside this
   immutable launch release. Never overwrite this release.

## Invitation ledger states

- `invited`: invitation sent; no acceptance decision.
- `accepted`: contributor agreed; no packet returned yet.
- `declined`: contributor declined; no case may be attached.
- `returned`: a sealed packet and submitted case IDs are hash-recorded.
- `withdrawn`: a previously invited or accepted participant withdrew.

## Return workflow

1. Give each accepted contributor a fresh copy of `authoring_packet/`.
2. Follow `authoring_packet/OPERATOR_GUIDE.md`; never share development cases, generated answers,
   gold answers, evaluator source, or another contributor's task.
3. Return a signed, sealed packet by the deadlines in `collection_plan.yaml`.
4. Verify it with `benchmark-authoring verify`, then use the separate intake, freeze, custodian
   materialization, and registration-candidate gates.
5. A returned packet does not modify `held_out_supported.yaml` or `readability.yaml`.

## Verify this release

```bash
python -m spintexture_agent.cli benchmark-collection verify --release <release-directory> \
  --require-ready
```

The verifier checks payload hashes, launch semantics, ZIP metadata, and a deterministic rebuild.
The detached `release_index.sha256` is useful only after its value is published through an
independent channel such as a signed GitHub release or archival DOI. Local hashes alone do not
prove participant independence or authorship.
"""


def _checksum_text(artifacts: list[FrozenCollectionArtifact]) -> str:
    return "".join(f"{item.sha256}  {item.path}\n" for item in artifacts)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _write_deterministic_archive(payload_dir: Path, archive_path: Path) -> None:
    with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
        for path in sorted(item for item in payload_dir.rglob("*") if item.is_file()):
            relative = path.relative_to(payload_dir).as_posix()
            archive.writestr(_zip_info(f"{ARCHIVE_ROOT}/{relative}"), path.read_bytes())


def _frozen_source_contracts(
    payload_dir: Path,
    benchmark_manifest: Path,
    benchmark_registry: BenchmarkManifestRegistry,
    capability_registry: Path,
    scorer_registry: Path,
) -> list[FrozenCollectionArtifact]:
    contracts = [
        _copy_contract(
            benchmark_manifest,
            payload_dir,
            "frozen_contract/benchmark_manifests/manifest.yaml",
        ),
        _copy_contract(
            capability_registry,
            payload_dir,
            "frozen_contract/knowledge_base/capabilities.yaml",
        ),
        _copy_contract(
            scorer_registry,
            payload_dir,
            "frozen_contract/knowledge_base/benchmark_scorers.yaml",
        ),
        _copy_contract(
            PROJECT_ROOT / "docs" / "BENCHMARK_CASE_AUTHORING_PROTOCOL.md",
            payload_dir,
            "frozen_contract/docs/BENCHMARK_CASE_AUTHORING_PROTOCOL.md",
        ),
    ]
    for reference in benchmark_registry.suite.partitions:
        source = _project_path(reference.path)
        contracts.append(
            _copy_contract(
                source,
                payload_dir,
                f"frozen_contract/benchmark_manifests/{reference.primary_partition}.yaml",
            )
        )
    return sorted(contracts, key=lambda item: item.path)


def launch_external_collection_round(
    out_dir: str | Path = DEFAULT_COLLECTION_RELEASE,
    *,
    benchmark_manifest: str | Path = DEFAULT_BENCHMARK_MANIFEST,
    capability_registry: str | Path = DEFAULT_REGISTRY_PATH,
    scorer_registry: str | Path = DEFAULT_SCORER_REGISTRY,
    frozen_at: str = "2026-07-27T12:00:00+08:00",
) -> CollectionLaunchResult:
    out_path = _project_path(out_dir)
    if out_path.exists():
        raise FileExistsError(
            f"Collection release already exists: {out_path}. Immutable releases are never overwritten."
        )
    _timestamp(frozen_at)
    benchmark_path = _project_path(benchmark_manifest)
    capability_path = _project_path(capability_registry)
    scorer_path = _project_path(scorer_registry)
    benchmark = BenchmarkManifestRegistry(benchmark_path)
    capabilities = CapabilityRegistry(capability_path)
    routes = _supported_routes(capabilities)
    if not routes:
        raise ValueError("Collection launch requires at least one full-derivation route")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out_path.name}.", dir=out_path.parent) as temp:
        build_dir = Path(temp) / out_path.name
        payload_dir = build_dir / RELEASE_PAYLOAD_DIR
        payload_dir.mkdir(parents=True)
        source_contracts = _frozen_source_contracts(
            payload_dir,
            benchmark_path,
            benchmark,
            capability_path,
            scorer_path,
        )
        generate_authoring_packet(
            payload_dir / "authoring_packet",
            benchmark_manifest=benchmark_path,
        )

        plan = ExternalCollectionPlan(
            frozen_at=frozen_at,
            benchmark_id=benchmark.suite.benchmark_id,
            benchmark_version=benchmark.suite.benchmark_version,
            scorer_registry_version=benchmark.suite.scorer_registry_version,
            target_quotas=[
                CollectionTargetQuota(
                    primary_partition="held_out_supported",
                    target_cases=sum(route.held_out_target_cases for route in routes),
                ),
                CollectionTargetQuota(primary_partition="readability", target_cases=6),
            ],
            allowed_supported_route_families=routes,
            semantic_fingerprint_exclusions=_registered_exclusions(benchmark),
            role_separation=RoleSeparationPolicy(),
            source_eligibility=SourceEligibilityPolicy(
                allowed_source_types=["primary_literature", "external_contribution"]
            ),
            readability_audience_coverage=[
                ReadabilityAudienceQuota(
                    audience_id="experimental_magnetism_researcher",
                    audience_description=(
                        "Experimental magnetism researcher without specialist derivation training"
                    ),
                    target_cases=2,
                    minimum_independent_raters_per_case=2,
                ),
                ReadabilityAudienceQuota(
                    audience_id="magnetic_imaging_or_device_researcher",
                    audience_description=(
                        "Magnetic imaging or spintronic-device researcher using theory outputs"
                    ),
                    target_cases=2,
                    minimum_independent_raters_per_case=2,
                ),
                ReadabilityAudienceQuota(
                    audience_id="physics_graduate_reader_outside_texture_theory",
                    audience_description=(
                        "Physics graduate reader outside magnetic-texture theory"
                    ),
                    target_cases=2,
                    minimum_independent_raters_per_case=2,
                ),
            ],
            deadlines=CollectionDeadlines(
                invitations_open="2026-08-03T00:00:00+08:00",
                acceptance_due="2026-08-17T23:59:59+08:00",
                sealed_submission_due="2026-09-30T23:59:59+08:00",
                custody_confirmation_due="2026-10-14T23:59:59+08:00",
                intake_review_close="2026-10-21T23:59:59+08:00",
            ),
            source_contracts=source_contracts,
        )
        plan_path = payload_dir / "collection_plan.yaml"
        _write_yaml(plan_path, plan)

        ledger = InvitationReturnLedger(allowed_states=list(LEDGER_STATES))
        ledger_path = payload_dir / "invitation_return_ledger.yaml"
        _write_yaml(ledger_path, ledger)
        instructions_path = payload_dir / "OPERATOR_INSTRUCTIONS.md"
        instructions_path.write_text(_operator_instructions(), encoding="utf-8")

        payload_artifacts = sorted(
            (
                _artifact(payload_dir, path)
                for path in payload_dir.rglob("*")
                if path.is_file()
            ),
            key=lambda item: item.path,
        )
        checksum_path = payload_dir / CHECKSUM_FILE
        checksum_path.write_text(_checksum_text(payload_artifacts), encoding="utf-8")
        payload_artifacts.append(_artifact(payload_dir, checksum_path))
        payload_artifacts.sort(key=lambda item: item.path)

        archive_path = build_dir / ARCHIVE_NAME
        _write_deterministic_archive(payload_dir, archive_path)
        archive_artifact = FrozenCollectionArtifact(
            path=ARCHIVE_NAME,
            sha256=_sha256(archive_path),
            size_bytes=archive_path.stat().st_size,
        )
        checksum_artifact = next(
            item for item in payload_artifacts if item.path == CHECKSUM_FILE
        )
        release_index = CollectionReleaseIndex(
            generated_at=frozen_at,
            archive=archive_artifact,
            checksum_index=checksum_artifact,
            payload_artifacts=payload_artifacts,
        )
        index_path = build_dir / RELEASE_INDEX_FILE
        _write_yaml(index_path, release_index)
        index_sha256 = _sha256(index_path)
        (build_dir / RELEASE_INDEX_DIGEST_FILE).write_text(
            f"{index_sha256}  {RELEASE_INDEX_FILE}\n",
            encoding="utf-8",
        )

        preflight = verify_collection_release(build_dir)
        if not preflight.ready_for_distribution:
            raise ValueError(
                "Generated collection release failed preflight verification: "
                + "; ".join(preflight.issues)
            )
        if out_path.exists():
            raise FileExistsError(
                f"Collection release appeared during generation: {out_path}. "
                "Immutable releases are never overwritten."
            )
        shutil.move(str(build_dir), str(out_path))

    final_index = out_path / RELEASE_INDEX_FILE
    result = CollectionLaunchResult(
        release_dir=str(out_path),
        plan_path=str(out_path / RELEASE_PAYLOAD_DIR / "collection_plan.yaml"),
        ledger_path=str(out_path / RELEASE_PAYLOAD_DIR / "invitation_return_ledger.yaml"),
        release_index_path=str(final_index),
        release_index_sha256=_sha256(final_index),
        archive_path=str(out_path / ARCHIVE_NAME),
        archive_sha256=_sha256(out_path / ARCHIVE_NAME),
        payload_file_count=len(release_index.payload_artifacts),
    )
    verification = verify_collection_release(out_path)
    if not verification.ready_for_distribution:
        raise ValueError(
            "Generated collection release failed verification: "
            + "; ".join(verification.issues)
        )
    return result


def _expected_checksum_entries(
    artifacts: list[FrozenCollectionArtifact],
) -> list[FrozenCollectionArtifact]:
    return [item for item in artifacts if item.path != CHECKSUM_FILE]


def _verify_archive(
    payload_dir: Path,
    archive_path: Path,
    expected_artifacts: list[FrozenCollectionArtifact],
    issues: list[str],
) -> bool:
    expected_names = [f"{ARCHIVE_ROOT}/{item.path}" for item in expected_artifacts]
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if names != expected_names:
                issues.append("archive file order or membership differs from the frozen payload")
            for info, expected_name in zip(infos, expected_names, strict=False):
                if info.filename != expected_name:
                    continue
                if info.date_time != (1980, 1, 1, 0, 0, 0):
                    issues.append(f"archive timestamp is not deterministic: {info.filename}")
                if info.compress_type != zipfile.ZIP_STORED:
                    issues.append(f"archive compression is not deterministic stored mode: {info.filename}")
                relative = info.filename.removeprefix(f"{ARCHIVE_ROOT}/")
                source = payload_dir / relative
                if not source.is_file() or archive.read(info) != source.read_bytes():
                    issues.append(f"archive bytes differ from payload: {relative}")
    except (OSError, zipfile.BadZipFile) as exc:
        issues.append(f"release archive cannot be read: {exc}")
        return False

    with tempfile.TemporaryDirectory(prefix="spintexture_collection_rebuild_") as temp:
        rebuilt = Path(temp) / ARCHIVE_NAME
        _write_deterministic_archive(payload_dir, rebuilt)
        if rebuilt.read_bytes() != archive_path.read_bytes():
            issues.append("archive cannot be reconstructed byte-for-byte")
            return False
    return True


def verify_collection_release(release_dir: str | Path) -> CollectionReleaseVerification:
    release_path = _project_path(release_dir)
    issues: list[str] = []
    index_path = release_path / RELEASE_INDEX_FILE
    digest_path = release_path / RELEASE_INDEX_DIGEST_FILE
    payload_dir = release_path / RELEASE_PAYLOAD_DIR
    if not index_path.is_file():
        raise FileNotFoundError(f"Collection release index is missing: {index_path}")
    if not digest_path.is_file():
        raise FileNotFoundError(f"Collection release index digest is missing: {digest_path}")
    if not payload_dir.is_dir():
        raise FileNotFoundError(f"Collection release payload is missing: {payload_dir}")

    index = CollectionReleaseIndex.model_validate(_load_yaml(index_path))
    expected_digest_line = f"{_sha256(index_path)}  {RELEASE_INDEX_FILE}\n"
    if digest_path.read_text(encoding="utf-8") != expected_digest_line:
        issues.append("detached release-index SHA-256 mismatch")

    actual_paths = sorted(
        path.relative_to(payload_dir).as_posix()
        for path in payload_dir.rglob("*")
        if path.is_file()
    )
    indexed_paths = [item.path for item in index.payload_artifacts]
    if actual_paths != sorted(indexed_paths):
        issues.append("release payload membership differs from the release index")
    for artifact in index.payload_artifacts:
        path = payload_dir / artifact.path
        if not path.is_file():
            issues.append(f"indexed payload artifact is missing: {artifact.path}")
        elif path.stat().st_size != artifact.size_bytes or _sha256(path) != artifact.sha256:
            issues.append(f"payload artifact hash or size drift: {artifact.path}")

    checksum_path = payload_dir / CHECKSUM_FILE
    expected_checksums = _checksum_text(_expected_checksum_entries(index.payload_artifacts))
    if not checksum_path.is_file() or checksum_path.read_text(encoding="utf-8") != expected_checksums:
        issues.append("payload checksum index does not match indexed artifacts")
    if index.checksum_index.path != CHECKSUM_FILE or index.checksum_index != next(
        (item for item in index.payload_artifacts if item.path == CHECKSUM_FILE),
        None,
    ):
        issues.append("release index does not bind the payload checksum index")

    plan_path = payload_dir / "collection_plan.yaml"
    ledger_path = payload_dir / "invitation_return_ledger.yaml"
    authoring_manifest_path = payload_dir / "authoring_packet" / "packet_manifest.yaml"
    plan: ExternalCollectionPlan | None = None
    ledger: InvitationReturnLedger | None = None
    authoring: AuthoringPacketManifest | None = None
    try:
        plan = ExternalCollectionPlan.model_validate(_load_yaml(plan_path))
        ledger = InvitationReturnLedger.model_validate(_load_yaml(ledger_path))
        authoring = AuthoringPacketManifest.model_validate(_load_yaml(authoring_manifest_path))
    except (FileNotFoundError, ValueError) as exc:
        issues.append(f"collection launch schema validation failed: {exc}")

    if authoring is not None and (
        authoring.packet_status != "template" or authoring.cases
    ):
        issues.append("distributed authoring packet must remain an empty template")
    if plan is not None:
        capability_snapshot = (
            payload_dir / "frozen_contract" / "knowledge_base" / "capabilities.yaml"
        )
        benchmark_snapshot_dir = (
            payload_dir / "frozen_contract" / "benchmark_manifests"
        )
        benchmark_snapshot = (
            benchmark_snapshot_dir / "manifest.yaml"
        )
        try:
            frozen_capabilities = CapabilityRegistry(
                capability_snapshot,
                verify_artifacts=False,
            )
            expected_routes = _supported_routes(frozen_capabilities)
            if plan.allowed_supported_route_families != expected_routes:
                issues.append("allowed route families drift from the frozen capability registry")

            frozen_suite = BenchmarkSuiteManifest.model_validate(_load_yaml(benchmark_snapshot))
            frozen_partitions = {
                partition_id: BenchmarkPartitionManifest.model_validate(
                    _load_yaml(benchmark_snapshot_dir / f"{partition_id}.yaml")
                )
                for partition_id in PRIMARY_PARTITIONS
            }
            expected_exclusions = _snapshot_exclusions(frozen_suite, frozen_partitions)
            if plan.semantic_fingerprint_exclusions != expected_exclusions:
                issues.append("semantic-fingerprint exclusions drift from frozen manifests")
            if plan.benchmark_id != frozen_suite.benchmark_id:
                issues.append("collection benchmark ID drifts from frozen manifest")
            if plan.benchmark_version != frozen_suite.benchmark_version:
                issues.append("collection benchmark version drifts from frozen manifest")
            if plan.scorer_registry_version != frozen_suite.scorer_registry_version:
                issues.append("collection scorer version drifts from frozen manifest")
            scorer_snapshot = (
                payload_dir
                / "frozen_contract"
                / "knowledge_base"
                / "benchmark_scorers.yaml"
            )
            scorer_payload = _load_yaml(scorer_snapshot)
            scorer_ids = {
                item.get("scorer_id")
                for item in scorer_payload.get("scorers", [])
                if isinstance(item, dict)
            }
            if plan.scorer_registry_version not in scorer_ids:
                issues.append("collection scorer is absent from the frozen scorer registry")
        except (FileNotFoundError, ValueError) as exc:
            issues.append(f"frozen collection contract cannot be verified: {exc}")
        actual_contracts = sorted(
            (
                _artifact(payload_dir, path)
                for path in (payload_dir / "frozen_contract").rglob("*")
                if path.is_file()
            ),
            key=lambda item: item.path,
        )
        if plan.source_contracts != actual_contracts:
            issues.append("frozen source-contract inventory is incomplete or drifted")
        for contract in plan.source_contracts:
            path = payload_dir / contract.path
            if not path.is_file() or _artifact(payload_dir, path) != contract:
                issues.append(f"frozen source-contract drift: {contract.path}")

    archive_path = release_path / index.archive.path
    byte_reconstruction = False
    if not archive_path.is_file():
        issues.append(f"release archive is missing: {index.archive.path}")
    elif (
        archive_path.stat().st_size != index.archive.size_bytes
        or _sha256(archive_path) != index.archive.sha256
    ):
        issues.append("release archive hash or size drift")
    else:
        byte_reconstruction = _verify_archive(
            payload_dir,
            archive_path,
            index.payload_artifacts,
            issues,
        )

    invited_count = len(plan.invited_participant_identities) if plan is not None else 0
    submitted_count = len(plan.submitted_case_ids) if plan is not None else 0
    if ledger is not None:
        invited_count += len(ledger.participant_identities) + len(ledger.entries)
        submitted_count += len(ledger.submitted_case_ids)
    ready = not issues and byte_reconstruction
    return CollectionReleaseVerification(
        collection_id=index.collection_id,
        ready_for_distribution=ready,
        byte_for_byte_reconstruction=byte_reconstruction,
        payload_file_count=len(index.payload_artifacts),
        invited_identity_count=invited_count,
        submitted_case_count=submitted_count,
        issues=issues,
    )
