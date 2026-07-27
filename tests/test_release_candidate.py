import hashlib
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import spintexture_agent.release_candidate as release_candidate
from spintexture_agent.cli import build_parser
from spintexture_agent.release_candidate import (
    MANIFEST_DIGEST_FILE,
    MANIFEST_FILE,
    ReleaseCandidateManifest,
    VerificationCommandResult,
    WolframKernelSnapshot,
    create_release_candidate,
    verify_release_candidate,
)


TIMESTAMP = "2026-07-27T18:00:00+08:00"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _reseal(candidate: Path, payload: dict) -> None:
    manifest = candidate / MANIFEST_FILE
    _write_yaml(manifest, payload)
    (candidate / MANIFEST_DIGEST_FILE).write_text(
        f"{_sha256(manifest)}  {MANIFEST_FILE}\n", encoding="utf-8"
    )


@pytest.fixture
def mocked_release_commands(monkeypatch):
    outputs = {
        "pytest_full": "230 passed in 1.00s\n",
        "ruff": "All checks passed!\n",
        "pip_check": "No broken requirements found.\n",
    }

    def fake_run(check_id, command, candidate_root, timeout_seconds):
        del timeout_seconds
        log_dir = candidate_root / "verification_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = log_dir / f"{check_id}_stdout.txt"
        stderr = log_dir / f"{check_id}_stderr.txt"
        stdout.write_text(outputs[check_id], encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return VerificationCommandResult(
            check_id=check_id,
            command=command,
            status="passed",
            exit_code=0,
            duration_seconds=1.0,
            stdout=release_candidate._candidate_artifact(
                candidate_root, stdout, "verification_log"
            ),
            stderr=release_candidate._candidate_artifact(
                candidate_root, stderr, "verification_log"
            ),
        )

    def fake_wolfram(candidate_root, timeout_seconds):
        del timeout_seconds
        log_dir = candidate_root / "verification_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = log_dir / "wolfram_metadata_stdout.txt"
        stderr = log_dir / "wolfram_metadata_stderr.txt"
        stdout.write_text(
            "STTA_WOLFRAM_METADATA_BEGIN\n14.3 for Mac OS X ARM (64-bit)\n"
            "MacOSX-ARM64\nSTTA_WOLFRAM_METADATA_END\n",
            encoding="utf-8",
        )
        stderr.write_text("", encoding="utf-8")
        return WolframKernelSnapshot(
            status="passed",
            executable="/Applications/Wolfram.app/Contents/MacOS/WolframKernel",
            command=["WolframKernel", "-noprompt", "-run", "metadata"],
            version="14.3 for Mac OS X ARM (64-bit)",
            system_id="MacOSX-ARM64",
            exit_code=0,
            duration_seconds=1.0,
            stdout=release_candidate._candidate_artifact(
                candidate_root, stdout, "wolfram_metadata"
            ),
            stderr=release_candidate._candidate_artifact(
                candidate_root, stderr, "wolfram_metadata"
            ),
        )

    monkeypatch.setattr(release_candidate, "_run_verification_command", fake_run)
    monkeypatch.setattr(release_candidate, "_probe_wolfram_kernel", fake_wolfram)


@pytest.fixture
def candidate_dir(tmp_path, mocked_release_commands):
    path = tmp_path / "project1_rc_test"
    result = create_release_candidate(
        path,
        candidate_id="project1_rc_test",
        created_at=TIMESTAMP,
    )
    assert result.software_release_candidate_ready
    return path


def test_candidate_binds_all_routes_and_keeps_claim_axes_separate(candidate_dir):
    manifest = ReleaseCandidateManifest.model_validate(
        yaml.safe_load((candidate_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
    )
    result = verify_release_candidate(candidate_dir)

    assert result.status == "pass"
    assert result.software_release_candidate_ready
    assert result.eligible_for_publication_step
    assert not result.public_release_badge_registration_ready
    assert len(manifest.route_evidence) == 7
    assert all(
        set(route.evidence_status) == set(release_candidate.REQUIRED_ROUTE_AXES)
        for route in manifest.route_evidence
    )
    assert manifest.package.name == "spintexture-theory-agent"
    assert manifest.package.version == "0.1.0"
    assert manifest.benchmark_state.evidence_status == "registered"
    assert manifest.benchmark_state.held_out_case_count == 0
    assert not manifest.benchmark_state.paper_benchmark_claim_allowed
    assert manifest.external_review_state.passed_route_count == 0
    assert manifest.external_review_state.pending_route_count == 7
    assert manifest.material_applicability_state.material_complete_routes == 0
    assert manifest.material_applicability_state.material_incomplete_routes == 7
    assert not manifest.claim_boundaries.public_release_axis_mutated


def test_candidate_creation_is_non_overwriting(candidate_dir, mocked_release_commands):
    with pytest.raises(FileExistsError, match="never overwritten"):
        create_release_candidate(
            candidate_dir,
            candidate_id="project1_rc_test",
            created_at=TIMESTAMP,
        )


def test_verifier_rejects_log_hash_drift(candidate_dir):
    log = candidate_dir / "verification_logs" / "ruff_stdout.txt"
    log.write_text(log.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")

    result = verify_release_candidate(candidate_dir)

    assert result.status == "fail"
    assert not result.artifact_integrity_passed
    assert any("ruff_stdout.txt" in issue for issue in result.issues)


def test_verifier_rejects_resealed_false_command_status(candidate_dir):
    manifest_path = candidate_dir / MANIFEST_FILE
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    next(
        item for item in payload["verification_commands"] if item["check_id"] == "ruff"
    )["status"] = "failed"
    _reseal(candidate_dir, payload)

    result = verify_release_candidate(candidate_dir)

    assert result.status == "fail"
    assert not result.verification_commands_passed
    assert "verification command did not pass: ruff" in result.issues


def test_verifier_rejects_resealed_nonlicense_artifact(candidate_dir):
    manifest_path = candidate_dir / MANIFEST_FILE
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    readme = PROJECT_ROOT / "README.md"
    payload["license_artifact"] = {
        "scope": "project",
        "path": "README.md",
        "sha256": _sha256(readme),
        "size_bytes": readme.stat().st_size,
        "category": "license",
    }
    _reseal(candidate_dir, payload)

    result = verify_release_candidate(candidate_dir)

    assert result.status == "fail"
    assert not result.documentation_license_passed
    assert any("LICENSE" in issue for issue in result.issues)


def test_verifier_rejects_route_evidence_path_swap(candidate_dir):
    manifest_path = candidate_dir / MANIFEST_FILE
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    first, second = payload["route_evidence"][:2]
    first["cas_execution_records"], second["cas_execution_records"] = (
        second["cas_execution_records"],
        first["cas_execution_records"],
    )
    _reseal(candidate_dir, payload)

    result = verify_release_candidate(candidate_dir)

    assert result.status == "fail"
    assert not result.route_evidence_passed
    assert any("route evidence path drift" in issue for issue in result.issues)


def test_claim_boundaries_cannot_be_weakened_even_with_new_digest(candidate_dir):
    manifest_path = candidate_dir / MANIFEST_FILE
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    payload["claim_boundaries"]["paper_benchmark_result_claimed"] = True
    _reseal(candidate_dir, payload)

    with pytest.raises(ValidationError):
        verify_release_candidate(candidate_dir)


def test_detached_manifest_digest_drift_fails(candidate_dir):
    manifest = candidate_dir / MANIFEST_FILE
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    result = verify_release_candidate(candidate_dir)

    assert result.status == "fail"
    assert "detached release-candidate manifest SHA-256 mismatch" in result.issues


def test_release_candidate_cli_defaults_are_fail_closed():
    parser = build_parser()
    create_args = parser.parse_args(["release-candidate", "create"])
    verify_args = parser.parse_args(
        ["release-candidate", "verify", "--candidate", "candidate"]
    )

    assert create_args.candidate_id == "project1_v0.1.0_rc01"
    assert create_args.pytest_timeout == 1800
    assert create_args.require_ready is False
    assert verify_args.require_ready is False
