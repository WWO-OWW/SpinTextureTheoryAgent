from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import urllib.error
import urllib.parse
import zipfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

try:
    import release_tools.project1_publication as publication_transport
except ModuleNotFoundError as exc:
    if exc.name != "release_tools":
        raise
    import project1_publication as publication_transport

from spintexture_agent.benchmark_collection import (
    ARCHIVE_NAME,
    ARCHIVE_ROOT,
    COLLECTION_ID,
    RELEASE_INDEX_DIGEST_FILE,
    RELEASE_INDEX_FILE,
    RELEASE_PAYLOAD_DIR,
    CollectionReleaseIndex,
    verify_collection_release,
)


_download_public_artifact = publication_transport._download_public_artifact
_parse_timestamp = publication_transport._parse_timestamp
_sha256 = publication_transport._sha256


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "1.0.0"
DEFAULT_COLLECTION_RELEASE = (
    PROJECT_ROOT / "benchmark_collection_releases" / "v1" / "round_01"
)
DEFAULT_HANDOFF_ID = "project1_benchmark_v1_round01_publication01"
DEFAULT_HANDOFF = (
    PROJECT_ROOT
    / "analysis"
    / "collection_publication_handoffs"
    / DEFAULT_HANDOFF_ID
)
HANDOFF_MANIFEST = "collection_publication_handoff.yaml"
HANDOFF_DIGEST = "collection_publication_handoff.sha256"
REGISTRATION_TEMPLATE = "collection_publication_registration.yaml"
REMOTE_RESULT = "collection_remote_verification.json"
REMOTE_RESULT_DIGEST = "collection_remote_verification.sha256"
PUBLIC_EVIDENCE = "collection_publication_evidence.yaml"
VERIFIER_COPY = "collection_verifier.py"
TRANSPORT_COPY = "publication_transport.py"

ASSET_KEYS = ("archive", "release_index", "release_index_digest")
ASSET_FILENAMES = {
    "archive": ARCHIVE_NAME,
    "release_index": RELEASE_INDEX_FILE,
    "release_index_digest": RELEASE_INDEX_DIGEST_FILE,
}

CLAIM_BOUNDARIES = {
    "held_out_cases_collected": False,
    "readability_cases_collected": False,
    "participant_identities_recorded": False,
    "human_ratings_recorded": False,
    "benchmark_performance_claimed": False,
    "external_review_claimed": False,
    "software_v0_1_0_release_mutated": False,
}


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


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


def _artifact(root: Path, path: Path, category: str) -> dict[str, Any]:
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return {
        "path": relative,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        "category": category,
    }


def _validate_artifact(root: Path, record: dict[str, Any]) -> Path:
    if not isinstance(record, dict):
        raise TypeError("Collection publication artifact record must be a mapping")
    if set(record) != {"path", "sha256", "size_bytes", "category"}:
        raise ValueError("Collection publication artifact fields drift")
    path = _resolve_relative(root, str(record["path"]))
    if not path.is_file():
        raise FileNotFoundError(f"Collection publication artifact is missing: {path}")
    if (
        path.stat().st_size != record["size_bytes"]
        or _sha256(path) != record["sha256"]
    ):
        raise ValueError(f"Collection publication artifact drift: {record['path']}")
    return path


def _parse_detached_digest(path: Path, expected_name: str) -> str:
    match = re.fullmatch(
        rf"([0-9a-f]{{64}})  {re.escape(expected_name)}\n",
        path.read_text(encoding="utf-8"),
    )
    if not match:
        raise ValueError(f"Detached digest format is invalid: {path}")
    return match.group(1)


def _collection_assets(root: Path) -> dict[str, Path]:
    return {key: root / filename for key, filename in ASSET_FILENAMES.items()}


def _verify_source_collection(root: Path) -> tuple[CollectionReleaseIndex, dict[str, Any]]:
    verification = verify_collection_release(root)
    if not verification.ready_for_distribution:
        raise ValueError(
            "Collection release is not distribution-ready: "
            + "; ".join(verification.issues)
        )
    if (
        verification.invited_identity_count != 0
        or verification.submitted_case_count != 0
    ):
        raise ValueError("Collection publication source is not the blank launch release")
    index = CollectionReleaseIndex.model_validate(
        _load_yaml(root / RELEASE_INDEX_FILE)
    )
    if (
        index.collection_id != COLLECTION_ID
        or index.authoring_packet_case_count != 0
        or index.participant_identity_count != 0
        or index.submitted_case_count != 0
        or index.real_manifests_modified is not False
    ):
        raise ValueError("Collection release index exceeds the blank-launch claim scope")
    return index, verification.model_dump(mode="json")


def _materialize_downloaded_collection(asset_root: Path, destination: Path) -> None:
    assets = _collection_assets(asset_root)
    index = CollectionReleaseIndex.model_validate(_load_yaml(assets["release_index"]))
    destination.mkdir(parents=True)
    for key in ASSET_KEYS:
        shutil.copy2(assets[key], destination / ASSET_FILENAMES[key])
    payload = destination / RELEASE_PAYLOAD_DIR
    payload.mkdir()
    expected_members = [
        f"{ARCHIVE_ROOT}/{artifact.path}" for artifact in index.payload_artifacts
    ]
    with zipfile.ZipFile(assets["archive"], "r") as archive:
        infos = archive.infolist()
        if [info.filename for info in infos] != expected_members:
            raise ValueError("Downloaded collection archive membership or order drift")
        for info, artifact in zip(infos, index.payload_artifacts, strict=True):
            relative = _safe_relative(artifact.path)
            target = _resolve_relative(payload, relative.as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(info)
            target.write_bytes(data)
            if target.stat().st_size != artifact.size_bytes or _sha256(target) != artifact.sha256:
                raise ValueError(f"Downloaded collection payload drift: {artifact.path}")


def _verify_asset_set(asset_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stta-collection-publication-") as temp:
        materialized = Path(temp) / "round_01"
        _materialize_downloaded_collection(asset_root, materialized)
        _, verification = _verify_source_collection(materialized)
    return verification


def create_handoff(
    collection_dir: str | Path = DEFAULT_COLLECTION_RELEASE,
    out_dir: str | Path = DEFAULT_HANDOFF,
    *,
    handoff_id: str = DEFAULT_HANDOFF_ID,
    created_at: str | None = None,
) -> dict[str, Any]:
    source = _project_path(collection_dir).resolve()
    out = _project_path(out_dir)
    if out.exists():
        raise FileExistsError(f"Collection publication handoff already exists: {out}")
    timestamp = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    _parse_timestamp(timestamp, "created_at")
    _, source_verification = _verify_source_collection(source)
    source_assets = _collection_assets(source)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}.", dir=out.parent) as temp:
        root = Path(temp) / out.name
        payload = root / "payload"
        verifier_dir = root / "verifier"
        payload.mkdir(parents=True)
        verifier_dir.mkdir()
        copied_assets: dict[str, Path] = {}
        for key in ASSET_KEYS:
            copied_assets[key] = payload / ASSET_FILENAMES[key]
            shutil.copy2(source_assets[key], copied_assets[key])
        verifier = verifier_dir / VERIFIER_COPY
        transport = verifier_dir / TRANSPORT_COPY
        shutil.copy2(Path(__file__).resolve(), verifier)
        shutil.copy2(Path(publication_transport.__file__).resolve(), transport)
        registration = root / REGISTRATION_TEMPLATE
        _write_yaml(
            registration,
            {
                "schema_version": SCHEMA_VERSION,
                "status": "pending_publication",
                "provider": None,
                "repository": None,
                "release_tag": None,
                "immutable_identifier": None,
                "published_at": None,
                "publisher": None,
                "assets": {
                    key: {
                        "filename": ASSET_FILENAMES[key],
                        "url": None,
                        "sha256": _sha256(copied_assets[key]),
                        "size_bytes": copied_assets[key].stat().st_size,
                    }
                    for key in ASSET_KEYS
                },
                "attestation": {
                    "dedicated_collection_release": False,
                    "all_exact_assets_uploaded": False,
                    "provider_record_public": False,
                    "software_v0_1_0_untouched": False,
                },
                "claim_boundaries": CLAIM_BOUNDARIES,
            },
        )
        guide = root / "PUBLICATION.md"
        guide.write_text(
            "\n".join(
                [
                    "# Round-01 collection publication handoff",
                    "",
                    "Publish the three exact files under `payload/` in a dedicated",
                    "versioned release. Do not add them to or alter software release",
                    "`v0.1.0`. Complete the registration record only after publication,",
                    "then run this verifier's `verify-remote` command.",
                    "",
                    "This blank collection release contains 0 participant identities,",
                    "0 submitted cases, and 0 human ratings. Publication does not create",
                    "held-out benchmark or readability evidence.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        artifacts = {
            **{
                key: _artifact(root, copied_assets[key], "collection_release_asset")
                for key in ASSET_KEYS
            },
            "registration_template": _artifact(root, registration, "registration"),
            "guide": _artifact(root, guide, "documentation"),
            "verifier": _artifact(root, verifier, "verifier"),
            "transport": _artifact(root, transport, "verifier_dependency"),
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "handoff_id": handoff_id,
            "collection_id": COLLECTION_ID,
            "created_at": timestamp,
            "source_path": str(source),
            "source_verification": source_verification,
            "assets": artifacts,
            "state": {
                "handoff_ready": True,
                "remote_publication_verified": False,
                "collection_publication_evidence_ready": False,
            },
            "claim_boundaries": CLAIM_BOUNDARIES,
        }
        _write_yaml(root / HANDOFF_MANIFEST, manifest)
        (root / HANDOFF_DIGEST).write_text(
            f"{_sha256(root / HANDOFF_MANIFEST)}  {HANDOFF_MANIFEST}\n",
            encoding="utf-8",
        )
        if out.exists():
            raise FileExistsError(f"Collection handoff appeared during creation: {out}")
        shutil.move(str(root), str(out))
    result = verify_handoff(out)
    if not result["handoff_ready"]:
        raise ValueError("Constructed collection publication handoff failed verification")
    return result


def verify_handoff(handoff_dir: str | Path) -> dict[str, Any]:
    root = _project_path(handoff_dir).resolve()
    manifest_path = root / HANDOFF_MANIFEST
    digest_path = root / HANDOFF_DIGEST
    if not manifest_path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("Collection publication handoff manifest or digest is missing")
    issues: list[str] = []
    manifest = _load_yaml(manifest_path)
    expected_fields = {
        "schema_version",
        "handoff_id",
        "collection_id",
        "created_at",
        "source_path",
        "source_verification",
        "assets",
        "state",
        "claim_boundaries",
    }
    if set(manifest) != expected_fields:
        issues.append("collection handoff manifest fields drift")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        issues.append("collection handoff schema version drift")
    if manifest.get("collection_id") != COLLECTION_ID:
        issues.append("collection handoff ID drift")
    try:
        _parse_timestamp(manifest.get("created_at"), "created_at")
        if _parse_detached_digest(digest_path, HANDOFF_MANIFEST) != _sha256(manifest_path):
            issues.append("collection handoff detached digest mismatch")
    except ValueError as exc:
        issues.append(str(exc))
    if manifest.get("state") != {
        "handoff_ready": True,
        "remote_publication_verified": False,
        "collection_publication_evidence_ready": False,
    }:
        issues.append("collection handoff state was prematurely promoted")
    if manifest.get("claim_boundaries") != CLAIM_BOUNDARIES:
        issues.append("collection handoff claim boundaries were weakened")
    artifacts = manifest.get("assets")
    required_artifacts = {
        *ASSET_KEYS,
        "registration_template",
        "guide",
        "verifier",
        "transport",
    }
    if not isinstance(artifacts, dict) or set(artifacts) != required_artifacts:
        issues.append("collection handoff artifact registry drift")
        artifacts = {}
    for record in artifacts.values():
        try:
            _validate_artifact(root, record)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            issues.append(str(exc))
    try:
        source = Path(str(manifest["source_path"]))
        if source.is_dir():
            _, source_verification = _verify_source_collection(source)
            if source_verification != manifest["source_verification"]:
                raise ValueError("collection source verification binding drift")
        with tempfile.TemporaryDirectory(prefix="stta-collection-handoff-") as temp:
            assets_root = Path(temp)
            for key in ASSET_KEYS:
                shutil.copy2(
                    _validate_artifact(root, artifacts[key]),
                    assets_root / ASSET_FILENAMES[key],
                )
            _verify_asset_set(assets_root)
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError, zipfile.BadZipFile) as exc:
        issues.append(f"collection handoff payload verification failed: {exc}")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if not issues else "fail",
        "handoff_ready": not issues,
        "remote_publication_verified": False,
        "collection_publication_evidence_ready": False,
        "manifest_sha256": _sha256(manifest_path),
        "collection_id": manifest.get("collection_id"),
        "participant_identity_count": 0,
        "submitted_case_count": 0,
        "human_rating_count": 0,
        "issues": list(dict.fromkeys(issues)),
    }


def _validate_asset_url(
    url: str,
    *,
    repository: str,
    release_tag: str,
    filename: str,
    identifier: str,
) -> None:
    if not all(
        isinstance(value, str) and value.strip()
        for value in (url, repository, release_tag, filename, identifier)
    ):
        raise ValueError("Collection publication URL binding is incomplete")
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ) or not re.fullmatch(r"[A-Za-z0-9._-]+", release_tag):
        raise ValueError("Collection repository or release tag format is invalid")
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Collection asset URL must be a clean GitHub HTTPS URL")
    owner, repo = repository.split("/", 1)
    expected = f"/{owner}/{repo}/releases/download/{release_tag}/{filename}"
    if parsed.path != expected:
        raise ValueError("Collection asset URL does not match repository, tag, or filename")
    if identifier != f"github:{repository}@{release_tag}":
        raise ValueError("Collection publication immutable identifier drift")
    if release_tag in {"latest", "main", "master", "nightly", "snapshot", "v0.1.0"}:
        raise ValueError("Collection publication must use a dedicated immutable tag")


def _validate_publication_record(
    record: dict[str, Any], manifest: dict[str, Any]
) -> None:
    required = {
        "schema_version",
        "status",
        "provider",
        "repository",
        "release_tag",
        "immutable_identifier",
        "published_at",
        "publisher",
        "assets",
        "attestation",
        "claim_boundaries",
    }
    if set(record) != required:
        raise ValueError("Collection publication record fields drift")
    if record["schema_version"] != SCHEMA_VERSION or record["status"] != "published":
        raise ValueError("Collection publication record is not published")
    if record["provider"] != "github_release":
        raise ValueError("Collection publication provider is unsupported")
    for field in (
        "repository",
        "release_tag",
        "immutable_identifier",
        "published_at",
        "publisher",
    ):
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError(f"Collection publication field is incomplete: {field}")
    _parse_timestamp(record["published_at"], "published_at")
    if record["claim_boundaries"] != CLAIM_BOUNDARIES:
        raise ValueError("Collection publication claim boundaries were weakened")
    if record["attestation"] != {
        "dedicated_collection_release": True,
        "all_exact_assets_uploaded": True,
        "provider_record_public": True,
        "software_v0_1_0_untouched": True,
    }:
        raise ValueError("Collection publication attestations are incomplete")
    if not isinstance(record["assets"], dict) or set(record["assets"]) != set(ASSET_KEYS):
        raise ValueError("Collection publication asset registry drift")
    for key in ASSET_KEYS:
        expected = manifest["assets"][key]
        actual = record["assets"][key]
        if not isinstance(actual, dict):
            raise ValueError(f"Collection publication asset is not a mapping: {key}")
        if set(actual) != {"filename", "url", "sha256", "size_bytes"}:
            raise ValueError(f"Collection publication asset fields drift: {key}")
        if (
            actual["filename"] != ASSET_FILENAMES[key]
            or actual["sha256"] != expected["sha256"]
            or actual["size_bytes"] != expected["size_bytes"]
        ):
            raise ValueError(f"Collection publication asset binding drift: {key}")
        _validate_asset_url(
            actual["url"],
            repository=record["repository"],
            release_tag=record["release_tag"],
            filename=ASSET_FILENAMES[key],
            identifier=record["immutable_identifier"],
        )


def verify_remote(
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
        raise FileExistsError(f"Collection remote verification already exists: {out}")
    handoff_result = verify_handoff(handoff)
    if not handoff_result["handoff_ready"]:
        raise ValueError("Collection publication handoff is not ready")
    manifest = _load_yaml(handoff / HANDOFF_MANIFEST)
    record = _load_yaml(record_path)
    timestamp = retrieved_at or datetime.now().astimezone().isoformat(timespec="seconds")
    _parse_timestamp(timestamp, "retrieved_at")
    issues: list[str] = []
    transport: dict[str, Any] = {}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{out.name}.", dir=out.parent) as temp:
        root = Path(temp) / out.name
        root.mkdir()
        shutil.copy2(record_path, root / "publication_record.yaml")
        shutil.copy2(handoff / HANDOFF_MANIFEST, root / HANDOFF_MANIFEST)
        shutil.copy2(handoff / HANDOFF_DIGEST, root / HANDOFF_DIGEST)
        shutil.copy2(Path(__file__).resolve(), root / VERIFIER_COPY)
        shutil.copy2(
            Path(publication_transport.__file__).resolve(), root / TRANSPORT_COPY
        )
        try:
            _validate_publication_record(record, manifest)
            published = _parse_timestamp(record["published_at"], "published_at")
            retrieved = _parse_timestamp(timestamp, "retrieved_at")
            if published > retrieved + timedelta(minutes=5):
                raise ValueError("Collection publication timestamp is later than retrieval")
            downloaded = root / "downloaded"
            downloaded.mkdir()
            for key in ASSET_KEYS:
                destination = downloaded / ASSET_FILENAMES[key]
                transport[key] = _download_public_artifact(
                    record["assets"][key]["url"],
                    destination,
                    timeout_seconds=timeout_seconds,
                    allow_rfc2544_proxy=allow_rfc2544_proxy,
                )
                expected = manifest["assets"][key]
                if (
                    destination.stat().st_size != expected["size_bytes"]
                    or _sha256(destination) != expected["sha256"]
                ):
                    raise ValueError(f"Remote collection asset hash or size mismatch: {key}")
            collection_verification = _verify_asset_set(downloaded)
        except (
            FileNotFoundError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
            urllib.error.URLError,
            zipfile.BadZipFile,
        ) as exc:
            issues.append(f"collection remote verification failed: {exc}")
            collection_verification = {}
        passed = not issues
        result = {
            "schema_version": SCHEMA_VERSION,
            "handoff_id": manifest["handoff_id"],
            "handoff_manifest_sha256": _sha256(handoff / HANDOFF_MANIFEST),
            "collection_id": COLLECTION_ID,
            "status": "pass" if passed else "fail",
            "remote_publication_verified": passed,
            "eligible_for_collection_invitation_launch": passed,
            "registry_mutated": False,
            "retrieved_at": timestamp,
            "provider": record.get("provider"),
            "immutable_identifier": record.get("immutable_identifier"),
            "network_policy": {
                "allow_rfc2544_proxy": allow_rfc2544_proxy,
                "tls_hostname_validation_required": True,
                "exact_asset_hashes_required": True,
            },
            "assets": {
                key: {
                    "filename": ASSET_FILENAMES[key],
                    "expected_sha256": manifest["assets"][key]["sha256"],
                    "retrieved_sha256": (
                        _sha256(root / "downloaded" / ASSET_FILENAMES[key])
                        if (root / "downloaded" / ASSET_FILENAMES[key]).is_file()
                        else None
                    ),
                    "expected_size_bytes": manifest["assets"][key]["size_bytes"],
                    "retrieved_size_bytes": (
                        (root / "downloaded" / ASSET_FILENAMES[key]).stat().st_size
                        if (root / "downloaded" / ASSET_FILENAMES[key]).is_file()
                        else None
                    ),
                    "transport": transport.get(key, {}),
                }
                for key in ASSET_KEYS
            },
            "collection_verification": collection_verification,
            "participant_identity_count": 0,
            "submitted_case_count": 0,
            "human_rating_count": 0,
            "claim_boundaries": CLAIM_BOUNDARIES,
            "issues": issues,
        }
        result_path = root / REMOTE_RESULT
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (root / REMOTE_RESULT_DIGEST).write_text(
            f"{_sha256(result_path)}  {REMOTE_RESULT}\n", encoding="utf-8"
        )
        if passed:
            _write_yaml(
                root / PUBLIC_EVIDENCE,
                {
                    "schema_version": SCHEMA_VERSION,
                    "evidence_type": "collection_publication",
                    "status": "passed",
                    "scope": "blank_external_collection_release",
                    "collection_id": COLLECTION_ID,
                    "handoff_id": manifest["handoff_id"],
                    "provider": record["provider"],
                    "immutable_identifier": record["immutable_identifier"],
                    "release_tag": record["release_tag"],
                    "assets": {
                        key: {
                            "url": record["assets"][key]["url"],
                            "sha256": manifest["assets"][key]["sha256"],
                            "size_bytes": manifest["assets"][key]["size_bytes"],
                        }
                        for key in ASSET_KEYS
                    },
                    "remote_verification_record": REMOTE_RESULT,
                    "retrieved_at": timestamp,
                    "eligible_for_collection_invitation_launch": True,
                    "participant_identity_count": 0,
                    "submitted_case_count": 0,
                    "human_rating_count": 0,
                    "claim_boundaries": CLAIM_BOUNDARIES,
                },
            )
        if out.exists():
            raise FileExistsError(f"Collection remote result appeared during creation: {out}")
        shutil.move(str(root), str(out))
    return result


def verify_remote_result(result_dir: str | Path) -> dict[str, Any]:
    root = _project_path(result_dir).resolve()
    result_path = root / REMOTE_RESULT
    digest_path = root / REMOTE_RESULT_DIGEST
    if not result_path.is_file() or not digest_path.is_file():
        raise FileNotFoundError("Collection remote result or digest is missing")
    issues: list[str] = []
    result = json.loads(result_path.read_text(encoding="utf-8"))
    try:
        if _parse_detached_digest(digest_path, REMOTE_RESULT) != _sha256(result_path):
            issues.append("collection remote-result detached digest mismatch")
    except ValueError as exc:
        issues.append(str(exc))
    required_fields = {
        "schema_version",
        "handoff_id",
        "handoff_manifest_sha256",
        "collection_id",
        "status",
        "remote_publication_verified",
        "eligible_for_collection_invitation_launch",
        "registry_mutated",
        "retrieved_at",
        "provider",
        "immutable_identifier",
        "network_policy",
        "assets",
        "collection_verification",
        "participant_identity_count",
        "submitted_case_count",
        "human_rating_count",
        "claim_boundaries",
        "issues",
    }
    if set(result) != required_fields:
        issues.append("collection remote-result fields drift")
    if result.get("schema_version") != SCHEMA_VERSION or result.get("collection_id") != COLLECTION_ID:
        issues.append("collection remote-result schema or collection ID drift")
    if result.get("registry_mutated") is not False:
        issues.append("collection remote verifier improperly claims registry mutation")
    try:
        _parse_timestamp(result.get("retrieved_at"), "retrieved_at")
    except ValueError as exc:
        issues.append(str(exc))
    if result.get("network_policy") != {
        "allow_rfc2544_proxy": result.get("network_policy", {}).get(
            "allow_rfc2544_proxy"
        )
        if isinstance(result.get("network_policy"), dict)
        else None,
        "tls_hostname_validation_required": True,
        "exact_asset_hashes_required": True,
    } or not isinstance(
        result.get("network_policy", {}).get("allow_rfc2544_proxy")
        if isinstance(result.get("network_policy"), dict)
        else None,
        bool,
    ):
        issues.append("collection remote-result network policy drift")
    if result.get("claim_boundaries") != CLAIM_BOUNDARIES:
        issues.append("collection remote-result claim boundaries were weakened")
    if any(result.get(key) != 0 for key in (
        "participant_identity_count",
        "submitted_case_count",
        "human_rating_count",
    )):
        issues.append("collection remote result exceeds blank-release scope")
    claimed_pass = all(
        (
            result.get("status") == "pass",
            result.get("remote_publication_verified") is True,
            result.get("eligible_for_collection_invitation_launch") is True,
            result.get("issues") == [],
        )
    )
    manifest: dict[str, Any] = {}
    try:
        manifest_path = root / HANDOFF_MANIFEST
        manifest = _load_yaml(manifest_path)
        if (
            _parse_detached_digest(root / HANDOFF_DIGEST, HANDOFF_MANIFEST)
            != _sha256(manifest_path)
            or _sha256(manifest_path) != result.get("handoff_manifest_sha256")
        ):
            raise ValueError("preserved collection handoff binding drift")
        if manifest["claim_boundaries"] != CLAIM_BOUNDARIES:
            raise ValueError("preserved collection handoff boundaries drift")
        if result.get("handoff_id") != manifest["handoff_id"]:
            raise ValueError("preserved collection handoff ID drift")
        if _sha256(root / VERIFIER_COPY) != manifest["assets"]["verifier"]["sha256"]:
            raise ValueError("collection verifier implementation binding drift")
        if _sha256(root / TRANSPORT_COPY) != manifest["assets"]["transport"]["sha256"]:
            raise ValueError("collection transport implementation binding drift")
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        issues.append(str(exc))
    if claimed_pass:
        try:
            record = _load_yaml(root / "publication_record.yaml")
            _validate_publication_record(record, manifest)
            if (
                record["immutable_identifier"] != result["immutable_identifier"]
                or record["provider"] != result["provider"]
            ):
                raise ValueError("collection publication identity binding drift")
            if not isinstance(result.get("assets"), dict) or set(
                result["assets"]
            ) != set(ASSET_KEYS):
                raise ValueError("collection remote-result asset registry drift")
            downloaded = root / "downloaded"
            if {
                path.name for path in downloaded.iterdir() if path.is_file()
            } != set(ASSET_FILENAMES.values()):
                raise ValueError("retained collection asset set drift")
            for key in ASSET_KEYS:
                path = downloaded / ASSET_FILENAMES[key]
                expected = manifest["assets"][key]
                asset_result = result["assets"][key]
                expected_asset_fields = {
                    "filename",
                    "expected_sha256",
                    "retrieved_sha256",
                    "expected_size_bytes",
                    "retrieved_size_bytes",
                    "transport",
                }
                if not isinstance(asset_result, dict) or set(
                    asset_result
                ) != expected_asset_fields:
                    raise ValueError(
                        f"collection remote-result asset fields drift: {key}"
                    )
                transport = asset_result["transport"]
                expected_transport_fields = {
                    "declared_url",
                    "final_url",
                    "declared_resolution",
                    "final_resolution",
                    "http_status",
                    "content_type",
                    "content_length_header",
                    "etag",
                    "last_modified",
                    "downloaded_size_bytes",
                }
                if not isinstance(transport, dict) or set(
                    transport
                ) != expected_transport_fields:
                    raise ValueError(
                        f"collection remote-result transport fields drift: {key}"
                    )
                if not all(
                    (
                        asset_result["filename"] == ASSET_FILENAMES[key],
                        path.stat().st_size == expected["size_bytes"],
                        _sha256(path) == expected["sha256"],
                        asset_result["expected_sha256"] == expected["sha256"],
                        asset_result["retrieved_sha256"] == expected["sha256"],
                        asset_result["expected_size_bytes"] == expected["size_bytes"],
                        asset_result["retrieved_size_bytes"] == expected["size_bytes"],
                        transport["declared_url"] == record["assets"][key]["url"],
                        transport["downloaded_size_bytes"] == expected["size_bytes"],
                        transport["http_status"] == 200,
                    )
                ):
                    raise ValueError(f"retained collection asset binding drift: {key}")
            retained_verification = _verify_asset_set(downloaded)
            if result.get("collection_verification") != retained_verification:
                raise ValueError("collection verification result binding drift")
            evidence = _load_yaml(root / PUBLIC_EVIDENCE)
            expected_evidence_fields = {
                "schema_version",
                "evidence_type",
                "status",
                "scope",
                "collection_id",
                "handoff_id",
                "provider",
                "immutable_identifier",
                "release_tag",
                "assets",
                "remote_verification_record",
                "retrieved_at",
                "eligible_for_collection_invitation_launch",
                "participant_identity_count",
                "submitted_case_count",
                "human_rating_count",
                "claim_boundaries",
            }
            if set(evidence) != expected_evidence_fields or not all(
                (
                    evidence["schema_version"] == SCHEMA_VERSION,
                    evidence["evidence_type"] == "collection_publication",
                    evidence["status"] == "passed",
                    evidence["scope"] == "blank_external_collection_release",
                    evidence["collection_id"] == COLLECTION_ID,
                    evidence["handoff_id"] == manifest["handoff_id"],
                    evidence["provider"] == record["provider"],
                    evidence["immutable_identifier"] == result["immutable_identifier"],
                    evidence["release_tag"] == record["release_tag"],
                    evidence["remote_verification_record"] == REMOTE_RESULT,
                    evidence["retrieved_at"] == result["retrieved_at"],
                    evidence["eligible_for_collection_invitation_launch"] is True,
                    evidence["participant_identity_count"] == 0,
                    evidence["submitted_case_count"] == 0,
                    evidence["human_rating_count"] == 0,
                    evidence["claim_boundaries"] == CLAIM_BOUNDARIES,
                    evidence["assets"]
                    == {
                        key: {
                            "url": record["assets"][key]["url"],
                            "sha256": manifest["assets"][key]["sha256"],
                            "size_bytes": manifest["assets"][key]["size_bytes"],
                        }
                        for key in ASSET_KEYS
                    },
                )
            ):
                raise ValueError("collection publication evidence binding drift")
        except (
            FileNotFoundError,
            KeyError,
            OSError,
            TypeError,
            ValueError,
            zipfile.BadZipFile,
        ) as exc:
            issues.append(str(exc))
    else:
        if result.get("status") != "fail":
            issues.append("non-passing collection remote result must have fail status")
        if (root / PUBLIC_EVIDENCE).exists():
            issues.append("failed collection remote result may not contain passed evidence")
    integrity = not issues
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if integrity else "fail",
        "result_integrity_passed": integrity,
        "remote_publication_verified": claimed_pass and integrity,
        "eligible_for_collection_invitation_launch": claimed_pass and integrity,
        "collection_id": result.get("collection_id"),
        "participant_identity_count": 0,
        "submitted_case_count": 0,
        "human_rating_count": 0,
        "issues": list(dict.fromkeys(issues)),
    }


def _print(result: dict[str, Any]) -> None:
    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish and verify the Project 1 Round-01 collection release"
    )
    sub = parser.add_subparsers(required=True, dest="command")
    create = sub.add_parser("create-handoff")
    create.add_argument("--collection", default=str(DEFAULT_COLLECTION_RELEASE))
    create.add_argument("--out", default=str(DEFAULT_HANDOFF))
    create.add_argument("--handoff-id", default=DEFAULT_HANDOFF_ID)
    create.add_argument("--created-at", default=None)
    handoff = sub.add_parser("verify-handoff")
    handoff.add_argument("--handoff", required=True)
    handoff.add_argument("--require-ready", action="store_true")
    remote = sub.add_parser("verify-remote")
    remote.add_argument("--handoff", required=True)
    remote.add_argument("--record", required=True)
    remote.add_argument("--out", required=True)
    remote.add_argument("--retrieved-at", default=None)
    remote.add_argument("--timeout", type=int, default=120)
    remote.add_argument("--allow-rfc2544-proxy", action="store_true")
    remote.add_argument("--require-pass", action="store_true")
    result = sub.add_parser("verify-remote-result")
    result.add_argument("--result", required=True)
    result.add_argument("--require-eligible", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "create-handoff":
        result = create_handoff(
            args.collection,
            args.out,
            handoff_id=args.handoff_id,
            created_at=args.created_at,
        )
    elif args.command == "verify-handoff":
        result = verify_handoff(args.handoff)
        if args.require_ready and not result["handoff_ready"]:
            _print(result)
            raise SystemExit(1)
    elif args.command == "verify-remote":
        result = verify_remote(
            args.handoff,
            args.record,
            args.out,
            retrieved_at=args.retrieved_at,
            timeout_seconds=args.timeout,
            allow_rfc2544_proxy=args.allow_rfc2544_proxy,
        )
        if args.require_pass and not result["remote_publication_verified"]:
            _print(result)
            raise SystemExit(1)
    else:
        result = verify_remote_result(args.result)
        if args.require_eligible and not result[
            "eligible_for_collection_invitation_launch"
        ]:
            _print(result)
            raise SystemExit(1)
    _print(result)


if __name__ == "__main__":
    main()
