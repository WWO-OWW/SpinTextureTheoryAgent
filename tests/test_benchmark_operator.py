import hashlib
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from spintexture_agent.benchmark_operator import (
    DEFAULT_PUBLICATION_EVIDENCE,
    DEFAULT_PUBLICATION_RECORD,
    OperatorEventRequest,
    initialize_private_ledger,
    plan_or_record_event,
    verify_private_ledger,
    verify_publication_gate,
)
from spintexture_agent.cli import build_parser


INIT_AT = "2026-07-27T21:50:00+08:00"
INIT_NOW = "2026-07-27T22:00:00+08:00"
OPEN_AT = "2026-08-03T10:00:00+08:00"
OPEN_NOW = "2026-08-03T10:05:00+08:00"
OPERATOR_ID = "op_round01test"
LEDGER_ID = "round01_test_ledger"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, payload: dict) -> Path:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return path


def _confirmations() -> dict:
    return {
        "real_world_event_occurred": True,
        "identity_checked_by_operator": True,
        "private_contact_kept_out_of_repository": True,
        "tool_did_not_send_message": True,
    }


def _contributor() -> dict:
    return {
        "private_participant_id": "priv_contributor_01",
        "public_participant_id": "p_a1b2c3d4e5f6",
        "role": "contributor",
        "name": "Synthetic Author",
        "affiliation": "Example Laboratory",
        "contact": "synthetic.author@example.test",
        "independent_of_project_development": True,
        "conflicts_disclosed": [],
    }


def _custodian() -> dict:
    return {
        "private_participant_id": "priv_custodian_01",
        "public_participant_id": "p_f6e5d4c3b2a1",
        "role": "custodian",
        "name": "Synthetic Custodian",
        "affiliation": "Independent Example Institute",
        "contact": "custodian@example.test",
        "independent_of_project_development": True,
        "conflicts_disclosed": [],
    }


def _invitation_payload(
    *,
    event_id: str = "event_invite_001",
    effective_at: str = OPEN_AT,
    recorded_at: str = OPEN_AT,
    participant: dict | None = None,
) -> dict:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_type": "invitation_sent",
        "invitation_id": "invite_001",
        "operator_id": OPERATOR_ID,
        "effective_at": effective_at,
        "recorded_at": recorded_at,
        "target_partition": "held_out_supported",
        "target_route_id": "afm_stripe_sot_full",
        "participant": participant or _contributor(),
        "confirmations": _confirmations(),
    }


def _state_payload(
    event_type: str,
    *,
    event_id: str,
    effective_at: str,
) -> dict:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_type": event_type,
        "invitation_id": "invite_001",
        "operator_id": OPERATOR_ID,
        "effective_at": effective_at,
        "recorded_at": effective_at,
        "confirmations": _confirmations(),
    }


def _initialize(tmp_path: Path) -> Path:
    ledger = tmp_path / "private_operator_ledger"
    preview = initialize_private_ledger(
        ledger,
        ledger_id=LEDGER_ID,
        operator_id=OPERATOR_ID,
        created_at=INIT_AT,
        current_time=INIT_NOW,
    )
    assert not ledger.exists()
    committed = initialize_private_ledger(
        ledger,
        ledger_id=LEDGER_ID,
        operator_id=OPERATOR_ID,
        created_at=INIT_AT,
        commit=True,
        preview_sha256=preview["preview_sha256"],
        current_time=INIT_NOW,
    )
    assert committed["write_performed"]
    return ledger


def _record(
    ledger: Path,
    tmp_path: Path,
    payload: dict,
    *,
    current_time: str,
) -> dict:
    request = _write_yaml(tmp_path / f"{payload['event_id']}.yaml", payload)
    preview = plan_or_record_event(
        ledger,
        request,
        current_time=current_time,
    )
    assert not preview["write_performed"]
    return plan_or_record_event(
        ledger,
        request,
        commit=True,
        preview_sha256=preview["preview_sha256"],
        confirm_real_event=True,
        current_time=current_time,
    )


def test_publication_gate_requires_verified_blank_launch_evidence():
    result = verify_publication_gate()

    assert result["publication_gate_passed"]
    assert result["eligible_for_private_ledger_initialization"]
    assert result["participant_identity_count"] == 0
    assert result["submitted_case_count"] == 0
    assert result["human_rating_count"] == 0


def test_initialization_preview_is_non_writing_and_commit_requires_exact_preview(tmp_path):
    ledger = tmp_path / "private_operator_ledger"
    preview = initialize_private_ledger(
        ledger,
        ledger_id=LEDGER_ID,
        operator_id=OPERATOR_ID,
        created_at=INIT_AT,
        current_time=INIT_NOW,
    )

    assert preview["status"] == "preview"
    assert not preview["write_performed"]
    assert not ledger.exists()
    with pytest.raises(ValueError, match="exact SHA-256"):
        initialize_private_ledger(
            ledger,
            ledger_id=LEDGER_ID,
            operator_id=OPERATOR_ID,
            created_at=INIT_AT,
            commit=True,
            preview_sha256="0" * 64,
            current_time=INIT_NOW,
        )
    assert not ledger.exists()


def test_initialized_ledger_is_blank_private_and_verifiable(tmp_path):
    ledger = _initialize(tmp_path)

    result = verify_private_ledger(ledger, current_time=INIT_NOW)

    assert result["ledger_valid"]
    assert result["snapshot_count"] == 1
    assert result["participant_identity_count"] == 0
    assert result["invitation_entry_count"] == 0
    assert result["submitted_case_count"] == 0
    assert result["human_rating_count"] == 0
    assert ledger.stat().st_mode & 0o777 == 0o700
    assert all(
        path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
        for path in ledger.rglob("*")
    )


def test_private_ledger_inside_repository_must_use_ignored_working_directory():
    with pytest.raises(ValueError, match="benchmark_collection_working"):
        initialize_private_ledger(
            "analysis/private_operator_ledger",
            ledger_id=LEDGER_ID,
            operator_id=OPERATOR_ID,
            created_at=INIT_AT,
            current_time=INIT_NOW,
        )


def test_invitation_before_opening_and_future_events_are_rejected(tmp_path):
    ledger = _initialize(tmp_path)
    before_open = _write_yaml(
        tmp_path / "before_open.yaml",
        _invitation_payload(
            effective_at="2026-08-02T23:59:59+08:00",
            recorded_at="2026-08-02T23:59:59+08:00",
        ),
    )
    with pytest.raises(ValueError, match="cannot predate 2026-08-03"):
        plan_or_record_event(
            ledger,
            before_open,
            current_time="2026-08-03T00:05:00+08:00",
        )

    future = _write_yaml(
        tmp_path / "future.yaml",
        _invitation_payload(
            event_id="event_invite_future",
            effective_at="2026-08-04T10:00:00+08:00",
            recorded_at="2026-08-04T10:00:00+08:00",
        ),
    )
    with pytest.raises(ValueError, match="future-dated"):
        plan_or_record_event(ledger, future, current_time=OPEN_NOW)


def test_invitation_preview_does_not_write_and_commit_requires_confirmation(tmp_path):
    ledger = _initialize(tmp_path)
    request = _write_yaml(tmp_path / "invitation.yaml", _invitation_payload())
    preview = plan_or_record_event(ledger, request, current_time=OPEN_NOW)

    assert preview["status"] == "preview"
    assert len(list((ledger / "snapshots").iterdir())) == 1
    with pytest.raises(ValueError, match="confirm-real-event"):
        plan_or_record_event(
            ledger,
            request,
            commit=True,
            preview_sha256=preview["preview_sha256"],
            current_time=OPEN_NOW,
        )
    assert len(list((ledger / "snapshots").iterdir())) == 1


def test_valid_invitation_is_append_only_and_does_not_leak_private_contact(tmp_path):
    ledger = _initialize(tmp_path)
    result = _record(ledger, tmp_path, _invitation_payload(), current_time=OPEN_NOW)
    verification = verify_private_ledger(ledger, current_time=OPEN_NOW)

    assert result["resulting_state"] == "invited"
    assert result["participant_identity_count"] == 1
    assert result["submitted_case_count"] == 0
    assert verification["snapshot_count"] == 2
    assert verification["ledger_valid"]
    public_result = json.dumps(result)
    assert "Synthetic Author" not in public_result
    assert "synthetic.author@example.test" not in public_result


def test_duplicate_event_id_is_rejected(tmp_path):
    ledger = _initialize(tmp_path)
    payload = _invitation_payload()
    _record(ledger, tmp_path, payload, current_time=OPEN_NOW)
    duplicate = _write_yaml(tmp_path / "duplicate.yaml", payload)

    with pytest.raises(ValueError, match="Event ID already exists"):
        plan_or_record_event(ledger, duplicate, current_time=OPEN_NOW)


def test_acceptance_then_withdrawal_is_valid_but_decline_after_acceptance_is_not(tmp_path):
    ledger = _initialize(tmp_path)
    _record(ledger, tmp_path, _invitation_payload(), current_time=OPEN_NOW)
    accepted_at = "2026-08-04T10:00:00+08:00"
    accepted = _record(
        ledger,
        tmp_path,
        _state_payload(
            "acceptance_received",
            event_id="event_accept_001",
            effective_at=accepted_at,
        ),
        current_time="2026-08-04T10:05:00+08:00",
    )
    assert accepted["resulting_state"] == "accepted"

    decline = _write_yaml(
        tmp_path / "decline.yaml",
        _state_payload(
            "decline_received",
            event_id="event_decline_001",
            effective_at="2026-08-05T10:00:00+08:00",
        ),
    )
    with pytest.raises(ValueError, match="Invalid transition"):
        plan_or_record_event(
            ledger,
            decline,
            current_time="2026-08-05T10:05:00+08:00",
        )

    withdrawn = _record(
        ledger,
        tmp_path,
        _state_payload(
            "withdrawal_received",
            event_id="event_withdraw_001",
            effective_at="2026-08-05T10:00:00+08:00",
        ),
        current_time="2026-08-05T10:05:00+08:00",
    )
    assert withdrawn["resulting_state"] == "withdrawn"


def test_return_requires_accepted_invitation(tmp_path):
    ledger = _initialize(tmp_path)
    _record(ledger, tmp_path, _invitation_payload(), current_time=OPEN_NOW)
    incoming = ledger / "incoming_returns"
    incoming.mkdir(mode=0o700)
    packet = incoming / "packet.zip"
    packet.write_bytes(b"synthetic sealed bytes")
    packet.chmod(0o600)
    payload = {
        **_state_payload(
            "sealed_return_received",
            event_id="event_return_001",
            effective_at="2026-08-05T10:00:00+08:00",
        ),
        "custodian": _custodian(),
        "returned_packet": {
            "path": "incoming_returns/packet.zip",
            "sha256": _sha256(packet),
            "size_bytes": packet.stat().st_size,
        },
        "submitted_case_ids": ["SYNTHETIC_CASE_001"],
    }
    request = _write_yaml(tmp_path / "return.yaml", payload)

    with pytest.raises(ValueError, match="Invalid transition"):
        plan_or_record_event(
            ledger,
            request,
            current_time="2026-08-05T10:05:00+08:00",
        )


def test_valid_return_binds_packet_cases_and_separate_custodian(tmp_path):
    ledger = _initialize(tmp_path)
    _record(ledger, tmp_path, _invitation_payload(), current_time=OPEN_NOW)
    _record(
        ledger,
        tmp_path,
        _state_payload(
            "acceptance_received",
            event_id="event_accept_001",
            effective_at="2026-08-04T10:00:00+08:00",
        ),
        current_time="2026-08-04T10:05:00+08:00",
    )
    incoming = ledger / "incoming_returns"
    incoming.mkdir(mode=0o700)
    packet = incoming / "packet.zip"
    packet.write_bytes(b"synthetic sealed bytes")
    packet.chmod(0o600)
    returned = {
        **_state_payload(
            "sealed_return_received",
            event_id="event_return_001",
            effective_at="2026-08-05T10:00:00+08:00",
        ),
        "custodian": _custodian(),
        "returned_packet": {
            "path": "incoming_returns/packet.zip",
            "sha256": _sha256(packet),
            "size_bytes": packet.stat().st_size,
        },
        "submitted_case_ids": ["SYNTHETIC_CASE_001"],
    }
    result = _record(
        ledger,
        tmp_path,
        returned,
        current_time="2026-08-05T10:05:00+08:00",
    )
    verification = verify_private_ledger(
        ledger,
        current_time="2026-08-05T10:05:00+08:00",
    )

    assert result["resulting_state"] == "returned"
    assert result["participant_identity_count"] == 2
    assert result["submitted_case_count"] == 1
    assert verification["ledger_valid"]
    assert verification["snapshot_count"] == 4


def test_return_rejects_same_custodian_and_packet_outside_incoming_returns(tmp_path):
    ledger = _initialize(tmp_path)
    _record(ledger, tmp_path, _invitation_payload(), current_time=OPEN_NOW)
    _record(
        ledger,
        tmp_path,
        _state_payload(
            "acceptance_received",
            event_id="event_accept_001",
            effective_at="2026-08-04T10:00:00+08:00",
        ),
        current_time="2026-08-04T10:05:00+08:00",
    )
    incoming = ledger / "incoming_returns"
    incoming.mkdir(mode=0o700)
    packet = incoming / "packet.zip"
    packet.write_bytes(b"synthetic sealed bytes")
    packet.chmod(0o600)
    same_person = _contributor()
    same_person["role"] = "custodian"
    payload = {
        **_state_payload(
            "sealed_return_received",
            event_id="event_return_001",
            effective_at="2026-08-05T10:00:00+08:00",
        ),
        "custodian": same_person,
        "returned_packet": {
            "path": "incoming_returns/packet.zip",
            "sha256": _sha256(packet),
            "size_bytes": packet.stat().st_size,
        },
        "submitted_case_ids": ["SYNTHETIC_CASE_001"],
    }
    request = _write_yaml(tmp_path / "return.yaml", payload)

    with pytest.raises(ValueError, match="private identities must differ"):
        plan_or_record_event(
            ledger,
            request,
            current_time="2026-08-05T10:05:00+08:00",
        )

    payload["custodian"] = _custodian()
    snapshot_artifact = next((ledger / "snapshots").glob("*/ledger_state.yaml"))
    payload["returned_packet"] = {
        "path": snapshot_artifact.relative_to(ledger).as_posix(),
        "sha256": _sha256(snapshot_artifact),
        "size_bytes": snapshot_artifact.stat().st_size,
    }
    _write_yaml(request, payload)
    with pytest.raises(ValueError, match="under incoming_returns"):
        plan_or_record_event(
            ledger,
            request,
            current_time="2026-08-05T10:05:00+08:00",
        )


def test_verifier_detects_snapshot_tampering_and_permission_drift(tmp_path):
    tampered = _initialize(tmp_path / "tampered")
    state = next((tampered / "snapshots").glob("*/ledger_state.yaml"))
    state.write_text(state.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert not verify_private_ledger(tampered, current_time=INIT_NOW)["ledger_valid"]

    permission_drift = _initialize(tmp_path / "permissions")
    checklist = permission_drift / "OPERATOR_CHECKLIST.md"
    checklist.chmod(0o644)
    result = verify_private_ledger(permission_drift, current_time=INIT_NOW)
    assert not result["ledger_valid"]
    assert any("permission drift" in issue for issue in result["issues"])


def test_publication_gate_rejects_unbound_evidence_copy(tmp_path):
    evidence = tmp_path / "publication_evidence.yaml"
    record = tmp_path / "publication_record.yaml"
    evidence.write_bytes(DEFAULT_PUBLICATION_EVIDENCE.read_bytes())
    record.write_bytes(DEFAULT_PUBLICATION_RECORD.read_bytes())

    result = verify_publication_gate(evidence, record)

    assert not result["publication_gate_passed"]


@pytest.mark.parametrize(
    "template_name",
    [
        "invitation_event_template.yaml",
        "acceptance_event_template.yaml",
        "return_event_template.yaml",
    ],
)
def test_operator_templates_cannot_be_submitted_without_real_inputs(template_name):
    payload = yaml.safe_load(
        (
            PROJECT_ROOT / "operator_templates" / "round_01" / template_name
        ).read_text(encoding="utf-8")
    )

    with pytest.raises(ValidationError):
        OperatorEventRequest.model_validate(payload)


@pytest.mark.parametrize("command", ["gate", "initialize", "record", "verify"])
def test_cli_registers_operator_ledger_commands(command):
    parser = build_parser()
    args = ["benchmark-operator-ledger", command]
    if command == "initialize":
        args += [
            "--out",
            "/tmp/example-ledger",
            "--ledger-id",
            LEDGER_ID,
            "--operator-id",
            OPERATOR_ID,
            "--created-at",
            INIT_AT,
        ]
    elif command == "record":
        args += ["--ledger", "/tmp/example-ledger", "--request", "/tmp/event.yaml"]
    elif command == "verify":
        args += ["--ledger", "/tmp/example-ledger"]

    parsed = parser.parse_args(args)

    assert callable(parsed.func)
