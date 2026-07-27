import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import spintexture_agent.distribution_bundle as distribution
import spintexture_agent.release_candidate as release_candidate
from spintexture_agent.cli import build_parser
from spintexture_agent.distribution_bundle import (
    CHECKSUMS_FILE,
    MANIFEST_DIGEST_FILE,
    MANIFEST_FILE,
    DistributionClaimBoundaries,
    DistributionCommandResult,
    DistributionManifest,
    FrozenBundleArtifact,
    create_distribution_bundle,
    verify_distribution_bundle,
)
from spintexture_agent.release_candidate import (
    VerificationCommandResult,
    WolframKernelSnapshot,
    create_release_candidate,
)


TIMESTAMP = "2026-07-27T20:00:00+08:00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _reseal(bundle: Path, payload: dict) -> None:
    manifest = bundle / MANIFEST_FILE
    _write_yaml(manifest, payload)
    (bundle / MANIFEST_DIGEST_FILE).write_text(
        f"{_sha256(manifest)}  {MANIFEST_FILE}\n", encoding="utf-8"
    )


def _fake_dependency_wheel(path: Path, name: str, version: str = "99.0") -> None:
    token = name.replace("-", "_")
    dist_info = f"{token}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")


@pytest.fixture(scope="module")
def distribution_bundle():
    analysis_root = distribution.PROJECT_ROOT / "analysis"
    analysis_root.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=".distribution-gate-test-", dir=analysis_root))
    candidate = root / "project1_rc_test"
    bundle = root / "project1_distribution_test"
    patcher = pytest.MonkeyPatch()

    release_outputs = {
        "pytest_full": "250 passed in 1.00s\n",
        "ruff": "All checks passed!\n",
        "pip_check": "No broken requirements found.\n",
    }

    def fake_release_command(check_id, command, candidate_root, timeout_seconds):
        del timeout_seconds
        log_dir = candidate_root / "verification_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = log_dir / f"{check_id}_stdout.txt"
        stderr = log_dir / f"{check_id}_stderr.txt"
        stdout.write_text(release_outputs[check_id], encoding="utf-8")
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

    def fake_release_wolfram(candidate_root, timeout_seconds):
        del timeout_seconds
        log_dir = candidate_root / "verification_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = log_dir / "wolfram_metadata_stdout.txt"
        stderr = log_dir / "wolfram_metadata_stderr.txt"
        stdout.write_text(
            "STTA_WOLFRAM_METADATA_BEGIN\n14.2\nMacOSX-x86-64\n"
            "STTA_WOLFRAM_METADATA_END\n",
            encoding="utf-8",
        )
        stderr.write_text("", encoding="utf-8")
        return WolframKernelSnapshot(
            status="passed",
            executable="WolframKernel",
            command=["WolframKernel", "-noprompt", "-run", "metadata"],
            version="14.2",
            system_id="MacOSX-x86-64",
            exit_code=0,
            duration_seconds=1.0,
            stdout=release_candidate._candidate_artifact(
                candidate_root, stdout, "wolfram_metadata"
            ),
            stderr=release_candidate._candidate_artifact(
                candidate_root, stderr, "wolfram_metadata"
            ),
        )

    patcher.setattr(release_candidate, "_run_verification_command", fake_release_command)
    patcher.setattr(release_candidate, "_probe_wolfram_kernel", fake_release_wolfram)
    candidate_result = create_release_candidate(
        candidate,
        candidate_id="project1_rc_distribution_test",
        created_at=TIMESTAMP,
    )
    assert candidate_result.software_release_candidate_ready

    original_run = distribution._run_logged_command

    def fake_distribution_command(
        bundle_root,
        check_id,
        command_contract,
        actual_command,
        *,
        cwd,
        timeout_seconds,
        environment=None,
    ):
        if check_id in {"build_sdist", "build_wheel"}:
            return original_run(
                bundle_root,
                check_id,
                command_contract,
                actual_command,
                cwd=cwd,
                timeout_seconds=timeout_seconds,
                environment=environment,
            )
        if check_id == "dependency_download":
            destination = Path(actual_command[actual_command.index("--dest") + 1])
            for name in ("pyyaml", "pydantic", "rich", "jinja2"):
                _fake_dependency_wheel(destination / f"{name}-99.0-py3-none-any.whl", name)
        if check_id == "venv_create":
            Path(actual_command[-1]).mkdir(parents=True)
        markers = {
            "import_smoke": "STTA_RESOURCE_SMOKE_OK\n",
            "validate_smoke": "Validation passed.\n",
            "plan_smoke": "Plan for afm_stripe_sot\n",
            "wolfram_load": "STTA_WOLFRAM_LOAD_OK\n",
        }
        logs = bundle_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stdout = logs / f"{check_id}_stdout.txt"
        stderr = logs / f"{check_id}_stderr.txt"
        stdout.write_text(markers.get(check_id, "test command passed\n"), encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return DistributionCommandResult(
            check_id=check_id,
            command_contract=command_contract,
            status="passed",
            exit_code=0,
            duration_seconds=1.0,
            stdout=distribution._bundle_artifact(bundle_root, stdout, "command_log"),
            stderr=distribution._bundle_artifact(bundle_root, stderr, "command_log"),
        )

    patcher.setattr(distribution, "_run_logged_command", fake_distribution_command)
    patcher.setattr(distribution, "_wolfram_kernel_path", lambda: Path("WolframKernel"))
    result = create_distribution_bundle(
        candidate,
        bundle,
        bundle_id="project1_distribution_test",
        created_at=TIMESTAMP,
    )
    assert result.distribution_ready
    patcher.undo()
    try:
        yield bundle
    finally:
        shutil.rmtree(root)


def test_distribution_bundle_passes_and_keeps_claims_separate(distribution_bundle):
    result = verify_distribution_bundle(distribution_bundle)
    manifest = DistributionManifest.model_validate(
        yaml.safe_load((distribution_bundle / MANIFEST_FILE).read_text(encoding="utf-8"))
    )

    assert result.status == "pass"
    assert result.distribution_ready
    assert result.source_reconstruction_passed
    assert result.package_contents_passed
    assert result.clean_install_passed
    assert result.wolfram_load_passed
    assert not result.public_release_badge_registration_ready
    assert manifest.claim_boundaries == DistributionClaimBoundaries()
    assert {wheel.name for wheel in manifest.dependencies.wheels} == {
        "pyyaml",
        "pydantic",
        "rich",
        "jinja2",
    }


def test_wheel_contains_runtime_resources_but_not_gold_scripts(distribution_bundle):
    payload = yaml.safe_load((distribution_bundle / MANIFEST_FILE).read_text(encoding="utf-8"))
    wheel = distribution_bundle / payload["package"]["wheel"]["path"]

    assert distribution._inspect_wheel(wheel, "spintexture-theory-agent", "0.1.0") == []
    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
    assert set(distribution.REQUIRED_WHEEL_RESOURCES).issubset(members)
    assert not any(item.startswith("spintexture_agent/mathematica/gold/") for item in members)


def test_normalized_source_archive_is_byte_reconstructable(distribution_bundle, tmp_path):
    manifest = DistributionManifest.model_validate(
        yaml.safe_load((distribution_bundle / MANIFEST_FILE).read_text(encoding="utf-8"))
    )
    rebuilt = tmp_path / "rebuilt.tar.gz"
    distribution._write_normalized_source_archive(
        rebuilt,
        manifest.package.source_members,
        manifest.package.name,
        manifest.package.version,
    )

    frozen = distribution_bundle / manifest.package.normalized_source_archive.path
    assert rebuilt.read_bytes() == frozen.read_bytes()


def test_distribution_creation_is_non_overwriting(distribution_bundle):
    with pytest.raises(FileExistsError, match="never overwritten"):
        create_distribution_bundle(
            "analysis/release_candidates/not_used",
            distribution_bundle,
            bundle_id="duplicate",
        )


def test_verifier_rejects_artifact_hash_drift(distribution_bundle, tmp_path):
    copied = tmp_path / "tampered"
    Path(copied).mkdir()
    for source in distribution_bundle.rglob("*"):
        target = copied / source.relative_to(distribution_bundle)
        if source.is_dir():
            target.mkdir(exist_ok=True)
        else:
            target.write_bytes(source.read_bytes())
    manifest = yaml.safe_load((copied / MANIFEST_FILE).read_text(encoding="utf-8"))
    wheel = copied / manifest["package"]["wheel"]["path"]
    wheel.write_bytes(wheel.read_bytes() + b"tamper")

    result = verify_distribution_bundle(copied)

    assert result.status == "fail"
    assert not result.artifact_integrity_passed


def test_verifier_rejects_resealed_false_command(distribution_bundle, tmp_path):
    copied = tmp_path / "false-command"
    Path(copied).mkdir()
    for source in distribution_bundle.rglob("*"):
        target = copied / source.relative_to(distribution_bundle)
        if source.is_dir():
            target.mkdir(exist_ok=True)
        else:
            target.write_bytes(source.read_bytes())
    payload = yaml.safe_load((copied / MANIFEST_FILE).read_text(encoding="utf-8"))
    next(item for item in payload["commands"] if item["check_id"] == "validate_smoke")[
        "status"
    ] = "failed"
    _reseal(copied, payload)

    result = verify_distribution_bundle(copied)

    assert result.status == "fail"
    assert not result.clean_install_passed
    assert "distribution command did not pass: validate_smoke" in result.issues


def test_verifier_rejects_resealed_command_contract_drift(distribution_bundle, tmp_path):
    copied = tmp_path / "command-drift"
    Path(copied).mkdir()
    for source in distribution_bundle.rglob("*"):
        target = copied / source.relative_to(distribution_bundle)
        if source.is_dir():
            target.mkdir(exist_ok=True)
        else:
            target.write_bytes(source.read_bytes())
    payload = yaml.safe_load((copied / MANIFEST_FILE).read_text(encoding="utf-8"))
    next(item for item in payload["commands"] if item["check_id"] == "clean_install")[
        "command_contract"
    ].remove("--no-index")
    _reseal(copied, payload)

    result = verify_distribution_bundle(copied)

    assert result.status == "fail"
    assert not result.clean_install_passed


def test_claim_boundaries_cannot_be_weakened():
    with pytest.raises(ValidationError):
        DistributionClaimBoundaries(public_release_axis_mutated=True)


def test_artifact_paths_cannot_escape_bundle():
    with pytest.raises(ValidationError):
        FrozenBundleArtifact(
            path="../outside",
            sha256="0" * 64,
            size_bytes=0,
            category="test",
        )


def test_distribution_cli_defaults_are_fail_closed():
    parser = build_parser()
    create_args = parser.parse_args(["distribution-bundle", "create"])
    verify_args = parser.parse_args(
        ["distribution-bundle", "verify", "--bundle", "bundle"]
    )

    assert create_args.bundle_id == distribution.DEFAULT_BUNDLE_ID
    assert create_args.release_candidate.endswith("project1_v0.1.0_rc04")
    assert create_args.require_ready is False
    assert verify_args.require_ready is False


def test_checksum_file_does_not_self_hash(distribution_bundle):
    lines = (distribution_bundle / CHECKSUMS_FILE).read_text(encoding="utf-8")
    assert CHECKSUMS_FILE not in lines
