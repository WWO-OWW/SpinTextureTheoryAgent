import json
from pathlib import Path

import yaml

from spintexture_agent.evidence import EvidenceCard
from spintexture_agent.expert_review import (
    REVIEW_ATTESTATION,
    generate_review_packet,
    verify_review_packet,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARD_PATH = PROJECT_ROOT / "evidence_cards/core3/A4_afm_stripe_sot.yaml"


def _fake_evidence_run(tmp_path: Path) -> Path:
    card = EvidenceCard.from_yaml(CARD_PATH)
    run_dir = tmp_path / "runs" / card.card_id
    run_dir.mkdir(parents=True)
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    script_path = generated_dir / "generated.wl"
    report_path = generated_dir / "report.md"
    record_path = generated_dir / "record.json"
    gold_result_path = tmp_path / "gold_result.json"
    script_path.write_text("Print[True];\n", encoding="utf-8")
    report_path.write_text("# Generated report\n", encoding="utf-8")
    gold_result_path.write_text("{}\n", encoding="utf-8")
    record_path.write_text(
        json.dumps(
            {
                "artifact_contract": {
                    "wolfram_script": str(script_path),
                    "human_report": str(report_path),
                    "machine_record": str(record_path),
                    "authoritative_source": "machine_record",
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result_path = run_dir / "evidence_result.json"
    checks = [
        {
            "check_id": check.check_id,
            "category": check.category,
            "comparison": check.comparison,
            "passed": True,
            "generated_key": check.generated_key,
            "gold_key": check.gold_key,
            "generated_value": "True",
            "gold_value": "True",
            "detail": "test fixture",
        }
        for check in card.checks
    ]
    result_path.write_text(
        json.dumps(
            {
                "card_id": card.card_id,
                "case_id": card.case_id,
                "route_id": card.route_id,
                "passed": True,
                "generated_execution_status": "passed",
                "gold_execution_status": "passed",
                "generated_record": str(record_path),
                "gold_result": str(gold_result_path),
                "expert_review_status": "pending",
                "checks": checks,
                "result_path": str(result_path),
                "summary_path": str(run_dir / "evidence_summary.md"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return tmp_path / "runs"


def _approve_review_form(form_path: Path) -> None:
    card = EvidenceCard.from_yaml(CARD_PATH)
    payload = yaml.safe_load(form_path.read_text(encoding="utf-8"))
    payload["reviewer"].update(
        {
            "name": "Test Reviewer",
            "affiliation": "Independent Theory Institute",
            "orcid": "0000-0000-0000-0000",
            "independence": "external",
            "qualified_for": card.expert_review.required_expertise,
        }
    )
    payload["decision"]["status"] = "approved"
    payload["decision"]["reviewed_at"] = "2026-07-20T12:00:00+08:00"
    for criterion in payload["decision"]["criteria"]:
        criterion["verdict"] = "approved"
        criterion["comment"] = "Reviewed against the frozen evidence."
    for response in payload["decision"]["open_question_responses"]:
        response["response"] = "Accepted within the declared assumptions."
    payload["signature"].update(
        {
            "signed_name": "Test Reviewer",
            "signed_at": "2026-07-20T12:05:00+08:00",
            "attestation": REVIEW_ATTESTATION,
        }
    )
    form_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def test_pending_review_packet_has_valid_integrity_but_cannot_promote(tmp_path):
    runs = _fake_evidence_run(tmp_path)
    packet = generate_review_packet(CARD_PATH, runs, tmp_path / "packet")
    verification = verify_review_packet(packet.packet_dir)

    assert verification.manifest_integrity_valid
    assert verification.all_records_integrity_valid
    assert verification.eligible_routes == []
    assert verification.reviews[0].status == "pending"
    assert verification.reviews[0].reasons == ["expert decision is pending"]


def test_complete_signed_review_is_eligible_for_expert_validation(tmp_path):
    runs = _fake_evidence_run(tmp_path)
    packet = generate_review_packet(CARD_PATH, runs, tmp_path / "packet")
    form_path = Path(packet.review_forms[0])
    _approve_review_form(form_path)

    verification = verify_review_packet(packet.packet_dir)

    assert verification.all_records_integrity_valid
    assert verification.eligible_routes == ["afm_stripe_sot_full"]
    assert verification.reviews[0].eligible_for_expert_validation
    assert verification.reviews[0].reasons == []


def test_tampered_frozen_artifact_blocks_review_promotion(tmp_path):
    runs = _fake_evidence_run(tmp_path)
    packet = generate_review_packet(CARD_PATH, runs, tmp_path / "packet")
    form_path = Path(packet.review_forms[0])
    _approve_review_form(form_path)
    generated_report = tmp_path / "generated/report.md"
    generated_report.write_text("# Tampered report\n", encoding="utf-8")

    verification = verify_review_packet(packet.packet_dir)

    assert not verification.all_records_integrity_valid
    assert verification.eligible_routes == []
    assert "frozen artifact hash mismatch: generated_human_report" in (
        verification.reviews[0].reasons
    )


def test_packet_accepts_separate_records_from_multiple_reviewers(tmp_path):
    runs = _fake_evidence_run(tmp_path)
    packet = generate_review_packet(CARD_PATH, runs, tmp_path / "packet")
    first_form = Path(packet.review_forms[0])
    second_form = first_form.with_name("A4_afm_stripe_sot_evidence_review_02.yaml")
    payload = yaml.safe_load(first_form.read_text(encoding="utf-8"))
    payload["review_id"] = "A4_afm_stripe_sot_evidence_review_02"
    second_form.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    _approve_review_form(second_form)

    verification = verify_review_packet(packet.packet_dir)

    assert len(verification.reviews) == 2
    assert {review.status for review in verification.reviews} == {"pending", "approved"}
    assert verification.eligible_routes == ["afm_stripe_sot_full"]


def test_review_packet_never_overwrites_existing_directory(tmp_path):
    runs = _fake_evidence_run(tmp_path)
    packet_dir = tmp_path / "packet"
    generate_review_packet(CARD_PATH, runs, packet_dir)

    try:
        generate_review_packet(CARD_PATH, runs, packet_dir)
    except FileExistsError as exc:
        assert "avoid overwriting reviews" in str(exc)
    else:
        raise AssertionError("review packet generation overwrote an existing directory")
