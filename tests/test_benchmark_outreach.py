import hashlib
from pathlib import Path

import pytest
import yaml

from spintexture_agent.benchmark_outreach import (
    ARTIFACT_LAYOUT,
    HANDOFF_DIGEST,
    HANDOFF_MANIFEST,
    OUTREACH_CLAIMS,
    OUTREACH_PLAN,
    create_outreach_handoff,
    verify_outreach_handoff,
)
from spintexture_agent.cli import build_parser


CREATED_AT = "2026-07-27T22:30:00+08:00"
CURRENT_TIME = "2026-07-27T22:31:00+08:00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _create(tmp_path: Path) -> Path:
    handoff = tmp_path / "outreach_handoff"
    result = create_outreach_handoff(
        handoff,
        created_at=CREATED_AT,
        current_time=CURRENT_TIME,
    )
    assert result["handoff_ready"]
    return handoff


def _reseal_artifact(handoff: Path, key: str) -> None:
    manifest_path = handoff / HANDOFF_MANIFEST
    manifest = _load_yaml(manifest_path)
    artifact = manifest["artifacts"][key]
    path = handoff / artifact["path"]
    artifact["sha256"] = _sha256(path)
    artifact["size_bytes"] = path.stat().st_size
    _write_yaml(manifest_path, manifest)
    (handoff / HANDOFF_DIGEST).write_text(
        f"{_sha256(manifest_path)}  {HANDOFF_MANIFEST}\n",
        encoding="utf-8",
    )


def _reseal_manifest(handoff: Path) -> None:
    manifest_path = handoff / HANDOFF_MANIFEST
    (handoff / HANDOFF_DIGEST).write_text(
        f"{_sha256(manifest_path)}  {HANDOFF_MANIFEST}\n",
        encoding="utf-8",
    )


def test_create_handoff_is_public_blank_and_verifiable(tmp_path):
    handoff = _create(tmp_path)
    result = verify_outreach_handoff(handoff)
    plan = _load_yaml(handoff / OUTREACH_PLAN)

    assert result["handoff_ready"]
    assert result["messages_sent"] is False
    assert result["participation_confirmed"] is False
    assert result["participant_identity_count"] == 0
    assert result["invitation_event_count"] == 0
    assert result["submitted_case_count"] == 0
    assert result["human_rating_count"] == 0
    assert plan["state"] == {
        "drafts_only": True,
        "messages_sent": False,
        "participation_confirmed": False,
        "returns_received": False,
        "readability_study_open": False,
    }
    assert plan["claim_boundaries"] == OUTREACH_CLAIMS


def test_handoff_has_exact_public_artifact_membership(tmp_path):
    handoff = _create(tmp_path)
    files = {
        path.relative_to(handoff).as_posix()
        for path in handoff.rglob("*")
        if path.is_file()
    }

    assert files == {
        HANDOFF_MANIFEST,
        HANDOFF_DIGEST,
        *(path for path, _ in ARTIFACT_LAYOUT.values()),
    }


def test_create_is_non_overwriting(tmp_path):
    handoff = _create(tmp_path)

    with pytest.raises(FileExistsError, match="already exists"):
        create_outreach_handoff(
            handoff,
            created_at=CREATED_AT,
            current_time=CURRENT_TIME,
        )


def test_create_rejects_future_or_prepublication_timestamp(tmp_path):
    with pytest.raises(ValueError, match="future-dated"):
        create_outreach_handoff(
            tmp_path / "future",
            created_at="2026-07-28T22:30:00+08:00",
            current_time=CURRENT_TIME,
        )
    with pytest.raises(ValueError, match="cannot predate durable publication"):
        create_outreach_handoff(
            tmp_path / "predates_publication",
            created_at="2026-07-27T20:00:00+08:00",
            current_time=CURRENT_TIME,
        )


def test_handoff_freezes_all_routes_audiences_and_deadlines(tmp_path):
    handoff = _create(tmp_path)
    plan = _load_yaml(handoff / OUTREACH_PLAN)
    routes = plan["targets"]["held_out"]["eligible_routes"]
    audiences = plan["targets"]["readability"]["audiences"]

    assert plan["outreach_opening_at"] == "2026-08-03T00:00:00+08:00"
    assert plan["targets"]["held_out"]["target_cases"] == 7
    assert len(routes) == 7
    assert all(route["held_out_target_cases"] == 1 for route in routes)
    assert plan["targets"]["readability"]["target_cases"] == 6
    assert len(audiences) == 3
    assert sum(item["target_cases"] for item in audiences) == 6
    assert all(item["minimum_independent_raters_per_case"] >= 2 for item in audiences)
    assert plan["deadlines"] == {
        "invitations_open": "2026-08-03T00:00:00+08:00",
        "acceptance_due": "2026-08-17T23:59:59+08:00",
        "sealed_submission_due": "2026-09-30T23:59:59+08:00",
        "custody_confirmation_due": "2026-10-14T23:59:59+08:00",
        "intake_review_close": "2026-10-21T23:59:59+08:00",
    }


def test_role_drafts_are_distinct_no_send_contracts_without_private_data(tmp_path):
    handoff = _create(tmp_path)
    contributor = (handoff / ARTIFACT_LAYOUT["contributor_draft"][0]).read_text()
    custodian = (handoff / ARTIFACT_LAYOUT["custodian_draft"][0]).read_text()
    rater = (handoff / ARTIFACT_LAYOUT["rater_draft"][0]).read_text()
    combined = "\n".join((contributor, custodian, rater))

    assert "case contributor" in contributor
    assert "gold custodian" in custodian
    assert "LATER NO-SEND" in rater
    assert "different person" in custodian
    assert "at least two eligible" in rater
    assert "benchmark-collection-v1-round-01" in combined
    assert not __import__("re").search(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        combined,
    )


def test_verifier_rejects_artifact_hash_drift(tmp_path):
    handoff = _create(tmp_path)
    draft = handoff / ARTIFACT_LAYOUT["contributor_draft"][0]
    draft.write_text(draft.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    result = verify_outreach_handoff(handoff)

    assert not result["handoff_ready"]
    assert any("hash or size drift" in issue for issue in result["issues"])


def test_verifier_rejects_mutable_url_after_attacker_reseals_hashes(tmp_path):
    handoff = _create(tmp_path)
    record_path = handoff / ARTIFACT_LAYOUT["publication_record"][0]
    record = _load_yaml(record_path)
    record["assets"]["archive"]["url"] = (
        "https://github.com/WWO-OWW/SpinTextureTheoryAgent/releases/latest/download/"
        "spintexture_benchmark_v1_external_collection_round_01.zip"
    )
    _write_yaml(record_path, record)
    _reseal_artifact(handoff, "publication_record")

    result = verify_outreach_handoff(handoff)

    assert not result["handoff_ready"]
    assert any("mutable or unbound release URL" in issue for issue in result["issues"])


def test_verifier_rejects_deadline_drift_after_attacker_reseals_hashes(tmp_path):
    handoff = _create(tmp_path)
    plan_path = handoff / OUTREACH_PLAN
    plan = _load_yaml(plan_path)
    plan["deadlines"]["acceptance_due"] = "2026-08-18T23:59:59+08:00"
    _write_yaml(plan_path, plan)
    _reseal_artifact(handoff, "outreach_plan")

    result = verify_outreach_handoff(handoff)

    assert not result["handoff_ready"]
    assert any("semantic or deadline drift" in issue for issue in result["issues"])


def test_verifier_rejects_private_email_after_attacker_reseals_hashes(tmp_path):
    handoff = _create(tmp_path)
    draft = handoff / ARTIFACT_LAYOUT["custodian_draft"][0]
    draft.write_text(
        draft.read_text(encoding="utf-8") + "\nRecipient: scientist@example.org\n",
        encoding="utf-8",
    )
    _reseal_artifact(handoff, "custodian_draft")

    result = verify_outreach_handoff(handoff)

    assert not result["handoff_ready"]
    assert any("contains an email address" in issue for issue in result["issues"])


def test_verifier_rejects_private_contact_field_without_email(tmp_path):
    handoff = _create(tmp_path)
    draft = handoff / ARTIFACT_LAYOUT["contributor_draft"][0]
    draft.write_text(
        draft.read_text(encoding="utf-8") + "\nRecipient: Example Person\n",
        encoding="utf-8",
    )
    _reseal_artifact(handoff, "contributor_draft")

    result = verify_outreach_handoff(handoff)

    assert not result["handoff_ready"]
    assert any("identity or contact field" in issue for issue in result["issues"])


def test_verifier_rejects_claim_that_outreach_occurred_after_reseal(tmp_path):
    handoff = _create(tmp_path)
    readme = handoff / ARTIFACT_LAYOUT["readme"][0]
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nWe have sent invitations.\n",
        encoding="utf-8",
    )
    _reseal_artifact(handoff, "readme")

    result = verify_outreach_handoff(handoff)

    assert not result["handoff_ready"]
    assert any("real event already occurred" in issue for issue in result["issues"])


def test_verifier_rejects_weakened_claim_boundary_after_manifest_reseal(tmp_path):
    handoff = _create(tmp_path)
    manifest_path = handoff / HANDOFF_MANIFEST
    manifest = _load_yaml(manifest_path)
    manifest["claim_boundaries"]["outreach_sent"] = True
    _write_yaml(manifest_path, manifest)
    _reseal_manifest(handoff)

    result = verify_outreach_handoff(handoff)

    assert not result["handoff_ready"]
    assert any("claim boundaries were weakened" in issue for issue in result["issues"])


def test_verifier_rejects_claimed_message_state_after_manifest_reseal(tmp_path):
    handoff = _create(tmp_path)
    manifest_path = handoff / HANDOFF_MANIFEST
    manifest = _load_yaml(manifest_path)
    manifest["state"]["messages_sent"] = True
    _write_yaml(manifest_path, manifest)
    _reseal_manifest(handoff)

    result = verify_outreach_handoff(handoff)

    assert not result["handoff_ready"]
    assert any("real event already occurred" in issue for issue in result["issues"])


def test_verifier_rejects_extra_file_and_symlink(tmp_path):
    handoff = _create(tmp_path)
    (handoff / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    result = verify_outreach_handoff(handoff)
    assert not result["handoff_ready"]
    assert any("membership or symlink" in issue for issue in result["issues"])

    (handoff / "unexpected.txt").unlink()
    (handoff / "draft-link").symlink_to(ARTIFACT_LAYOUT["contributor_draft"][0])
    result = verify_outreach_handoff(handoff)
    assert not result["handoff_ready"]
    assert any("membership or symlink" in issue for issue in result["issues"])


@pytest.mark.parametrize("command", ["create", "verify"])
def test_cli_registers_outreach_handoff_commands(command):
    parser = build_parser()
    args = ["benchmark-outreach-handoff", command]
    if command == "create":
        args += ["--out", "/tmp/outreach-handoff", "--created-at", CREATED_AT]
    else:
        args += ["--handoff", "/tmp/outreach-handoff"]

    parsed = parser.parse_args(args)

    assert callable(parsed.func)
