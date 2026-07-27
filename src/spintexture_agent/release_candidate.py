from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .benchmark_manifest import BenchmarkManifestRegistry, PRIMARY_PARTITIONS
from .capabilities import CapabilityRegistry, DEFAULT_REGISTRY_PATH
from .cross_engine import verify_cross_engine_result
from .cross_engine_extended import (
    EXPECTED_CHECK_IDS as EXTENDED_CROSS_ENGINE_ROUTES,
)
from .cross_engine_extended import verify_extended_cross_engine_result
from .wolfram import KNOWN_WOLFRAM_KERNEL_PATHS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELEASE_CANDIDATE_SCHEMA_VERSION = "1.0.0"
DEFAULT_CANDIDATE_ID = "project1_v0.1.0_rc01"
DEFAULT_CANDIDATE_OUT = (
    PROJECT_ROOT / "analysis" / "release_candidates" / DEFAULT_CANDIDATE_ID
)
MANIFEST_FILE = "release_candidate_manifest.yaml"
MANIFEST_DIGEST_FILE = "release_candidate_manifest.sha256"
VERIFICATION_JSON = "verification_report.json"
VERIFICATION_MARKDOWN = "verification_report.md"

MANDATORY_DOCUMENTS: tuple[str, ...] = (
    "README.md",
    "docs/PROJECT_1_APPLICATION_CONTRACT.md",
    "docs/EVIDENCE_GOVERNANCE.md",
    "docs/ASSERTION_COVERAGE_PROTOCOL.md",
    "docs/EXTENDED_LITERATURE_REPRODUCTION_PROTOCOL.md",
    "docs/PROJECT_1_RELEASE_CANDIDATE_PROTOCOL.md",
    "docs/PROJECT_1_DISTRIBUTION_BUNDLE_PROTOCOL.md",
    "docs/SPINTEXTURE_DYNAMICS_BENCH_V1_DATASET_CARD.md",
)

REPRODUCTION_COMMANDS: tuple[str, ...] = (
    "python -m pip install -e '.[dev,cross-engine]'",
    "python -m pytest -q",
    "python -m ruff check src tests analysis/scripts",
    "python -m pip check",
    "python -m spintexture_agent.cli capabilities --json",
    (
        "python -m spintexture_agent.cli assertion-coverage --evidence-runs "
        "analysis/evidence_runs/core3_latest "
        "analysis/evidence_runs/extended_literature_01 --out <new-output> "
        "--require-complete"
    ),
    (
        "python -m spintexture_agent.cli release-candidate verify "
        "--candidate <candidate-directory> --require-ready"
    ),
)

EvidenceAxis = Literal[
    "cas_execution",
    "analytic_reproduction",
    "literature_reproduction",
    "assertion_coverage",
    "cross_engine",
]

REQUIRED_ROUTE_AXES: tuple[str, ...] = (
    "cas_execution",
    "analytic_reproduction",
    "literature_reproduction",
    "assertion_coverage",
    "cross_engine",
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
        raise ValueError(f"Release-candidate artifact path must be safe: {value}")
    return path


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _stored_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Release artifact is outside the project root: {path}") from exc


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
        raise ValueError("Release-candidate timestamp must include a timezone")
    return parsed


class FrozenReleaseArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["project", "candidate"]
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    category: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_path(self) -> "FrozenReleaseArtifact":
        _safe_relative(self.path)
        return self


class PackageReleaseMetadata(BaseModel):
    name: str
    version: str
    requires_python: str
    build_backend: str
    pyproject: FrozenReleaseArtifact
    source_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_control_revision: str | None = None
    version_control_status: Literal["recorded", "unavailable"]


class EnvironmentSnapshot(BaseModel):
    python_version: str
    python_implementation: str
    python_executable: str
    platform: str
    dependency_versions: dict[str, str]


class VerificationCommandResult(BaseModel):
    check_id: Literal["pytest_full", "ruff", "pip_check"]
    command: list[str] = Field(min_length=3)
    status: Literal["passed", "failed"]
    exit_code: int
    duration_seconds: float = Field(ge=0)
    stdout: FrozenReleaseArtifact
    stderr: FrozenReleaseArtifact


class WolframKernelSnapshot(BaseModel):
    status: Literal["passed", "failed", "missing"]
    executable: str | None = None
    command: list[str] = Field(default_factory=list)
    version: str | None = None
    system_id: str | None = None
    exit_code: int | None = None
    duration_seconds: float = Field(ge=0)
    stdout: FrozenReleaseArtifact
    stderr: FrozenReleaseArtifact


class RouteReleaseEvidence(BaseModel):
    route_id: str = Field(pattern=r"^[a-z0-9_]+$")
    evidence_status: dict[EvidenceAxis, Literal["passed"]]
    cas_execution_records: list[FrozenReleaseArtifact] = Field(min_length=1)
    analytic_reproduction_records: list[FrozenReleaseArtifact] = Field(min_length=1)
    literature_reproduction_record: FrozenReleaseArtifact
    assertion_coverage_records: list[FrozenReleaseArtifact] = Field(min_length=1)
    cross_engine_records: list[FrozenReleaseArtifact] = Field(min_length=1)
    supporting_artifacts: list[FrozenReleaseArtifact] = Field(min_length=1)
    machine_audit_record: FrozenReleaseArtifact

    @model_validator(mode="after")
    def validate_axes(self) -> "RouteReleaseEvidence":
        if set(self.evidence_status) != set(REQUIRED_ROUTE_AXES):
            raise ValueError(f"Route {self.route_id} must bind all release evidence axes")
        return self


class BenchmarkDisclosure(BaseModel):
    evidence_status: Literal["registered"] = "registered"
    benchmark_id: str
    benchmark_version: str
    freeze_status: str
    release_ready: bool
    partition_case_counts: dict[str, int]
    held_out_case_count: int
    paper_benchmark_claim_allowed: Literal[False] = False
    required_for_software_candidate: Literal[False] = False


class ExternalReviewDisclosure(BaseModel):
    full_route_count: int = Field(ge=1)
    passed_route_count: int = Field(ge=0)
    pending_route_count: int = Field(ge=0)
    required_for_software_candidate: Literal[False] = False
    novel_material_claim_allowed: Literal[False] = False


class MaterialApplicabilityDisclosure(BaseModel):
    formal_routes_passed: int = Field(ge=0)
    material_complete_routes: int = Field(ge=0)
    material_incomplete_routes: int = Field(ge=0)
    machine_audit_suite_statuses: list[str]
    required_for_generic_software_candidate: Literal[False] = False
    named_material_prediction_allowed: Literal[False] = False


class ReleaseClaimBoundaries(BaseModel):
    public_release_axis_mutated: Literal[False] = False
    paper_benchmark_result_claimed: Literal[False] = False
    external_review_claimed: Literal[False] = False
    named_material_validation_claimed: Literal[False] = False
    candidate_is_publication: Literal[False] = False


class ReleaseCandidateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[RELEASE_CANDIDATE_SCHEMA_VERSION] = (
        RELEASE_CANDIDATE_SCHEMA_VERSION
    )
    candidate_id: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    created_at: str
    package: PackageReleaseMetadata
    environment: EnvironmentSnapshot
    source_artifacts: list[FrozenReleaseArtifact] = Field(min_length=1)
    documentation_artifacts: list[FrozenReleaseArtifact] = Field(min_length=1)
    license_artifact: FrozenReleaseArtifact
    capability_registry: FrozenReleaseArtifact
    route_evidence: list[RouteReleaseEvidence] = Field(min_length=1)
    machine_audit_summaries: list[FrozenReleaseArtifact] = Field(min_length=2)
    benchmark_manifest: FrozenReleaseArtifact
    benchmark_partitions: list[FrozenReleaseArtifact] = Field(min_length=5)
    benchmark_state: BenchmarkDisclosure
    external_review_state: ExternalReviewDisclosure
    material_applicability_state: MaterialApplicabilityDisclosure
    wolfram_kernel: WolframKernelSnapshot
    verification_commands: list[VerificationCommandResult] = Field(min_length=3)
    reproduction_commands: list[str] = Field(min_length=1)
    claim_boundaries: ReleaseClaimBoundaries

    @model_validator(mode="after")
    def validate_manifest(self) -> "ReleaseCandidateManifest":
        _timestamp(self.created_at)
        route_ids = [route.route_id for route in self.route_evidence]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("Release-candidate route IDs must be unique")
        check_ids = [check.check_id for check in self.verification_commands]
        if set(check_ids) != {"pytest_full", "ruff", "pip_check"}:
            raise ValueError("Release candidate must run pytest, Ruff, and pip check")
        if set(self.benchmark_state.partition_case_counts) != set(PRIMARY_PARTITIONS):
            raise ValueError("Release candidate must disclose all benchmark partitions")
        return self


class ReleaseCandidateVerification(BaseModel):
    schema_version: Literal[RELEASE_CANDIDATE_SCHEMA_VERSION] = (
        RELEASE_CANDIDATE_SCHEMA_VERSION
    )
    candidate_id: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pass", "fail"]
    software_release_candidate_ready: bool
    eligible_for_publication_step: bool
    public_release_badge_registration_ready: Literal[False] = False
    artifact_integrity_passed: bool
    source_snapshot_passed: bool
    route_evidence_passed: bool
    verification_commands_passed: bool
    wolfram_metadata_passed: bool
    documentation_license_passed: bool
    benchmark_state: BenchmarkDisclosure
    external_review_state: ExternalReviewDisclosure
    material_applicability_state: MaterialApplicabilityDisclosure
    claim_boundaries: ReleaseClaimBoundaries
    issues: list[str]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)


class ReleaseCandidateCreation(BaseModel):
    candidate_dir: str
    manifest_path: str
    manifest_sha256: str
    verification_json: str
    verification_markdown: str
    software_release_candidate_ready: bool


def _project_artifact(path: str | Path, category: str) -> FrozenReleaseArtifact:
    resolved = _project_path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Release artifact is missing: {resolved}")
    return FrozenReleaseArtifact(
        scope="project",
        path=_stored_project_path(resolved),
        sha256=_sha256(resolved),
        size_bytes=resolved.stat().st_size,
        category=category,
    )


def _candidate_artifact(
    candidate_root: Path,
    path: Path,
    category: str,
) -> FrozenReleaseArtifact:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(candidate_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Candidate artifact escapes candidate root: {path}") from exc
    return FrozenReleaseArtifact(
        scope="candidate",
        path=relative,
        sha256=_sha256(resolved),
        size_bytes=resolved.stat().st_size,
        category=category,
    )


def _dedupe_artifacts(
    artifacts: list[FrozenReleaseArtifact],
) -> list[FrozenReleaseArtifact]:
    unique: dict[tuple[str, str], FrozenReleaseArtifact] = {}
    for artifact in artifacts:
        key = (artifact.scope, artifact.path)
        previous = unique.get(key)
        if previous and previous.sha256 != artifact.sha256:
            raise ValueError(f"Conflicting hashes for release artifact: {artifact.path}")
        unique[key] = artifact
    return [unique[key] for key in sorted(unique)]


def _source_artifacts() -> list[FrozenReleaseArtifact]:
    paths = [
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "setup.py",
        PROJECT_ROOT / "MANIFEST.in",
    ]
    for root, patterns in (
        (PROJECT_ROOT / "src" / "spintexture_agent", ("*.py", "*.j2")),
        (PROJECT_ROOT / "mathematica", ("*.wl",)),
        (PROJECT_ROOT / "knowledge_base", ("*.yaml",)),
        (PROJECT_ROOT / "configs", ("*.yaml",)),
        (PROJECT_ROOT / "tests", ("test_*.py",)),
    ):
        for pattern in patterns:
            paths.extend(sorted(root.rglob(pattern)))
    return _dedupe_artifacts([_project_artifact(path, "source") for path in paths])


def _tree_digest(artifacts: list[FrozenReleaseArtifact]) -> str:
    payload = [
        {
            "path": artifact.path,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
        }
        for artifact in sorted(artifacts, key=lambda item: item.path)
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _pyproject_metadata(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    fields = {
        "name": r'(?m)^name\s*=\s*"([^"]+)"',
        "version": r'(?m)^version\s*=\s*"([^"]+)"',
        "requires_python": r'(?m)^requires-python\s*=\s*"([^"]+)"',
        "build_backend": r'(?m)^build-backend\s*=\s*"([^"]+)"',
    }
    values: dict[str, str] = {}
    for field, pattern in fields.items():
        match = re.search(pattern, text)
        if not match:
            raise ValueError(f"pyproject.toml is missing {field}")
        values[field] = match.group(1)
    return values


def _dependency_versions() -> dict[str, str]:
    packages = (
        "spintexture-theory-agent",
        "pyyaml",
        "pydantic",
        "rich",
        "jinja2",
        "pytest",
        "ruff",
        "sympy",
        "mpmath",
    )
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def _command_specs() -> dict[str, list[str]]:
    return {
        "pytest_full": [sys.executable, "-m", "pytest", "-q"],
        "ruff": [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "src",
            "tests",
            "analysis/scripts",
        ],
        "pip_check": [sys.executable, "-m", "pip", "check"],
    }


def _command_semantics(check_id: str, stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}"
    if check_id == "pytest_full":
        return bool(re.search(r"\b\d+ passed\b", combined)) and " failed" not in combined
    if check_id == "ruff":
        return "All checks passed!" in combined
    if check_id == "pip_check":
        return "No broken requirements found." in combined
    return False


def _run_verification_command(
    check_id: str,
    command: list[str],
    candidate_root: Path,
    timeout_seconds: int,
) -> VerificationCommandResult:
    log_dir = candidate_root / "verification_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
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
    duration = time.perf_counter() - started
    stdout_path = log_dir / f"{check_id}_stdout.txt"
    stderr_path = log_dir / f"{check_id}_stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    status = (
        "passed"
        if exit_code == 0 and _command_semantics(check_id, stdout, stderr)
        else "failed"
    )
    return VerificationCommandResult(
        check_id=check_id,
        command=command,
        status=status,
        exit_code=exit_code,
        duration_seconds=duration,
        stdout=_candidate_artifact(candidate_root, stdout_path, "verification_log"),
        stderr=_candidate_artifact(candidate_root, stderr_path, "verification_log"),
    )


def _wolfram_kernel_path() -> Path | None:
    resolved = shutil.which("WolframKernel")
    if resolved:
        return Path(resolved)
    for path in KNOWN_WOLFRAM_KERNEL_PATHS:
        if path.is_file():
            return path
    return None


def _probe_wolfram_kernel(
    candidate_root: Path,
    timeout_seconds: int,
) -> WolframKernelSnapshot:
    log_dir = candidate_root / "verification_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "wolfram_metadata_stdout.txt"
    stderr_path = log_dir / "wolfram_metadata_stderr.txt"
    kernel = _wolfram_kernel_path()
    if kernel is None:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("WolframKernel was not found.\n", encoding="utf-8")
        return WolframKernelSnapshot(
            status="missing",
            duration_seconds=0.0,
            stdout=_candidate_artifact(candidate_root, stdout_path, "wolfram_metadata"),
            stderr=_candidate_artifact(candidate_root, stderr_path, "wolfram_metadata"),
        )
    marker_begin = "STTA_WOLFRAM_METADATA_BEGIN"
    marker_end = "STTA_WOLFRAM_METADATA_END"
    command = [
        str(kernel),
        "-noprompt",
        "-run",
        (
            f'Print["{marker_begin}"];Print[$Version];Print[$SystemID];'
            f'Print["{marker_end}"];Quit[]'
        ),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
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
    duration = time.perf_counter() - started
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    lines = [line.strip().strip('"') for line in stdout.splitlines()]
    metadata: list[str] = []
    if marker_begin in lines and marker_end in lines:
        start = lines.index(marker_begin) + 1
        end = lines.index(marker_end, start)
        metadata = [line for line in lines[start:end] if line]
    status = "passed" if exit_code == 0 and len(metadata) >= 2 else "failed"
    return WolframKernelSnapshot(
        status=status,
        executable=str(kernel),
        command=command,
        version=metadata[0] if metadata else None,
        system_id=metadata[1] if len(metadata) > 1 else None,
        exit_code=exit_code,
        duration_seconds=duration,
        stdout=_candidate_artifact(candidate_root, stdout_path, "wolfram_metadata"),
        stderr=_candidate_artifact(candidate_root, stderr_path, "wolfram_metadata"),
    )


def _files_under(path: Path, category: str) -> list[FrozenReleaseArtifact]:
    return [
        _project_artifact(item, category)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    ]


def _machine_audit_records() -> tuple[dict[str, Path], list[Path], dict[str, object]]:
    summary_paths = [
        PROJECT_ROOT / "analysis/machine_audit/core3_latest/machine_audit_summary.json",
        PROJECT_ROOT
        / "analysis/machine_audit/extended_literature_01/machine_audit_summary.json",
    ]
    route_paths: dict[str, Path] = {}
    suite_statuses: list[str] = []
    formal_passed = 0
    material_complete = 0
    material_incomplete = 0
    for summary_path in summary_paths:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        suite_statuses.append(str(payload["suite_status"]))
        for result in payload["results"]:
            route_paths[str(result["route_id"])] = Path(str(result["result_path"]))
            formal_passed += result["formal_route_status"] == "pass"
            material_complete += result["material_applicability_status"] == "pass"
            material_incomplete += result["material_applicability_status"] == "incomplete"
    disclosure = {
        "formal_routes_passed": formal_passed,
        "material_complete_routes": material_complete,
        "material_incomplete_routes": material_incomplete,
        "machine_audit_suite_statuses": suite_statuses,
    }
    return route_paths, summary_paths, disclosure


def _route_bindings(
    registry: CapabilityRegistry,
    machine_records: dict[str, Path],
) -> list[RouteReleaseEvidence]:
    bindings: list[RouteReleaseEvidence] = []
    for route in registry.routes:
        if route.support_level != "full_derivation":
            continue
        evidence = route.evidence
        status = route.evidence_status
        axes = {axis: getattr(status, axis) for axis in REQUIRED_ROUTE_AXES}
        supporting_paths = [
            evidence.config,
            *evidence.benchmark_cases,
            evidence.evidence_card,
            evidence.independent_gold_script,
            evidence.machine_audit_spec,
            evidence.assertion_coverage_registry,
        ]
        supporting = [
            _project_artifact(path, "route_contract")
            for path in supporting_paths
            if path
        ]
        for record in evidence.analytic_reproduction_records:
            supporting.extend(_files_under(_project_path(record).parent, "evidence_bundle"))
        for record in evidence.cross_engine_records:
            supporting.extend(_files_under(_project_path(record).parent, "cross_engine_bundle"))
        machine_path = machine_records[route.route_id]
        supporting.extend(_files_under(machine_path.parent, "machine_audit_bundle"))
        bindings.append(
            RouteReleaseEvidence(
                route_id=route.route_id,
                evidence_status=axes,
                cas_execution_records=[
                    _project_artifact(path, "cas_execution")
                    for path in evidence.cas_execution_records
                ],
                analytic_reproduction_records=[
                    _project_artifact(path, "analytic_reproduction")
                    for path in evidence.analytic_reproduction_records
                ],
                literature_reproduction_record=_project_artifact(
                    evidence.literature_reproduction_record or "",
                    "literature_reproduction",
                ),
                assertion_coverage_records=[
                    _project_artifact(path, "assertion_coverage")
                    for path in evidence.assertion_coverage_records
                ],
                cross_engine_records=[
                    _project_artifact(path, "cross_engine")
                    for path in evidence.cross_engine_records
                ],
                supporting_artifacts=_dedupe_artifacts(supporting),
                machine_audit_record=_project_artifact(
                    machine_path, "machine_audit"
                ),
            )
        )
    return sorted(bindings, key=lambda item: item.route_id)


def _benchmark_disclosure(
    benchmark: BenchmarkManifestRegistry,
) -> BenchmarkDisclosure:
    record = benchmark.to_record()
    counts = {
        partition: len(benchmark.partitions[partition].cases)
        for partition in PRIMARY_PARTITIONS
    }
    return BenchmarkDisclosure(
        benchmark_id=benchmark.suite.benchmark_id,
        benchmark_version=benchmark.suite.benchmark_version,
        freeze_status=benchmark.suite.freeze_status,
        release_ready=bool(record["release_ready"]),
        partition_case_counts=counts,
        held_out_case_count=counts["held_out_supported"],
    )


def _manifest_artifacts(
    manifest: ReleaseCandidateManifest,
) -> list[FrozenReleaseArtifact]:
    artifacts = [
        manifest.package.pyproject,
        *manifest.source_artifacts,
        *manifest.documentation_artifacts,
        manifest.license_artifact,
        manifest.capability_registry,
        *manifest.machine_audit_summaries,
        manifest.benchmark_manifest,
        *manifest.benchmark_partitions,
        manifest.wolfram_kernel.stdout,
        manifest.wolfram_kernel.stderr,
    ]
    for command in manifest.verification_commands:
        artifacts.extend([command.stdout, command.stderr])
    for route in manifest.route_evidence:
        artifacts.extend(route.cas_execution_records)
        artifacts.extend(route.analytic_reproduction_records)
        artifacts.append(route.literature_reproduction_record)
        artifacts.extend(route.assertion_coverage_records)
        artifacts.extend(route.cross_engine_records)
        artifacts.extend(route.supporting_artifacts)
        artifacts.append(route.machine_audit_record)
    return _dedupe_artifacts(artifacts)


def _resolve_artifact(
    candidate_root: Path,
    artifact: FrozenReleaseArtifact,
) -> Path:
    root = PROJECT_ROOT if artifact.scope == "project" else candidate_root
    path = (root / artifact.path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Release artifact escapes its scope: {artifact.path}") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Release artifact is missing: {artifact.path}")
    if path.stat().st_size != artifact.size_bytes or _sha256(path) != artifact.sha256:
        raise ValueError(f"Release artifact hash or size drift: {artifact.path}")
    return path


def _expected_route_paths(route) -> dict[str, list[str]]:
    evidence = route.evidence
    return {
        "cas_execution": evidence.cas_execution_records,
        "analytic_reproduction": evidence.analytic_reproduction_records,
        "literature_reproduction": [evidence.literature_reproduction_record or ""],
        "assertion_coverage": evidence.assertion_coverage_records,
        "cross_engine": evidence.cross_engine_records,
    }


def _bound_route_paths(binding: RouteReleaseEvidence) -> dict[str, list[str]]:
    return {
        "cas_execution": [item.path for item in binding.cas_execution_records],
        "analytic_reproduction": [
            item.path for item in binding.analytic_reproduction_records
        ],
        "literature_reproduction": [binding.literature_reproduction_record.path],
        "assertion_coverage": [item.path for item in binding.assertion_coverage_records],
        "cross_engine": [item.path for item in binding.cross_engine_records],
    }


def _write_verification_reports(
    candidate_root: Path,
    result: ReleaseCandidateVerification,
) -> tuple[Path, Path]:
    json_path = candidate_root / VERIFICATION_JSON
    markdown_path = candidate_root / VERIFICATION_MARKDOWN
    json_path.write_text(result.to_json() + "\n", encoding="utf-8")
    lines = [
        "# Project 1 release-candidate verification",
        "",
        f"- Candidate: `{result.candidate_id}`",
        f"- Status: `{result.status}`",
        (
            "- Software release candidate ready: "
            f"`{str(result.software_release_candidate_ready).lower()}`"
        ),
        "- Public-release badge registration ready: `false`",
        "- Paper benchmark claim allowed: `false`",
        "",
        "## Independent disclosures",
        "",
        f"- Held-out cases: `{result.benchmark_state.held_out_case_count}`",
        (
            "- External review: "
            f"`{result.external_review_state.passed_route_count}` passed, "
            f"`{result.external_review_state.pending_route_count}` pending"
        ),
        (
            "- Material applicability: "
            f"`{result.material_applicability_state.material_complete_routes}` complete, "
            f"`{result.material_applicability_state.material_incomplete_routes}` incomplete"
        ),
        "",
        "## Issues",
        "",
    ]
    lines.extend(f"- {issue}" for issue in result.issues)
    if not result.issues:
        lines.append("- None")
    lines.extend(
        [
            "",
            "This candidate does not mutate the capability registry. A public release badge",
            "requires a separately published, durably identified artifact and registration step.",
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def verify_release_candidate(
    candidate_dir: str | Path,
) -> ReleaseCandidateVerification:
    candidate_root = _project_path(candidate_dir).resolve()
    manifest_path = candidate_root / MANIFEST_FILE
    digest_path = candidate_root / MANIFEST_DIGEST_FILE
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Release-candidate manifest is missing: {manifest_path}")
    if not digest_path.is_file():
        raise FileNotFoundError(f"Release-candidate digest is missing: {digest_path}")
    manifest = ReleaseCandidateManifest.model_validate(_load_yaml(manifest_path))
    issues: list[str] = []
    manifest_sha = _sha256(manifest_path)
    expected_digest = f"{manifest_sha}  {MANIFEST_FILE}\n"
    if digest_path.read_text(encoding="utf-8") != expected_digest:
        issues.append("detached release-candidate manifest SHA-256 mismatch")

    artifact_issues: list[str] = []
    for artifact in _manifest_artifacts(manifest):
        try:
            _resolve_artifact(candidate_root, artifact)
        except (FileNotFoundError, ValueError) as exc:
            artifact_issues.append(str(exc))
    issues.extend(artifact_issues)
    artifact_integrity = not artifact_issues

    source_snapshot = False
    if artifact_integrity:
        source_snapshot = _tree_digest(manifest.source_artifacts) == (
            manifest.package.source_tree_sha256
        )
        if not source_snapshot:
            issues.append("source-tree digest mismatch")
        metadata = _pyproject_metadata(_resolve_artifact(candidate_root, manifest.package.pyproject))
        for key in ("name", "version", "requires_python", "build_backend"):
            if metadata[key] != getattr(manifest.package, key):
                issues.append(f"package metadata drift: {key}")
                source_snapshot = False

    required_docs = set(MANDATORY_DOCUMENTS)
    bound_docs = {item.path for item in manifest.documentation_artifacts}
    documentation_license = required_docs.issubset(bound_docs)
    if not documentation_license:
        issues.append("mandatory release documentation is not fully bound")
    if (
        manifest.license_artifact.scope != "project"
        or manifest.license_artifact.path != "LICENSE"
        or manifest.license_artifact.category != "license"
    ):
        documentation_license = False
        issues.append("license artifact must be the project LICENSE file")
    try:
        license_path = _resolve_artifact(candidate_root, manifest.license_artifact)
        if "BSD 3-Clause License" not in license_path.read_text(encoding="utf-8"):
            documentation_license = False
            issues.append("LICENSE does not contain the registered BSD 3-Clause text")
    except (FileNotFoundError, ValueError):
        documentation_license = False

    commands_passed = True
    expected_commands = _command_specs()
    for check in manifest.verification_commands:
        try:
            stdout = _resolve_artifact(candidate_root, check.stdout).read_text(
                encoding="utf-8"
            )
            stderr = _resolve_artifact(candidate_root, check.stderr).read_text(
                encoding="utf-8"
            )
        except (FileNotFoundError, ValueError):
            commands_passed = False
            continue
        if (
            check.command != expected_commands[check.check_id]
            or check.exit_code != 0
            or check.status != "passed"
            or not _command_semantics(check.check_id, stdout, stderr)
        ):
            commands_passed = False
            issues.append(f"verification command did not pass: {check.check_id}")

    wolfram_passed = (
        manifest.wolfram_kernel.status == "passed"
        and manifest.wolfram_kernel.exit_code == 0
        and bool(manifest.wolfram_kernel.version)
        and bool(manifest.wolfram_kernel.system_id)
    )
    if not wolfram_passed:
        issues.append("Wolfram kernel metadata probe did not pass")

    route_evidence_passed = True
    try:
        capability_path = _resolve_artifact(candidate_root, manifest.capability_registry)
        registry = CapabilityRegistry(capability_path)
        full_routes = {
            route.route_id: route
            for route in registry.routes
            if route.support_level == "full_derivation"
        }
        bindings = {binding.route_id: binding for binding in manifest.route_evidence}
        if len(full_routes) != 7 or set(bindings) != set(full_routes):
            raise ValueError("release candidate must bind exactly the seven full routes")
        for route_id, route in full_routes.items():
            binding = bindings[route_id]
            for axis in REQUIRED_ROUTE_AXES:
                if getattr(route.evidence_status, axis) != "passed":
                    raise ValueError(f"route {route_id} lacks passed {axis}")
            if _bound_route_paths(binding) != _expected_route_paths(route):
                raise ValueError(f"route evidence path drift: {route_id}")
            for artifact in binding.cas_execution_records:
                payload = json.loads(
                    _resolve_artifact(candidate_root, artifact).read_text(encoding="utf-8")
                )
                if not payload.get("passed") or payload.get(
                    "generated_execution_status"
                ) != "passed":
                    raise ValueError(f"CAS result is not passed: {route_id}")
            verifier = (
                verify_extended_cross_engine_result
                if route_id in EXTENDED_CROSS_ENGINE_ROUTES
                else verify_cross_engine_result
            )
            if not any(
                verifier(
                    _resolve_artifact(candidate_root, artifact)
                ).eligible_for_cross_engine_pass
                for artifact in binding.cross_engine_records
            ):
                raise ValueError(f"cross-engine result is not passed: {route_id}")
            audit = json.loads(
                _resolve_artifact(
                    candidate_root, binding.machine_audit_record
                ).read_text(encoding="utf-8")
            )
            if audit.get("formal_route_status") != "pass":
                raise ValueError(f"formal machine audit is not passed: {route_id}")
        assertion_paths = {
            artifact.path
            for binding in manifest.route_evidence
            for artifact in binding.assertion_coverage_records
        }
        for path in assertion_paths:
            assertion = json.loads((PROJECT_ROOT / path).read_text(encoding="utf-8"))
            if assertion.get("suite_status") != "pass" or assertion.get(
                "routes_passed"
            ) != 7:
                raise ValueError("assertion-coverage suite is not complete")
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        route_evidence_passed = False
        issues.append(f"route evidence verification failed: {exc}")

    benchmark_matches = False
    try:
        benchmark_path = _resolve_artifact(candidate_root, manifest.benchmark_manifest)
        benchmark = BenchmarkManifestRegistry(benchmark_path)
        benchmark_matches = _benchmark_disclosure(benchmark) == manifest.benchmark_state
    except (FileNotFoundError, ValueError) as exc:
        issues.append(f"benchmark disclosure verification failed: {exc}")
    if not benchmark_matches:
        issues.append("benchmark disclosure drift")

    external_matches = False
    material_matches = False
    try:
        registry = CapabilityRegistry(
            _resolve_artifact(candidate_root, manifest.capability_registry)
        )
        full_routes = [
            route for route in registry.routes if route.support_level == "full_derivation"
        ]
        expected_external = ExternalReviewDisclosure(
            full_route_count=len(full_routes),
            passed_route_count=sum(
                route.evidence_status.external_review == "passed" for route in full_routes
            ),
            pending_route_count=sum(
                route.evidence_status.external_review == "pending" for route in full_routes
            ),
        )
        external_matches = expected_external == manifest.external_review_state
        route_paths, summary_paths, material = _machine_audit_records()
        del route_paths, summary_paths
        expected_material = MaterialApplicabilityDisclosure(**material)
        material_matches = expected_material == manifest.material_applicability_state
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        issues.append(f"independent-state disclosure verification failed: {exc}")
    if not external_matches:
        issues.append("external-review disclosure drift")
    if not material_matches:
        issues.append("material-applicability disclosure drift")

    boundaries_valid = manifest.claim_boundaries == ReleaseClaimBoundaries()
    if not boundaries_valid:
        issues.append("release claim boundaries were weakened")
    ready = all(
        (
            artifact_integrity,
            source_snapshot,
            route_evidence_passed,
            commands_passed,
            wolfram_passed,
            documentation_license,
            benchmark_matches,
            external_matches,
            material_matches,
            boundaries_valid,
        )
    ) and not issues
    return ReleaseCandidateVerification(
        candidate_id=manifest.candidate_id,
        manifest_sha256=manifest_sha,
        status="pass" if ready else "fail",
        software_release_candidate_ready=ready,
        eligible_for_publication_step=ready,
        artifact_integrity_passed=artifact_integrity,
        source_snapshot_passed=source_snapshot,
        route_evidence_passed=route_evidence_passed,
        verification_commands_passed=commands_passed,
        wolfram_metadata_passed=wolfram_passed,
        documentation_license_passed=documentation_license,
        benchmark_state=manifest.benchmark_state,
        external_review_state=manifest.external_review_state,
        material_applicability_state=manifest.material_applicability_state,
        claim_boundaries=manifest.claim_boundaries,
        issues=list(dict.fromkeys(issues)),
    )


def create_release_candidate(
    out_dir: str | Path = DEFAULT_CANDIDATE_OUT,
    *,
    candidate_id: str = DEFAULT_CANDIDATE_ID,
    created_at: str | None = None,
    capability_registry: str | Path = DEFAULT_REGISTRY_PATH,
    pytest_timeout: int = 1800,
    command_timeout: int = 300,
    wolfram_timeout: int = 120,
) -> ReleaseCandidateCreation:
    out_path = _project_path(out_dir)
    if out_path.exists():
        raise FileExistsError(
            f"Release candidate already exists: {out_path}. Candidates are never overwritten."
        )
    timestamp = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    _timestamp(timestamp)
    registry = CapabilityRegistry(capability_registry)
    benchmark = BenchmarkManifestRegistry()
    machine_records, machine_summaries, material = _machine_audit_records()
    source_artifacts = _source_artifacts()
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    package_values = _pyproject_metadata(pyproject_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out_path.name}.", dir=out_path.parent) as temp:
        build = Path(temp) / out_path.name
        build.mkdir()
        commands = []
        for check_id, command in _command_specs().items():
            timeout = pytest_timeout if check_id == "pytest_full" else command_timeout
            commands.append(
                _run_verification_command(check_id, command, build, timeout)
            )
        wolfram = _probe_wolfram_kernel(build, wolfram_timeout)
        full_routes = [
            route for route in registry.routes if route.support_level == "full_derivation"
        ]
        benchmark_manifest = _project_artifact(
            "benchmark_manifests/v1/manifest.yaml", "benchmark_manifest"
        )
        benchmark_partitions = [
            _project_artifact(
                benchmark.suite.partitions[index].path, "benchmark_partition"
            )
            for index in range(len(benchmark.suite.partitions))
        ]
        manifest = ReleaseCandidateManifest(
            candidate_id=candidate_id,
            created_at=timestamp,
            package=PackageReleaseMetadata(
                **package_values,
                pyproject=_project_artifact(pyproject_path, "package_metadata"),
                source_tree_sha256=_tree_digest(source_artifacts),
                version_control_revision=None,
                version_control_status="unavailable",
            ),
            environment=EnvironmentSnapshot(
                python_version=platform.python_version(),
                python_implementation=platform.python_implementation(),
                python_executable=sys.executable,
                platform=platform.platform(),
                dependency_versions=_dependency_versions(),
            ),
            source_artifacts=source_artifacts,
            documentation_artifacts=[
                _project_artifact(path, "documentation") for path in MANDATORY_DOCUMENTS
            ],
            license_artifact=_project_artifact("LICENSE", "license"),
            capability_registry=_project_artifact(
                capability_registry, "capability_registry"
            ),
            route_evidence=_route_bindings(registry, machine_records),
            machine_audit_summaries=[
                _project_artifact(path, "machine_audit_summary")
                for path in machine_summaries
            ],
            benchmark_manifest=benchmark_manifest,
            benchmark_partitions=benchmark_partitions,
            benchmark_state=_benchmark_disclosure(benchmark),
            external_review_state=ExternalReviewDisclosure(
                full_route_count=len(full_routes),
                passed_route_count=sum(
                    route.evidence_status.external_review == "passed"
                    for route in full_routes
                ),
                pending_route_count=sum(
                    route.evidence_status.external_review == "pending"
                    for route in full_routes
                ),
            ),
            material_applicability_state=MaterialApplicabilityDisclosure(**material),
            wolfram_kernel=wolfram,
            verification_commands=commands,
            reproduction_commands=list(REPRODUCTION_COMMANDS),
            claim_boundaries=ReleaseClaimBoundaries(),
        )
        manifest_path = build / MANIFEST_FILE
        _write_yaml(manifest_path, manifest)
        manifest_sha = _sha256(manifest_path)
        (build / MANIFEST_DIGEST_FILE).write_text(
            f"{manifest_sha}  {MANIFEST_FILE}\n", encoding="utf-8"
        )
        result = verify_release_candidate(build)
        _write_verification_reports(build, result)
        if out_path.exists():
            raise FileExistsError(
                f"Release candidate appeared during creation: {out_path}"
            )
        shutil.move(str(build), str(out_path))
    final = verify_release_candidate(out_path)
    return ReleaseCandidateCreation(
        candidate_dir=str(out_path),
        manifest_path=str(out_path / MANIFEST_FILE),
        manifest_sha256=final.manifest_sha256,
        verification_json=str(out_path / VERIFICATION_JSON),
        verification_markdown=str(out_path / VERIFICATION_MARKDOWN),
        software_release_candidate_ready=final.software_release_candidate_ready,
    )
