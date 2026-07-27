import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
import spintexture_agent.benchmark_materialization as materialization_module

from spintexture_agent.benchmark_authoring import (
    ReadabilityCriterionTemplate,
    ReadabilityRubricTemplate,
)
from spintexture_agent.benchmark_intake import (
    generate_freeze_preview,
    stage_authoring_packet,
)
from spintexture_agent.benchmark_materialization import (
    CUSTODIAN_MATERIALIZATION_ATTESTATION,
    MATERIALIZATION_SCHEMA_VERSION,
    SYSTEM_FREEZE_ATTESTATION,
    CanonicalGoldResult,
    CustodianCaseHandoff,
    CustodianHandoffManifest,
    CustodianSignature,
    EquivalentFormRule,
    ExecutableBenchmarkCasePayload,
    ExpectedScoringContract,
    FrozenMaterializationArtifact,
    MaterializedGoldAnswer,
    PlaintextAccessEvent,
    ReleaseManagerApproval,
    SystemFreezeRecord,
    UnsealEvent,
    create_system_freeze_package,
    generate_custodian_handoff_template,
    generate_registration_candidate,
    verify_custodian_handoff,
    verify_system_freeze_package,
)
from spintexture_agent.cli import build_parser
from spintexture_agent.schema import TheoryTask
from test_benchmark_authoring import _valid_packet as _valid_partition_packet
from test_benchmark_intake import _complete_review, _stage


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload) -> None:
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _artifact(root: Path, path: Path) -> FrozenMaterializationArtifact:
    return FrozenMaterializationArtifact(
        path=str(path.relative_to(root)),
        sha256=_sha256(path),
    )


def _approval() -> ReleaseManagerApproval:
    signed_at = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(
        timespec="seconds"
    )
    return ReleaseManagerApproval(
        manager_id="release_manager_01",
        name="Independent Release Manager",
        affiliation="Benchmark Release Office",
        signed_at=signed_at,
        attestation=SYSTEM_FREEZE_ATTESTATION,
    )


def _accepted_stage(tmp_path: Path, partition: str = "held_out_supported") -> Path:
    if partition == "held_out_supported":
        stage_dir = _stage(tmp_path)
    else:
        packet = _valid_partition_packet(tmp_path, partition="readability")
        stage_dir = tmp_path / "intake_stage"
        stage_authoring_packet(packet, stage_dir)
    _complete_review(stage_dir, "accepted")
    return stage_dir


def _freeze(tmp_path: Path, partition: str = "held_out_supported") -> Path:
    stage_dir = _accepted_stage(tmp_path, partition)
    preview_dir = tmp_path / "freeze_preview"
    generate_freeze_preview(stage_dir, preview_dir)
    system_artifact = tmp_path / "synthetic_system_release.tar.gz"
    system_artifact.write_bytes(b"synthetic frozen system release; not a real release")
    freeze_dir = tmp_path / "system_freeze"
    create_system_freeze_package(
        stage_dir,
        preview_dir,
        system_artifact,
        freeze_dir,
        _approval(),
    )
    return freeze_dir


def _handoff(
    tmp_path: Path,
    freeze_dir: Path,
    *,
    equivalence: str = "exact",
    event_before_freeze: bool = False,
    repeated_unseal: bool = False,
    developer_access: bool = False,
    post_unseal_tuning: bool = False,
    custody_complete: bool = True,
    include_readability_rubric: bool = True,
) -> Path:
    record_path = freeze_dir / "system_freeze_record.yaml"
    record = SystemFreezeRecord.model_validate(_load_yaml(record_path))
    policy = record.case_policies[0]
    freeze_time = datetime.fromisoformat(record.frozen_at)
    event_time = freeze_time + timedelta(seconds=1)
    if event_before_freeze:
        event_time = freeze_time - timedelta(seconds=1)

    handoff_dir = tmp_path / "custodian_handoff"
    executable_path = handoff_dir / "materialized" / "cases" / f"{policy.case_id}.yaml"
    gold_path = handoff_dir / "materialized" / "gold" / f"{policy.case_id}.yaml"
    executable = ExecutableBenchmarkCasePayload(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        case_id=policy.case_id,
        description="Synthetic materialized benchmark case for contract testing.",
        task=TheoryTask(
            task_name=policy.case_id,
            material="collinear_antiferromagnet",
            texture="domain_wall",
            drive="magnetic_field",
            goals=["collective_coordinate_projection"],
            assumptions=["strong_exchange_limit"],
        ),
        expected=ExpectedScoringContract(
            material_class="collinear_antiferromagnet",
            primary_order_parameter="n",
            dynamics_type="sigma_model",
            equation_type="collective_coordinate_equation",
            support_level="scaffold",
            topology_field="n",
        ),
        required_wolfram_symbols=["AFMSigmaEquation"],
        forbidden_wolfram_symbols=["Thiele target equation"],
    )
    gold = MaterializedGoldAnswer(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        case_id=policy.case_id,
        derivation_scope="Synthetic AFM wall collective-coordinate derivation.",
        canonical_result=CanonicalGoldResult(
            equation_type="collective_coordinate_equation",
            support_level="scaffold",
            equation="M Xddot + Gamma Xdot = F",
            dynamics_class="afm_sigma_model",
        ),
        required_assumptions=["strong_exchange_limit"],
        source_symbol_mapping={"X": "domain-wall position"},
        required_physics=["AFM inertia", "damping", "generalized force"],
        allowed_equivalent_forms=[
            EquivalentFormRule(
                target="terminal_equation",
                comparison=equivalence,
                accepted_forms=["M Xddot + Gamma Xdot = F"],
                rationale="Equivalent rearrangements must preserve all coefficients.",
            )
        ],
        failure_conditions=["ferromagnetic first-order dynamics"],
    )
    _write_yaml(executable_path, executable)
    _write_yaml(gold_path, gold)

    rubric_artifact = None
    if policy.primary_partition == "readability" and include_readability_rubric:
        rubric_path = (
            handoff_dir / "materialized" / "rubrics" / f"{policy.case_id}.yaml"
        )
        rubric = ReadabilityRubricTemplate(
            schema_version=MATERIALIZATION_SCHEMA_VERSION,
            case_id=policy.case_id,
            audience="experimental magnetism researcher",
            scale="1-5",
            criteria=[
                ReadabilityCriterionTemplate(
                    criterion_id="physics_fidelity",
                    prompt="Does the explanation preserve the governing equation?",
                    critical=True,
                    minimum_score=4,
                )
            ],
        )
        _write_yaml(rubric_path, rubric)
        rubric_artifact = _artifact(handoff_dir, rubric_path)

    custodian_id = "external_custodian_01"
    if policy.case_id == "R1_explanation":
        custodian_id = "external_custodian_01"
    event = UnsealEvent(
        event_id=f"{policy.case_id}_unseal_01",
        case_id=policy.case_id,
        freeze_id=record.freeze_id,
        custodian_id=custodian_id,
        occurred_at=event_time.isoformat(timespec="seconds"),
        prior_unseal_event_count=0,
        sealed_artifact_sha256s=policy.sealed_artifact_sha256s,
        authorization="post_freeze_materialization",
    )
    events = [event]
    if repeated_unseal:
        events.append(event.model_copy(update={"event_id": f"{policy.case_id}_unseal_02"}))
    case_handoff = CustodianCaseHandoff(
        case_id=policy.case_id,
        custodian_id=custodian_id,
        executable_case=_artifact(handoff_dir, executable_path),
        gold_answer=_artifact(handoff_dir, gold_path),
        readability_rubric=rubric_artifact,
        unseal_events=events,
        access_events=[
            PlaintextAccessEvent(
                event_id=f"{policy.case_id}_access_01",
                actor_id=custodian_id,
                actor_role="gold_custodian",
                accessed_at=event_time.isoformat(timespec="seconds"),
                purpose="authorized_materialization",
            )
        ],
        development_team_plaintext_access=developer_access,
        post_unseal_system_tuning=post_unseal_tuning,
        system_changed_after_freeze=False,
        scorer_changed_after_freeze=False,
        custody_complete=custody_complete,
        signature=CustodianSignature(
            signed_by=custodian_id,
            signed_at=event_time.isoformat(timespec="seconds"),
            attestation=CUSTODIAN_MATERIALIZATION_ATTESTATION,
        ),
    )
    manifest = CustodianHandoffManifest(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        handoff_id="synthetic_custodian_handoff_01",
        status="submitted",
        created_at=event_time.isoformat(timespec="seconds"),
        workspace_class="isolated_evaluation",
        system_freeze_id=record.freeze_id,
        system_freeze_record_sha256=_sha256(record_path),
        cases=[case_handoff],
    )
    _write_yaml(handoff_dir / "handoff_manifest.yaml", manifest)
    return handoff_dir


def test_system_freeze_binds_system_scorer_split_and_policy(tmp_path):
    freeze_dir = _freeze(tmp_path)
    verification = verify_system_freeze_package(freeze_dir)
    record = SystemFreezeRecord.model_validate(
        _load_yaml(freeze_dir / "system_freeze_record.yaml")
    )

    assert verification.ready_for_custodian_handoff
    assert len(verification.accepted_case_ids) == 1
    assert set(record.benchmark_partitions) == {
        "development_supported",
        "held_out_supported",
        "negative_ood",
        "candidate_extension",
        "readability",
    }
    assert record.scorer_implementation_artifacts
    assert not record.post_freeze_system_changes_allowed
    assert not record.post_freeze_scorer_changes_allowed


def test_system_freeze_is_non_overwriting(tmp_path):
    freeze_dir = _freeze(tmp_path)
    stage_dir = tmp_path / "intake_stage"
    preview_dir = tmp_path / "freeze_preview"
    system_artifact = tmp_path / "synthetic_system_release.tar.gz"

    with pytest.raises(FileExistsError, match="already exists"):
        create_system_freeze_package(
            stage_dir,
            preview_dir,
            system_artifact,
            freeze_dir,
            _approval(),
        )


def test_release_manager_cannot_be_gold_custodian(tmp_path):
    stage_dir = _accepted_stage(tmp_path)
    preview_dir = tmp_path / "freeze_preview"
    generate_freeze_preview(stage_dir, preview_dir)
    system_artifact = tmp_path / "system.tar.gz"
    system_artifact.write_bytes(b"synthetic")
    approval = _approval().model_copy(
        update={"manager_id": "external_custodian_01", "is_gold_custodian": True}
    )

    with pytest.raises(ValueError, match="not eligible"):
        create_system_freeze_package(
            stage_dir,
            preview_dir,
            system_artifact,
            tmp_path / "freeze",
            approval,
        )


def test_tampered_frozen_scorer_artifact_breaks_freeze_verification(tmp_path):
    freeze_dir = _freeze(tmp_path)
    record = SystemFreezeRecord.model_validate(
        _load_yaml(freeze_dir / "system_freeze_record.yaml")
    )
    scorer_path = freeze_dir / record.scorer_implementation_artifacts[0].path
    scorer_path.write_text("tampered scorer", encoding="utf-8")
    verification = verify_system_freeze_package(freeze_dir)

    assert not verification.ready_for_custodian_handoff
    assert any("SHA-256 mismatch" in issue for issue in verification.issues)


def test_self_consistent_preview_hash_rewrite_still_fails_policy_verification(tmp_path):
    freeze_dir = _freeze(tmp_path)
    record_path = freeze_dir / "system_freeze_record.yaml"
    record_payload = _load_yaml(record_path)
    preview_artifact = record_payload["partition_previews"]["held_out_supported"]
    preview_path = freeze_dir / preview_artifact["path"]
    preview_payload = _load_yaml(preview_path)
    preview_payload["entries"][0]["scorer"] = "changed_scorer"
    _write_yaml(preview_path, preview_payload)
    preview_artifact["sha256"] = _sha256(preview_path)

    report_artifact = record_payload["freeze_preview_report"]
    report_path = freeze_dir / report_artifact["path"]
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    report_payload["partition_previews"]["held_out_supported"]["sha256"] = _sha256(
        preview_path
    )
    report_path.write_text(
        json.dumps(report_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    report_artifact["sha256"] = _sha256(report_path)
    _write_yaml(record_path, record_payload)
    verification = verify_system_freeze_package(freeze_dir)

    assert not verification.ready_for_custodian_handoff
    assert any("preview policy drift" in issue for issue in verification.issues)


def test_valid_custodian_handoff_is_registration_candidate_ready(tmp_path):
    freeze_dir = _freeze(tmp_path)
    handoff_dir = _handoff(tmp_path, freeze_dir)
    verification = verify_custodian_handoff(freeze_dir, handoff_dir)

    assert verification.ready_for_registration_candidate
    assert len(verification.cases) == 1
    assert verification.cases[0].passed


def test_valid_readability_handoff_with_rubric_is_ready(tmp_path):
    freeze_dir = _freeze(tmp_path, partition="readability")
    handoff_dir = _handoff(tmp_path, freeze_dir)
    verification = verify_custodian_handoff(freeze_dir, handoff_dir)

    assert verification.ready_for_registration_candidate
    assert verification.cases[0].passed


def test_generated_handoff_template_is_non_overwriting_and_cannot_be_submitted(tmp_path):
    freeze_dir = _freeze(tmp_path)
    template_dir = tmp_path / "handoff_template"
    result = generate_custodian_handoff_template(freeze_dir, template_dir)
    verification = verify_custodian_handoff(freeze_dir, template_dir)

    assert Path(result.handoff_manifest).exists()
    assert (template_dir / "CUSTODIAN_GUIDE.md").exists()
    assert not verification.ready_for_registration_candidate
    assert "custodian handoff remains a template" in verification.issues
    assert any(
        "still contains template placeholders" in issue
        for issue in verification.cases[0].issues
    )
    with pytest.raises(FileExistsError, match="already exists"):
        generate_custodian_handoff_template(freeze_dir, template_dir)


@pytest.mark.parametrize(
    ("option", "expected_issue"),
    [
        ("event_before_freeze", "unsealed before system freeze"),
        ("repeated_unseal", "exactly one unseal"),
        ("developer_access", "development team had plaintext"),
        ("post_unseal_tuning", "post-unseal system tuning"),
        ("custody_complete", "custody handoff is incomplete"),
    ],
)
def test_handoff_rejects_custody_and_leakage_failures(
    tmp_path,
    option,
    expected_issue,
):
    freeze_dir = _freeze(tmp_path)
    value = False if option == "custody_complete" else True
    handoff_dir = _handoff(tmp_path, freeze_dir, **{option: value})
    verification = verify_custodian_handoff(freeze_dir, handoff_dir)

    assert not verification.ready_for_registration_candidate
    assert any(expected_issue in issue for issue in verification.cases[0].issues)


def test_handoff_rejects_equivalence_kind_not_supported_by_frozen_scorer(tmp_path):
    freeze_dir = _freeze(tmp_path)
    handoff_dir = _handoff(tmp_path, freeze_dir, equivalence="numeric_tolerance")
    verification = verify_custodian_handoff(freeze_dir, handoff_dir)

    assert not verification.ready_for_registration_candidate
    assert any(
        "does not support equivalence kinds" in issue
        for issue in verification.cases[0].issues
    )


def test_handoff_rejects_materialized_gold_hash_drift(tmp_path):
    freeze_dir = _freeze(tmp_path)
    handoff_dir = _handoff(tmp_path, freeze_dir)
    manifest = _load_yaml(handoff_dir / "handoff_manifest.yaml")
    gold_path = handoff_dir / manifest["cases"][0]["gold_answer"]["path"]
    gold_path.write_text("tampered plaintext gold", encoding="utf-8")
    verification = verify_custodian_handoff(freeze_dir, handoff_dir)

    assert not verification.ready_for_registration_candidate
    assert any(
        "SHA-256 mismatch" in issue for issue in verification.cases[0].issues
    )


def test_handoff_rejects_registered_task_fingerprint_overlap(tmp_path, monkeypatch):
    freeze_dir = _freeze(tmp_path)
    handoff_dir = _handoff(tmp_path, freeze_dir)
    record = SystemFreezeRecord.model_validate(
        _load_yaml(freeze_dir / "system_freeze_record.yaml")
    )
    real_registry = materialization_module.BenchmarkManifestRegistry

    class OverlapRegistry:
        def __init__(self, path):
            self._registry = real_registry(path)
            self.suite = self._registry.suite
            self.cases = self._registry.cases + [
                SimpleNamespace(
                    case_id="already_registered_external_case",
                    task_fingerprint=record.case_policies[0].task_fingerprint,
                )
            ]

    monkeypatch.setattr(
        materialization_module,
        "BenchmarkManifestRegistry",
        OverlapRegistry,
    )
    verification = verify_custodian_handoff(freeze_dir, handoff_dir)

    assert not verification.ready_for_registration_candidate
    assert any(
        "fingerprint overlaps" in issue for issue in verification.cases[0].issues
    )


def test_readability_handoff_requires_materialized_rubric(tmp_path):
    freeze_dir = _freeze(tmp_path, partition="readability")
    handoff_dir = _handoff(
        tmp_path,
        freeze_dir,
        include_readability_rubric=False,
    )
    verification = verify_custodian_handoff(freeze_dir, handoff_dir)

    assert not verification.ready_for_registration_candidate
    assert any(
        "lacks a materialized rubric" in issue
        for issue in verification.cases[0].issues
    )


def test_registration_candidate_is_hashed_and_never_edits_real_manifests(tmp_path):
    freeze_dir = _freeze(tmp_path)
    handoff_dir = _handoff(tmp_path, freeze_dir)
    manifest_paths = sorted((PROJECT_ROOT / "benchmark_manifests" / "v1").glob("*.yaml"))
    before = {path: _sha256(path) for path in manifest_paths}
    result = generate_registration_candidate(
        freeze_dir,
        handoff_dir,
        tmp_path / "registration_candidate",
    )
    after = {path: _sha256(path) for path in manifest_paths}
    index = _load_yaml(Path(result.candidate_index))

    assert before == after
    assert not result.real_manifests_modified
    assert index["status"] == "registration_candidate"
    assert index["automatic_registration_allowed"] is False
    assert index["real_manifests_modified"] is False
    assert index["final_registration_blockers"]
    assert Path(result.checksums).read_text(encoding="utf-8").strip()


def test_registration_candidate_is_non_overwriting(tmp_path):
    freeze_dir = _freeze(tmp_path)
    handoff_dir = _handoff(tmp_path, freeze_dir)
    out_dir = tmp_path / "registration_candidate"
    generate_registration_candidate(freeze_dir, handoff_dir, out_dir)

    with pytest.raises(FileExistsError, match="already exists"):
        generate_registration_candidate(freeze_dir, handoff_dir, out_dir)


def test_cli_registers_materialization_commands():
    parser = build_parser()
    freeze_args = parser.parse_args(
        [
            "benchmark-materialization",
            "freeze",
            "--stage",
            "s",
            "--preview",
            "p",
            "--system-artifact",
            "a",
            "--out",
            "o",
            "--manager-id",
            "m",
            "--manager-name",
            "Manager",
            "--manager-affiliation",
            "Office",
            "--signed-at",
            "2026-07-27T00:00:00+08:00",
        ]
    )
    verify_freeze_args = parser.parse_args(
        ["benchmark-materialization", "verify-freeze", "--freeze", "f"]
    )
    verify_handoff_args = parser.parse_args(
        [
            "benchmark-materialization",
            "verify-handoff",
            "--freeze",
            "f",
            "--handoff",
            "h",
        ]
    )
    candidate_args = parser.parse_args(
        [
            "benchmark-materialization",
            "registration-candidate",
            "--freeze",
            "f",
            "--handoff",
            "h",
            "--out",
            "o",
        ]
    )

    assert freeze_args.func.__name__ == "cmd_benchmark_materialization_freeze"
    assert verify_freeze_args.func.__name__ == "cmd_benchmark_materialization_verify_freeze"
    handoff_template_args = parser.parse_args(
        [
            "benchmark-materialization",
            "handoff-template",
            "--freeze",
            "f",
            "--out",
            "o",
        ]
    )
    assert (
        handoff_template_args.func.__name__
        == "cmd_benchmark_materialization_handoff_template"
    )
    assert verify_handoff_args.func.__name__ == "cmd_benchmark_materialization_verify_handoff"
    assert (
        candidate_args.func.__name__
        == "cmd_benchmark_materialization_registration_candidate"
    )
