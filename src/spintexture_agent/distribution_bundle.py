from __future__ import annotations

import email
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .release_candidate import (
    MANIFEST_FILE as RELEASE_MANIFEST_FILE,
    PROJECT_ROOT,
    ReleaseCandidateManifest,
    verify_release_candidate,
)
from .wolfram import KNOWN_WOLFRAM_KERNEL_PATHS


DISTRIBUTION_SCHEMA_VERSION = "1.0.0"
DEFAULT_BUNDLE_ID = "project1_v0.1.0_rc04_distribution01"
DEFAULT_BUNDLE_OUT = PROJECT_ROOT / "analysis" / "distribution_bundles" / DEFAULT_BUNDLE_ID
MANIFEST_FILE = "distribution_manifest.yaml"
MANIFEST_DIGEST_FILE = "distribution_manifest.sha256"
CHECKSUMS_FILE = "CHECKSUMS.sha256"
VERIFICATION_JSON = "distribution_verification.json"
VERIFICATION_MARKDOWN = "distribution_verification.md"
SOURCE_DATE_EPOCH = 315532800

REQUIRED_WHEEL_RESOURCES: tuple[str, ...] = (
    "spintexture_agent/templates/derivation.wl.j2",
    "spintexture_agent/templates/summary.md.j2",
    "spintexture_agent/knowledge_base/materials.yaml",
    "spintexture_agent/knowledge_base/textures.yaml",
    "spintexture_agent/knowledge_base/drives.yaml",
    "spintexture_agent/knowledge_base/hamiltonians.yaml",
    "spintexture_agent/knowledge_base/benchmarks.yaml",
    "spintexture_agent/knowledge_base/capabilities.yaml",
    "spintexture_agent/mathematica/SpinTextureTheory.wl",
)

COMMAND_IDS: tuple[str, ...] = (
    "build_sdist",
    "build_wheel",
    "dependency_download",
    "venv_create",
    "clean_install",
    "import_smoke",
    "validate_smoke",
    "plan_smoke",
    "wolfram_load",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"Distribution artifact path must be safe: {value}")
    return path


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _stored_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Path is outside the project root: {path}") from exc


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def _write_yaml(path: Path, value: BaseModel | dict[str, object]) -> None:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Distribution timestamp must include a timezone")
    return parsed


class FrozenBundleArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    category: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_path(self) -> "FrozenBundleArtifact":
        _safe_relative(self.path)
        return self


class FrozenSourceMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_path: str = Field(min_length=1)
    archive_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_paths(self) -> "FrozenSourceMember":
        _safe_relative(self.project_path)
        _safe_relative(self.archive_path)
        return self


class ReleaseCandidateBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    candidate_path: str
    manifest_path: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    software_release_candidate_ready: Literal[True] = True

    @model_validator(mode="after")
    def validate_paths(self) -> "ReleaseCandidateBinding":
        _safe_relative(self.candidate_path)
        _safe_relative(self.manifest_path)
        return self


class DistributionPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    normalized_source_archive: FrozenBundleArtifact
    wheel: FrozenBundleArtifact
    sdist: FrozenBundleArtifact
    wolfram_library: FrozenBundleArtifact
    example_config: FrozenBundleArtifact
    source_members: list[FrozenSourceMember] = Field(min_length=1)


class DependencyWheel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    requires_python: str | None = None
    artifact: FrozenBundleArtifact


class DependencyInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    declared_requirements: list[str] = Field(min_length=1)
    wheels: list[DependencyWheel] = Field(min_length=1)
    inventory_artifact: FrozenBundleArtifact


class DistributionCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str = Field(pattern=r"^[a-z0-9_]+$")
    command_contract: list[str] = Field(min_length=1)
    status: Literal["passed", "failed"]
    exit_code: int
    duration_seconds: float = Field(ge=0)
    stdout: FrozenBundleArtifact
    stderr: FrozenBundleArtifact


class DistributionClaimBoundaries(BaseModel):
    public_release_axis_mutated: Literal[False] = False
    paper_benchmark_result_claimed: Literal[False] = False
    held_out_evidence_claimed: Literal[False] = False
    external_review_claimed: Literal[False] = False
    named_material_validation_claimed: Literal[False] = False
    bundle_is_durable_publication: Literal[False] = False


class DistributionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[DISTRIBUTION_SCHEMA_VERSION] = DISTRIBUTION_SCHEMA_VERSION
    bundle_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    created_at: str
    release_candidate: ReleaseCandidateBinding
    package: DistributionPackage
    dependencies: DependencyInventory
    reproduction_guide: FrozenBundleArtifact
    checksums: FrozenBundleArtifact
    commands: list[DistributionCommandResult] = Field(min_length=len(COMMAND_IDS))
    claim_boundaries: DistributionClaimBoundaries

    @model_validator(mode="after")
    def validate_manifest(self) -> "DistributionManifest":
        _timestamp(self.created_at)
        ids = [item.check_id for item in self.commands]
        if tuple(ids) != COMMAND_IDS:
            raise ValueError("Distribution commands must use the frozen execution order")
        return self


class DistributionVerification(BaseModel):
    schema_version: Literal[DISTRIBUTION_SCHEMA_VERSION] = DISTRIBUTION_SCHEMA_VERSION
    bundle_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pass", "fail"]
    distribution_ready: bool
    eligible_for_publication_step: bool
    public_release_badge_registration_ready: Literal[False] = False
    release_candidate_binding_passed: bool
    artifact_integrity_passed: bool
    source_reconstruction_passed: bool
    package_contents_passed: bool
    dependency_inventory_passed: bool
    clean_install_passed: bool
    wolfram_load_passed: bool
    claim_boundaries_passed: bool
    issues: list[str]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


class DistributionCreation(BaseModel):
    bundle_dir: str
    manifest_path: str
    manifest_sha256: str
    verification_json: str
    verification_markdown: str
    distribution_ready: bool


def _bundle_artifact(root: Path, path: Path, category: str) -> FrozenBundleArtifact:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Distribution artifact escapes bundle root: {path}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"Distribution artifact is missing: {path}")
    return FrozenBundleArtifact(
        path=relative,
        sha256=_sha256(resolved),
        size_bytes=resolved.stat().st_size,
        category=category,
    )


def _resolve_bundle_artifact(root: Path, artifact: FrozenBundleArtifact) -> Path:
    path = (root / artifact.path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Distribution artifact escapes bundle root: {artifact.path}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Distribution artifact is missing: {artifact.path}")
    if path.stat().st_size != artifact.size_bytes or _sha256(path) != artifact.sha256:
        raise ValueError(f"Distribution artifact hash or size drift: {artifact.path}")
    return path


def _source_members(candidate: ReleaseCandidateManifest) -> list[FrozenSourceMember]:
    artifacts = [
        *candidate.source_artifacts,
        *candidate.documentation_artifacts,
        candidate.license_artifact,
    ]
    members: dict[str, FrozenSourceMember] = {}
    for artifact in artifacts:
        if artifact.scope != "project":
            raise ValueError(f"Source member is not project-scoped: {artifact.path}")
        path = _project_path(artifact.path)
        if not path.is_file() or _sha256(path) != artifact.sha256:
            raise ValueError(f"Release-candidate source member drift: {artifact.path}")
        members[artifact.path] = FrozenSourceMember(
            project_path=artifact.path,
            archive_path=artifact.path,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
        )
    return [members[key] for key in sorted(members)]


def _archive_root(name: str, version: str) -> str:
    return f"{re.sub(r'[-_.]+', '-', name).lower()}-{version}"


def _write_normalized_source_archive(
    destination: Path,
    members: list[FrozenSourceMember],
    name: str,
    version: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    root = _archive_root(name, version)
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for member in sorted(members, key=lambda item: item.archive_path):
                    source = _project_path(member.project_path)
                    if source.stat().st_size != member.size_bytes or _sha256(source) != member.sha256:
                        raise ValueError(f"Source member drift: {member.project_path}")
                    info = tarfile.TarInfo(f"{root}/{member.archive_path}")
                    info.size = member.size_bytes
                    info.mtime = 0
                    info.mode = 0o644
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with source.open("rb") as handle:
                        tar.addfile(info, handle)


def _stage_source_tree(
    destination: Path,
    members: list[FrozenSourceMember],
    name: str,
    version: str,
) -> Path:
    root = destination / _archive_root(name, version)
    for member in members:
        target = root / member.archive_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_project_path(member.project_path), target)
    return root


def _normalize_zip(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as input_zip, zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as output_zip:
        for name in sorted(input_zip.namelist()):
            if name.endswith("/"):
                continue
            data = input_zip.read(name)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            output_zip.writestr(info, data)


def _normalize_tar_gz(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source, "r:gz") as input_tar:
        files = [item for item in input_tar.getmembers() if item.isfile()]
        payloads = [(item.name, input_tar.extractfile(item).read()) for item in files]
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as tar:
                for name, data in sorted(payloads):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mtime = 0
                    info.mode = 0o644
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    tar.addfile(info, io.BytesIO(data))


def _command_contracts(
    declared_requirements: list[str], wheel_path: str
) -> dict[str, list[str]]:
    return {
        "build_sdist": [
            "<build-python>",
            "setup.py",
            "sdist",
            "--dist-dir",
            "<raw-dist>",
        ],
        "build_wheel": [
            "<build-python>",
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            "<raw-dist>",
        ],
        "dependency_download": [
            "<build-python>",
            "-m",
            "pip",
            "download",
            "--only-binary=:all:",
            "--dest",
            "<wheelhouse>",
            *declared_requirements,
        ],
        "venv_create": ["<build-python>", "-m", "venv", "<clean-venv>"],
        "clean_install": [
            "<clean-python>",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            "<wheelhouse>",
            f"<bundle>/{wheel_path}",
        ],
        "import_smoke": ["<clean-python>", "-c", "<resource-smoke>"],
        "validate_smoke": [
            "<clean-python>",
            "-m",
            "spintexture_agent.cli",
            "validate",
            "<bundle>/examples/afm_stripe_sot.yaml",
        ],
        "plan_smoke": [
            "<clean-python>",
            "-m",
            "spintexture_agent.cli",
            "plan",
            "<bundle>/examples/afm_stripe_sot.yaml",
        ],
        "wolfram_load": [
            "<wolfram-kernel>",
            "-noprompt",
            "-run",
            "<bundle-wolfram-load-smoke>",
        ],
    }


def _run_logged_command(
    root: Path,
    check_id: str,
    command_contract: list[str],
    actual_command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    environment: dict[str, str] | None = None,
) -> DistributionCommandResult:
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout_path = logs / f"{check_id}_stdout.txt"
    stderr_path = logs / f"{check_id}_stderr.txt"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            actual_command,
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
            env=environment,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stderr += f"\nTimed out after {timeout_seconds} seconds.\n"
        exit_code = 124
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return DistributionCommandResult(
        check_id=check_id,
        command_contract=command_contract,
        status="passed" if exit_code == 0 else "failed",
        exit_code=exit_code,
        duration_seconds=time.perf_counter() - started,
        stdout=_bundle_artifact(root, stdout_path, "command_log"),
        stderr=_bundle_artifact(root, stderr_path, "command_log"),
    )


def _wheel_metadata(path: Path) -> tuple[str, str, str | None]:
    with zipfile.ZipFile(path) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError(f"Wheel must contain exactly one METADATA file: {path.name}")
        message = email.message_from_bytes(archive.read(metadata_names[0]))
    name = message.get("Name")
    version = message.get("Version")
    if not name or not version:
        raise ValueError(f"Wheel metadata is missing name or version: {path.name}")
    return name, version, message.get("Requires-Python")


def _declared_requirements() -> list[str]:
    payload = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = payload.get("project", {}).get("dependencies", [])
    if not isinstance(requirements, list) or not all(isinstance(item, str) for item in requirements):
        raise ValueError("pyproject.toml project.dependencies must be a list of strings")
    return requirements


def _dependency_inventory(
    root: Path, declared: list[str], wheelhouse: Path
) -> tuple[DependencyInventory, Path]:
    wheels: list[DependencyWheel] = []
    for path in sorted(wheelhouse.glob("*.whl")):
        name, version, requires_python = _wheel_metadata(path)
        wheels.append(
            DependencyWheel(
                name=name,
                version=version,
                requires_python=requires_python,
                artifact=_bundle_artifact(root, path, "dependency_wheel"),
            )
        )
    if not wheels:
        raise ValueError("Dependency wheelhouse is empty")
    inventory_path = root / "dependency_inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "declared_requirements": declared,
                "wheels": [item.model_dump(mode="json") for item in wheels],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return (
        DependencyInventory(
            declared_requirements=declared,
            wheels=wheels,
            inventory_artifact=_bundle_artifact(root, inventory_path, "dependency_inventory"),
        ),
        inventory_path,
    )


def _wolfram_kernel_path() -> Path | None:
    resolved = shutil.which("WolframKernel")
    if resolved:
        return Path(resolved)
    for path in KNOWN_WOLFRAM_KERNEL_PATHS:
        if path.is_file():
            return path
    return None


def _command_semantics(check_id: str, stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}"
    markers = {
        "import_smoke": "STTA_RESOURCE_SMOKE_OK",
        "validate_smoke": "Validation passed.",
        "plan_smoke": "Plan for afm_stripe_sot",
        "wolfram_load": "STTA_WOLFRAM_LOAD_OK",
    }
    marker = markers.get(check_id)
    return marker in combined if marker else True


def _manifest_artifacts(manifest: DistributionManifest) -> list[FrozenBundleArtifact]:
    artifacts = [
        manifest.package.normalized_source_archive,
        manifest.package.wheel,
        manifest.package.sdist,
        manifest.package.wolfram_library,
        manifest.package.example_config,
        manifest.dependencies.inventory_artifact,
        *[item.artifact for item in manifest.dependencies.wheels],
        manifest.reproduction_guide,
        manifest.checksums,
    ]
    for command in manifest.commands:
        artifacts.extend((command.stdout, command.stderr))
    unique: dict[str, FrozenBundleArtifact] = {}
    for artifact in artifacts:
        previous = unique.get(artifact.path)
        if previous and previous != artifact:
            raise ValueError(f"Conflicting distribution artifact binding: {artifact.path}")
        unique[artifact.path] = artifact
    return [unique[key] for key in sorted(unique)]


def _write_checksums(root: Path, artifacts: list[FrozenBundleArtifact]) -> Path:
    path = root / CHECKSUMS_FILE
    lines = [
        f"{artifact.sha256}  {artifact.path}"
        for artifact in sorted(artifacts, key=lambda item: item.path)
        if artifact.path != CHECKSUMS_FILE
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_reproduction_guide(
    root: Path,
    bundle_id: str,
    candidate: ReleaseCandidateBinding,
    package: DistributionPackage,
) -> Path:
    path = root / "REPRODUCE.md"
    path.write_text(
        "\n".join(
            [
                f"# {bundle_id}",
                "",
                f"Frozen from `{candidate.candidate_id}` manifest `{candidate.manifest_sha256}`.",
                "",
                "## Verify",
                "",
                "```bash",
                "python -m spintexture_agent.cli distribution-bundle verify \\",
                "  --bundle <bundle-directory> --require-ready",
                "```",
                "",
                "## Offline install",
                "",
                "```bash",
                "python -m venv .venv-reproduction",
                (
                    ".venv-reproduction/bin/python -m pip install --no-index "
                    f"--find-links wheelhouse {package.wheel.path}"
                ),
                "```",
                "",
                "The bundled dependency wheels are platform-specific. The normalized source",
                "archive and sdist are provided for source inspection and rebuilds.",
                "This bundle is not a durable public publication and does not change",
                "benchmark, external-review, or named-material evidence states.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_verification_reports(root: Path, result: DistributionVerification) -> None:
    (root / VERIFICATION_JSON).write_text(result.to_json() + "\n", encoding="utf-8")
    lines = [
        "# Project 1 distribution verification",
        "",
        f"- Bundle: `{result.bundle_id}`",
        f"- Status: `{result.status}`",
        f"- Distribution ready: `{str(result.distribution_ready).lower()}`",
        "- Public-release badge registration ready: `false`",
        "- Paper benchmark result claimed: `false`",
        "- External review claimed: `false`",
        "- Named-material validation claimed: `false`",
        "",
        "## Issues",
        "",
    ]
    lines.extend(f"- {issue}" for issue in result.issues)
    if not result.issues:
        lines.append("- None")
    (root / VERIFICATION_MARKDOWN).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _inspect_wheel(path: Path, name: str, version: str) -> list[str]:
    issues: list[str] = []
    try:
        wheel_name, wheel_version, _ = _wheel_metadata(path)
        if wheel_name != name or wheel_version != version:
            issues.append("wheel metadata name or version drift")
        with zipfile.ZipFile(path) as archive:
            members = set(archive.namelist())
        missing = sorted(set(REQUIRED_WHEEL_RESOURCES) - members)
        if missing:
            issues.append("wheel runtime resources missing: " + ", ".join(missing))
        if any(member.startswith("spintexture_agent/mathematica/gold/") for member in members):
            issues.append("wheel contains non-runtime Wolfram gold scripts")
        if not any(member.endswith(".dist-info/entry_points.txt") for member in members):
            issues.append("wheel console entry point is missing")
    except (ValueError, zipfile.BadZipFile) as exc:
        issues.append(f"wheel inspection failed: {exc}")
    return issues


def _inspect_sdist(path: Path, name: str, version: str) -> list[str]:
    issues: list[str] = []
    required_suffixes = {
        "pyproject.toml",
        "setup.py",
        "LICENSE",
        "README.md",
        "src/spintexture_agent/generator.py",
        "src/spintexture_agent/templates/derivation.wl.j2",
        "knowledge_base/materials.yaml",
        "mathematica/SpinTextureTheory.wl",
    }
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = {item.name for item in archive.getmembers() if item.isfile()}
            metadata_members = [
                item
                for item in archive.getmembers()
                if item.name.endswith("/PKG-INFO") and item.name.count("/") == 1
            ]
            if len(metadata_members) != 1:
                issues.append("sdist must contain exactly one root PKG-INFO file")
            else:
                metadata_file = archive.extractfile(metadata_members[0])
                if metadata_file is None:
                    issues.append("sdist PKG-INFO is unreadable")
                else:
                    metadata = email.message_from_bytes(metadata_file.read())
                    if metadata.get("Name") != name or metadata.get("Version") != version:
                        issues.append("sdist metadata name or version drift")
        missing = sorted(
            suffix for suffix in required_suffixes if not any(item.endswith(suffix) for item in members)
        )
        if missing:
            issues.append("sdist contents missing: " + ", ".join(missing))
        expected_root = _archive_root(name, version)
        setuptools_root = f"{name.replace('-', '_')}-{version}"
        roots = {item.split("/", 1)[0] for item in members}
        if len(roots) != 1 or next(iter(roots), "") not in {
            expected_root,
            setuptools_root,
        }:
            issues.append("sdist root name or version drift")
    except (tarfile.TarError, OSError) as exc:
        issues.append(f"sdist inspection failed: {exc}")
    return issues


def verify_distribution_bundle(bundle_dir: str | Path) -> DistributionVerification:
    root = _project_path(bundle_dir).resolve()
    manifest_path = root / MANIFEST_FILE
    digest_path = root / MANIFEST_DIGEST_FILE
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Distribution manifest is missing: {manifest_path}")
    if not digest_path.is_file():
        raise FileNotFoundError(f"Distribution manifest digest is missing: {digest_path}")
    manifest = DistributionManifest.model_validate(_load_yaml(manifest_path))
    issues: list[str] = []
    manifest_sha = _sha256(manifest_path)
    if digest_path.read_text(encoding="utf-8") != f"{manifest_sha}  {MANIFEST_FILE}\n":
        issues.append("detached distribution manifest SHA-256 mismatch")

    candidate_passed = False
    binding = manifest.release_candidate
    try:
        candidate_dir = _project_path(binding.candidate_path)
        candidate_manifest_path = _project_path(binding.manifest_path)
        candidate_result = verify_release_candidate(candidate_dir)
        candidate_manifest = ReleaseCandidateManifest.model_validate(
            _load_yaml(candidate_manifest_path)
        )
        candidate_passed = all(
            (
                candidate_result.software_release_candidate_ready,
                candidate_result.candidate_id == binding.candidate_id,
                candidate_result.manifest_sha256 == binding.manifest_sha256,
                candidate_manifest.package.source_tree_sha256 == binding.source_tree_sha256,
                candidate_manifest.package.name == manifest.package.name,
                candidate_manifest.package.version == manifest.package.version,
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        issues.append(f"release-candidate binding failed: {exc}")
    if not candidate_passed:
        issues.append("release-candidate binding drift")

    artifact_integrity = True
    artifacts: list[FrozenBundleArtifact] = []
    try:
        artifacts = _manifest_artifacts(manifest)
        for artifact in artifacts:
            _resolve_bundle_artifact(root, artifact)
        expected_checksums = "\n".join(
            f"{item.sha256}  {item.path}"
            for item in artifacts
            if item.path != CHECKSUMS_FILE
        ) + "\n"
        actual_checksums = _resolve_bundle_artifact(root, manifest.checksums).read_text(
            encoding="utf-8"
        )
        if actual_checksums != expected_checksums:
            artifact_integrity = False
            issues.append("CHECKSUMS.sha256 content drift")
    except (FileNotFoundError, ValueError) as exc:
        artifact_integrity = False
        issues.append(str(exc))

    source_reconstruction = False
    try:
        with tempfile.TemporaryDirectory(prefix="stta-source-rebuild-") as temp:
            rebuilt = Path(temp) / "source.tar.gz"
            _write_normalized_source_archive(
                rebuilt,
                manifest.package.source_members,
                manifest.package.name,
                manifest.package.version,
            )
            frozen_source = _resolve_bundle_artifact(
                root, manifest.package.normalized_source_archive
            )
            source_reconstruction = rebuilt.read_bytes() == frozen_source.read_bytes()
        if not source_reconstruction:
            issues.append("normalized source archive reconstruction mismatch")
    except (FileNotFoundError, ValueError) as exc:
        issues.append(f"source reconstruction failed: {exc}")

    package_issues: list[str] = []
    if artifact_integrity:
        package_issues.extend(
            _inspect_wheel(
                _resolve_bundle_artifact(root, manifest.package.wheel),
                manifest.package.name,
                manifest.package.version,
            )
        )
        package_issues.extend(
            _inspect_sdist(
                _resolve_bundle_artifact(root, manifest.package.sdist),
                manifest.package.name,
                manifest.package.version,
            )
        )
        canonical_wolfram = PROJECT_ROOT / "mathematica" / "SpinTextureTheory.wl"
        if _sha256(canonical_wolfram) != manifest.package.wolfram_library.sha256:
            package_issues.append("packaged Wolfram library drift")
    issues.extend(package_issues)
    package_contents = not package_issues

    dependency_passed = False
    try:
        inventory_path = _resolve_bundle_artifact(
            root, manifest.dependencies.inventory_artifact
        )
        inventory_payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        expected_payload = {
            "declared_requirements": manifest.dependencies.declared_requirements,
            "wheels": [item.model_dump(mode="json") for item in manifest.dependencies.wheels],
        }
        dependency_passed = inventory_payload == expected_payload
        for wheel in manifest.dependencies.wheels:
            path = _resolve_bundle_artifact(root, wheel.artifact)
            wheel_name, wheel_version, requires_python = _wheel_metadata(path)
            if (wheel_name, wheel_version, requires_python) != (
                wheel.name,
                wheel.version,
                wheel.requires_python,
            ):
                dependency_passed = False
        direct_names = {
            re.split(r"[<>=!~;\[]", requirement, maxsplit=1)[0]
            .strip()
            .lower()
            .replace("_", "-")
            for requirement in manifest.dependencies.declared_requirements
        }
        inventory_names = {
            wheel.name.lower().replace("_", "-")
            for wheel in manifest.dependencies.wheels
        }
        if not direct_names.issubset(inventory_names):
            dependency_passed = False
        if manifest.dependencies.declared_requirements != _declared_requirements():
            dependency_passed = False
    except (FileNotFoundError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        issues.append(f"dependency inventory verification failed: {exc}")
    if not dependency_passed:
        issues.append("dependency inventory drift")

    contracts = _command_contracts(
        manifest.dependencies.declared_requirements, manifest.package.wheel.path
    )
    clean_install_passed = True
    wolfram_load_passed = True
    for command in manifest.commands:
        try:
            stdout = _resolve_bundle_artifact(root, command.stdout).read_text(encoding="utf-8")
            stderr = _resolve_bundle_artifact(root, command.stderr).read_text(encoding="utf-8")
        except (FileNotFoundError, ValueError):
            clean_install_passed = False
            if command.check_id == "wolfram_load":
                wolfram_load_passed = False
            continue
        valid = all(
            (
                command.command_contract == contracts[command.check_id],
                command.status == "passed",
                command.exit_code == 0,
                _command_semantics(command.check_id, stdout, stderr),
            )
        )
        if not valid:
            issues.append(f"distribution command did not pass: {command.check_id}")
            if command.check_id == "wolfram_load":
                wolfram_load_passed = False
            else:
                clean_install_passed = False

    boundaries_passed = manifest.claim_boundaries == DistributionClaimBoundaries()
    if not boundaries_passed:
        issues.append("distribution claim boundaries were weakened")
    ready = all(
        (
            candidate_passed,
            artifact_integrity,
            source_reconstruction,
            package_contents,
            dependency_passed,
            clean_install_passed,
            wolfram_load_passed,
            boundaries_passed,
        )
    ) and not issues
    return DistributionVerification(
        bundle_id=manifest.bundle_id,
        manifest_sha256=manifest_sha,
        status="pass" if ready else "fail",
        distribution_ready=ready,
        eligible_for_publication_step=ready,
        release_candidate_binding_passed=candidate_passed,
        artifact_integrity_passed=artifact_integrity,
        source_reconstruction_passed=source_reconstruction,
        package_contents_passed=package_contents,
        dependency_inventory_passed=dependency_passed,
        clean_install_passed=clean_install_passed,
        wolfram_load_passed=wolfram_load_passed,
        claim_boundaries_passed=boundaries_passed,
        issues=list(dict.fromkeys(issues)),
    )


def create_distribution_bundle(
    release_candidate_dir: str | Path,
    out_dir: str | Path = DEFAULT_BUNDLE_OUT,
    *,
    bundle_id: str = DEFAULT_BUNDLE_ID,
    created_at: str | None = None,
    command_timeout: int = 600,
    wolfram_timeout: int = 120,
) -> DistributionCreation:
    out_path = _project_path(out_dir)
    if out_path.exists():
        raise FileExistsError(
            f"Distribution bundle already exists: {out_path}. Bundles are never overwritten."
        )
    timestamp = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    _timestamp(timestamp)
    candidate_path = _project_path(release_candidate_dir).resolve()
    candidate_result = verify_release_candidate(candidate_path)
    if not candidate_result.software_release_candidate_ready:
        raise ValueError("Release candidate is not ready for distribution")
    candidate_manifest_path = candidate_path / RELEASE_MANIFEST_FILE
    candidate = ReleaseCandidateManifest.model_validate(_load_yaml(candidate_manifest_path))
    binding = ReleaseCandidateBinding(
        candidate_id=candidate.candidate_id,
        candidate_path=_stored_project_path(candidate_path),
        manifest_path=_stored_project_path(candidate_manifest_path),
        manifest_sha256=candidate_result.manifest_sha256,
        source_tree_sha256=candidate.package.source_tree_sha256,
    )
    members = _source_members(candidate)
    declared = _declared_requirements()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out_path.name}.", dir=out_path.parent) as temp:
        root = Path(temp) / out_path.name
        root.mkdir()
        source_dir = root / "source"
        dist_dir = root / "dist"
        raw_dist = root / ".raw_dist"
        wheelhouse = root / "wheelhouse"
        source_dir.mkdir()
        dist_dir.mkdir()
        raw_dist.mkdir()
        wheelhouse.mkdir()

        normalized_source = source_dir / (
            f"{_archive_root(candidate.package.name, candidate.package.version)}-normalized.tar.gz"
        )
        _write_normalized_source_archive(
            normalized_source, members, candidate.package.name, candidate.package.version
        )
        staged = _stage_source_tree(
            root / ".build_source", members, candidate.package.name, candidate.package.version
        )
        build_env = os.environ.copy()
        build_env.update(
            {
                "SOURCE_DATE_EPOCH": str(SOURCE_DATE_EPOCH),
                "PYTHONHASHSEED": "0",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            }
        )
        provisional_contracts = _command_contracts(declared, "dist/<pending-wheel>")
        commands = [
            _run_logged_command(
                root,
                "build_sdist",
                provisional_contracts["build_sdist"],
                [sys.executable, "setup.py", "sdist", "--dist-dir", str(raw_dist)],
                cwd=staged,
                timeout_seconds=command_timeout,
                environment=build_env,
            ),
            _run_logged_command(
                root,
                "build_wheel",
                provisional_contracts["build_wheel"],
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    ".",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(raw_dist),
                ],
                cwd=staged,
                timeout_seconds=command_timeout,
                environment=build_env,
            ),
        ]
        if any(command.status != "passed" for command in commands):
            raise ValueError("Distribution package build failed; inspect retained command output")
        raw_wheels = sorted(raw_dist.glob("*.whl"))
        raw_sdists = sorted(raw_dist.glob("*.tar.gz"))
        if len(raw_wheels) != 1 or len(raw_sdists) != 1:
            raise ValueError("Build must produce exactly one wheel and one sdist")
        wheel_path = dist_dir / raw_wheels[0].name
        sdist_path = dist_dir / raw_sdists[0].name
        _normalize_zip(raw_wheels[0], wheel_path)
        _normalize_tar_gz(raw_sdists[0], sdist_path)
        wheel_name, wheel_version, _ = _wheel_metadata(wheel_path)
        if (wheel_name, wheel_version) != (candidate.package.name, candidate.package.version):
            raise ValueError("Built wheel name or version does not match release candidate")

        contracts = _command_contracts(declared, f"dist/{wheel_path.name}")
        commands[0] = commands[0].model_copy(
            update={"command_contract": contracts["build_sdist"]}
        )
        commands[1] = commands[1].model_copy(
            update={"command_contract": contracts["build_wheel"]}
        )
        commands.append(
            _run_logged_command(
                root,
                "dependency_download",
                contracts["dependency_download"],
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    "--only-binary=:all:",
                    "--dest",
                    str(wheelhouse),
                    *declared,
                ],
                cwd=staged,
                timeout_seconds=command_timeout,
                environment=build_env,
            )
        )
        if commands[-1].status != "passed":
            raise ValueError("Dependency wheel download failed")

        wolfram_dir = root / "wolfram"
        example_dir = root / "examples"
        wolfram_dir.mkdir()
        example_dir.mkdir()
        wolfram_path = wolfram_dir / "SpinTextureTheory.wl"
        config_path = example_dir / "afm_stripe_sot.yaml"
        shutil.copy2(PROJECT_ROOT / "mathematica" / "SpinTextureTheory.wl", wolfram_path)
        shutil.copy2(PROJECT_ROOT / "configs" / "afm_stripe_sot.yaml", config_path)

        clean_venv = root / ".clean_venv"
        commands.append(
            _run_logged_command(
                root,
                "venv_create",
                contracts["venv_create"],
                [sys.executable, "-m", "venv", str(clean_venv)],
                cwd=root,
                timeout_seconds=command_timeout,
            )
        )
        clean_python = clean_venv / "bin" / "python"
        commands.append(
            _run_logged_command(
                root,
                "clean_install",
                contracts["clean_install"],
                [
                    str(clean_python),
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--find-links",
                    str(wheelhouse),
                    str(wheel_path),
                ],
                cwd=root,
                timeout_seconds=command_timeout,
            )
        )
        resource_smoke = (
            "from spintexture_agent.resources import resource_file;"
            "assert resource_file('templates','derivation.wl.j2').is_file();"
            "assert resource_file('knowledge_base','materials.yaml').is_file();"
            "assert resource_file('mathematica','SpinTextureTheory.wl').is_file();"
            "print('STTA_RESOURCE_SMOKE_OK')"
        )
        commands.append(
            _run_logged_command(
                root,
                "import_smoke",
                contracts["import_smoke"],
                [str(clean_python), "-c", resource_smoke],
                cwd=root,
                timeout_seconds=command_timeout,
            )
        )
        for check_id, operation in (("validate_smoke", "validate"), ("plan_smoke", "plan")):
            commands.append(
                _run_logged_command(
                    root,
                    check_id,
                    contracts[check_id],
                    [
                        str(clean_python),
                        "-m",
                        "spintexture_agent.cli",
                        operation,
                        str(config_path),
                    ],
                    cwd=root,
                    timeout_seconds=command_timeout,
                )
            )
        kernel = _wolfram_kernel_path()
        if kernel is None:
            raise ValueError("WolframKernel is required for the distribution load gate")
        wl_marker = "STTA_WOLFRAM_LOAD_OK"
        wl_code = (
            f'Get["{wolfram_path}"];'
            'If[Length[Names["SpinTextureTheory`*"]]>0,'
            f'Print["{wl_marker}"],Print["STTA_WOLFRAM_LOAD_FAILED"]];Quit[]'
        )
        commands.append(
            _run_logged_command(
                root,
                "wolfram_load",
                contracts["wolfram_load"],
                [str(kernel), "-noprompt", "-run", wl_code],
                cwd=root,
                timeout_seconds=wolfram_timeout,
            )
        )
        failed_smokes = [
            command.check_id
            for command in commands
            if command.status != "passed"
            or not _command_semantics(
                command.check_id,
                _resolve_bundle_artifact(root, command.stdout).read_text(encoding="utf-8"),
                _resolve_bundle_artifact(root, command.stderr).read_text(encoding="utf-8"),
            )
        ]
        if failed_smokes:
            raise ValueError(
                "Clean-install or Wolfram load smoke gate failed: "
                + ", ".join(failed_smokes)
            )

        shutil.rmtree(clean_venv)
        shutil.rmtree(root / ".build_source")
        shutil.rmtree(raw_dist)
        dependency_inventory, _ = _dependency_inventory(root, declared, wheelhouse)
        package = DistributionPackage(
            name=candidate.package.name,
            version=candidate.package.version,
            normalized_source_archive=_bundle_artifact(
                root, normalized_source, "normalized_source_archive"
            ),
            wheel=_bundle_artifact(root, wheel_path, "project_wheel"),
            sdist=_bundle_artifact(root, sdist_path, "project_sdist"),
            wolfram_library=_bundle_artifact(root, wolfram_path, "wolfram_library"),
            example_config=_bundle_artifact(root, config_path, "example_config"),
            source_members=members,
        )
        guide_path = _write_reproduction_guide(root, bundle_id, binding, package)
        provisional_manifest = DistributionManifest(
            bundle_id=bundle_id,
            created_at=timestamp,
            release_candidate=binding,
            package=package,
            dependencies=dependency_inventory,
            reproduction_guide=_bundle_artifact(root, guide_path, "reproduction_guide"),
            checksums=FrozenBundleArtifact(
                path=CHECKSUMS_FILE,
                sha256="0" * 64,
                size_bytes=0,
                category="checksums",
            ),
            commands=commands,
            claim_boundaries=DistributionClaimBoundaries(),
        )
        pre_checksum_artifacts = [
            artifact
            for artifact in _manifest_artifacts(provisional_manifest)
            if artifact.path != CHECKSUMS_FILE
        ]
        checksums_path = _write_checksums(root, pre_checksum_artifacts)
        manifest = provisional_manifest.model_copy(
            update={"checksums": _bundle_artifact(root, checksums_path, "checksums")}
        )
        manifest_path = root / MANIFEST_FILE
        _write_yaml(manifest_path, manifest)
        manifest_sha = _sha256(manifest_path)
        (root / MANIFEST_DIGEST_FILE).write_text(
            f"{manifest_sha}  {MANIFEST_FILE}\n", encoding="utf-8"
        )
        result = verify_distribution_bundle(root)
        _write_verification_reports(root, result)
        if not result.distribution_ready:
            raise ValueError(
                "Constructed distribution bundle failed independent verification: "
                + "; ".join(result.issues)
            )
        if out_path.exists():
            raise FileExistsError(f"Distribution bundle appeared during creation: {out_path}")
        shutil.move(str(root), str(out_path))
    final = verify_distribution_bundle(out_path)
    return DistributionCreation(
        bundle_dir=str(out_path),
        manifest_path=str(out_path / MANIFEST_FILE),
        manifest_sha256=final.manifest_sha256,
        verification_json=str(out_path / VERIFICATION_JSON),
        verification_markdown=str(out_path / VERIFICATION_MARKDOWN),
        distribution_ready=final.distribution_ready,
    )
