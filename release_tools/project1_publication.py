from __future__ import annotations

import argparse
import gzip
import hashlib
import ipaddress
import json
import re
import shutil
import socket
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_SCHEMA_VERSION = "1.0.0"
PUBLICATION_RECORD_SCHEMA_VERSION = "1.0.0"
REMOTE_RESULT_SCHEMA_VERSION = "1.1.0"
DEFAULT_DISTRIBUTION = (
    PROJECT_ROOT
    / "analysis"
    / "distribution_bundles"
    / "project1_v0.1.0_rc04_distribution01"
)
DEFAULT_HANDOFF_ID = "project1_v0.1.0_rc04_publication01"
DEFAULT_HANDOFF = PROJECT_ROOT / "analysis" / "publication_handoffs" / DEFAULT_HANDOFF_ID
HANDOFF_MANIFEST = "publication_handoff_manifest.yaml"
HANDOFF_MANIFEST_DIGEST = "publication_handoff_manifest.sha256"
HANDOFF_CHECKSUMS = "CHECKSUMS.sha256"
HANDOFF_VERIFICATION_JSON = "handoff_verification.json"
HANDOFF_VERIFICATION_MARKDOWN = "handoff_verification.md"
REGISTRATION_TEMPLATE = "publication_registration_template.yaml"
REMOTE_RESULT_JSON = "remote_publication_verification.json"
REMOTE_RESULT_MARKDOWN = "remote_publication_verification.md"
REMOTE_RESULT_DIGEST = "remote_publication_verification.sha256"
PUBLIC_RELEASE_EVIDENCE = "public_release_evidence_record.yaml"
REMOTE_VERIFIER_COPY = "remote_verifier.py"
PUBLIC_SNAPSHOT_SCHEMA_VERSION = "1.0.0"
PUBLIC_SNAPSHOT_MANIFEST = "public_evidence_snapshot.yaml"
PUBLIC_SNAPSHOT_DIGEST = "public_evidence_snapshot.sha256"
PUBLIC_SNAPSHOT_SUMMARY = "remote_verification_summary.json"
PUBLIC_SNAPSHOT_GUIDE = "VERIFY.md"
SOURCE_DATE_EPOCH = 0
MAX_REMOTE_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES = 512 * 1024 * 1024
RFC2544_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")

FALSE_CLAIM_BOUNDARIES = {
    "public_release_axis_mutated": False,
    "paper_benchmark_result_claimed": False,
    "held_out_evidence_claimed": False,
    "external_review_claimed": False,
    "named_material_validation_claimed": False,
    "handoff_is_publication": False,
}

PUBLICATION_ATTESTATION_KEYS = (
    "exact_archive_uploaded",
    "immutable_reference",
    "provider_record_public",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"Unsafe relative path: {value}")
    return path


def _resolve_relative(root: Path, value: str) -> Path:
    relative = _safe_relative(value)
    path = (root / Path(*relative.parts)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path escapes root: {value}") from exc
    return path


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _stored_project_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _parse_timestamp(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _artifact(root: Path, path: Path, category: str) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"Artifact escapes handoff root: {path}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"Artifact is missing: {resolved}")
    return {
        "path": relative,
        "sha256": _sha256(resolved),
        "size_bytes": resolved.stat().st_size,
        "category": category,
    }


def _validate_artifact(root: Path, artifact: dict[str, Any]) -> Path:
    expected = {"path", "sha256", "size_bytes", "category"}
    if set(artifact) != expected:
        raise ValueError("Artifact record fields drift")
    path = _resolve_relative(root, str(artifact["path"]))
    if not path.is_file():
        raise FileNotFoundError(f"Handoff artifact is missing: {artifact['path']}")
    if (
        path.stat().st_size != artifact["size_bytes"]
        or _sha256(path) != artifact["sha256"]
    ):
        raise ValueError(f"Handoff artifact hash or size drift: {artifact['path']}")
    return path


def _parse_detached_digest(path: Path, expected_name: str) -> str:
    match = re.fullmatch(
        rf"([0-9a-f]{{64}})  {re.escape(expected_name)}\n",
        path.read_text(encoding="utf-8"),
    )
    if not match:
        raise ValueError(f"Detached digest format is invalid: {path}")
    return match.group(1)


def _parse_checksums(text: str) -> dict[str, str]:
    records: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"Invalid checksum line: {line}")
        path = match.group(2)
        _safe_relative(path)
        if path in records:
            raise ValueError(f"Duplicate checksum path: {path}")
        records[path] = match.group(1)
    if list(records) != sorted(records):
        raise ValueError("Checksum entries must be sorted")
    return records


def _verify_distribution_bundle_local(bundle: Path) -> dict[str, Any]:
    if not bundle.is_dir():
        raise FileNotFoundError(f"Distribution bundle does not exist: {bundle}")
    if any(path.is_symlink() for path in bundle.rglob("*")):
        raise ValueError("Distribution bundle may not contain symbolic links")
    manifest_path = bundle / "distribution_manifest.yaml"
    digest_path = bundle / "distribution_manifest.sha256"
    checksums_path = bundle / "CHECKSUMS.sha256"
    verification_path = bundle / "distribution_verification.json"
    for path in (manifest_path, digest_path, checksums_path, verification_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required distribution artifact is missing: {path}")
    manifest_sha = _sha256(manifest_path)
    if _parse_detached_digest(digest_path, manifest_path.name) != manifest_sha:
        raise ValueError("Distribution manifest detached digest mismatch")
    manifest = _load_yaml(manifest_path)
    if manifest.get("bundle_id") != bundle.name:
        raise ValueError("Distribution bundle ID does not match its directory")
    boundaries = manifest.get("claim_boundaries")
    expected_distribution_boundaries = {
        "public_release_axis_mutated": False,
        "paper_benchmark_result_claimed": False,
        "held_out_evidence_claimed": False,
        "external_review_claimed": False,
        "named_material_validation_claimed": False,
        "bundle_is_durable_publication": False,
    }
    if boundaries != expected_distribution_boundaries:
        raise ValueError("Distribution claim boundaries were weakened")
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    required_true = (
        "distribution_ready",
        "eligible_for_publication_step",
        "release_candidate_binding_passed",
        "artifact_integrity_passed",
        "source_reconstruction_passed",
        "package_contents_passed",
        "dependency_inventory_passed",
        "clean_install_passed",
        "wolfram_load_passed",
        "claim_boundaries_passed",
    )
    if verification.get("status") != "pass" or not all(
        verification.get(key) is True for key in required_true
    ):
        raise ValueError("Distribution verification is not fully passed")
    if verification.get("public_release_badge_registration_ready") is not False:
        raise ValueError("Distribution improperly claims public-release readiness")
    if verification.get("manifest_sha256") != manifest_sha:
        raise ValueError("Distribution verification manifest binding drift")
    checksums = _parse_checksums(checksums_path.read_text(encoding="utf-8"))
    for relative, expected_sha in checksums.items():
        path = _resolve_relative(bundle, relative)
        if not path.is_file() or _sha256(path) != expected_sha:
            raise ValueError(f"Distribution checksum drift: {relative}")
    return manifest


def _bundle_inventory(bundle: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Distribution contains a symbolic link: {path}")
        if not path.is_file():
            continue
        records.append(
            {
                "path": path.relative_to(bundle).as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    if not records:
        raise ValueError("Distribution bundle is empty")
    return records


def _write_deterministic_archive(
    bundle: Path,
    inventory: list[dict[str, Any]],
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for record in inventory:
                    source = _resolve_relative(bundle, record["path"])
                    if (
                        source.stat().st_size != record["size_bytes"]
                        or _sha256(source) != record["sha256"]
                    ):
                        raise ValueError(f"Distribution file drift: {record['path']}")
                    info = tarfile.TarInfo(f"{bundle.name}/{record['path']}")
                    info.size = record["size_bytes"]
                    info.mtime = SOURCE_DATE_EPOCH
                    info.mode = 0o644
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with source.open("rb") as handle:
                        archive.addfile(info, handle)


def _archive_payloads(path: Path) -> tuple[dict[str, bytes], list[str]]:
    payloads: dict[str, bytes] = {}
    issues: list[str] = []
    expanded_size = 0
    try:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    issues.append(f"publication archive contains non-file member: {member.name}")
                    continue
                try:
                    _safe_relative(member.name)
                except ValueError:
                    issues.append(f"publication archive contains unsafe member: {member.name}")
                    continue
                if member.name in payloads:
                    issues.append(f"publication archive contains duplicate member: {member.name}")
                    continue
                expanded_size += member.size
                if (
                    member.size > MAX_REMOTE_ARCHIVE_BYTES
                    or expanded_size > MAX_ARCHIVE_EXPANDED_BYTES
                ):
                    issues.append("publication archive expanded size exceeds the safety limit")
                    break
                if (
                    member.mtime != SOURCE_DATE_EPOCH
                    or member.uid != 0
                    or member.gid != 0
                    or member.mode != 0o644
                ):
                    issues.append(f"publication archive metadata drift: {member.name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    issues.append(f"publication archive member is unreadable: {member.name}")
                    continue
                payloads[member.name] = extracted.read()
    except (OSError, tarfile.TarError) as exc:
        issues.append(f"publication archive is unreadable: {exc}")
    return payloads, issues


def _verify_archive(
    archive_path: Path,
    bundle_id: str,
    inventory: list[dict[str, Any]],
    distribution_manifest_sha256: str,
) -> list[str]:
    payloads, issues = _archive_payloads(archive_path)
    expected_paths = {f"{bundle_id}/{record['path']}" for record in inventory}
    if set(payloads) != expected_paths:
        missing = sorted(expected_paths - set(payloads))
        extra = sorted(set(payloads) - expected_paths)
        if missing:
            issues.append("publication archive members missing: " + ", ".join(missing))
        if extra:
            issues.append("publication archive members unexpected: " + ", ".join(extra))
    by_path = {record["path"]: record for record in inventory}
    for archive_name, data in payloads.items():
        prefix = f"{bundle_id}/"
        if not archive_name.startswith(prefix):
            continue
        relative = archive_name[len(prefix) :]
        record = by_path.get(relative)
        if record and (
            len(data) != record["size_bytes"]
            or _sha256_bytes(data) != record["sha256"]
        ):
            issues.append(f"publication archive payload drift: {relative}")
    embedded_manifest = payloads.get(f"{bundle_id}/distribution_manifest.yaml")
    if (
        embedded_manifest is None
        or _sha256_bytes(embedded_manifest) != distribution_manifest_sha256
    ):
        issues.append("embedded distribution manifest hash drift")
    embedded_digest = payloads.get(f"{bundle_id}/distribution_manifest.sha256")
    expected_digest = (
        f"{distribution_manifest_sha256}  distribution_manifest.yaml\n".encode()
    )
    if embedded_digest != expected_digest:
        issues.append("embedded distribution manifest detached digest drift")
    return issues


def _write_handoff_documents(
    root: Path,
    handoff_id: str,
    distribution: dict[str, Any],
    archive_name: str,
    archive_sha: str,
) -> tuple[Path, Path, Path]:
    package = distribution["package"]
    candidate = distribution["release_candidate"]
    release_notes = root / "RELEASE_NOTES.md"
    release_notes.write_text(
        "\n".join(
            [
                f"# SpinTextureTheoryAgent {package['version']}",
                "",
                f"Publication handoff: `{handoff_id}`",
                f"Software candidate: `{candidate['candidate_id']}`",
                f"Distribution: `{distribution['bundle_id']}`",
                "",
                "This release provides the Mathematica-centered symbolic derivation",
                "workflow, seven formally supported derivation routes, installed runtime",
                "templates and knowledge, a frozen dependency wheelhouse, and reproducible",
                "release/clean-install evidence.",
                "",
                "Scientific scope remains bounded: held-out benchmark evidence is absent,",
                "external review remains pending, and named-material applicability is not",
                "claimed. Candidate and review-only routes retain their original warnings.",
                "",
                f"Upload artifact: `{archive_name}`",
                f"Expected SHA-256: `{archive_sha}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    guide = root / "PUBLICATION_HANDOFF.md"
    guide.write_text(
        "\n".join(
            [
                "# Durable publication handoff",
                "",
                "1. Upload the exact file under `payload/` to an immutable GitHub release,",
                "   Zenodo record, or institutional archive.",
                "2. Publish the adjacent archive SHA-256 and distribution-manifest SHA-256.",
                "3. Fill `publication_registration_template.yaml` with genuine provider",
                "   metadata; do not change expected hashes or claim boundaries.",
                "4. Run the bundled verifier with `verify-remote`. Only a successful remote",
                "   byte retrieval is eligible for a later registry update.",
                "",
                "Mutable branch URLs, local files, `latest` links, typed but unreachable",
                "DOIs, and manually asserted publication states are rejected.",
                "",
                "This handoff is ready for upload but is not itself a public publication.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    template = root / REGISTRATION_TEMPLATE
    _write_yaml(
        template,
        {
            "schema_version": PUBLICATION_RECORD_SCHEMA_VERSION,
            "status": "pending_publication",
            "provider": None,
            "artifact_url": None,
            "immutable_identifier": None,
            "release_tag": None,
            "published_at": None,
            "publisher": None,
            "expected_archive": {
                "filename": archive_name,
                "sha256": archive_sha,
            },
            "attestation": {
                key: False for key in PUBLICATION_ATTESTATION_KEYS
            },
            "claim_boundaries": {
                "paper_benchmark_result_claimed": False,
                "held_out_evidence_claimed": False,
                "external_review_claimed": False,
                "named_material_validation_claimed": False,
                "registry_mutated_before_remote_verification": False,
            },
        },
    )
    return release_notes, guide, template


def _write_handoff_checksums(root: Path, artifacts: list[dict[str, Any]]) -> Path:
    path = root / HANDOFF_CHECKSUMS
    path.write_text(
        "\n".join(
            f"{artifact['sha256']}  {artifact['path']}"
            for artifact in sorted(artifacts, key=lambda item: item["path"])
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _handoff_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    keys = (
        "publication_archive",
        "archive_digest",
        "distribution_manifest_digest",
        "release_notes",
        "handoff_guide",
        "registration_template",
        "verifier",
        "checksums",
    )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(keys):
        raise ValueError("Handoff artifact registry fields drift")
    return [artifacts[key] for key in keys]


def create_publication_handoff(
    distribution_dir: str | Path = DEFAULT_DISTRIBUTION,
    out_dir: str | Path = DEFAULT_HANDOFF,
    *,
    handoff_id: str = DEFAULT_HANDOFF_ID,
    created_at: str | None = None,
) -> dict[str, Any]:
    bundle = _project_path(distribution_dir).resolve()
    out = _project_path(out_dir)
    if out.exists():
        raise FileExistsError(f"Publication handoff already exists: {out}")
    timestamp = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    _parse_timestamp(timestamp, "created_at")
    distribution = _verify_distribution_bundle_local(bundle)
    inventory = _bundle_inventory(bundle)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}.", dir=out.parent) as temp:
        root = Path(temp) / out.name
        payload_dir = root / "payload"
        verifier_dir = root / "verifier"
        payload_dir.mkdir(parents=True)
        verifier_dir.mkdir()
        archive_name = f"{bundle.name}.tar.gz"
        archive_path = payload_dir / archive_name
        _write_deterministic_archive(bundle, inventory, archive_path)
        archive_sha = _sha256(archive_path)
        archive_digest_path = payload_dir / f"{archive_name}.sha256"
        archive_digest_path.write_text(
            f"{archive_sha}  {archive_name}\n", encoding="utf-8"
        )
        distribution_manifest_sha = _sha256(bundle / "distribution_manifest.yaml")
        distribution_digest_path = payload_dir / "distribution_manifest.sha256"
        distribution_digest_path.write_text(
            f"{distribution_manifest_sha}  distribution_manifest.yaml\n",
            encoding="utf-8",
        )
        release_notes, guide, registration_template = _write_handoff_documents(
            root,
            handoff_id,
            distribution,
            archive_name,
            archive_sha,
        )
        verifier_path = verifier_dir / "project1_publication.py"
        shutil.copy2(Path(__file__).resolve(), verifier_path)
        preliminary = [
            _artifact(root, archive_path, "publication_archive"),
            _artifact(root, archive_digest_path, "archive_digest"),
            _artifact(root, distribution_digest_path, "distribution_manifest_digest"),
            _artifact(root, release_notes, "release_notes"),
            _artifact(root, guide, "handoff_guide"),
            _artifact(root, registration_template, "registration_template"),
            _artifact(root, verifier_path, "remote_verifier"),
        ]
        checksums_path = _write_handoff_checksums(root, preliminary)
        artifacts = {
            item["category"]: item
            for item in [*preliminary, _artifact(root, checksums_path, "checksums")]
        }
        manifest = {
            "schema_version": HANDOFF_SCHEMA_VERSION,
            "handoff_id": handoff_id,
            "created_at": timestamp,
            "distribution": {
                "bundle_id": distribution["bundle_id"],
                "source_path": _stored_project_path(bundle),
                "manifest_sha256": distribution_manifest_sha,
                "release_candidate_id": distribution["release_candidate"]["candidate_id"],
                "release_candidate_manifest_sha256": distribution["release_candidate"][
                    "manifest_sha256"
                ],
                "package_name": distribution["package"]["name"],
                "package_version": distribution["package"]["version"],
                "bundle_file_count": len(inventory),
                "bundle_files": inventory,
            },
            "artifacts": {
                "publication_archive": artifacts["publication_archive"],
                "archive_digest": artifacts["archive_digest"],
                "distribution_manifest_digest": artifacts[
                    "distribution_manifest_digest"
                ],
                "release_notes": artifacts["release_notes"],
                "handoff_guide": artifacts["handoff_guide"],
                "registration_template": artifacts["registration_template"],
                "verifier": artifacts["remote_verifier"],
                "checksums": artifacts["checksums"],
            },
            "state": {
                "handoff_ready_for_upload": True,
                "remote_publication_verified": False,
                "public_release_badge_registration_ready": False,
            },
            "claim_boundaries": dict(FALSE_CLAIM_BOUNDARIES),
        }
        manifest_path = root / HANDOFF_MANIFEST
        _write_yaml(manifest_path, manifest)
        manifest_sha = _sha256(manifest_path)
        (root / HANDOFF_MANIFEST_DIGEST).write_text(
            f"{manifest_sha}  {HANDOFF_MANIFEST}\n", encoding="utf-8"
        )
        result = verify_publication_handoff(root)
        _write_handoff_verification(root, result)
        if not result["handoff_ready_for_upload"]:
            raise ValueError(
                "Constructed publication handoff failed verification: "
                + "; ".join(result["issues"])
            )
        if out.exists():
            raise FileExistsError(f"Publication handoff appeared during creation: {out}")
        shutil.move(str(root), str(out))
    return verify_publication_handoff(out)


def verify_publication_handoff(handoff_dir: str | Path) -> dict[str, Any]:
    root = _project_path(handoff_dir).resolve()
    manifest_path = root / HANDOFF_MANIFEST
    digest_path = root / HANDOFF_MANIFEST_DIGEST
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Handoff manifest is missing: {manifest_path}")
    if not digest_path.is_file():
        raise FileNotFoundError(f"Handoff manifest digest is missing: {digest_path}")
    manifest = _load_yaml(manifest_path)
    issues: list[str] = []
    manifest_sha = _sha256(manifest_path)
    try:
        if _parse_detached_digest(digest_path, HANDOFF_MANIFEST) != manifest_sha:
            issues.append("handoff manifest detached digest mismatch")
    except ValueError as exc:
        issues.append(str(exc))
    if manifest.get("schema_version") != HANDOFF_SCHEMA_VERSION:
        issues.append("handoff schema version drift")
    try:
        _parse_timestamp(manifest.get("created_at"), "created_at")
    except ValueError as exc:
        issues.append(str(exc))
    state = manifest.get("state")
    expected_state = {
        "handoff_ready_for_upload": True,
        "remote_publication_verified": False,
        "public_release_badge_registration_ready": False,
    }
    if state != expected_state:
        issues.append("handoff state was fabricated or prematurely promoted")
    if manifest.get("claim_boundaries") != FALSE_CLAIM_BOUNDARIES:
        issues.append("handoff claim boundaries were weakened")
    artifacts: list[dict[str, Any]] = []
    try:
        artifacts = _handoff_artifacts(manifest)
        for artifact in artifacts:
            _validate_artifact(root, artifact)
        checksum_artifact = manifest["artifacts"]["checksums"]
        expected_checksums = {
            item["path"]: item["sha256"]
            for item in artifacts
            if item["path"] != checksum_artifact["path"]
        }
        actual_checksums = _parse_checksums(
            _validate_artifact(root, checksum_artifact).read_text(encoding="utf-8")
        )
        if actual_checksums != dict(sorted(expected_checksums.items())):
            issues.append("handoff checksum index drift")
    except (FileNotFoundError, ValueError, TypeError) as exc:
        issues.append(f"handoff artifact verification failed: {exc}")
    distribution = manifest.get("distribution")
    if not isinstance(distribution, dict):
        issues.append("handoff distribution binding is missing")
        distribution = {}
    inventory = distribution.get("bundle_files")
    if not isinstance(inventory, list) or len(inventory) != distribution.get(
        "bundle_file_count"
    ):
        issues.append("handoff bundle inventory is invalid")
        inventory = []
    else:
        paths = [item.get("path") for item in inventory if isinstance(item, dict)]
        if len(paths) != len(inventory) or paths != sorted(paths) or len(paths) != len(set(paths)):
            issues.append("handoff bundle inventory paths are invalid")
        for item in inventory:
            try:
                _safe_relative(item["path"])
                if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                    raise ValueError("invalid SHA-256")
                if not isinstance(item["size_bytes"], int) or item["size_bytes"] < 0:
                    raise ValueError("invalid byte count")
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(f"invalid bundle inventory record: {exc}")
                break
    try:
        archive = _validate_artifact(root, manifest["artifacts"]["publication_archive"])
        issues.extend(
            _verify_archive(
                archive,
                distribution.get("bundle_id", ""),
                inventory,
                distribution.get("manifest_sha256", ""),
            )
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        issues.append(f"publication archive verification failed: {exc}")
    source_reconstruction = "not_available"
    source_path = distribution.get("source_path")
    if isinstance(source_path, str):
        bundle = _project_path(source_path)
        if bundle.is_dir():
            try:
                current_distribution = _verify_distribution_bundle_local(bundle)
                current_inventory = _bundle_inventory(bundle)
                if current_distribution.get("bundle_id") != distribution.get("bundle_id"):
                    raise ValueError("source distribution ID drift")
                if current_inventory != inventory:
                    raise ValueError("source distribution inventory drift")
                with tempfile.TemporaryDirectory(prefix="stta-publication-rebuild-") as temp:
                    rebuilt = Path(temp) / "rebuilt.tar.gz"
                    _write_deterministic_archive(bundle, inventory, rebuilt)
                    frozen_archive = _validate_artifact(
                        root, manifest["artifacts"]["publication_archive"]
                    )
                    if rebuilt.read_bytes() != frozen_archive.read_bytes():
                        raise ValueError("publication archive byte reconstruction mismatch")
                source_reconstruction = "passed"
            except (FileNotFoundError, ValueError) as exc:
                source_reconstruction = "failed"
                issues.append(f"source reconstruction failed: {exc}")
    ready = not issues and source_reconstruction != "failed"
    return {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "handoff_id": str(manifest.get("handoff_id", "unknown")),
        "manifest_sha256": manifest_sha,
        "status": "pass" if ready else "fail",
        "handoff_ready_for_upload": ready,
        "source_reconstruction": source_reconstruction,
        "remote_publication_verified": False,
        "public_release_badge_registration_ready": False,
        "issues": list(dict.fromkeys(issues)),
    }


def _write_handoff_verification(root: Path, result: dict[str, Any]) -> None:
    (root / HANDOFF_VERIFICATION_JSON).write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Publication handoff verification",
        "",
        f"- Handoff: `{result['handoff_id']}`",
        f"- Status: `{result['status']}`",
        f"- Ready for upload: `{str(result['handoff_ready_for_upload']).lower()}`",
        "- Remote publication verified: `false`",
        "- Public-release badge registration ready: `false`",
        "",
        "## Issues",
        "",
    ]
    lines.extend(f"- {issue}" for issue in result["issues"])
    if not result["issues"]:
        lines.append("- None")
    (root / HANDOFF_VERIFICATION_MARKDOWN).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _publication_record_claim_boundaries() -> dict[str, bool]:
    return {
        "paper_benchmark_result_claimed": False,
        "held_out_evidence_claimed": False,
        "external_review_claimed": False,
        "named_material_validation_claimed": False,
        "registry_mutated_before_remote_verification": False,
    }


def _validate_publication_url(
    value: str,
    provider: str,
    identifier: str,
    release_tag: str,
    expected_filename: str,
) -> None:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Artifact URL must use HTTPS with a public hostname")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError("Artifact URL may not contain credentials, query, or fragment")
    if parsed.port not in (None, 443):
        raise ValueError("Artifact URL may only use the default HTTPS port")
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Artifact URL may not use a local hostname")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Artifact URL may not use a non-public IP address")
    segments = [urllib.parse.unquote(item) for item in parsed.path.split("/") if item]
    if not segments or segments[-1] != expected_filename:
        raise ValueError("Artifact URL filename does not match the frozen archive")
    mutable = {"latest", "main", "master", "head", "nightly", "snapshot"}
    if any(segment.lower() in mutable for segment in segments):
        raise ValueError("Artifact URL contains a mutable path segment")
    if provider == "github_release":
        match = re.fullmatch(
            rf"/([^/]+)/([^/]+)/releases/download/([^/]+)/{re.escape(expected_filename)}",
            parsed.path,
        )
        if host != "github.com" or not match:
            raise ValueError("GitHub artifact URL must be a versioned release download")
        owner, repository, tag = match.groups()
        if tag != release_tag:
            raise ValueError("GitHub release tag does not match the URL")
        if identifier != f"github:{owner}/{repository}@{tag}":
            raise ValueError("GitHub immutable identifier does not match the URL")
    elif provider == "zenodo":
        match = re.fullmatch(
            rf"/records/(\d+)/files/{re.escape(expected_filename)}", parsed.path
        )
        if host not in {"zenodo.org", "www.zenodo.org"} or not match:
            raise ValueError("Zenodo artifact URL must identify a numbered record file")
        record_id = match.group(1)
        if identifier not in {
            f"zenodo:{record_id}",
            f"doi:10.5281/zenodo.{record_id}",
        }:
            raise ValueError("Zenodo identifier does not match the record URL")
    elif provider == "institutional_archive":
        if not re.fullmatch(r"(?:doi:10\.\S+|handle:\S+|ark:/\S+)", identifier):
            raise ValueError("Institutional archive requires a DOI, Handle, or ARK")
    elif provider == "generic_immutable":
        if not re.fullmatch(r"(?:doi:10\.\S+|handle:\S+|ark:/\S+|swh:\S+)", identifier):
            raise ValueError("Generic immutable provider requires a durable identifier")
    else:
        raise ValueError(f"Unsupported publication provider: {provider}")


def _validate_publication_record(
    record: dict[str, Any], handoff_manifest: dict[str, Any]
) -> None:
    required = {
        "schema_version",
        "status",
        "provider",
        "artifact_url",
        "immutable_identifier",
        "release_tag",
        "published_at",
        "publisher",
        "expected_archive",
        "attestation",
        "claim_boundaries",
    }
    if set(record) != required:
        raise ValueError("Publication record fields drift")
    if record["schema_version"] != PUBLICATION_RECORD_SCHEMA_VERSION:
        raise ValueError("Publication record schema version drift")
    if record["status"] != "published":
        raise ValueError("Publication record is not in published state")
    for field in (
        "provider",
        "artifact_url",
        "immutable_identifier",
        "release_tag",
        "published_at",
        "publisher",
    ):
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError(f"Publication record field is incomplete: {field}")
    _parse_timestamp(record["published_at"], "published_at")
    archive = handoff_manifest["artifacts"]["publication_archive"]
    expected_archive = {
        "filename": Path(archive["path"]).name,
        "sha256": archive["sha256"],
    }
    if record["expected_archive"] != expected_archive:
        raise ValueError("Publication record expected-archive binding drift")
    attestation = record["attestation"]
    if not isinstance(attestation, dict) or set(attestation) != set(
        PUBLICATION_ATTESTATION_KEYS
    ):
        raise ValueError("Publication attestation fields drift")
    if not all(attestation[key] is True for key in PUBLICATION_ATTESTATION_KEYS):
        raise ValueError("Publication attestations are incomplete")
    if record["claim_boundaries"] != _publication_record_claim_boundaries():
        raise ValueError("Publication record claim boundaries were weakened")
    _validate_publication_url(
        record["artifact_url"],
        record["provider"],
        record["immutable_identifier"],
        record["release_tag"],
        expected_archive["filename"],
    )


def _assert_public_transport_url(
    value: str,
    *,
    allow_rfc2544_proxy: bool = False,
) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Remote transport URL is not HTTPS")
    host = parsed.hostname.rstrip(".")
    addresses = {
        item[4][0]
        for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    }
    if not addresses:
        raise ValueError("Remote hostname did not resolve")
    proxy_addresses: list[str] = []
    for resolved in addresses:
        address = ipaddress.ip_address(resolved)
        if address.is_global:
            continue
        if address in RFC2544_PROXY_NETWORK:
            proxy_addresses.append(resolved)
            continue
        raise ValueError("Remote hostname resolves to a forbidden non-public address")
    if proxy_addresses and not allow_rfc2544_proxy:
        raise ValueError("Remote hostname resolves through an RFC2544 proxy address")
    return {
        "hostname": host,
        "resolved_addresses": sorted(addresses),
        "resolution_mode": (
            "rfc2544_https_proxy" if proxy_addresses else "direct_public"
        ),
    }


def _download_public_artifact(
    url: str,
    destination: Path,
    *,
    timeout_seconds: int,
    allow_rfc2544_proxy: bool = False,
) -> dict[str, Any]:
    declared_resolution = _assert_public_transport_url(
        url,
        allow_rfc2544_proxy=allow_rfc2544_proxy,
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "SpinTextureTheoryAgent-publication-verifier/1.0"},
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        final_url = response.geturl()
        final_resolution = _assert_public_transport_url(
            final_url,
            allow_rfc2544_proxy=allow_rfc2544_proxy,
        )
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_REMOTE_ARCHIVE_BYTES:
            raise ValueError("Remote archive exceeds the maximum permitted size")
        total = 0
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_REMOTE_ARCHIVE_BYTES:
                    raise ValueError("Remote archive exceeds the maximum permitted size")
                handle.write(chunk)
        return {
            "declared_url": url,
            "final_url": final_url,
            "declared_resolution": declared_resolution,
            "final_resolution": final_resolution,
            "http_status": getattr(response, "status", 200),
            "content_type": response.headers.get("Content-Type"),
            "content_length_header": content_length,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "downloaded_size_bytes": total,
        }


def verify_remote_publication(
    handoff_dir: str | Path,
    publication_record: str | Path,
    out_dir: str | Path,
    *,
    retrieved_at: str | None = None,
    timeout_seconds: int = 120,
    allow_rfc2544_proxy: bool = False,
) -> dict[str, Any]:
    handoff = _project_path(handoff_dir).resolve()
    record_path = _project_path(publication_record).resolve()
    out = _project_path(out_dir)
    if out.exists():
        raise FileExistsError(f"Remote publication result already exists: {out}")
    timestamp = retrieved_at or datetime.now().astimezone().isoformat(timespec="seconds")
    _parse_timestamp(timestamp, "retrieved_at")
    handoff_result = verify_publication_handoff(handoff)
    if not handoff_result["handoff_ready_for_upload"]:
        raise ValueError("Publication handoff is not ready for remote verification")
    manifest = _load_yaml(handoff / HANDOFF_MANIFEST)
    record = _load_yaml(record_path)
    issues: list[str] = []
    transport: dict[str, Any] = {}
    archive_sha = "0" * 64
    archive_size = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}.", dir=out.parent) as temp:
        root = Path(temp) / out.name
        root.mkdir()
        copied_record = root / "publication_record.yaml"
        shutil.copy2(record_path, copied_record)
        shutil.copy2(handoff / HANDOFF_MANIFEST, root / HANDOFF_MANIFEST)
        shutil.copy2(handoff / HANDOFF_MANIFEST_DIGEST, root / HANDOFF_MANIFEST_DIGEST)
        verifier_copy = root / REMOTE_VERIFIER_COPY
        shutil.copy2(Path(__file__).resolve(), verifier_copy)
        verifier_sha = _sha256(verifier_copy)
        try:
            _validate_publication_record(record, manifest)
            published_at = _parse_timestamp(record["published_at"], "published_at")
            retrieval_time = _parse_timestamp(timestamp, "retrieved_at")
            if published_at > retrieval_time + timedelta(minutes=5):
                raise ValueError("Publication timestamp is later than retrieval time")
            archive = manifest["artifacts"]["publication_archive"]
            downloaded = root / "downloaded" / Path(archive["path"]).name
            downloaded.parent.mkdir(parents=True)
            transport = _download_public_artifact(
                record["artifact_url"],
                downloaded,
                timeout_seconds=timeout_seconds,
                allow_rfc2544_proxy=allow_rfc2544_proxy,
            )
            archive_sha = _sha256(downloaded)
            archive_size = downloaded.stat().st_size
            if archive_sha != archive["sha256"] or archive_size != archive["size_bytes"]:
                issues.append("remote publication archive hash or size mismatch")
            issues.extend(
                _verify_archive(
                    downloaded,
                    manifest["distribution"]["bundle_id"],
                    manifest["distribution"]["bundle_files"],
                    manifest["distribution"]["manifest_sha256"],
                )
            )
        except (
            FileNotFoundError,
            OSError,
            TypeError,
            ValueError,
            urllib.error.URLError,
        ) as exc:
            issues.append(f"remote publication verification failed: {exc}")
        passed = not issues
        result = {
            "schema_version": REMOTE_RESULT_SCHEMA_VERSION,
            "handoff_id": manifest["handoff_id"],
            "handoff_manifest_sha256": handoff_result["manifest_sha256"],
            "status": "pass" if passed else "fail",
            "remote_publication_verified": passed,
            "eligible_for_public_release_registration": passed,
            "registry_mutated": False,
            "verifier_sha256": verifier_sha,
            "network_policy": {
                "allow_rfc2544_proxy": allow_rfc2544_proxy,
                "tls_hostname_validation_required": True,
                "exact_archive_hash_required": True,
            },
            "retrieved_at": timestamp,
            "provider": record.get("provider"),
            "immutable_identifier": record.get("immutable_identifier"),
            "transport": transport,
            "expected_archive_sha256": manifest["artifacts"]["publication_archive"][
                "sha256"
            ],
            "retrieved_archive_sha256": archive_sha,
            "retrieved_archive_size_bytes": archive_size,
            "distribution_manifest_sha256": manifest["distribution"]["manifest_sha256"],
            "claim_boundaries": _publication_record_claim_boundaries(),
            "issues": list(dict.fromkeys(issues)),
        }
        result_path = root / REMOTE_RESULT_JSON
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (root / REMOTE_RESULT_DIGEST).write_text(
            f"{_sha256(result_path)}  {REMOTE_RESULT_JSON}\n", encoding="utf-8"
        )
        _write_remote_markdown(root, result)
        if passed:
            _write_yaml(
                root / PUBLIC_RELEASE_EVIDENCE,
                {
                    "schema_version": "1.0.0",
                    "evidence_axis": "public_release",
                    "status": "passed",
                    "scope": "software_distribution",
                    "handoff_id": manifest["handoff_id"],
                    "provider": record["provider"],
                    "immutable_identifier": record["immutable_identifier"],
                    "artifact_url": record["artifact_url"],
                    "archive_sha256": archive_sha,
                    "distribution_manifest_sha256": manifest["distribution"][
                        "manifest_sha256"
                    ],
                    "remote_verification_record": REMOTE_RESULT_JSON,
                    "remote_verifier": {
                        "path": REMOTE_VERIFIER_COPY,
                        "sha256": verifier_sha,
                    },
                    "network_policy": result["network_policy"],
                    "retrieved_at": timestamp,
                    "registry_registration_requires_separate_change": True,
                    "claim_boundaries": _publication_record_claim_boundaries(),
                },
            )
        if out.exists():
            raise FileExistsError(f"Remote publication result appeared during creation: {out}")
        shutil.move(str(root), str(out))
    return result


def verify_remote_result(result_dir: str | Path) -> dict[str, Any]:
    root = _project_path(result_dir).resolve()
    result_path = root / REMOTE_RESULT_JSON
    digest_path = root / REMOTE_RESULT_DIGEST
    if not result_path.is_file():
        raise FileNotFoundError(f"Remote verification result is missing: {result_path}")
    if not digest_path.is_file():
        raise FileNotFoundError(f"Remote verification digest is missing: {digest_path}")
    issues: list[str] = []
    result = json.loads(result_path.read_text(encoding="utf-8"))
    try:
        if _parse_detached_digest(digest_path, REMOTE_RESULT_JSON) != _sha256(
            result_path
        ):
            issues.append("remote verification detached digest mismatch")
    except ValueError as exc:
        issues.append(str(exc))
    required_fields = {
        "schema_version",
        "handoff_id",
        "handoff_manifest_sha256",
        "status",
        "remote_publication_verified",
        "eligible_for_public_release_registration",
        "registry_mutated",
        "verifier_sha256",
        "network_policy",
        "retrieved_at",
        "provider",
        "immutable_identifier",
        "transport",
        "expected_archive_sha256",
        "retrieved_archive_sha256",
        "retrieved_archive_size_bytes",
        "distribution_manifest_sha256",
        "claim_boundaries",
        "issues",
    }
    if set(result) != required_fields:
        issues.append("remote verification result fields drift")
    if result.get("schema_version") != REMOTE_RESULT_SCHEMA_VERSION:
        issues.append("remote verification schema version drift")
    try:
        _parse_timestamp(result.get("retrieved_at"), "retrieved_at")
    except ValueError as exc:
        issues.append(str(exc))
    if result.get("registry_mutated") is not False:
        issues.append("remote verification improperly claims registry mutation")
    if result.get("claim_boundaries") != _publication_record_claim_boundaries():
        issues.append("remote verification claim boundaries were weakened")
    network_policy = result.get("network_policy")
    if (
        not isinstance(network_policy, dict)
        or set(network_policy)
        != {
            "allow_rfc2544_proxy",
            "tls_hostname_validation_required",
            "exact_archive_hash_required",
        }
        or not isinstance(network_policy.get("allow_rfc2544_proxy"), bool)
        or network_policy.get("tls_hostname_validation_required") is not True
        or network_policy.get("exact_archive_hash_required") is not True
    ):
        issues.append("remote verification network policy is invalid")
    verifier_path = root / REMOTE_VERIFIER_COPY
    if (
        not verifier_path.is_file()
        or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("verifier_sha256", "")))
        or _sha256(verifier_path) != result.get("verifier_sha256")
    ):
        issues.append("remote verifier implementation binding drift")
    claimed_pass = all(
        (
            result.get("status") == "pass",
            result.get("remote_publication_verified") is True,
            result.get("eligible_for_public_release_registration") is True,
            result.get("issues") == [],
        )
    )
    evidence_path = root / PUBLIC_RELEASE_EVIDENCE
    record_path = root / "publication_record.yaml"
    handoff_manifest_path = root / HANDOFF_MANIFEST
    handoff_digest_path = root / HANDOFF_MANIFEST_DIGEST
    handoff_manifest: dict[str, Any] | None = None
    if not handoff_manifest_path.is_file() or not handoff_digest_path.is_file():
        issues.append("remote result lacks the preserved handoff manifest binding")
    else:
        try:
            handoff_manifest = _load_yaml(handoff_manifest_path)
            handoff_sha = _sha256(handoff_manifest_path)
            if (
                _parse_detached_digest(handoff_digest_path, HANDOFF_MANIFEST)
                != handoff_sha
                or handoff_sha != result.get("handoff_manifest_sha256")
            ):
                issues.append("preserved handoff manifest binding drift")
            if handoff_manifest.get("handoff_id") != result.get("handoff_id"):
                issues.append("preserved handoff ID binding drift")
            if handoff_manifest.get("claim_boundaries") != FALSE_CLAIM_BOUNDARIES:
                issues.append("preserved handoff claim boundaries were weakened")
            if handoff_manifest.get("state") != {
                "handoff_ready_for_upload": True,
                "remote_publication_verified": False,
                "public_release_badge_registration_ready": False,
            }:
                issues.append("preserved handoff state drift")
            if (
                handoff_manifest.get("distribution", {}).get("manifest_sha256")
                != result.get("distribution_manifest_sha256")
            ):
                issues.append("preserved distribution-manifest binding drift")
            if (
                handoff_manifest.get("artifacts", {})
                .get("publication_archive", {})
                .get("sha256")
                != result.get("expected_archive_sha256")
            ):
                issues.append("preserved publication-archive binding drift")
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(f"preserved handoff manifest is invalid: {exc}")
    if claimed_pass:
        record: dict[str, Any] | None = None
        if not record_path.is_file():
            issues.append("successful remote verification lacks publication record")
        elif handoff_manifest is None:
            issues.append("publication record cannot be checked without handoff binding")
        else:
            try:
                record = _load_yaml(record_path)
                _validate_publication_record(record, handoff_manifest)
                published_at = _parse_timestamp(record["published_at"], "published_at")
                retrieved_at = _parse_timestamp(result["retrieved_at"], "retrieved_at")
                if published_at > retrieved_at + timedelta(minutes=5):
                    raise ValueError("Publication timestamp is later than retrieval time")
                if (
                    record["provider"] != result.get("provider")
                    or record["immutable_identifier"]
                    != result.get("immutable_identifier")
                ):
                    raise ValueError("Publication record identity binding drift")
                transport = result.get("transport")
                if (
                    not isinstance(transport, dict)
                    or transport.get("declared_url") != record["artifact_url"]
                    or transport.get("http_status") != 200
                    or transport.get("downloaded_size_bytes")
                    != result.get("retrieved_archive_size_bytes")
                ):
                    raise ValueError("Publication transport binding drift")
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(f"publication record binding failed: {exc}")
        if not evidence_path.is_file():
            issues.append("successful remote verification lacks public-release evidence")
        downloaded = root / "downloaded"
        archives = sorted(downloaded.glob("*.tar.gz")) if downloaded.is_dir() else []
        if len(archives) != 1:
            issues.append("successful remote verification must retain exactly one archive")
        else:
            archive = archives[0]
            if (
                _sha256(archive) != result.get("retrieved_archive_sha256")
                or archive.stat().st_size != result.get("retrieved_archive_size_bytes")
                or result.get("retrieved_archive_sha256")
                != result.get("expected_archive_sha256")
            ):
                issues.append("retained remote archive binding drift")
        if evidence_path.is_file():
            evidence = _load_yaml(evidence_path)
            required_evidence = {
                "schema_version",
                "evidence_axis",
                "status",
                "scope",
                "handoff_id",
                "provider",
                "immutable_identifier",
                "artifact_url",
                "archive_sha256",
                "distribution_manifest_sha256",
                "remote_verification_record",
                "remote_verifier",
                "network_policy",
                "retrieved_at",
                "registry_registration_requires_separate_change",
                "claim_boundaries",
            }
            if set(evidence) != required_evidence:
                issues.append("public-release evidence fields drift")
            elif not all(
                (
                    evidence["evidence_axis"] == "public_release",
                    evidence["status"] == "passed",
                    evidence["scope"] == "software_distribution",
                    evidence["handoff_id"] == result.get("handoff_id"),
                    evidence["provider"] == result.get("provider"),
                    evidence["immutable_identifier"]
                    == result.get("immutable_identifier"),
                    record is not None,
                    evidence["artifact_url"]
                    == (record or {}).get("artifact_url"),
                    evidence["archive_sha256"]
                    == result.get("retrieved_archive_sha256"),
                    evidence["distribution_manifest_sha256"]
                    == result.get("distribution_manifest_sha256"),
                    evidence["remote_verification_record"] == REMOTE_RESULT_JSON,
                    evidence["remote_verifier"]
                    == {
                        "path": REMOTE_VERIFIER_COPY,
                        "sha256": result.get("verifier_sha256"),
                    },
                    evidence["network_policy"] == result.get("network_policy"),
                    evidence["retrieved_at"] == result.get("retrieved_at"),
                    evidence["registry_registration_requires_separate_change"] is True,
                    evidence["claim_boundaries"]
                    == _publication_record_claim_boundaries(),
                )
            ):
                issues.append("public-release evidence binding drift")
    else:
        if result.get("status") != "fail":
            issues.append("non-passing remote verification must have fail status")
        if result.get("remote_publication_verified") is not False:
            issues.append("failed remote verification claims remote publication")
        if result.get("eligible_for_public_release_registration") is not False:
            issues.append("failed remote verification claims registration eligibility")
        if evidence_path.exists():
            issues.append("failed remote verification may not contain passed evidence")
    integrity_passed = not issues
    return {
        "schema_version": REMOTE_RESULT_SCHEMA_VERSION,
        "integrity_status": "pass" if integrity_passed else "fail",
        "result_integrity_passed": integrity_passed,
        "remote_publication_verified": claimed_pass and integrity_passed,
        "eligible_for_public_release_registration": claimed_pass and integrity_passed,
        "issues": list(dict.fromkeys(issues)),
    }


def _public_snapshot_summary(result: dict[str, Any], result_sha256: str) -> dict[str, Any]:
    transport = result["transport"]
    final_url = urllib.parse.urlparse(transport["final_url"])
    return {
        "schema_version": PUBLIC_SNAPSHOT_SCHEMA_VERSION,
        "source_remote_result": {
            "schema_version": result["schema_version"],
            "sha256": result_sha256,
        },
        "status": result["status"],
        "remote_publication_verified": result["remote_publication_verified"],
        "eligible_for_public_release_registration": result[
            "eligible_for_public_release_registration"
        ],
        "retrieved_at": result["retrieved_at"],
        "provider": result["provider"],
        "immutable_identifier": result["immutable_identifier"],
        "transport": {
            "declared_url": transport["declared_url"],
            "final_hostname": final_url.hostname,
            "declared_resolution": transport["declared_resolution"],
            "final_resolution": transport["final_resolution"],
            "http_status": transport["http_status"],
            "content_type": transport["content_type"],
            "content_length_header": transport["content_length_header"],
            "etag": transport["etag"],
            "last_modified": transport["last_modified"],
            "downloaded_size_bytes": transport["downloaded_size_bytes"],
        },
        "expected_archive_sha256": result["expected_archive_sha256"],
        "retrieved_archive_sha256": result["retrieved_archive_sha256"],
        "retrieved_archive_size_bytes": result["retrieved_archive_size_bytes"],
        "distribution_manifest_sha256": result["distribution_manifest_sha256"],
        "verifier_sha256": result["verifier_sha256"],
        "network_policy": result["network_policy"],
        "claim_boundaries": result["claim_boundaries"],
        "issues": result["issues"],
    }


def _write_public_snapshot_guide(root: Path) -> Path:
    path = root / PUBLIC_SNAPSHOT_GUIDE
    path.write_text(
        "\n".join(
            [
                "# Verify the Project 1 v0.1.0 public release",
                "",
                "This snapshot binds the immutable publication record, the original",
                "remote-verification metadata, the handoff inventory, and the verifier",
                "implementation. It intentionally does not duplicate the release archive.",
                "",
                "Verify the checked-in evidence without network access:",
                "",
                "```bash",
                "python release_tools/project1_publication.py verify-public-snapshot \\",
                "  --snapshot public_release_evidence/v0.1.0 --require-pass",
                "```",
                "",
                "Re-fetch the immutable release asset and verify its exact bytes and",
                "archive members:",
                "",
                "```bash",
                "python release_tools/project1_publication.py verify-public-snapshot \\",
                "  --snapshot public_release_evidence/v0.1.0 --re-fetch --require-pass",
                "```",
                "",
                "Only documented transparent networks that map public HTTPS hosts into",
                "RFC 2544 range 198.18.0.0/15 may add `--allow-rfc2544-proxy`.",
                "TLS hostname validation and exact archive hashing remain mandatory.",
                "",
                "Passing this check proves public software-distribution integrity only.",
                "It does not prove held-out benchmark performance, external physics",
                "review, or named-material validity.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def create_public_evidence_snapshot(
    remote_result_dir: str | Path,
    out_dir: str | Path,
    *,
    snapshot_id: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    source = _project_path(remote_result_dir).resolve()
    out = _project_path(out_dir)
    if out.exists():
        raise FileExistsError(f"Public evidence snapshot already exists: {out}")
    verified = verify_remote_result(source)
    if not verified["eligible_for_public_release_registration"]:
        raise ValueError("Remote result is not eligible for a public evidence snapshot")
    timestamp = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    _parse_timestamp(timestamp, "created_at")
    result_path = source / REMOTE_RESULT_JSON
    result = json.loads(result_path.read_text(encoding="utf-8"))
    publication_record = _load_yaml(source / "publication_record.yaml")
    handoff_manifest = _load_yaml(source / HANDOFF_MANIFEST)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}.", dir=out.parent) as temp:
        root = Path(temp) / out.name
        root.mkdir()
        copied_names = (
            "publication_record.yaml",
            PUBLIC_RELEASE_EVIDENCE,
            HANDOFF_MANIFEST,
            HANDOFF_MANIFEST_DIGEST,
            REMOTE_VERIFIER_COPY,
        )
        for name in copied_names:
            shutil.copy2(source / name, root / name)
        summary = _public_snapshot_summary(result, _sha256(result_path))
        (root / PUBLIC_SNAPSHOT_SUMMARY).write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        _write_public_snapshot_guide(root)
        artifact_names = (*copied_names, PUBLIC_SNAPSHOT_SUMMARY, PUBLIC_SNAPSHOT_GUIDE)
        artifacts = {
            name: _artifact(root, root / name, "public_release_evidence")
            for name in sorted(artifact_names)
        }
        archive = handoff_manifest["artifacts"]["publication_archive"]
        manifest = {
            "schema_version": PUBLIC_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "created_at": timestamp,
            "source_remote_result": summary["source_remote_result"],
            "publication": {
                "provider": publication_record["provider"],
                "immutable_identifier": publication_record["immutable_identifier"],
                "release_tag": publication_record["release_tag"],
                "artifact_url": publication_record["artifact_url"],
            },
            "release_binding": {
                "handoff_id": result["handoff_id"],
                "handoff_manifest_sha256": result["handoff_manifest_sha256"],
                "archive_filename": Path(archive["path"]).name,
                "archive_sha256": result["retrieved_archive_sha256"],
                "archive_size_bytes": result["retrieved_archive_size_bytes"],
                "distribution_manifest_sha256": result[
                    "distribution_manifest_sha256"
                ],
                "verifier_sha256": result["verifier_sha256"],
            },
            "network_policy": result["network_policy"],
            "claim_boundaries": result["claim_boundaries"],
            "state": {
                "source_remote_result_verified": True,
                "public_release_registration_eligible": True,
                "retained_archive_in_snapshot": False,
                "remote_refetch_supported": True,
                "claim_scope": "software_distribution",
            },
            "artifacts": artifacts,
        }
        _write_yaml(root / PUBLIC_SNAPSHOT_MANIFEST, manifest)
        (root / PUBLIC_SNAPSHOT_DIGEST).write_text(
            f"{_sha256(root / PUBLIC_SNAPSHOT_MANIFEST)}  {PUBLIC_SNAPSHOT_MANIFEST}\n",
            encoding="utf-8",
        )
        if out.exists():
            raise FileExistsError(f"Public evidence snapshot appeared during creation: {out}")
        shutil.move(str(root), str(out))
    result = verify_public_evidence_snapshot(out)
    if not result["snapshot_integrity_passed"]:
        raise ValueError("Constructed public evidence snapshot failed verification")
    return result


def verify_public_evidence_snapshot(
    snapshot_dir: str | Path,
    *,
    re_fetch: bool = False,
    timeout_seconds: int = 120,
    allow_rfc2544_proxy: bool = False,
) -> dict[str, Any]:
    root = _project_path(snapshot_dir).resolve()
    issues: list[str] = []
    manifest_path = root / PUBLIC_SNAPSHOT_MANIFEST
    digest_path = root / PUBLIC_SNAPSHOT_DIGEST
    if not manifest_path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("Public evidence snapshot manifest or digest is missing")
    manifest = _load_yaml(manifest_path)
    expected_manifest_fields = {
        "schema_version",
        "snapshot_id",
        "created_at",
        "source_remote_result",
        "publication",
        "release_binding",
        "network_policy",
        "claim_boundaries",
        "state",
        "artifacts",
    }
    if set(manifest) != expected_manifest_fields:
        issues.append("public evidence snapshot manifest fields drift")
    if manifest.get("schema_version") != PUBLIC_SNAPSHOT_SCHEMA_VERSION:
        issues.append("public evidence snapshot schema version drift")
    try:
        _parse_timestamp(manifest.get("created_at"), "created_at")
        if _parse_detached_digest(digest_path, PUBLIC_SNAPSHOT_MANIFEST) != _sha256(
            manifest_path
        ):
            issues.append("public evidence snapshot detached digest mismatch")
    except ValueError as exc:
        issues.append(str(exc))
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        issues.append("public evidence snapshot artifact registry is invalid")
        artifacts = {}
    required_artifacts = {
        "publication_record.yaml",
        PUBLIC_RELEASE_EVIDENCE,
        HANDOFF_MANIFEST,
        HANDOFF_MANIFEST_DIGEST,
        REMOTE_VERIFIER_COPY,
        PUBLIC_SNAPSHOT_SUMMARY,
        PUBLIC_SNAPSHOT_GUIDE,
    }
    if set(artifacts) != required_artifacts:
        issues.append("public evidence snapshot artifact registry fields drift")
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            issues.append(f"public snapshot artifact record is invalid: {name}")
            continue
        if name != artifact.get("path"):
            issues.append(f"public snapshot artifact path binding drift: {name}")
            continue
        try:
            _validate_artifact(root, artifact)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            issues.append(str(exc))
    expected_files = required_artifacts | {
        PUBLIC_SNAPSHOT_MANIFEST,
        PUBLIC_SNAPSHOT_DIGEST,
    }
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if actual_files != expected_files:
        issues.append("public evidence snapshot file set drift")
    if any(path.is_symlink() for path in root.rglob("*")):
        issues.append("public evidence snapshot may not contain symbolic links")
    if any(path.name.endswith((".tar.gz", ".whl", ".zip")) for path in root.rglob("*")):
        issues.append("public evidence snapshot improperly duplicates a release artifact")

    publication: dict[str, Any] = {}
    handoff: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    try:
        publication = _load_yaml(root / "publication_record.yaml")
        handoff = _load_yaml(root / HANDOFF_MANIFEST)
        evidence = _load_yaml(root / PUBLIC_RELEASE_EVIDENCE)
        summary = json.loads((root / PUBLIC_SNAPSHOT_SUMMARY).read_text(encoding="utf-8"))
        expected_summary_fields = {
            "schema_version",
            "source_remote_result",
            "status",
            "remote_publication_verified",
            "eligible_for_public_release_registration",
            "retrieved_at",
            "provider",
            "immutable_identifier",
            "transport",
            "expected_archive_sha256",
            "retrieved_archive_sha256",
            "retrieved_archive_size_bytes",
            "distribution_manifest_sha256",
            "verifier_sha256",
            "network_policy",
            "claim_boundaries",
            "issues",
        }
        expected_summary_transport_fields = {
            "declared_url",
            "final_hostname",
            "declared_resolution",
            "final_resolution",
            "http_status",
            "content_type",
            "content_length_header",
            "etag",
            "last_modified",
            "downloaded_size_bytes",
        }
        expected_evidence_fields = {
            "schema_version",
            "evidence_axis",
            "status",
            "scope",
            "handoff_id",
            "provider",
            "immutable_identifier",
            "artifact_url",
            "archive_sha256",
            "distribution_manifest_sha256",
            "remote_verification_record",
            "remote_verifier",
            "network_policy",
            "retrieved_at",
            "registry_registration_requires_separate_change",
            "claim_boundaries",
        }
        if set(summary) != expected_summary_fields:
            raise ValueError("public snapshot summary fields drift")
        if set(summary.get("transport", {})) != expected_summary_transport_fields:
            raise ValueError("public snapshot summary transport fields drift")
        if set(evidence) != expected_evidence_fields:
            raise ValueError("public-release evidence fields drift")
        _validate_publication_record(publication, handoff)
        handoff_sha = _sha256(root / HANDOFF_MANIFEST)
        if (
            _parse_detached_digest(root / HANDOFF_MANIFEST_DIGEST, HANDOFF_MANIFEST)
            != handoff_sha
        ):
            raise ValueError("preserved handoff manifest digest mismatch")
        release_binding = manifest["release_binding"]
        archive = handoff["artifacts"]["publication_archive"]
        expected_release_binding = {
            "handoff_id": handoff["handoff_id"],
            "handoff_manifest_sha256": handoff_sha,
            "archive_filename": Path(archive["path"]).name,
            "archive_sha256": archive["sha256"],
            "archive_size_bytes": archive["size_bytes"],
            "distribution_manifest_sha256": handoff["distribution"][
                "manifest_sha256"
            ],
            "verifier_sha256": _sha256(root / REMOTE_VERIFIER_COPY),
        }
        if release_binding != expected_release_binding:
            raise ValueError("public snapshot release binding drift")
        expected_publication = {
            key: publication[key]
            for key in ("provider", "immutable_identifier", "release_tag", "artifact_url")
        }
        if manifest["publication"] != expected_publication:
            raise ValueError("public snapshot publication binding drift")
        expected_state = {
            "source_remote_result_verified": True,
            "public_release_registration_eligible": True,
            "retained_archive_in_snapshot": False,
            "remote_refetch_supported": True,
            "claim_scope": "software_distribution",
        }
        if manifest["state"] != expected_state:
            raise ValueError("public snapshot state drift")
        if manifest["claim_boundaries"] != _publication_record_claim_boundaries():
            raise ValueError("public snapshot claim boundaries were weakened")
        if manifest["network_policy"] != summary["network_policy"]:
            raise ValueError("public snapshot network-policy binding drift")
        if manifest["source_remote_result"] != summary["source_remote_result"]:
            raise ValueError("public snapshot source-result binding drift")
        if not all(
            (
                summary["schema_version"] == PUBLIC_SNAPSHOT_SCHEMA_VERSION,
                summary["status"] == "pass",
                summary["remote_publication_verified"] is True,
                summary["eligible_for_public_release_registration"] is True,
                summary["provider"] == publication["provider"],
                summary["immutable_identifier"] == publication["immutable_identifier"],
                summary["transport"]["declared_url"] == publication["artifact_url"],
                summary["transport"]["http_status"] == 200,
                summary["expected_archive_sha256"] == archive["sha256"],
                summary["retrieved_archive_sha256"] == archive["sha256"],
                summary["retrieved_archive_size_bytes"] == archive["size_bytes"],
                summary["distribution_manifest_sha256"]
                == handoff["distribution"]["manifest_sha256"],
                summary["verifier_sha256"] == _sha256(root / REMOTE_VERIFIER_COPY),
                summary["claim_boundaries"] == _publication_record_claim_boundaries(),
                summary["issues"] == [],
            )
        ):
            raise ValueError("public snapshot remote-verification summary drift")
        if not all(
            (
                evidence["evidence_axis"] == "public_release",
                evidence["status"] == "passed",
                evidence["scope"] == "software_distribution",
                evidence["immutable_identifier"] == publication["immutable_identifier"],
                evidence["artifact_url"] == publication["artifact_url"],
                evidence["archive_sha256"] == archive["sha256"],
                evidence["distribution_manifest_sha256"]
                == handoff["distribution"]["manifest_sha256"],
                evidence["remote_verifier"]["sha256"]
                == _sha256(root / REMOTE_VERIFIER_COPY),
                evidence["claim_boundaries"] == _publication_record_claim_boundaries(),
            )
        ):
            raise ValueError("public-release evidence binding drift")
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        issues.append(str(exc))

    snapshot_integrity_passed = not issues
    refetch_status = "not_requested"
    refetch_transport: dict[str, Any] = {}
    if re_fetch and not issues:
        try:
            with tempfile.TemporaryDirectory(prefix="stta-public-refetch-") as temp:
                downloaded = Path(temp) / manifest["release_binding"]["archive_filename"]
                refetch_transport = _download_public_artifact(
                    publication["artifact_url"],
                    downloaded,
                    timeout_seconds=timeout_seconds,
                    allow_rfc2544_proxy=allow_rfc2544_proxy,
                )
                if (
                    _sha256(downloaded) != manifest["release_binding"]["archive_sha256"]
                    or downloaded.stat().st_size
                    != manifest["release_binding"]["archive_size_bytes"]
                ):
                    raise ValueError("re-fetched public archive hash or size mismatch")
                archive_issues = _verify_archive(
                    downloaded,
                    handoff["distribution"]["bundle_id"],
                    handoff["distribution"]["bundle_files"],
                    handoff["distribution"]["manifest_sha256"],
                )
                if archive_issues:
                    raise ValueError("; ".join(archive_issues))
            refetch_status = "passed"
        except (OSError, TypeError, ValueError, urllib.error.URLError) as exc:
            issues.append(f"public release re-fetch failed: {exc}")
            refetch_status = "failed"
    passed = snapshot_integrity_passed and (
        not re_fetch or refetch_status == "passed"
    )
    return {
        "schema_version": PUBLIC_SNAPSHOT_SCHEMA_VERSION,
        "status": "pass" if passed else "fail",
        "snapshot_integrity_passed": snapshot_integrity_passed,
        "remote_refetch": refetch_status,
        "remote_refetch_transport": refetch_transport,
        "release_identifier": manifest.get("publication", {}).get(
            "immutable_identifier"
        ),
        "archive_sha256": manifest.get("release_binding", {}).get("archive_sha256"),
        "claim_scope": manifest.get("state", {}).get("claim_scope"),
        "issues": list(dict.fromkeys(issues)),
    }


def _write_remote_markdown(root: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Remote publication verification",
        "",
        f"- Handoff: `{result['handoff_id']}`",
        f"- Status: `{result['status']}`",
        (
            "- Remote publication verified: "
            f"`{str(result['remote_publication_verified']).lower()}`"
        ),
        (
            "- Eligible for public-release registration: "
            f"`{str(result['eligible_for_public_release_registration']).lower()}`"
        ),
        "- Registry mutated: `false`",
        "",
        "## Issues",
        "",
    ]
    lines.extend(f"- {issue}" for issue in result["issues"])
    if not result["issues"]:
        lines.append("- None")
    (root / REMOTE_RESULT_MARKDOWN).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and verify Project 1 durable-publication sidecars"
    )
    sub = parser.add_subparsers(required=True, dest="command")
    create = sub.add_parser("create-handoff")
    create.add_argument("--distribution", default=str(DEFAULT_DISTRIBUTION))
    create.add_argument("--out", default=str(DEFAULT_HANDOFF))
    create.add_argument("--handoff-id", default=DEFAULT_HANDOFF_ID)
    create.add_argument("--created-at", default=None)

    verify = sub.add_parser("verify-handoff")
    verify.add_argument("--handoff", required=True)
    verify.add_argument("--require-ready", action="store_true")

    remote = sub.add_parser("verify-remote")
    remote.add_argument("--handoff", required=True)
    remote.add_argument("--record", required=True)
    remote.add_argument("--out", required=True)
    remote.add_argument("--retrieved-at", default=None)
    remote.add_argument("--timeout", type=int, default=120)
    remote.add_argument("--allow-rfc2544-proxy", action="store_true")
    remote.add_argument("--require-pass", action="store_true")

    remote_result = sub.add_parser("verify-remote-result")
    remote_result.add_argument("--result", required=True)
    remote_result.add_argument("--require-eligible", action="store_true")

    snapshot_create = sub.add_parser("create-public-snapshot")
    snapshot_create.add_argument("--result", required=True)
    snapshot_create.add_argument("--out", required=True)
    snapshot_create.add_argument("--snapshot-id", required=True)
    snapshot_create.add_argument("--created-at", default=None)

    snapshot_verify = sub.add_parser("verify-public-snapshot")
    snapshot_verify.add_argument("--snapshot", required=True)
    snapshot_verify.add_argument("--re-fetch", action="store_true")
    snapshot_verify.add_argument("--timeout", type=int, default=120)
    snapshot_verify.add_argument("--allow-rfc2544-proxy", action="store_true")
    snapshot_verify.add_argument("--require-pass", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "create-handoff":
        result = create_publication_handoff(
            args.distribution,
            args.out,
            handoff_id=args.handoff_id,
            created_at=args.created_at,
        )
    elif args.command == "verify-remote":
        result = verify_remote_publication(
            args.handoff,
            args.record,
            args.out,
            retrieved_at=args.retrieved_at,
            timeout_seconds=args.timeout,
            allow_rfc2544_proxy=args.allow_rfc2544_proxy,
        )
        if args.require_pass and not result["remote_publication_verified"]:
            _print_result(result)
            raise SystemExit(1)
    elif args.command == "verify-remote-result":
        result = verify_remote_result(args.result)
        if args.require_eligible and not result[
            "eligible_for_public_release_registration"
        ]:
            _print_result(result)
            raise SystemExit(1)
    elif args.command == "create-public-snapshot":
        result = create_public_evidence_snapshot(
            args.result,
            args.out,
            snapshot_id=args.snapshot_id,
            created_at=args.created_at,
        )
    elif args.command == "verify-public-snapshot":
        result = verify_public_evidence_snapshot(
            args.snapshot,
            re_fetch=args.re_fetch,
            timeout_seconds=args.timeout,
            allow_rfc2544_proxy=args.allow_rfc2544_proxy,
        )
        if args.require_pass and not result["snapshot_integrity_passed"]:
            _print_result(result)
            raise SystemExit(1)
    else:
        result = verify_publication_handoff(args.handoff)
        if args.require_ready and not result["handoff_ready_for_upload"]:
            _print_result(result)
            raise SystemExit(1)
    _print_result(result)


if __name__ == "__main__":
    main()
