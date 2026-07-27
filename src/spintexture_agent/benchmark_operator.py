from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .benchmark_collection import (
    ARCHIVE_NAME,
    COLLECTION_ID,
    DEFAULT_COLLECTION_RELEASE,
    RELEASE_INDEX_DIGEST_FILE,
    RELEASE_INDEX_FILE,
    RELEASE_PAYLOAD_DIR,
    FrozenCollectionArtifact,
    verify_collection_release,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPERATOR_SCHEMA_VERSION = "1.0.0"
DEFAULT_PUBLICATION_EVIDENCE = (
    PROJECT_ROOT
    / "public_collection_evidence"
    / "v1"
    / "round_01"
    / "publication_evidence.yaml"
)
DEFAULT_PUBLICATION_RECORD = DEFAULT_PUBLICATION_EVIDENCE.with_name(
    "publication_record.yaml"
)
DEFAULT_PRIVATE_ROOT = PROJECT_ROOT / "benchmark_collection_working"
SNAPSHOT_MANIFEST = "snapshot_manifest.yaml"
SNAPSHOT_DIGEST = "snapshot_manifest.sha256"
STATE_FILE = "ledger_state.yaml"
EVENT_FILE = "event_request.yaml"
CHECKLIST_FILE = "OPERATOR_CHECKLIST.md"
INCOMING_RETURNS_DIR = "incoming_returns"
CLOCK_SKEW = timedelta(minutes=5)

EventType = Literal[
    "invitation_sent",
    "acceptance_received",
    "decline_received",
    "withdrawal_received",
    "sealed_return_received",
]
InvitationState = Literal["invited", "accepted", "declined", "returned", "withdrawn"]
TargetPartition = Literal["held_out_supported", "readability"]

FALSE_CLAIMS = {
    "held_out_cases_collected": False,
    "readability_cases_collected": False,
    "participant_identities_recorded": False,
    "human_ratings_recorded": False,
    "benchmark_performance_claimed": False,
    "external_review_claimed": False,
    "software_v0_1_0_release_mutated": False,
}


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def _write_yaml(path: Path, payload: BaseModel | dict[str, Any]) -> None:
    value = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _now(value: str | None = None) -> datetime:
    return _timestamp(value, "current_time") if value else datetime.now().astimezone()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"Private-ledger artifact path must be safe and relative: {value}")
    return path


def _resolve_relative(root: Path, value: str) -> Path:
    relative = _safe_relative(value)
    path = (root / Path(*relative.parts)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Private-ledger artifact escapes its root: {value}") from exc
    return path


def _private_output_path(value: str | Path) -> Path:
    path = _project_path(value).resolve()
    try:
        relative = path.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return path
    if not relative.parts or relative.parts[0] != DEFAULT_PRIVATE_ROOT.name:
        raise ValueError(
            "Private ledgers inside the project must be under the ignored "
            "benchmark_collection_working/ directory"
        )
    gitignore = PROJECT_ROOT / ".gitignore"
    if "benchmark_collection_working/" not in gitignore.read_text(encoding="utf-8"):
        raise ValueError("Private working-ledger ignore rule is missing")
    return path


def _canonical_hash(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class PrivateParticipant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    private_participant_id: str = Field(pattern=r"^priv_[a-z0-9][a-z0-9_.-]{5,39}$")
    public_participant_id: str = Field(pattern=r"^p_[a-z0-9]{12,32}$")
    role: Literal["contributor", "custodian"]
    name: str = Field(min_length=2)
    affiliation: str = Field(min_length=2)
    contact: str = Field(min_length=3)
    independent_of_project_development: Literal[True] = True
    conflicts_disclosed: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pseudonym(self) -> "PrivateParticipant":
        public = self.public_participant_id.lower()
        private_tokens: set[str] = set()
        for value in (self.name, self.affiliation, self.contact):
            private_tokens.update(re.findall(r"[a-z0-9]{4,}", value.lower()))
        if any(token in public for token in private_tokens):
            raise ValueError("Public participant ID appears to encode private identity data")
        return self


class RealEventConfirmations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    real_world_event_occurred: Literal[True]
    identity_checked_by_operator: Literal[True]
    private_contact_kept_out_of_repository: Literal[True]
    tool_did_not_send_message: Literal[True]


class OperatorEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[OPERATOR_SCHEMA_VERSION] = OPERATOR_SCHEMA_VERSION
    event_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{5,63}$")
    event_type: EventType
    invitation_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    operator_id: str = Field(pattern=r"^op_[a-z0-9]{8,32}$")
    effective_at: str
    recorded_at: str
    target_partition: TargetPartition | None = None
    target_route_id: str | None = None
    audience_id: str | None = None
    participant: PrivateParticipant | None = None
    custodian: PrivateParticipant | None = None
    returned_packet: FrozenCollectionArtifact | None = None
    submitted_case_ids: list[str] = Field(default_factory=list)
    confirmations: RealEventConfirmations

    @model_validator(mode="after")
    def validate_event_shape(self) -> "OperatorEventRequest":
        effective = _timestamp(self.effective_at, "effective_at")
        recorded = _timestamp(self.recorded_at, "recorded_at")
        if recorded < effective:
            raise ValueError("recorded_at cannot precede effective_at")
        if len(self.submitted_case_ids) != len(set(self.submitted_case_ids)):
            raise ValueError("Submitted case IDs must be unique")
        if any(not re.fullmatch(r"[A-Za-z0-9_]+", case_id) for case_id in self.submitted_case_ids):
            raise ValueError("Submitted case IDs have invalid format")

        if self.event_type == "invitation_sent":
            if not self.participant or self.participant.role != "contributor":
                raise ValueError("Invitation events require a contributor identity")
            if not self.target_partition:
                raise ValueError("Invitation events require a target partition")
            if self.target_partition == "held_out_supported":
                if not self.target_route_id or self.audience_id:
                    raise ValueError("Held-out invitations require one route and no audience")
            elif not self.audience_id or self.target_route_id:
                raise ValueError("Readability invitations require one audience and no route")
            if self.custodian or self.returned_packet or self.submitted_case_ids:
                raise ValueError("Invitation events cannot attach return material")
        elif self.event_type == "sealed_return_received":
            if self.participant or self.target_partition or self.target_route_id or self.audience_id:
                raise ValueError("Return events cannot redefine the invitation target")
            if not self.custodian or self.custodian.role != "custodian":
                raise ValueError("Return events require a custodian identity")
            if not self.returned_packet or not self.submitted_case_ids:
                raise ValueError("Return events require a packet and submitted case IDs")
        elif any(
            (
                self.participant,
                self.custodian,
                self.returned_packet,
                self.submitted_case_ids,
                self.target_partition,
                self.target_route_id,
                self.audience_id,
            )
        ):
            raise ValueError("State-only events cannot redefine identities, targets, or returns")
        return self


class PublicationBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication_record_path: str
    publication_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_evidence_path: str
    publication_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    immutable_identifier: str
    published_at: str
    remote_publication_verified: Literal[True] = True


class OperatorPolicyBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    invitations_open: str
    acceptance_due: str
    sealed_submission_due: str
    custody_confirmation_due: str
    intake_review_close: str
    allowed_route_ids: list[str]
    allowed_audience_ids: list[str]


class OperatorInvitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invitation_id: str
    contributor_private_id: str
    contributor_public_id: str
    custodian_private_id: str | None = None
    custodian_public_id: str | None = None
    target_partition: TargetPartition
    target_route_id: str | None = None
    audience_id: str | None = None
    state: InvitationState
    invited_at: str
    accepted_at: str | None = None
    declined_at: str | None = None
    withdrawn_at: str | None = None
    returned_at: str | None = None
    returned_packet: FrozenCollectionArtifact | None = None
    submitted_case_ids: list[str] = Field(default_factory=list)


class OperatorLedgerState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[OPERATOR_SCHEMA_VERSION] = OPERATOR_SCHEMA_VERSION
    collection_id: Literal[COLLECTION_ID] = COLLECTION_ID
    ledger_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{5,63}$")
    snapshot_sequence: int = Field(ge=0)
    created_at: str
    updated_at: str
    operator_id: str = Field(pattern=r"^op_[a-z0-9]{8,32}$")
    publication: PublicationBinding
    policy: OperatorPolicyBinding
    participants: list[PrivateParticipant] = Field(default_factory=list)
    invitations: list[OperatorInvitation] = Field(default_factory=list)
    submitted_case_ids: list[str] = Field(default_factory=list)
    human_rating_count: Literal[0] = 0
    real_manifests_modified: Literal[False] = False

    @model_validator(mode="after")
    def validate_state(self) -> "OperatorLedgerState":
        _timestamp(self.created_at, "created_at")
        _timestamp(self.updated_at, "updated_at")
        private_ids = [item.private_participant_id for item in self.participants]
        public_ids = [item.public_participant_id for item in self.participants]
        invitation_ids = [item.invitation_id for item in self.invitations]
        if len(private_ids) != len(set(private_ids)):
            raise ValueError("Private participant IDs must be unique")
        if len(public_ids) != len(set(public_ids)):
            raise ValueError("Public participant IDs must be unique")
        if len(invitation_ids) != len(set(invitation_ids)):
            raise ValueError("Invitation IDs must be unique")
        if len(self.submitted_case_ids) != len(set(self.submitted_case_ids)):
            raise ValueError("Ledger case IDs must be unique")
        return self


def _parse_checksum_index(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match.group(2) in records:
            raise ValueError("Public collection checksum index is malformed")
        records[match.group(2)] = match.group(1)
    return records


def verify_publication_gate(
    publication_evidence: str | Path = DEFAULT_PUBLICATION_EVIDENCE,
    publication_record: str | Path = DEFAULT_PUBLICATION_RECORD,
    collection_release: str | Path = DEFAULT_COLLECTION_RELEASE,
) -> dict[str, Any]:
    evidence_path = _project_path(publication_evidence).resolve()
    record_path = _project_path(publication_record).resolve()
    release = _project_path(collection_release).resolve()
    issues: list[str] = []
    evidence: dict[str, Any] = {}
    record: dict[str, Any] = {}
    try:
        evidence = _load_yaml(evidence_path)
        record = _load_yaml(record_path)
        checksums = _parse_checksum_index(evidence_path.with_name("CHECKSUMS.sha256"))
        expected_checksum_files = {"publication_record.yaml", "publication_evidence.yaml", "VERIFY.md"}
        if set(checksums) != expected_checksum_files:
            raise ValueError("Public collection checksum membership drift")
        for filename, digest in checksums.items():
            if _sha256(evidence_path.with_name(filename)) != digest:
                raise ValueError(f"Public collection checksum drift: {filename}")
        if evidence.get("status") != "passed" or evidence.get("collection_id") != COLLECTION_ID:
            raise ValueError("Collection publication evidence is not passed")
        remote = evidence.get("remote_verification", {})
        if not all(
            (
                remote.get("remote_publication_verified") is True,
                remote.get("eligible_for_collection_invitation_launch") is True,
                remote.get("byte_for_byte_reconstruction") is True,
                remote.get("payload_file_count") == 24,
            )
        ):
            raise ValueError("Collection publication evidence is not launch-eligible")
        if any(
            evidence.get(field) != 0
            for field in (
                "participant_identity_count",
                "submitted_case_count",
                "human_rating_count",
            )
        ):
            raise ValueError("Collection publication evidence exceeds blank-launch scope")
        if evidence.get("claim_boundaries") != FALSE_CLAIMS:
            raise ValueError("Collection publication claim boundaries were weakened")
        if evidence.get("public_ci", {}).get("conclusion") != "success":
            raise ValueError("Collection publication public CI did not pass")
        if evidence.get("software_release_separation", {}).get("unchanged") is not True:
            raise ValueError("Software-release separation is not attested")
        publication_binding = evidence.get("publication_record", {})
        if (
            publication_binding.get("path") != record_path.name
            or publication_binding.get("sha256") != _sha256(record_path)
        ):
            raise ValueError("Collection publication record binding drift")
        if record.get("status") != "published" or record.get("provider") != "github_release":
            raise ValueError("Collection publication record is incomplete")
        if record.get("claim_boundaries") != FALSE_CLAIMS:
            raise ValueError("Collection publication record claim boundaries drift")

        release_verification = verify_collection_release(release)
        if not release_verification.ready_for_distribution:
            raise ValueError("Frozen collection release no longer verifies")
        assets = {
            "archive": release / ARCHIVE_NAME,
            "release_index": release / RELEASE_INDEX_FILE,
            "release_index_digest": release / RELEASE_INDEX_DIGEST_FILE,
        }
        if set(record.get("assets", {})) != set(assets):
            raise ValueError("Collection publication asset registry drift")
        for key, path in assets.items():
            item = record["assets"][key]
            if item.get("sha256") != _sha256(path) or item.get("size_bytes") != path.stat().st_size:
                raise ValueError(f"Collection publication asset binding drift: {key}")
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as exc:
        issues.append(str(exc))
        release_verification = None
    passed = not issues
    return {
        "schema_version": OPERATOR_SCHEMA_VERSION,
        "status": "pass" if passed else "fail",
        "publication_gate_passed": passed,
        "eligible_for_private_ledger_initialization": passed,
        "collection_id": COLLECTION_ID,
        "publication_record_path": str(record_path),
        "publication_record_sha256": _sha256(record_path) if record_path.is_file() else None,
        "publication_evidence_path": str(evidence_path),
        "publication_evidence_sha256": _sha256(evidence_path) if evidence_path.is_file() else None,
        "immutable_identifier": record.get("immutable_identifier"),
        "published_at": record.get("published_at"),
        "release_verification": (
            release_verification.model_dump(mode="json") if release_verification else {}
        ),
        "participant_identity_count": 0,
        "submitted_case_count": 0,
        "human_rating_count": 0,
        "issues": issues,
    }


def _policy_binding(collection_release: Path) -> OperatorPolicyBinding:
    plan_path = collection_release / RELEASE_PAYLOAD_DIR / "collection_plan.yaml"
    plan = _load_yaml(plan_path)
    deadlines = plan["deadlines"]
    for key, value in deadlines.items():
        _timestamp(value, key)
    return OperatorPolicyBinding(
        collection_plan_sha256=_sha256(plan_path),
        invitations_open=deadlines["invitations_open"],
        acceptance_due=deadlines["acceptance_due"],
        sealed_submission_due=deadlines["sealed_submission_due"],
        custody_confirmation_due=deadlines["custody_confirmation_due"],
        intake_review_close=deadlines["intake_review_close"],
        allowed_route_ids=sorted(
            item["route_id"] for item in plan["allowed_supported_route_families"]
        ),
        allowed_audience_ids=sorted(
            item["audience_id"] for item in plan["readability_audience_coverage"]
        ),
    )


def _artifact_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _write_snapshot(
    root: Path,
    state: OperatorLedgerState,
    event: dict[str, Any],
    *,
    previous_manifest_sha256: str | None,
) -> Path:
    snapshots = root / "snapshots"
    snapshots.mkdir(exist_ok=True)
    snapshots.chmod(0o700)
    event_id = str(event["event_id"])
    snapshot_name = f"{state.snapshot_sequence:06d}_{event_id}"
    destination = snapshots / snapshot_name
    if destination.exists():
        raise FileExistsError(f"Operator-ledger snapshot already exists: {destination}")
    with tempfile.TemporaryDirectory(prefix=f".{snapshot_name}.", dir=snapshots) as temp:
        snapshot = Path(temp) / snapshot_name
        snapshot.mkdir(mode=0o700)
        state_path = snapshot / STATE_FILE
        event_path = snapshot / EVENT_FILE
        _write_yaml(state_path, state)
        _write_yaml(event_path, event)
        manifest = {
            "schema_version": OPERATOR_SCHEMA_VERSION,
            "collection_id": COLLECTION_ID,
            "ledger_id": state.ledger_id,
            "snapshot_id": snapshot_name,
            "snapshot_sequence": state.snapshot_sequence,
            "created_at": state.updated_at,
            "previous_snapshot_manifest_sha256": previous_manifest_sha256,
            "artifacts": {
                "state": _artifact_record(snapshot, state_path),
                "event": _artifact_record(snapshot, event_path),
            },
            "counts": {
                "participant_identities": len(state.participants),
                "invitation_entries": len(state.invitations),
                "submitted_cases": len(state.submitted_case_ids),
                "human_ratings": state.human_rating_count,
            },
            "real_manifests_modified": False,
        }
        manifest_path = snapshot / SNAPSHOT_MANIFEST
        _write_yaml(manifest_path, manifest)
        (snapshot / SNAPSHOT_DIGEST).write_text(
            f"{_sha256(manifest_path)}  {SNAPSHOT_MANIFEST}\n",
            encoding="utf-8",
        )
        (snapshot / SNAPSHOT_DIGEST).chmod(0o600)
        shutil.move(str(snapshot), str(destination))
    return destination


def _checklist() -> str:
    return """# Private Round-01 operator checklist

This directory may contain personal contact information. Keep it outside Git,
restrict access to the authorized operator, encrypt backups, and never paste it
into issues, chat logs, reports, or public benchmark artifacts.

Before recording an event:

- [ ] The real-world event already occurred; this tool did not send the message.
- [ ] The contributor identity and independence statement were checked.
- [ ] The public participant ID is pseudonymous and contains no name/contact clue.
- [ ] A dry-run preview was reviewed and its SHA-256 is supplied to the commit.
- [ ] Invitation, acceptance, return, and custody deadlines are satisfied.
- [ ] Contributor and gold custodian are different real people.
- [ ] Returned packet bytes are retained under the hash recorded in the event.

No private-ledger snapshot modifies a real benchmark manifest or establishes
physics correctness, independence, custody, or readability evidence by itself.
"""


def initialize_private_ledger(
    out_dir: str | Path,
    *,
    ledger_id: str,
    operator_id: str,
    created_at: str,
    publication_evidence: str | Path = DEFAULT_PUBLICATION_EVIDENCE,
    publication_record: str | Path = DEFAULT_PUBLICATION_RECORD,
    collection_release: str | Path = DEFAULT_COLLECTION_RELEASE,
    commit: bool = False,
    preview_sha256: str | None = None,
    current_time: str | None = None,
) -> dict[str, Any]:
    out = _private_output_path(out_dir)
    if out.exists():
        raise FileExistsError(f"Private operator ledger already exists: {out}")
    now = _now(current_time)
    created = _timestamp(created_at, "created_at")
    if created > now + CLOCK_SKEW:
        raise ValueError("Private-ledger initialization cannot be future-dated")
    gate = verify_publication_gate(
        publication_evidence,
        publication_record,
        collection_release,
    )
    if not gate["publication_gate_passed"]:
        raise ValueError("Verified Round-01 publication evidence is required")
    published = _timestamp(gate["published_at"], "published_at")
    if created < published:
        raise ValueError("Private ledger cannot predate the durable publication")
    collection = _project_path(collection_release).resolve()
    policy = _policy_binding(collection)
    publication = PublicationBinding(
        publication_record_path=gate["publication_record_path"],
        publication_record_sha256=gate["publication_record_sha256"],
        publication_evidence_path=gate["publication_evidence_path"],
        publication_evidence_sha256=gate["publication_evidence_sha256"],
        immutable_identifier=gate["immutable_identifier"],
        published_at=gate["published_at"],
    )
    state = OperatorLedgerState(
        ledger_id=ledger_id,
        snapshot_sequence=0,
        created_at=created_at,
        updated_at=created_at,
        operator_id=operator_id,
        publication=publication,
        policy=policy,
    )
    preview_payload = {
        "operation": "initialize_private_operator_ledger",
        "output": str(out),
        "ledger_id": ledger_id,
        "operator_id": operator_id,
        "created_at": created_at,
        "publication_record_sha256": publication.publication_record_sha256,
        "publication_evidence_sha256": publication.publication_evidence_sha256,
        "initial_state_sha256": _canonical_hash(state.model_dump(mode="json")),
    }
    preview = _canonical_hash(preview_payload)
    result = {
        "schema_version": OPERATOR_SCHEMA_VERSION,
        "operation": "initialize_private_operator_ledger",
        "status": "preview" if not commit else "committed",
        "write_performed": False,
        "preview_sha256": preview,
        "ledger_dir": str(out),
        "ledger_id": ledger_id,
        "publication_gate_passed": True,
        "participant_identity_count": 0,
        "invitation_event_count": 0,
        "submitted_case_count": 0,
        "human_rating_count": 0,
        "real_manifests_modified": False,
    }
    if not commit:
        return result
    if preview_sha256 != preview:
        raise ValueError("Commit requires the exact SHA-256 from a prior dry-run preview")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}.", dir=out.parent) as temp:
        root = Path(temp) / out.name
        root.mkdir(mode=0o700)
        checklist = root / CHECKLIST_FILE
        checklist.write_text(_checklist(), encoding="utf-8")
        checklist.chmod(0o600)
        initialization = {
            "schema_version": OPERATOR_SCHEMA_VERSION,
            "event_id": "ledger_initialized",
            "event_type": "ledger_initialized",
            "operator_id": operator_id,
            "effective_at": created_at,
            "recorded_at": created_at,
            "real_world_invitation_event": False,
            "participant_identity_count": 0,
            "submitted_case_count": 0,
            "human_rating_count": 0,
        }
        _write_snapshot(root, state, initialization, previous_manifest_sha256=None)
        if out.exists():
            raise FileExistsError(f"Private ledger appeared during initialization: {out}")
        shutil.move(str(root), str(out))
    verification = verify_private_ledger(out, current_time=current_time)
    if not verification["ledger_valid"]:
        raise ValueError("Constructed private operator ledger failed verification")
    result["write_performed"] = True
    result["head_snapshot_manifest_sha256"] = verification[
        "head_snapshot_manifest_sha256"
    ]
    return result


def _snapshot_dirs(root: Path) -> list[Path]:
    snapshots = root / "snapshots"
    if not snapshots.is_dir():
        raise FileNotFoundError("Private operator ledger snapshot directory is missing")
    paths = sorted(path for path in snapshots.iterdir() if path.is_dir())
    if not paths:
        raise ValueError("Private operator ledger has no snapshots")
    return paths


def _latest_state(root: Path) -> tuple[OperatorLedgerState, str, set[str]]:
    snapshots = _snapshot_dirs(root)
    latest = snapshots[-1]
    state = OperatorLedgerState.model_validate(_load_yaml(latest / STATE_FILE))
    manifest_sha = _sha256(latest / SNAPSHOT_MANIFEST)
    event_ids = {
        str(_load_yaml(snapshot / EVENT_FILE).get("event_id")) for snapshot in snapshots
    }
    return state, manifest_sha, event_ids


def _event_deadline(policy: OperatorPolicyBinding, event_type: EventType) -> datetime:
    field = {
        "invitation_sent": "acceptance_due",
        "acceptance_received": "acceptance_due",
        "decline_received": "acceptance_due",
        "sealed_return_received": "sealed_submission_due",
        "withdrawal_received": "intake_review_close",
    }[event_type]
    return _timestamp(getattr(policy, field), field)


def _apply_event(
    state: OperatorLedgerState,
    event: OperatorEventRequest,
    root: Path,
    *,
    current_time: str | None,
    enforce_wall_clock: bool,
) -> OperatorLedgerState:
    if event.operator_id != state.operator_id:
        raise ValueError("Event operator does not match the private ledger")
    effective = _timestamp(event.effective_at, "effective_at")
    recorded = _timestamp(event.recorded_at, "recorded_at")
    open_at = _timestamp(state.policy.invitations_open, "invitations_open")
    if effective < open_at:
        raise ValueError("Round-01 invitation events cannot predate 2026-08-03")
    if effective > _event_deadline(state.policy, event.event_type):
        raise ValueError(f"{event.event_type} exceeds its frozen Round-01 deadline")
    if enforce_wall_clock:
        now = _now(current_time)
        if effective > now + CLOCK_SKEW or recorded > now + CLOCK_SKEW:
            raise ValueError("A real operator event cannot be future-dated")

    payload = state.model_dump(mode="json")
    invitations = payload["invitations"]
    participants = payload["participants"]
    invitation_index = next(
        (
            index
            for index, invitation in enumerate(invitations)
            if invitation["invitation_id"] == event.invitation_id
        ),
        None,
    )
    if event.event_type == "invitation_sent":
        if invitation_index is not None:
            raise ValueError("Invitation ID already exists")
        participant = event.participant
        assert participant is not None
        if participant.private_participant_id in {
            item["private_participant_id"] for item in participants
        } or participant.public_participant_id in {
            item["public_participant_id"] for item in participants
        }:
            raise ValueError("Contributor private or public ID already exists")
        if (
            event.target_route_id
            and event.target_route_id not in state.policy.allowed_route_ids
        ):
            raise ValueError("Invitation route is not eligible in frozen Round-01")
        if event.audience_id and event.audience_id not in state.policy.allowed_audience_ids:
            raise ValueError("Invitation audience is not eligible in frozen Round-01")
        participants.append(participant.model_dump(mode="json"))
        invitations.append(
            OperatorInvitation(
                invitation_id=event.invitation_id,
                contributor_private_id=participant.private_participant_id,
                contributor_public_id=participant.public_participant_id,
                target_partition=event.target_partition,
                target_route_id=event.target_route_id,
                audience_id=event.audience_id,
                state="invited",
                invited_at=event.effective_at,
            ).model_dump(mode="json")
        )
    else:
        if invitation_index is None:
            raise ValueError("Event refers to an unknown invitation")
        invitation = invitations[invitation_index]
        if effective < _timestamp(invitation["invited_at"], "invited_at"):
            raise ValueError("Invitation transition predates the invitation")
        allowed = {
            "acceptance_received": {"invited"},
            "decline_received": {"invited"},
            "withdrawal_received": {"invited", "accepted"},
            "sealed_return_received": {"accepted"},
        }[event.event_type]
        if invitation["state"] not in allowed:
            raise ValueError(
                f"Invalid transition from {invitation['state']} via {event.event_type}"
            )
        if event.event_type == "acceptance_received":
            invitation["state"] = "accepted"
            invitation["accepted_at"] = event.effective_at
        elif event.event_type == "decline_received":
            invitation["state"] = "declined"
            invitation["declined_at"] = event.effective_at
        elif event.event_type == "withdrawal_received":
            invitation["state"] = "withdrawn"
            invitation["withdrawn_at"] = event.effective_at
        else:
            if effective < _timestamp(invitation["accepted_at"], "accepted_at"):
                raise ValueError("Return predates contributor acceptance")
            custodian = event.custodian
            artifact = event.returned_packet
            assert custodian is not None and artifact is not None
            if custodian.private_participant_id == invitation["contributor_private_id"]:
                raise ValueError("Contributor and custodian private identities must differ")
            if custodian.public_participant_id == invitation["contributor_public_id"]:
                raise ValueError("Contributor and custodian public IDs must differ")
            if custodian.private_participant_id in {
                item["private_participant_id"] for item in participants
            } or custodian.public_participant_id in {
                item["public_participant_id"] for item in participants
            }:
                raise ValueError("Custodian private or public ID already exists")
            if _safe_relative(artifact.path).parts[0] != INCOMING_RETURNS_DIR:
                raise ValueError("Returned packets must remain under incoming_returns/")
            packet = _resolve_relative(root, artifact.path)
            if not packet.is_file():
                raise FileNotFoundError(f"Returned packet is missing: {artifact.path}")
            if packet.stat().st_size != artifact.size_bytes or _sha256(packet) != artifact.sha256:
                raise ValueError("Returned packet hash or size drift")
            overlap = set(payload["submitted_case_ids"]) & set(event.submitted_case_ids)
            if overlap:
                raise ValueError("Submitted case ID already exists in the private ledger")
            participants.append(custodian.model_dump(mode="json"))
            invitation.update(
                {
                    "state": "returned",
                    "custodian_private_id": custodian.private_participant_id,
                    "custodian_public_id": custodian.public_participant_id,
                    "returned_at": event.effective_at,
                    "returned_packet": artifact.model_dump(mode="json"),
                    "submitted_case_ids": event.submitted_case_ids,
                }
            )
            payload["submitted_case_ids"].extend(event.submitted_case_ids)
    payload["snapshot_sequence"] += 1
    payload["updated_at"] = event.recorded_at
    return OperatorLedgerState.model_validate(payload)


def plan_or_record_event(
    ledger_dir: str | Path,
    request_file: str | Path,
    *,
    commit: bool = False,
    preview_sha256: str | None = None,
    confirm_real_event: bool = False,
    current_time: str | None = None,
) -> dict[str, Any]:
    root = _private_output_path(ledger_dir)
    verification = verify_private_ledger(root, current_time=current_time)
    if not verification["ledger_valid"]:
        raise ValueError("Private operator ledger failed verification")
    request_path = _project_path(request_file).resolve()
    event = OperatorEventRequest.model_validate(_load_yaml(request_path))
    state, head_sha, event_ids = _latest_state(root)
    if event.event_id in event_ids:
        raise ValueError("Event ID already exists in the append-only ledger")
    next_state = _apply_event(
        state,
        event,
        root,
        current_time=current_time,
        enforce_wall_clock=True,
    )
    preview_payload = {
        "operation": "record_real_operator_event",
        "ledger_id": state.ledger_id,
        "head_snapshot_manifest_sha256": head_sha,
        "request_sha256": _sha256(request_path),
        "event_id": event.event_id,
        "event_type": event.event_type,
        "next_state_sha256": _canonical_hash(next_state.model_dump(mode="json")),
    }
    preview = _canonical_hash(preview_payload)
    invitation = next(
        item for item in next_state.invitations if item.invitation_id == event.invitation_id
    )
    result = {
        "schema_version": OPERATOR_SCHEMA_VERSION,
        "operation": "record_real_operator_event",
        "status": "preview" if not commit else "committed",
        "write_performed": False,
        "preview_sha256": preview,
        "ledger_id": state.ledger_id,
        "event_id": event.event_id,
        "event_type": event.event_type,
        "invitation_id": event.invitation_id,
        "resulting_state": invitation.state,
        "participant_identity_count": len(next_state.participants),
        "invitation_entry_count": len(next_state.invitations),
        "submitted_case_count": len(next_state.submitted_case_ids),
        "human_rating_count": 0,
        "real_manifests_modified": False,
    }
    if not commit:
        return result
    if not confirm_real_event:
        raise ValueError("Commit requires --confirm-real-event")
    if preview_sha256 != preview:
        raise ValueError("Commit requires the exact SHA-256 from a prior dry-run preview")
    snapshot = _write_snapshot(
        root,
        next_state,
        event.model_dump(mode="json"),
        previous_manifest_sha256=head_sha,
    )
    post = verify_private_ledger(root, current_time=current_time)
    if not post["ledger_valid"]:
        raise ValueError("Committed private-ledger snapshot failed verification")
    result["write_performed"] = True
    result["snapshot"] = str(snapshot)
    result["head_snapshot_manifest_sha256"] = post["head_snapshot_manifest_sha256"]
    return result


def _verify_permissions(root: Path, issues: list[str]) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            issues.append(f"Private ledger may not contain symlinks: {path.relative_to(root)}")
            continue
        mode = path.stat().st_mode & 0o777
        expected = 0o700 if path.is_dir() else 0o600
        if mode != expected:
            issues.append(
                f"Private-ledger permission drift: {path.relative_to(root)} is {oct(mode)}"
            )


def _validate_snapshot_artifact(snapshot: Path, record: dict[str, Any]) -> Path:
    if set(record) != {"path", "sha256", "size_bytes"}:
        raise ValueError("Private snapshot artifact fields drift")
    path = _resolve_relative(snapshot, str(record["path"]))
    if not path.is_file():
        raise FileNotFoundError(f"Private snapshot artifact is missing: {record['path']}")
    if path.stat().st_size != record["size_bytes"] or _sha256(path) != record["sha256"]:
        raise ValueError(f"Private snapshot artifact drift: {record['path']}")
    return path


def verify_private_ledger(
    ledger_dir: str | Path,
    *,
    current_time: str | None = None,
) -> dict[str, Any]:
    root = _private_output_path(ledger_dir)
    issues: list[str] = []
    latest_state: OperatorLedgerState | None = None
    head_sha: str | None = None
    event_ids: set[str] = set()
    if not root.is_dir():
        raise FileNotFoundError(f"Private operator ledger does not exist: {root}")
    _verify_permissions(root, issues)
    root_members = {path.name for path in root.iterdir()}
    allowed_root_members = {CHECKLIST_FILE, "snapshots", INCOMING_RETURNS_DIR}
    if not {CHECKLIST_FILE, "snapshots"}.issubset(root_members) or not root_members.issubset(
        allowed_root_members
    ):
        issues.append("Private operator ledger root membership drift")
    try:
        snapshots = _snapshot_dirs(root)
        previous_state: OperatorLedgerState | None = None
        previous_manifest_sha: str | None = None
        for sequence, snapshot in enumerate(snapshots):
            expected_files = {STATE_FILE, EVENT_FILE, SNAPSHOT_MANIFEST, SNAPSHOT_DIGEST}
            if {path.name for path in snapshot.iterdir()} != expected_files:
                raise ValueError(f"Private snapshot membership drift: {snapshot.name}")
            manifest_path = snapshot / SNAPSHOT_MANIFEST
            digest_line = (snapshot / SNAPSHOT_DIGEST).read_text(encoding="utf-8")
            if digest_line != f"{_sha256(manifest_path)}  {SNAPSHOT_MANIFEST}\n":
                raise ValueError(f"Private snapshot detached digest drift: {snapshot.name}")
            manifest = _load_yaml(manifest_path)
            required_manifest = {
                "schema_version",
                "collection_id",
                "ledger_id",
                "snapshot_id",
                "snapshot_sequence",
                "created_at",
                "previous_snapshot_manifest_sha256",
                "artifacts",
                "counts",
                "real_manifests_modified",
            }
            if set(manifest) != required_manifest:
                raise ValueError(f"Private snapshot manifest fields drift: {snapshot.name}")
            if (
                manifest["schema_version"] != OPERATOR_SCHEMA_VERSION
                or manifest["collection_id"] != COLLECTION_ID
                or manifest["snapshot_id"] != snapshot.name
                or manifest["snapshot_sequence"] != sequence
                or manifest["previous_snapshot_manifest_sha256"] != previous_manifest_sha
                or manifest["real_manifests_modified"] is not False
            ):
                raise ValueError(f"Private snapshot chain binding drift: {snapshot.name}")
            if set(manifest["artifacts"]) != {"state", "event"}:
                raise ValueError(f"Private snapshot artifact registry drift: {snapshot.name}")
            state_path = _validate_snapshot_artifact(snapshot, manifest["artifacts"]["state"])
            event_path = _validate_snapshot_artifact(snapshot, manifest["artifacts"]["event"])
            state = OperatorLedgerState.model_validate(_load_yaml(state_path))
            event_payload = _load_yaml(event_path)
            event_id = str(event_payload.get("event_id"))
            if event_id in event_ids:
                raise ValueError(f"Duplicate private-ledger event ID: {event_id}")
            event_ids.add(event_id)
            counts = {
                "participant_identities": len(state.participants),
                "invitation_entries": len(state.invitations),
                "submitted_cases": len(state.submitted_case_ids),
                "human_ratings": state.human_rating_count,
            }
            if manifest["counts"] != counts or state.snapshot_sequence != sequence:
                raise ValueError(f"Private snapshot count or sequence drift: {snapshot.name}")
            if sequence == 0:
                if (
                    event_payload.get("event_type") != "ledger_initialized"
                    or state.participants
                    or state.invitations
                    or state.submitted_case_ids
                ):
                    raise ValueError("Initial private-ledger snapshot is not blank")
                gate = verify_publication_gate(
                    state.publication.publication_evidence_path,
                    state.publication.publication_record_path,
                    DEFAULT_COLLECTION_RELEASE,
                )
                if not gate["publication_gate_passed"] or any(
                    (
                        gate["publication_record_sha256"]
                        != state.publication.publication_record_sha256,
                        gate["publication_evidence_sha256"]
                        != state.publication.publication_evidence_sha256,
                        gate["immutable_identifier"]
                        != state.publication.immutable_identifier,
                    )
                ):
                    raise ValueError("Private ledger publication binding drift")
            else:
                assert previous_state is not None
                event = OperatorEventRequest.model_validate(event_payload)
                replayed = _apply_event(
                    previous_state,
                    event,
                    root,
                    current_time=current_time,
                    enforce_wall_clock=current_time is not None,
                )
                if replayed.model_dump(mode="json") != state.model_dump(mode="json"):
                    raise ValueError(f"Private snapshot replay drift: {snapshot.name}")
            previous_state = state
            previous_manifest_sha = _sha256(manifest_path)
            latest_state = state
            head_sha = previous_manifest_sha
    except (
        FileNotFoundError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        issues.append(str(exc))
    valid = not issues and latest_state is not None
    return {
        "schema_version": OPERATOR_SCHEMA_VERSION,
        "status": "pass" if valid else "fail",
        "ledger_valid": valid,
        "collection_id": COLLECTION_ID,
        "ledger_id": latest_state.ledger_id if latest_state else None,
        "snapshot_count": latest_state.snapshot_sequence + 1 if latest_state else 0,
        "head_snapshot_manifest_sha256": head_sha,
        "participant_identity_count": len(latest_state.participants) if latest_state else 0,
        "invitation_entry_count": len(latest_state.invitations) if latest_state else 0,
        "submitted_case_count": len(latest_state.submitted_case_ids) if latest_state else 0,
        "human_rating_count": latest_state.human_rating_count if latest_state else 0,
        "real_manifests_modified": False,
        "issues": list(dict.fromkeys(issues)),
    }
