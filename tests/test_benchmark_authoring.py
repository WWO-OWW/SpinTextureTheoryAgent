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
    GoldAnswerTemplate,
    GoldCustodyRecord,
    HashedPacketArtifact,
    LeakageAttestation,
    ParticipantIdentity,
    PublicCaseBrief,
    ReadabilityRubricTemplate,
    SealedEvaluationArtifact,
    SourceAuthoringRecord,
    generate_authoring_packet,
    verify_authoring_packet,
)
from spintexture_agent.benchmark_manifest import (
    DEFAULT_BENCHMARK_MANIFEST,
    RepetitionPolicy,
)
from spintexture_agent.cli import build_parser


TIMESTAMP = "2026-07-26T12:00:00+08:00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, payload) -> None:
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _valid_packet(tmp_path: Path, partition: str = "held_out_supported") -> Path:
    packet_dir = tmp_path / "authoring_packet"
    generate_authoring_packet(packet_dir)
    case_id = "H1_external_afm_wall" if partition == "held_out_supported" else "R1_explanation"
    fingerprint = (
        "external_afm_wall_field_response"
        if partition == "held_out_supported"
        else "external_afm_explanation_readability"
    )
    repetition = RepetitionPolicy(
        deterministic_runs=1,
        stochastic_runs=3,
        aggregation="mean_and_confidence_interval",
    )
    public = PublicCaseBrief(
        schema_version=AUTHORING_SCHEMA_VERSION,
        case_id=case_id,
        primary_partition=partition,
        task_fingerprint=fingerprint,
        title="Independent AFM wall task",
        prompt="Derive the registered continuum response from the supplied physical task.",
        structured_input={
            "material": "collinear_antiferromagnet",
            "texture": "domain_wall",
            "drive": "magnetic_field",
        },
        target_outputs=(
            ["physics_ir", "wolfram_derivation"]
            if partition == "held_out_supported"
            else ["accessible_explanation"]
        ),
        audience="experimental magnetism researcher" if partition == "readability" else None,
        allowed_tools=["python_orchestrator", "wolfram_kernel"],
        repetition_policy=repetition,
    )
    public_path = packet_dir / "returned" / "public_cases" / f"{case_id}.yaml"
    _write_yaml(public_path, public)
    source_path = packet_dir / "returned" / "source_snapshots" / f"{case_id}.txt"
    source_path.write_text("Independent source snapshot, equation 12.\n", encoding="utf-8")
    gold_path = packet_dir / "returned" / "sealed_gold" / f"{case_id}_gold.enc"
    gold_path.write_bytes(b"opaque encrypted gold bytes")

    author = ParticipantIdentity(
        participant_id="external_author_01",
        name="External Case Author",
        affiliation="Independent Magnetism Group",
        contact="author@example.org",
        independent_of_project_development=True,
    )
    custodian = ParticipantIdentity(
        participant_id="external_custodian_01",
        name="External Gold Custodian",
        affiliation="Independent Data Office",
        contact="custodian@example.org",
        independent_of_project_development=True,
    )
    artifacts = [
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
    ]
    if partition == "readability":
        rubric_path = (
            packet_dir / "returned" / "sealed_gold" / f"{case_id}_rubric.enc"
        )
        rubric_path.write_bytes(b"opaque encrypted readability rubric")
        artifacts.append(
            SealedEvaluationArtifact(
                artifact_type="readability_rubric",
                path=str(rubric_path.relative_to(packet_dir)),
                sha256=_sha256(rubric_path),
                protection="encrypted_archive",
                seal_state="sealed",
                mutable=False,
                opened_before_evaluation=False,
                sealed_at=TIMESTAMP,
            )
        )

    case = AuthoringCaseSubmission(
        case_id=case_id,
        primary_partition=partition,
        task_fingerprint=fingerprint,
        claim_class=(
            "known_theory_derivation"
            if partition == "held_out_supported"
            else "accessible_explanation"
        ),
        scorer="structured_rule_scorer_v1",
        allowed_tools=public.allowed_tools,
        repetition_policy=repetition,
        public_brief=HashedPacketArtifact(
            path=str(public_path.relative_to(packet_dir)),
            sha256=_sha256(public_path),
        ),
        source_provenance=SourceAuthoringRecord(
            source_type="primary_literature",
            citation="Independent Author, Journal 1, 1 (2025)",
            locator="https://example.org/independent-source",
            equation_locators=["Equation 12, page 4"],
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
        sealed_artifacts=artifacts,
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
        packet_id="external_packet_01",
        packet_status="submitted",
        created_at=TIMESTAMP,
        benchmark_manifest=str(DEFAULT_BENCHMARK_MANIFEST),
        cases=[case],
    )
    _write_yaml(packet_dir / "packet_manifest.yaml", manifest)
    return packet_dir


def test_empty_packet_and_all_templates_are_schema_valid(tmp_path):
    packet = generate_authoring_packet(tmp_path / "packet")
    packet_dir = Path(packet.packet_dir)
    manifest = AuthoringPacketManifest.model_validate(
        _load_yaml(Path(packet.manifest_path))
    )

    assert manifest.packet_status == "template"
    assert manifest.cases == []
    assert len(packet.template_paths) == 6
    for partition in ("held_out_supported", "readability"):
        PublicCaseBrief.model_validate(
            _load_yaml(
                packet_dir / "case_author" / f"{partition}_public_case_template.yaml"
            )
        )
        AuthoringCaseSubmission.model_validate(
            _load_yaml(
                packet_dir / "case_author" / f"{partition}_registration_template.yaml"
            )
        )
    GoldAnswerTemplate.model_validate(
        _load_yaml(packet_dir / "gold_custodian" / "gold_answer_template.yaml")
    )
    ReadabilityRubricTemplate.model_validate(
        _load_yaml(packet_dir / "gold_custodian" / "readability_rubric_template.yaml")
    )

    verification = verify_authoring_packet(packet_dir)
    assert not verification.ready_for_intake
    assert verification.case_count == 0
    assert "packet contains no submitted cases" in verification.packet_issues


def test_authoring_packet_generation_is_non_overwriting(tmp_path):
    packet_dir = tmp_path / "packet"
    generate_authoring_packet(packet_dir)

    with pytest.raises(FileExistsError, match="never overwritten"):
        generate_authoring_packet(packet_dir)


@pytest.mark.parametrize("partition", ["held_out_supported", "readability"])
def test_independent_sealed_submission_is_ready_for_intake(tmp_path, partition):
    packet_dir = _valid_packet(tmp_path, partition)
    verification = verify_authoring_packet(packet_dir)

    assert verification.ready_for_intake
    assert verification.passed_cases == 1
    assert verification.cases[0].issues == []


def test_verifier_rejects_development_fingerprint_overlap(tmp_path):
    packet_dir = _valid_packet(tmp_path)
    manifest_path = packet_dir / "packet_manifest.yaml"
    payload = _load_yaml(manifest_path)
    payload["cases"][0]["task_fingerprint"] = "afm_stripe_sot_wall_chain"
    public_path = packet_dir / payload["cases"][0]["public_brief"]["path"]
    public = _load_yaml(public_path)
    public["task_fingerprint"] = "afm_stripe_sot_wall_chain"
    _write_yaml(public_path, public)
    payload["cases"][0]["public_brief"]["sha256"] = _sha256(public_path)
    _write_yaml(manifest_path, payload)

    verification = verify_authoring_packet(packet_dir)
    assert not verification.ready_for_intake
    assert "task fingerprint overlaps development-exposed data" in (
        verification.cases[0].issues
    )


def test_verifier_rejects_missing_source_snapshot(tmp_path):
    packet_dir = _valid_packet(tmp_path)
    payload = _load_yaml(packet_dir / "packet_manifest.yaml")
    source_path = packet_dir / payload["cases"][0]["source_provenance"]["snapshot"]["path"]
    source_path.unlink()

    verification = verify_authoring_packet(packet_dir)
    assert not verification.ready_for_intake
    assert any("source" in issue and "missing" in issue for issue in verification.cases[0].issues)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("mutable", True, "marked mutable"),
        ("opened_before_evaluation", True, "opened before evaluation"),
        ("seal_state", "opened", "not in sealed state"),
    ],
)
def test_verifier_rejects_unsealed_or_mutable_gold(tmp_path, field, value, message):
    packet_dir = _valid_packet(tmp_path)
    manifest_path = packet_dir / "packet_manifest.yaml"
    payload = _load_yaml(manifest_path)
    payload["cases"][0]["sealed_artifacts"][0][field] = value
    _write_yaml(manifest_path, payload)

    verification = verify_authoring_packet(packet_dir)
    assert not verification.ready_for_intake
    assert any(message in issue for issue in verification.cases[0].issues)


def test_verifier_rejects_incomplete_custody_and_leakage_attestation(tmp_path):
    packet_dir = _valid_packet(tmp_path)
    manifest_path = packet_dir / "packet_manifest.yaml"
    payload = _load_yaml(manifest_path)
    case = payload["cases"][0]
    case["custody"]["author_handoff_complete"] = False
    case["custody"]["development_team_has_gold_access"] = True
    case["leakage_attestation"]["inspected_evaluator_implementation"] = True
    _write_yaml(manifest_path, payload)

    verification = verify_authoring_packet(packet_dir)
    issues = verification.cases[0].issues
    assert not verification.ready_for_intake
    assert "gold custody handoff is incomplete" in issues
    assert "Project 1 development team has gold access" in issues
    assert "leakage attestation records access to development evidence" in issues


def test_verifier_rejects_public_brief_with_expected_answer_key(tmp_path):
    packet_dir = _valid_packet(tmp_path)
    manifest_path = packet_dir / "packet_manifest.yaml"
    payload = _load_yaml(manifest_path)
    public_path = packet_dir / payload["cases"][0]["public_brief"]["path"]
    public = _load_yaml(public_path)
    public["structured_input"]["expected_equation"] = "secret terminal equation"
    _write_yaml(public_path, public)
    payload["cases"][0]["public_brief"]["sha256"] = _sha256(public_path)
    _write_yaml(manifest_path, payload)

    verification = verify_authoring_packet(packet_dir)
    assert not verification.ready_for_intake
    assert any("leaks private evaluation keys" in issue for issue in verification.cases[0].issues)


def test_same_person_author_and_custodian_is_schema_rejected(tmp_path):
    packet_dir = _valid_packet(tmp_path)
    manifest_path = packet_dir / "packet_manifest.yaml"
    payload = _load_yaml(manifest_path)
    case = payload["cases"][0]
    case["gold_custodian"]["participant_id"] = case["case_author"]["participant_id"]
    case["custody"]["custodian_id"] = case["case_author"]["participant_id"]
    _write_yaml(manifest_path, payload)

    with pytest.raises(ValueError, match="must be different participants"):
        verify_authoring_packet(packet_dir)


def test_cli_registers_authoring_packet_and_verify_commands():
    parser = build_parser()
    packet_args = parser.parse_args(["benchmark-authoring", "packet"])
    verify_args = parser.parse_args(
        ["benchmark-authoring", "verify", "--packet", "returned_packet"]
    )

    assert packet_args.func.__name__ == "cmd_benchmark_authoring_packet"
    assert verify_args.func.__name__ == "cmd_benchmark_authoring_verify"
