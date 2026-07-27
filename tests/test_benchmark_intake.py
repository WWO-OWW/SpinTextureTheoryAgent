import hashlib
from pathlib import Path

import pytest
import yaml

from spintexture_agent.benchmark_authoring import (
    AUTHORING_SCHEMA_VERSION,
    CUSTODY_ATTESTATION,
    LEAKAGE_ATTESTATION,
    AuthoringCaseSubmission,
    AuthoringPacketManifest,
    GoldCustodyRecord,
    HashedPacketArtifact,
    LeakageAttestation,
    ParticipantIdentity,
    PublicCaseBrief,
    SealedEvaluationArtifact,
    SourceAuthoringRecord,
    generate_authoring_packet,
)
from spintexture_agent.benchmark_intake import (
    INTAKE_ATTESTATION,
    IntakeReviewRecord,
    generate_freeze_preview,
    stage_authoring_packet,
    verify_intake_stage,
)
from spintexture_agent.benchmark_manifest import (
    DEFAULT_BENCHMARK_MANIFEST,
    RepetitionPolicy,
)
from spintexture_agent.cli import build_parser


TIMESTAMP = "2026-07-26T14:00:00+08:00"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload) -> None:
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _valid_authoring_packet(tmp_path: Path) -> Path:
    packet_dir = tmp_path / "returned_packet"
    generate_authoring_packet(packet_dir)
    case_id = "H1_external_wall_field"
    fingerprint = "external_afm_domain_wall_field_response"
    repetition = RepetitionPolicy(
        deterministic_runs=1,
        stochastic_runs=3,
        aggregation="mean_and_confidence_interval",
    )
    public = PublicCaseBrief(
        schema_version=AUTHORING_SCHEMA_VERSION,
        case_id=case_id,
        primary_partition="held_out_supported",
        task_fingerprint=fingerprint,
        title="Independent AFM domain-wall response",
        prompt="Derive the continuum collective-coordinate response for this external task.",
        structured_input={
            "material": "collinear_antiferromagnet",
            "texture": "domain_wall",
            "drive": "magnetic_field",
        },
        target_outputs=["physics_ir", "wolfram_derivation", "validation_report"],
        allowed_tools=["python_orchestrator", "wolfram_kernel"],
        repetition_policy=repetition,
    )
    public_path = packet_dir / "returned" / "public_cases" / f"{case_id}.yaml"
    _write_yaml(public_path, public)
    source_path = packet_dir / "returned" / "source_snapshots" / f"{case_id}.txt"
    source_path.write_text(
        "Independent primary-source snapshot with target equations 8-10.\n",
        encoding="utf-8",
    )
    gold_path = packet_dir / "returned" / "sealed_gold" / f"{case_id}_gold.enc"
    gold_path.write_bytes(b"encrypted opaque gold payload for intake tests")
    author = ParticipantIdentity(
        participant_id="external_author_01",
        name="External Author",
        affiliation="External Magnetism Laboratory",
        contact="author@example.org",
        independent_of_project_development=True,
    )
    custodian = ParticipantIdentity(
        participant_id="external_custodian_01",
        name="External Custodian",
        affiliation="External Data Office",
        contact="custodian@example.org",
        independent_of_project_development=True,
    )
    case = AuthoringCaseSubmission(
        case_id=case_id,
        primary_partition="held_out_supported",
        task_fingerprint=fingerprint,
        claim_class="known_theory_derivation",
        scorer="structured_rule_scorer_v1",
        allowed_tools=public.allowed_tools,
        repetition_policy=repetition,
        public_brief=HashedPacketArtifact(
            path=str(public_path.relative_to(packet_dir)),
            sha256=_sha256(public_path),
        ),
        source_provenance=SourceAuthoringRecord(
            source_type="primary_literature",
            citation="External Author, Journal 1, 1 (2025)",
            locator="https://example.org/external-source",
            equation_locators=["Equations 8-10, page 3"],
            snapshot=HashedPacketArtifact(
                path=str(source_path.relative_to(packet_dir)),
                sha256=_sha256(source_path),
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
            signed_at=TIMESTAMP,
        ),
        sealed_artifacts=[
            SealedEvaluationArtifact(
                artifact_type="gold_answer",
                path=str(gold_path.relative_to(packet_dir)),
                sha256=_sha256(gold_path),
                protection="encrypted_archive",
                seal_state="sealed",
                mutable=False,
                opened_before_evaluation=False,
                sealed_at=TIMESTAMP,
            )
        ],
        custody=GoldCustodyRecord(
            custodian_id=custodian.participant_id,
            author_handoff_complete=True,
            author_retained_plaintext_copy=False,
            development_team_has_gold_access=False,
            disclosure_events=[],
            attestation=CUSTODY_ATTESTATION,
            signed_by=custodian.name,
            signed_at=TIMESTAMP,
        ),
    )
    manifest = AuthoringPacketManifest(
        schema_version=AUTHORING_SCHEMA_VERSION,
        packet_id="external_intake_test_packet",
        packet_status="submitted",
        created_at=TIMESTAMP,
        benchmark_manifest=str(DEFAULT_BENCHMARK_MANIFEST),
        cases=[case],
    )
    _write_yaml(packet_dir / "packet_manifest.yaml", manifest)
    return packet_dir


def _stage(tmp_path: Path) -> Path:
    packet = _valid_authoring_packet(tmp_path)
    stage_dir = tmp_path / "intake_stage"
    stage_authoring_packet(packet, stage_dir)
    return stage_dir


def _complete_review(stage_dir: Path, decision: str = "accepted") -> Path:
    review_path = next((stage_dir / "reviews").glob("*.yaml"))
    payload = _load_yaml(review_path)
    payload["decision"] = decision
    payload["reviewer"].update(
        {
            "reviewer_id": "intake_reviewer_01",
            "name": "Independent Intake Reviewer",
            "affiliation": "Benchmark Curation Office",
            "role": "benchmark_intake_reviewer",
            "involved_in_case_authorship": False,
            "has_plaintext_gold_access": False,
            "conflict_declared": False,
            "conflict_details": "",
        }
    )
    if decision == "accepted":
        payload["source_eligibility"].update(
            {
                "status": "eligible",
                "citation_resolves": True,
                "equation_locators_verified": True,
                "source_not_used_in_development": True,
                "scientifically_relevant": True,
                "gold_scope_supported_by_source": True,
                "rationale": "Source and equation scope independently verified.",
            }
        )
        payload["gates"] = {key: True for key in payload["gates"]}
        payload["decision_rationale"] = "All source, split, scorer, and custody gates passed."
    else:
        payload["source_eligibility"].update(
            {
                "status": "ineligible",
                "citation_resolves": False,
                "equation_locators_verified": True,
                "source_not_used_in_development": True,
                "scientifically_relevant": True,
                "gold_scope_supported_by_source": True,
                "rationale": "The submitted source locator cannot be resolved.",
            }
        )
        payload["gates"] = {key: True for key in payload["gates"]}
        payload["decision_rationale"] = "Rejected because source eligibility failed."
    payload["reviewed_at"] = TIMESTAMP
    payload["signature"].update(
        {
            "signed_by": "intake_reviewer_01",
            "signed_at": TIMESTAMP,
            "attestation": INTAKE_ATTESTATION,
        }
    )
    IntakeReviewRecord.model_validate(payload)
    _write_yaml(review_path, payload)
    return review_path


def test_blank_authoring_template_cannot_be_staged(tmp_path):
    packet_dir = tmp_path / "blank_packet"
    generate_authoring_packet(packet_dir)

    with pytest.raises(ValueError, match="not ready for intake"):
        stage_authoring_packet(packet_dir, tmp_path / "stage")


def test_staging_is_non_overwriting(tmp_path):
    packet = _valid_authoring_packet(tmp_path)
    stage_dir = tmp_path / "stage"
    stage_authoring_packet(packet, stage_dir)

    with pytest.raises(FileExistsError, match="never overwritten"):
        stage_authoring_packet(packet, stage_dir)


def test_valid_packet_is_snapshotted_without_opening_gold_and_starts_pending(tmp_path):
    packet = _valid_authoring_packet(tmp_path)
    original_gold = packet / "returned" / "sealed_gold" / "H1_external_wall_field_gold.enc"
    stage_dir = tmp_path / "stage"
    result = stage_authoring_packet(packet, stage_dir)
    staged_gold = (
        stage_dir
        / "packet_snapshot"
        / "returned"
        / "sealed_gold"
        / "H1_external_wall_field_gold.enc"
    )
    verification = verify_intake_stage(stage_dir)

    assert Path(result.stage_manifest).exists()
    assert (stage_dir / "authoring_verification.json").exists()
    assert staged_gold.read_bytes() == original_gold.read_bytes()
    assert _sha256(staged_gold) == _sha256(original_gold)
    assert verification.status == "pending"
    assert verification.integrity_valid
    assert verification.decision_counts["pending"] == 1
    assert not verification.freeze_preview_ready


def test_accepted_review_makes_stage_ready_for_blind_freeze_preview(tmp_path):
    stage_dir = _stage(tmp_path)
    _complete_review(stage_dir, "accepted")
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "decided"
    assert verification.decision_counts["accepted"] == 1
    assert verification.freeze_preview_ready


def test_rejected_review_is_preserved_but_cannot_freeze_without_accepted_cases(tmp_path):
    stage_dir = _stage(tmp_path)
    _complete_review(stage_dir, "rejected")
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "decided"
    assert verification.decision_counts["rejected"] == 1
    assert not verification.freeze_preview_ready


def test_rejected_review_with_unfinished_gates_remains_incomplete(tmp_path):
    stage_dir = _stage(tmp_path)
    review_path = _complete_review(stage_dir, "rejected")
    payload = _load_yaml(review_path)
    payload["gates"]["custody_intact"] = None
    _write_yaml(review_path, payload)
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "incomplete"
    assert verification.decision_counts["incomplete"] == 1
    assert any(
        "incomplete intake gates" in reason
        for reason in verification.cases[0].reasons
    )


def test_accepted_label_with_incomplete_source_gate_is_incomplete(tmp_path):
    stage_dir = _stage(tmp_path)
    review_path = _complete_review(stage_dir, "accepted")
    payload = _load_yaml(review_path)
    payload["source_eligibility"]["equation_locators_verified"] = False
    _write_yaml(review_path, payload)
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "incomplete"
    assert verification.decision_counts["incomplete"] == 1
    assert any(
        "incomplete source-eligibility checks" in reason
        for reason in verification.cases[0].reasons
    )


def test_case_author_cannot_approve_their_own_intake(tmp_path):
    stage_dir = _stage(tmp_path)
    review_path = _complete_review(stage_dir, "accepted")
    payload = _load_yaml(review_path)
    payload["reviewer"]["reviewer_id"] = "external_author_01"
    payload["signature"]["signed_by"] = "external_author_01"
    _write_yaml(review_path, payload)
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "incomplete"
    assert any(
        "cannot be the case author" in reason
        for reason in verification.cases[0].reasons
    )


def test_tampered_staged_sealed_bytes_break_integrity(tmp_path):
    stage_dir = _stage(tmp_path)
    _complete_review(stage_dir, "accepted")
    staged_gold = next((stage_dir / "packet_snapshot" / "returned" / "sealed_gold").glob("*.enc"))
    staged_gold.write_bytes(b"tampered sealed bytes")
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "incomplete"
    assert not verification.integrity_valid
    assert any("SHA-256 mismatch" in reason for reason in verification.cases[0].reasons)


def test_freeze_preview_is_preview_only_and_never_changes_real_manifests(tmp_path):
    stage_dir = _stage(tmp_path)
    _complete_review(stage_dir, "accepted")
    manifest_paths = sorted((PROJECT_ROOT / "benchmark_manifests" / "v1").glob("*.yaml"))
    before = {path: _sha256(path) for path in manifest_paths}
    report = generate_freeze_preview(stage_dir, tmp_path / "freeze_preview")
    after = {path: _sha256(path) for path in manifest_paths}

    assert report.status == "blind_split_ready"
    assert report.blind_split_freeze_ready
    assert not report.direct_manifest_registration_ready
    assert not report.real_manifests_modified
    assert report.direct_registration_blockers
    assert before == after
    preview_path = tmp_path / "freeze_preview" / "held_out_supported_preview.yaml"
    preview = _load_yaml(preview_path)
    assert preview["preview_only"] is True
    assert preview["do_not_register_directly"] is True
    assert preview["entries"][0]["registration_status"] == "blinded_staged"
    assert preview["entries"][0]["direct_registration_blockers"]


def test_pending_stage_generates_blocked_report_without_partition_previews(tmp_path):
    stage_dir = _stage(tmp_path)
    report = generate_freeze_preview(stage_dir, tmp_path / "blocked_preview")

    assert report.status == "blocked"
    assert not report.blind_split_freeze_ready
    assert report.partition_previews == {}
    assert report.blockers
    assert (tmp_path / "blocked_preview" / "freeze_preview.json").exists()


def test_scorer_registry_drift_blocks_accepted_stage(tmp_path):
    stage_dir = _stage(tmp_path)
    _complete_review(stage_dir, "accepted")
    manifest_path = stage_dir / "intake_manifest.yaml"
    payload = _load_yaml(manifest_path)
    payload["scorer_registry_version"] = "changed_scorer"
    _write_yaml(manifest_path, payload)
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "incomplete"
    assert any("scorer registry version drift" in issue for issue in verification.issues)


def test_stage_manifest_cannot_redirect_review_outside_stage(tmp_path):
    stage_dir = _stage(tmp_path)
    manifest_path = stage_dir / "intake_manifest.yaml"
    payload = _load_yaml(manifest_path)
    payload["cases"][0]["review_path"] = "../../outside_review.yaml"
    _write_yaml(manifest_path, payload)
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "incomplete"
    assert not verification.freeze_preview_ready
    assert any(
        "escapes stage directory" in reason
        for reason in verification.cases[0].reasons
    )


def test_benchmark_manifest_hash_drift_blocks_stage(tmp_path):
    stage_dir = _stage(tmp_path)
    manifest_path = stage_dir / "intake_manifest.yaml"
    payload = _load_yaml(manifest_path)
    payload["benchmark_manifest_sha256"] = "0" * 64
    _write_yaml(manifest_path, payload)
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "incomplete"
    assert any("benchmark manifest SHA-256 drift" in issue for issue in verification.issues)


def test_benchmark_partition_hash_drift_blocks_stage(tmp_path):
    stage_dir = _stage(tmp_path)
    manifest_path = stage_dir / "intake_manifest.yaml"
    payload = _load_yaml(manifest_path)
    payload["benchmark_partition_sha256"]["held_out_supported"] = "0" * 64
    _write_yaml(manifest_path, payload)
    verification = verify_intake_stage(stage_dir)

    assert verification.status == "incomplete"
    assert any(
        "benchmark partition SHA-256 drift" in issue
        for issue in verification.issues
    )


def test_cli_registers_intake_commands():
    parser = build_parser()
    stage_args = parser.parse_args(
        ["benchmark-intake", "stage", "--packet", "p", "--out", "o"]
    )
    verify_args = parser.parse_args(
        ["benchmark-intake", "verify", "--stage", "s"]
    )
    freeze_args = parser.parse_args(
        ["benchmark-intake", "freeze-preview", "--stage", "s", "--out", "o"]
    )

    assert stage_args.func.__name__ == "cmd_benchmark_intake_stage"
    assert verify_args.func.__name__ == "cmd_benchmark_intake_verify"
    assert freeze_args.func.__name__ == "cmd_benchmark_intake_freeze_preview"
