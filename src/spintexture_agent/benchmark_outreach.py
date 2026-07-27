from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .benchmark_collection import (
    ARCHIVE_NAME,
    COLLECTION_ID,
    DEFAULT_COLLECTION_RELEASE,
    RELEASE_INDEX_DIGEST_FILE,
    RELEASE_INDEX_FILE,
    RELEASE_PAYLOAD_DIR,
    verify_collection_release,
)
from .benchmark_operator import (
    DEFAULT_PUBLICATION_EVIDENCE,
    DEFAULT_PUBLICATION_RECORD,
    FALSE_CLAIMS,
    verify_publication_gate,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTREACH_SCHEMA_VERSION = "1.0.0"
DEFAULT_HANDOFF_ID = "project1_benchmark_v1_round01_outreach01"
DEFAULT_HANDOFF = (
    PROJECT_ROOT / "analysis" / "collection_outreach_handoffs" / DEFAULT_HANDOFF_ID
)
DEFAULT_LEDGER_PROTOCOL = PROJECT_ROOT / "docs" / "BENCHMARK_PRIVATE_OPERATOR_LEDGER.md"
HANDOFF_MANIFEST = "outreach_handoff.yaml"
HANDOFF_DIGEST = "outreach_handoff.sha256"
OUTREACH_PLAN = "outreach_plan.yaml"
OPENING_AT = "2026-08-03T00:00:00+08:00"
CLOCK_SKEW = timedelta(minutes=5)

OUTREACH_CLAIMS = {
    **FALSE_CLAIMS,
    "outreach_sent": False,
    "invitation_event_recorded": False,
    "participation_confirmed": False,
    "returned_packet_received": False,
}

ASSET_FILENAMES = {
    "archive": ARCHIVE_NAME,
    "release_index": RELEASE_INDEX_FILE,
    "release_index_digest": RELEASE_INDEX_DIGEST_FILE,
}

ARTIFACT_LAYOUT = {
    "publication_record": ("bindings/publication_record.yaml", "publication_binding"),
    "publication_evidence": ("bindings/publication_evidence.yaml", "publication_binding"),
    "collection_plan": ("bindings/collection_plan.yaml", "collection_contract"),
    "ledger_protocol": ("bindings/PRIVATE_LEDGER_PROTOCOL.md", "operator_protocol"),
    "source_operator_instructions": (
        "bindings/SOURCE_OPERATOR_INSTRUCTIONS.md",
        "collection_contract",
    ),
    "outreach_plan": (OUTREACH_PLAN, "outreach_contract"),
    "contributor_draft": ("drafts/case_contributor_invitation.md", "no_send_draft"),
    "custodian_draft": ("drafts/gold_custodian_invitation.md", "no_send_draft"),
    "rater_draft": ("drafts/readability_rater_invitation.md", "later_no_send_draft"),
    "operator_checklist": ("OPERATOR_CHECKLIST.md", "operator_checklist"),
    "readme": ("README.md", "documentation"),
}

SENSITIVE_TEXT_KEYS = {
    "recipient_name",
    "recipient_email",
    "recipient_phone",
    "participant_name",
    "participant_email",
    "participant_phone",
    "private_participant_id",
    "public_participant_id",
    "contact",
    "email",
    "phone",
}

PAST_EVENT_PATTERNS = (
    re.compile(
        r"\b(?:we|project|operator)\s+(?:have\s+)?"
        r"(?:sent|invited|contacted|received|collected|confirmed)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:participant|contributor|custodian|rater)\s+(?:has|have)\s+"
        r"(?:accepted|participated|returned|rated)\b",
        re.IGNORECASE,
    ),
)


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


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"Unsafe outreach-handoff path: {value}")
    return path


def _resolve_relative(root: Path, value: str) -> Path:
    relative = _safe_relative(value)
    path = (root / Path(*relative.parts)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Outreach artifact escapes the handoff: {value}") from exc
    return path


def _artifact(root: Path, path: Path, category: str) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "category": category,
    }


def _validate_artifact(root: Path, record: dict[str, Any]) -> Path:
    if not isinstance(record, dict) or set(record) != {
        "path",
        "sha256",
        "size_bytes",
        "category",
    }:
        raise ValueError("Outreach artifact fields drift")
    path = _resolve_relative(root, str(record["path"]))
    if not path.is_file():
        raise FileNotFoundError(f"Outreach artifact is missing: {record['path']}")
    if path.stat().st_size != record["size_bytes"] or _sha256(path) != record["sha256"]:
        raise ValueError(f"Outreach artifact hash or size drift: {record['path']}")
    return path


def _validate_release_url(url: str, expected_path: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.port is not None
    ):
        raise ValueError("Outreach handoff contains a mutable or unbound release URL")


def _validate_publication(
    record: dict[str, Any],
    evidence: dict[str, Any],
    *,
    expected_record_sha256: str,
) -> None:
    repository = record.get("repository")
    tag = record.get("release_tag")
    identifier = record.get("immutable_identifier")
    if (
        record.get("schema_version") != "1.0.0"
        or record.get("status") != "published"
        or record.get("provider") != "github_release"
        or repository != "WWO-OWW/SpinTextureTheoryAgent"
        or tag != "benchmark-collection-v1-round-01"
        or identifier != f"github:{repository}@{tag}"
        or record.get("claim_boundaries") != FALSE_CLAIMS
    ):
        raise ValueError("Outreach publication record binding drift")
    _timestamp(record.get("published_at"), "published_at")
    if record.get("attestation") != {
        "dedicated_collection_release": True,
        "all_exact_assets_uploaded": True,
        "provider_record_public": True,
        "software_v0_1_0_untouched": True,
    }:
        raise ValueError("Outreach publication attestations drift")

    assets = record.get("assets")
    if not isinstance(assets, dict) or set(assets) != set(ASSET_FILENAMES):
        raise ValueError("Outreach publication asset registry drift")
    owner, repo = repository.split("/", 1)
    for key, filename in ASSET_FILENAMES.items():
        item = assets[key]
        if not isinstance(item, dict) or set(item) != {
            "filename",
            "url",
            "sha256",
            "size_bytes",
        }:
            raise ValueError(f"Outreach publication asset fields drift: {key}")
        if item["filename"] != filename or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError(f"Outreach publication asset identity drift: {key}")
        _validate_release_url(
            item["url"],
            f"/{owner}/{repo}/releases/download/{tag}/{filename}",
        )

    release = evidence.get("release", {})
    if (
        evidence.get("schema_version") != "1.0.0"
        or evidence.get("status") != "passed"
        or evidence.get("collection_id") != COLLECTION_ID
        or evidence.get("claim_boundaries") != FALSE_CLAIMS
        or evidence.get("participant_identity_count") != 0
        or evidence.get("submitted_case_count") != 0
        or evidence.get("human_rating_count") != 0
        or evidence.get("remote_verification", {}).get(
            "eligible_for_collection_invitation_launch"
        )
        is not True
        or release.get("repository") != repository
        or release.get("tag") != tag
    ):
        raise ValueError("Outreach publication evidence binding drift")
    if evidence.get("publication_record") != {
        "path": "publication_record.yaml",
        "sha256": expected_record_sha256,
    }:
        raise ValueError("Outreach publication record digest binding drift")
    _validate_release_url(release.get("url"), f"/{owner}/{repo}/releases/tag/{tag}")


def _validate_no_private_text(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text):
        raise ValueError(f"Outreach artifact contains an email address: {path.name}")
    if re.search(
        r"(?im)^\s*(?:recipient|name|contact|email|phone|affiliation)\s*:",
        text,
    ):
        raise ValueError(
            f"Outreach artifact contains a private identity or contact field: {path.name}"
        )
    if re.search(r"(?im)^\s*(?:private|public)_participant_id\s*:", text):
        raise ValueError(f"Outreach artifact contains a participant ID field: {path.name}")
    if any(pattern.search(text) for pattern in PAST_EVENT_PATTERNS):
        raise ValueError(f"Outreach artifact claims a real event already occurred: {path.name}")


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in SENSITIVE_TEXT_KEYS or _contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _targets(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "held_out": {
            "target_cases": next(
                item["target_cases"]
                for item in plan["target_quotas"]
                if item["primary_partition"] == "held_out_supported"
            ),
            "eligible_routes": plan["allowed_supported_route_families"],
        },
        "readability": {
            "target_cases": next(
                item["target_cases"]
                for item in plan["target_quotas"]
                if item["primary_partition"] == "readability"
            ),
            "audiences": plan["readability_audience_coverage"],
        },
    }


def _outreach_plan(
    *, handoff_id: str, created_at: str, record: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": OUTREACH_SCHEMA_VERSION,
        "collection_id": COLLECTION_ID,
        "handoff_id": handoff_id,
        "plan_status": "no_send_operator_handoff",
        "created_at": created_at,
        "outreach_opening_at": OPENING_AT,
        "deadlines": plan["deadlines"],
        "publication": {
            "immutable_identifier": record["immutable_identifier"],
            "release_page_url": (
                "https://github.com/WWO-OWW/SpinTextureTheoryAgent/releases/tag/"
                "benchmark-collection-v1-round-01"
            ),
            "assets": record["assets"],
        },
        "targets": _targets(plan),
        "role_contract": plan["role_separation"],
        "source_eligibility": plan["source_eligibility"],
        "private_ledger": {
            "protocol_artifact": "bindings/PRIVATE_LEDGER_PROTOCOL.md",
            "required_after_real_operator_event": True,
            "tool_sends_messages": False,
        },
        "state": {
            "drafts_only": True,
            "messages_sent": False,
            "participation_confirmed": False,
            "returns_received": False,
            "readability_study_open": False,
        },
        "counts": {
            "participant_identities": 0,
            "invitation_events": 0,
            "submitted_cases": 0,
            "human_ratings": 0,
        },
        "claim_boundaries": OUTREACH_CLAIMS,
    }


def _drafts(release_url: str, deadlines: dict[str, str]) -> dict[str, str]:
    common = (
        f"\nPublic Round-01 release: {release_url}\n"
        "This is a no-send draft. A human operator must choose the recipient and "
        "communication channel. No response or participation is implied.\n"
    )
    return {
        "contributor_draft": f"""# NO-SEND DRAFT: independent case contributor

Subject: Invitation to contribute an independent SpinTextureDynamicsBench case

Dear colleague,

We are preparing an independently authored evaluation set for a symbolic magnetic-texture
theory agent. The proposed role is to select an eligible primary-literature source that was not
used in project development and prepare a public task brief with exact equation or page locators.
Do not include expected equations, gold answers, rubrics, Project 1 outputs, or evaluator details.

Eligibility requires independence from Project 1 development and disclosure of relevant
conflicts. A different person must serve as gold custodian. Availability should be answered by
{deadlines['acceptance_due']}; a sealed submission is due by
{deadlines['sealed_submission_due']}. Personal details and responses stay in the operator's
private workflow.
{common}
Receiving this draft establishes no invitation, acceptance, authorship, or benchmark evidence.
""",
        "custodian_draft": f"""# NO-SEND DRAFT: independent gold custodian

Subject: Request for independent sealed-gold custody

Dear colleague,

The proposed role is to be a gold custodian for an externally authored magnetic-texture benchmark
case. The custodian must be independent of Project 1 development and must be a different person
from the case contributor. The role is to complete private gold material, seal it as encrypted or
institutionally access-controlled opaque bytes, retain the key, and provide only hashes and the
sealed packet to the development team. Plaintext gold must remain unavailable until the frozen
evaluation workflow authorizes access.

Relevant conflicts and any custody deviation must be disclosed. Custody confirmation is due by
{deadlines['custody_confirmation_due']}. Do not place personal details, plaintext gold, or keys in
public artifacts.
{common}
Receiving this draft establishes no custody agreement, return, or independent-review evidence.
""",
        "rater_draft": f"""# LATER NO-SEND DRAFT: accessible-report readability rater

Subject: Later invitation to a blinded readability study

Dear colleague,

This draft is reserved for a later study after readability cases and the study packet are frozen.
The proposed role is to assess accessible reports using the five registered dimensions without
changing formulas, assumptions, warnings, certainty, or validity limits. Raters must match one of
the frozen audiences, disclose relevant conflicts, and work independently; at least two eligible
raters are required per case. Gold equations and other raters' scores are not provided during
blinded scoring.

Do not use this draft to recruit anyone before the separate readability study is ready. The
collection intake review closes at {deadlines['intake_review_close']}; the actual rating schedule
must be frozen in the later study packet.
{common}
Receiving this draft establishes no rating request, completed score, or readability evidence.
""",
    }


def _checklist() -> str:
    return """# Round-01 authorized-operator outreach checklist

This package contains no recipient data and sends nothing.

Before any case-contributor or custodian outreach:

- [ ] Confirm local date/time is on or after 2026-08-03T00:00:00+08:00.
- [ ] Re-run the publication and handoff verifiers.
- [ ] Select only a route or audience listed in `outreach_plan.yaml`.
- [ ] Verify identity, independence, conflicts, and source novelty privately.
- [ ] Keep recipient details and replies outside this handoff and outside Git.
- [ ] Use a human-controlled communication channel; this tool does not send messages.
- [ ] After a real event, preview and append it to the private ledger.
- [ ] Keep case contributor and gold custodian roles with different people.
- [ ] Never disclose development outputs, evaluator internals, plaintext gold, or keys.

For readability raters, wait until the separate frozen readability study packet exists.
No checklist mark is evidence of identity, independence, scientific correctness, or participation.
"""


def _readme() -> str:
    return """# Round-01 outreach operator handoff

This is a public-data-only, no-send preparation artifact. It binds role-specific drafts and an
operator checklist to the verified immutable Round-01 collection release. It contains zero real
identities, invitation events, submitted cases, returns, and human ratings.

Run `benchmark-outreach-handoff verify` before use. An authorized human selects recipients and
sends any eventual communication outside this tool. Only events that actually occurred may be
recorded through the separate private-ledger two-step workflow.
"""


def create_outreach_handoff(
    out_dir: str | Path = DEFAULT_HANDOFF,
    *,
    handoff_id: str = DEFAULT_HANDOFF_ID,
    created_at: str | None = None,
    publication_evidence: str | Path = DEFAULT_PUBLICATION_EVIDENCE,
    publication_record: str | Path = DEFAULT_PUBLICATION_RECORD,
    collection_release: str | Path = DEFAULT_COLLECTION_RELEASE,
    ledger_protocol: str | Path = DEFAULT_LEDGER_PROTOCOL,
    current_time: str | None = None,
) -> dict[str, Any]:
    out = _project_path(out_dir)
    if out.exists():
        raise FileExistsError(f"Outreach handoff already exists: {out}")
    now = _timestamp(current_time, "current_time") if current_time else datetime.now().astimezone()
    timestamp = created_at or now.isoformat(timespec="seconds")
    created = _timestamp(timestamp, "created_at")
    if created > now + CLOCK_SKEW:
        raise ValueError("Outreach handoff cannot be future-dated")

    gate = verify_publication_gate(
        publication_evidence,
        publication_record,
        collection_release,
    )
    if not gate["publication_gate_passed"]:
        raise ValueError("Verified blank Round-01 publication evidence is required")
    if created < _timestamp(gate["published_at"], "published_at"):
        raise ValueError("Outreach handoff cannot predate durable publication")

    evidence_path = _project_path(publication_evidence).resolve()
    record_path = _project_path(publication_record).resolve()
    release = _project_path(collection_release).resolve()
    protocol_path = _project_path(ledger_protocol).resolve()
    source_instructions = release / RELEASE_PAYLOAD_DIR / "OPERATOR_INSTRUCTIONS.md"
    plan_path = release / RELEASE_PAYLOAD_DIR / "collection_plan.yaml"
    for source in (evidence_path, record_path, protocol_path, source_instructions, plan_path):
        if not source.is_file():
            raise FileNotFoundError(f"Outreach source artifact is missing: {source}")
    record = _load_yaml(record_path)
    evidence = _load_yaml(evidence_path)
    collection_plan = _load_yaml(plan_path)
    _validate_publication(
        record,
        evidence,
        expected_record_sha256=_sha256(record_path),
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}.", dir=out.parent) as temp:
        root = Path(temp) / out.name
        root.mkdir()
        destinations = {
            key: root / relative for key, (relative, _) in ARTIFACT_LAYOUT.items()
        }
        for path in destinations.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(record_path, destinations["publication_record"])
        shutil.copy2(evidence_path, destinations["publication_evidence"])
        shutil.copy2(plan_path, destinations["collection_plan"])
        shutil.copy2(protocol_path, destinations["ledger_protocol"])
        shutil.copy2(source_instructions, destinations["source_operator_instructions"])
        _write_yaml(
            destinations["outreach_plan"],
            _outreach_plan(
                handoff_id=handoff_id,
                created_at=timestamp,
                record=record,
                plan=collection_plan,
            ),
        )
        release_url = evidence["release"]["url"]
        for key, content in _drafts(release_url, collection_plan["deadlines"]).items():
            destinations[key].write_text(content, encoding="utf-8")
        destinations["operator_checklist"].write_text(_checklist(), encoding="utf-8")
        destinations["readme"].write_text(_readme(), encoding="utf-8")

        artifacts = {
            key: _artifact(root, destinations[key], category)
            for key, (_, category) in ARTIFACT_LAYOUT.items()
        }
        manifest = {
            "schema_version": OUTREACH_SCHEMA_VERSION,
            "handoff_id": handoff_id,
            "collection_id": COLLECTION_ID,
            "created_at": timestamp,
            "publication_binding": {
                "immutable_identifier": record["immutable_identifier"],
                "publication_record_sha256": _sha256(record_path),
                "publication_evidence_sha256": _sha256(evidence_path),
                "release_page_url": evidence["release"]["url"],
            },
            "artifacts": artifacts,
            "state": {
                "handoff_ready": True,
                "no_send_drafts": True,
                "messages_sent": False,
                "participation_confirmed": False,
                "returns_received": False,
            },
            "counts": {
                "participant_identities": 0,
                "invitation_events": 0,
                "submitted_cases": 0,
                "human_ratings": 0,
            },
            "claim_boundaries": OUTREACH_CLAIMS,
        }
        _write_yaml(root / HANDOFF_MANIFEST, manifest)
        (root / HANDOFF_DIGEST).write_text(
            f"{_sha256(root / HANDOFF_MANIFEST)}  {HANDOFF_MANIFEST}\n",
            encoding="utf-8",
        )
        if out.exists():
            raise FileExistsError(f"Outreach handoff appeared during creation: {out}")
        shutil.move(str(root), str(out))
    result = verify_outreach_handoff(out, collection_release=release)
    if not result["handoff_ready"]:
        raise ValueError("Constructed outreach handoff failed verification")
    return result


def verify_outreach_handoff(
    handoff_dir: str | Path,
    *,
    collection_release: str | Path = DEFAULT_COLLECTION_RELEASE,
    ledger_protocol: str | Path = DEFAULT_LEDGER_PROTOCOL,
) -> dict[str, Any]:
    root = _project_path(handoff_dir).resolve()
    manifest_path = root / HANDOFF_MANIFEST
    digest_path = root / HANDOFF_DIGEST
    if not manifest_path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("Outreach handoff manifest or digest is missing")
    issues: list[str] = []
    manifest = _load_yaml(manifest_path)
    expected_manifest_fields = {
        "schema_version",
        "handoff_id",
        "collection_id",
        "created_at",
        "publication_binding",
        "artifacts",
        "state",
        "counts",
        "claim_boundaries",
    }
    if set(manifest) != expected_manifest_fields:
        issues.append("Outreach handoff manifest fields drift")
    if (
        manifest.get("schema_version") != OUTREACH_SCHEMA_VERSION
        or manifest.get("collection_id") != COLLECTION_ID
    ):
        issues.append("Outreach handoff schema or collection ID drift")
    try:
        _timestamp(manifest.get("created_at"), "created_at")
        detached = digest_path.read_text(encoding="utf-8")
        if detached != f"{_sha256(manifest_path)}  {HANDOFF_MANIFEST}\n":
            raise ValueError("Outreach handoff detached digest drift")
    except ValueError as exc:
        issues.append(str(exc))
    expected_state = {
        "handoff_ready": True,
        "no_send_drafts": True,
        "messages_sent": False,
        "participation_confirmed": False,
        "returns_received": False,
    }
    expected_counts = {
        "participant_identities": 0,
        "invitation_events": 0,
        "submitted_cases": 0,
        "human_ratings": 0,
    }
    if manifest.get("state") != expected_state:
        issues.append("Outreach handoff claims a real event already occurred")
    if manifest.get("counts") != expected_counts:
        issues.append("Outreach handoff participant or evidence counts are not blank")
    if manifest.get("claim_boundaries") != OUTREACH_CLAIMS:
        issues.append("Outreach handoff claim boundaries were weakened")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACT_LAYOUT):
        issues.append("Outreach handoff artifact registry drift")
        artifacts = {}
    artifact_paths: dict[str, Path] = {}
    for key, (expected_path, expected_category) in ARTIFACT_LAYOUT.items():
        try:
            record = artifacts[key]
            if record.get("path") != expected_path or record.get("category") != expected_category:
                raise ValueError(f"Outreach artifact path or category drift: {key}")
            artifact_paths[key] = _validate_artifact(root, record)
        except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
            issues.append(str(exc))

    expected_files = {
        HANDOFF_MANIFEST,
        HANDOFF_DIGEST,
        *(relative for relative, _ in ARTIFACT_LAYOUT.values()),
    }
    actual_files = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    }
    if actual_files != expected_files or any(path.is_symlink() for path in root.rglob("*")):
        issues.append("Outreach handoff file membership or symlink policy drift")

    if len(artifact_paths) == len(ARTIFACT_LAYOUT):
        try:
            record = _load_yaml(artifact_paths["publication_record"])
            evidence = _load_yaml(artifact_paths["publication_evidence"])
            collection_plan = _load_yaml(artifact_paths["collection_plan"])
            outreach_plan = _load_yaml(artifact_paths["outreach_plan"])
            _validate_publication(
                record,
                evidence,
                expected_record_sha256=_sha256(artifact_paths["publication_record"]),
            )
            binding = manifest.get("publication_binding")
            expected_binding = {
                "immutable_identifier": record["immutable_identifier"],
                "publication_record_sha256": _sha256(artifact_paths["publication_record"]),
                "publication_evidence_sha256": _sha256(
                    artifact_paths["publication_evidence"]
                ),
                "release_page_url": evidence["release"]["url"],
            }
            if binding != expected_binding:
                raise ValueError("Outreach handoff publication binding drift")

            release = _project_path(collection_release).resolve()
            release_verification = verify_collection_release(release)
            if not release_verification.ready_for_distribution:
                raise ValueError("Outreach source collection release no longer verifies")
            local_plan = release / RELEASE_PAYLOAD_DIR / "collection_plan.yaml"
            if _sha256(local_plan) != _sha256(artifact_paths["collection_plan"]):
                raise ValueError("Outreach collection-plan binding drift")
            for key, filename in ASSET_FILENAMES.items():
                local_asset = release / filename
                item = record["assets"][key]
                if (
                    _sha256(local_asset) != item["sha256"]
                    or local_asset.stat().st_size != item["size_bytes"]
                ):
                    raise ValueError(f"Outreach release asset binding drift: {key}")
            if collection_plan.get("deadlines", {}).get("invitations_open") != OPENING_AT:
                raise ValueError("Outreach opening date drift")
            for value in collection_plan["deadlines"].values():
                _timestamp(value, "collection deadline")

            expected_plan = _outreach_plan(
                handoff_id=manifest["handoff_id"],
                created_at=manifest["created_at"],
                record=record,
                plan=collection_plan,
            )
            if outreach_plan != expected_plan:
                raise ValueError("Outreach plan semantic or deadline drift")
            if _contains_sensitive_key(outreach_plan):
                raise ValueError("Outreach plan contains a private identity or contact field")
            protocol = _project_path(ledger_protocol).resolve()
            if _sha256(protocol) != _sha256(artifact_paths["ledger_protocol"]):
                raise ValueError("Outreach private-ledger protocol binding drift")
            source_instructions = (
                release / RELEASE_PAYLOAD_DIR / "OPERATOR_INSTRUCTIONS.md"
            )
            if _sha256(source_instructions) != _sha256(
                artifact_paths["source_operator_instructions"]
            ):
                raise ValueError("Outreach source-operator protocol binding drift")
            for key in (
                "outreach_plan",
                "contributor_draft",
                "custodian_draft",
                "rater_draft",
                "operator_checklist",
                "readme",
            ):
                _validate_no_private_text(artifact_paths[key])
        except (FileNotFoundError, KeyError, OSError, TypeError, ValueError) as exc:
            issues.append(str(exc))

    ready = not issues
    return {
        "schema_version": OUTREACH_SCHEMA_VERSION,
        "status": "pass" if ready else "fail",
        "handoff_ready": ready,
        "collection_id": manifest.get("collection_id"),
        "handoff_id": manifest.get("handoff_id"),
        "manifest_sha256": _sha256(manifest_path),
        "outreach_opening_at": OPENING_AT,
        "messages_sent": False,
        "participation_confirmed": False,
        "participant_identity_count": 0,
        "invitation_event_count": 0,
        "submitted_case_count": 0,
        "human_rating_count": 0,
        "issues": list(dict.fromkeys(issues)),
    }
