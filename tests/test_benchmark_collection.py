import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from spintexture_agent.benchmark_collection import (
    ARCHIVE_NAME,
    CHECKSUM_FILE,
    COLLECTION_ID,
    COLLECTION_SCHEMA_VERSION,
    LEDGER_STATES,
    RELEASE_INDEX_DIGEST_FILE,
    RELEASE_INDEX_FILE,
    RELEASE_PAYLOAD_DIR,
    CollectionLedgerEntry,
    CollectionReleaseIndex,
    FrozenCollectionArtifact,
    InvitationReturnLedger,
    _write_deterministic_archive,
    launch_external_collection_round,
    verify_collection_release,
)
from spintexture_agent.cli import build_parser


TIMESTAMP = "2026-07-27T12:00:00+08:00"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _artifact(payload_dir: Path, path: Path) -> FrozenCollectionArtifact:
    return FrozenCollectionArtifact(
        path=path.relative_to(payload_dir).as_posix(),
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
    )


def _reseal_release(release_dir: Path) -> None:
    payload_dir = release_dir / RELEASE_PAYLOAD_DIR
    checksum_path = payload_dir / CHECKSUM_FILE
    without_checksum = sorted(
        (
            _artifact(payload_dir, path)
            for path in payload_dir.rglob("*")
            if path.is_file() and path != checksum_path
        ),
        key=lambda item: item.path,
    )
    checksum_path.write_text(
        "".join(f"{item.sha256}  {item.path}\n" for item in without_checksum),
        encoding="utf-8",
    )
    all_artifacts = sorted(
        (
            _artifact(payload_dir, path)
            for path in payload_dir.rglob("*")
            if path.is_file()
        ),
        key=lambda item: item.path,
    )
    archive_path = release_dir / ARCHIVE_NAME
    archive_path.unlink()
    _write_deterministic_archive(payload_dir, archive_path)

    index_path = release_dir / RELEASE_INDEX_FILE
    index = CollectionReleaseIndex.model_validate(_load_yaml(index_path))
    index = index.model_copy(
        update={
            "archive": FrozenCollectionArtifact(
                path=ARCHIVE_NAME,
                sha256=_sha256(archive_path),
                size_bytes=archive_path.stat().st_size,
            ),
            "checksum_index": next(
                item for item in all_artifacts if item.path == CHECKSUM_FILE
            ),
            "payload_artifacts": all_artifacts,
        }
    )
    _write_yaml(index_path, index)
    (release_dir / RELEASE_INDEX_DIGEST_FILE).write_text(
        f"{_sha256(index_path)}  {RELEASE_INDEX_FILE}\n",
        encoding="utf-8",
    )


@pytest.fixture
def release_dir(tmp_path: Path) -> Path:
    path = tmp_path / "round_01"
    launch_external_collection_round(path, frozen_at=TIMESTAMP)
    return path


def test_launch_release_is_empty_frozen_and_distribution_ready(release_dir):
    result = verify_collection_release(release_dir)
    plan = _load_yaml(release_dir / RELEASE_PAYLOAD_DIR / "collection_plan.yaml")
    ledger = _load_yaml(
        release_dir / RELEASE_PAYLOAD_DIR / "invitation_return_ledger.yaml"
    )
    authoring = _load_yaml(
        release_dir
        / RELEASE_PAYLOAD_DIR
        / "authoring_packet"
        / "packet_manifest.yaml"
    )

    assert result.ready_for_distribution
    assert result.byte_for_byte_reconstruction
    assert result.payload_file_count == 24
    assert result.invited_identity_count == 0
    assert result.submitted_case_count == 0
    assert plan["schema_version"] == COLLECTION_SCHEMA_VERSION
    assert plan["collection_id"] == COLLECTION_ID
    assert plan["plan_status"] == "frozen"
    assert plan["invited_participant_identities"] == []
    assert plan["submitted_case_ids"] == []
    assert ledger["allowed_states"] == list(LEDGER_STATES)
    assert ledger["entries"] == []
    assert authoring["packet_status"] == "template"
    assert authoring["cases"] == []


def test_collection_plan_covers_all_full_routes_and_registered_fingerprints(release_dir):
    plan = _load_yaml(release_dir / RELEASE_PAYLOAD_DIR / "collection_plan.yaml")
    route_ids = {
        route["route_id"] for route in plan["allowed_supported_route_families"]
    }
    fingerprints = {
        item["task_fingerprint"] for item in plan["semantic_fingerprint_exclusions"]
    }
    targets = {
        item["primary_partition"]: item["target_cases"]
        for item in plan["target_quotas"]
    }

    assert len(route_ids) == 7
    assert "afm_stripe_sot_full" in route_ids
    assert "fm_skyrmion_sot_full" in route_ids
    assert "altermagnet_stripe_sot_review" not in route_ids
    assert len(fingerprints) == 11
    assert "afm_stripe_sot_wall_chain" in fingerprints
    assert "ferrimagnet_skyrmion_compensation_candidate" in fingerprints
    assert targets == {"held_out_supported": 7, "readability": 6}


def test_readability_quota_covers_three_external_audiences(release_dir):
    plan = _load_yaml(release_dir / RELEASE_PAYLOAD_DIR / "collection_plan.yaml")
    audiences = plan["readability_audience_coverage"]

    assert len(audiences) == 3
    assert sum(item["target_cases"] for item in audiences) == 6
    assert all(item["minimum_independent_raters_per_case"] >= 2 for item in audiences)


def test_launch_is_non_overwriting(release_dir):
    with pytest.raises(FileExistsError, match="never overwritten"):
        launch_external_collection_round(release_dir, frozen_at=TIMESTAMP)


def test_launch_does_not_modify_real_benchmark_manifests(tmp_path):
    manifests = sorted((PROJECT_ROOT / "benchmark_manifests" / "v1").glob("*.yaml"))
    before = {path: _sha256(path) for path in manifests}

    launch_external_collection_round(tmp_path / "fresh_release", frozen_at=TIMESTAMP)

    assert {path: _sha256(path) for path in manifests} == before


def test_two_deterministic_rebuilds_match_the_frozen_archive(release_dir, tmp_path):
    payload_dir = release_dir / RELEASE_PAYLOAD_DIR
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    _write_deterministic_archive(payload_dir, first)
    _write_deterministic_archive(payload_dir, second)

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() == (release_dir / ARCHIVE_NAME).read_bytes()


def test_verifier_rejects_payload_hash_drift(release_dir):
    plan_path = release_dir / RELEASE_PAYLOAD_DIR / "collection_plan.yaml"
    plan_path.write_text(plan_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    result = verify_collection_release(release_dir)

    assert not result.ready_for_distribution
    assert any("payload artifact hash or size drift" in issue for issue in result.issues)


def test_verifier_rejects_archive_hash_drift(release_dir):
    archive = release_dir / ARCHIVE_NAME
    archive.write_bytes(archive.read_bytes() + b"tamper")

    result = verify_collection_release(release_dir)

    assert not result.ready_for_distribution
    assert "release archive hash or size drift" in result.issues


def test_verifier_rejects_detached_index_digest_drift(release_dir):
    (release_dir / RELEASE_INDEX_DIGEST_FILE).write_text(
        f"{'0' * 64}  {RELEASE_INDEX_FILE}\n",
        encoding="utf-8",
    )

    result = verify_collection_release(release_dir)

    assert not result.ready_for_distribution
    assert "detached release-index SHA-256 mismatch" in result.issues


def test_self_consistent_route_rewrite_still_fails_frozen_capability_gate(release_dir):
    plan_path = release_dir / RELEASE_PAYLOAD_DIR / "collection_plan.yaml"
    plan = _load_yaml(plan_path)
    plan["allowed_supported_route_families"] = plan[
        "allowed_supported_route_families"
    ][1:]
    plan["target_quotas"][0]["target_cases"] = 6
    _write_yaml(plan_path, plan)
    _reseal_release(release_dir)

    result = verify_collection_release(release_dir)

    assert not result.ready_for_distribution
    assert "allowed route families drift from the frozen capability registry" in result.issues


def test_self_consistent_fingerprint_deletion_still_fails_manifest_gate(release_dir):
    plan_path = release_dir / RELEASE_PAYLOAD_DIR / "collection_plan.yaml"
    plan = _load_yaml(plan_path)
    plan["semantic_fingerprint_exclusions"] = plan[
        "semantic_fingerprint_exclusions"
    ][1:]
    _write_yaml(plan_path, plan)
    _reseal_release(release_dir)

    result = verify_collection_release(release_dir)

    assert not result.ready_for_distribution
    assert "semantic-fingerprint exclusions drift from frozen manifests" in result.issues


def test_self_consistent_authoring_case_status_rewrite_is_rejected(release_dir):
    manifest_path = (
        release_dir
        / RELEASE_PAYLOAD_DIR
        / "authoring_packet"
        / "packet_manifest.yaml"
    )
    manifest = _load_yaml(manifest_path)
    manifest["packet_status"] = "submitted"
    _write_yaml(manifest_path, manifest)
    _reseal_release(release_dir)

    result = verify_collection_release(release_dir)

    assert not result.ready_for_distribution
    assert "distributed authoring packet must remain an empty template" in result.issues


def test_launch_ledger_rejects_any_identity_or_entry():
    with pytest.raises(ValidationError, match="no identities, cases, or entries"):
        InvitationReturnLedger(
            allowed_states=list(LEDGER_STATES),
            participant_identities=[{"participant_id": "not_blank"}],
        )


@pytest.mark.parametrize(
    ("state", "fields"),
    [
        ("invited", {}),
        ("accepted", {"accepted_at": TIMESTAMP}),
        ("declined", {"declined_at": TIMESTAMP}),
        ("withdrawn", {"withdrawn_at": TIMESTAMP}),
        (
            "returned",
            {
                "accepted_at": TIMESTAMP,
                "returned_at": TIMESTAMP,
                "custodian_id": "external_custodian",
                "returned_packet": FrozenCollectionArtifact(
                    path="returned/packet.zip",
                    sha256="0" * 64,
                    size_bytes=0,
                ),
                "submitted_case_ids": ["H1_external_case"],
            },
        ),
    ],
)
def test_ledger_schema_distinguishes_all_transition_states(state, fields):
    entry = CollectionLedgerEntry(
        invitation_id="invitation_01",
        contributor_id="external_contributor",
        state=state,
        invited_at=TIMESTAMP,
        **fields,
    )

    assert entry.state == state


def test_returned_ledger_state_requires_packet_custodian_and_case_ids():
    with pytest.raises(ValidationError, match="named custodian"):
        CollectionLedgerEntry(
            invitation_id="invitation_01",
            contributor_id="external_contributor",
            state="returned",
            invited_at=TIMESTAMP,
            accepted_at=TIMESTAMP,
            returned_at=TIMESTAMP,
        )


def test_cli_registers_collection_launch_and_verify_commands():
    parser = build_parser()
    launch = parser.parse_args(["benchmark-collection", "launch"])
    verify = parser.parse_args(
        ["benchmark-collection", "verify", "--release", "round_01"]
    )

    assert launch.func.__name__ == "cmd_benchmark_collection_launch"
    assert verify.func.__name__ == "cmd_benchmark_collection_verify"
