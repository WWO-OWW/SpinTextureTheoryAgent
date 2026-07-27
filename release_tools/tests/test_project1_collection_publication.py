import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

import release_tools.project1_collection_publication as publication


TIMESTAMP = "2026-07-27T23:00:00+08:00"
TAG = "benchmark-collection-v1-round-01"
REPOSITORY = "example/spintexture"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False, width=100),
        encoding="utf-8",
    )


def _reseal_handoff(handoff: Path, payload: dict) -> None:
    manifest = handoff / publication.HANDOFF_MANIFEST
    _write_yaml(manifest, payload)
    (handoff / publication.HANDOFF_DIGEST).write_text(
        f"{_sha256(manifest)}  {publication.HANDOFF_MANIFEST}\n",
        encoding="utf-8",
    )


def _reseal_result(result_dir: Path, payload: dict) -> None:
    result = result_dir / publication.REMOTE_RESULT
    result.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (result_dir / publication.REMOTE_RESULT_DIGEST).write_text(
        f"{_sha256(result)}  {publication.REMOTE_RESULT}\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def handoff():
    root = Path(tempfile.mkdtemp(prefix="stta-collection-publication-test-"))
    path = root / "handoff"
    result = publication.create_handoff(
        publication.DEFAULT_COLLECTION_RELEASE,
        path,
        handoff_id="collection_publication_test",
        created_at=TIMESTAMP,
    )
    assert result["handoff_ready"]
    try:
        yield path
    finally:
        shutil.rmtree(root)


def _published_record(handoff: Path) -> dict:
    record = yaml.safe_load(
        (handoff / publication.REGISTRATION_TEMPLATE).read_text(encoding="utf-8")
    )
    record.update(
        {
            "status": "published",
            "provider": "github_release",
            "repository": REPOSITORY,
            "release_tag": TAG,
            "immutable_identifier": f"github:{REPOSITORY}@{TAG}",
            "published_at": TIMESTAMP,
            "publisher": "release-manager-test",
        }
    )
    record["attestation"] = {
        "dedicated_collection_release": True,
        "all_exact_assets_uploaded": True,
        "provider_record_public": True,
        "software_v0_1_0_untouched": True,
    }
    for asset in record["assets"].values():
        asset["url"] = (
            f"https://github.com/{REPOSITORY}/releases/download/{TAG}/"
            f"{asset['filename']}"
        )
    return record


def _fake_download_factory(handoff: Path, *, tamper: str | None = None):
    sources = {
        path.name: path
        for path in (handoff / "payload").iterdir()
        if path.is_file()
    }

    def fake_download(
        url, destination, *, timeout_seconds, allow_rfc2544_proxy=False
    ):
        del timeout_seconds, allow_rfc2544_proxy
        source = sources[url.rsplit("/", 1)[-1]]
        shutil.copy2(source, destination)
        if source.name == tamper:
            destination.write_bytes(destination.read_bytes() + b"tamper")
        size = destination.stat().st_size
        resolution = {
            "hostname": "github.com",
            "resolved_addresses": ["192.0.2.1"],
            "resolution_mode": "direct_public",
        }
        return {
            "declared_url": url,
            "final_url": url,
            "declared_resolution": resolution,
            "final_resolution": resolution,
            "http_status": 200,
            "content_type": "application/octet-stream",
            "content_length_header": str(size),
            "etag": '"test-etag"',
            "last_modified": "Mon, 27 Jul 2026 15:00:00 GMT",
            "downloaded_size_bytes": size,
        }

    return fake_download


def test_handoff_is_ready_and_preserves_blank_collection_scope(handoff):
    result = publication.verify_handoff(handoff)

    assert result["status"] == "pass"
    assert result["handoff_ready"]
    assert not result["remote_publication_verified"]
    assert result["participant_identity_count"] == 0
    assert result["submitted_case_count"] == 0
    assert result["human_rating_count"] == 0


def test_direct_cli_entrypoint_is_runnable():
    completed = subprocess.run(
        [sys.executable, str(Path(publication.__file__)), "--help"],
        cwd=publication.PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Round-01 collection release" in completed.stdout


def test_handoff_is_portable_when_original_source_is_unavailable(handoff, tmp_path):
    copied = tmp_path / "portable"
    shutil.copytree(handoff, copied)
    manifest_path = copied / publication.HANDOFF_MANIFEST
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["source_path"] = str(tmp_path / "absent-source")
    _reseal_handoff(copied, manifest)

    assert publication.verify_handoff(copied)["handoff_ready"]


def test_handoff_creation_is_non_overwriting(handoff):
    with pytest.raises(FileExistsError, match="already exists"):
        publication.create_handoff(
            publication.DEFAULT_COLLECTION_RELEASE,
            handoff,
            handoff_id="duplicate",
        )


def test_handoff_rejects_tampered_archive(handoff, tmp_path):
    copied = tmp_path / "tampered"
    shutil.copytree(handoff, copied)
    archive = copied / "payload" / publication.ARCHIVE_NAME
    archive.write_bytes(archive.read_bytes() + b"tamper")

    result = publication.verify_handoff(copied)

    assert result["status"] == "fail"
    assert any("drift" in issue for issue in result["issues"])


def test_handoff_rejects_resealed_premature_state(handoff, tmp_path):
    copied = tmp_path / "premature"
    shutil.copytree(handoff, copied)
    manifest_path = copied / publication.HANDOFF_MANIFEST
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["state"]["remote_publication_verified"] = True
    _reseal_handoff(copied, manifest)

    result = publication.verify_handoff(copied)

    assert result["status"] == "fail"
    assert "collection handoff state was prematurely promoted" in result["issues"]


def test_pending_record_cannot_pass(handoff):
    manifest = yaml.safe_load(
        (handoff / publication.HANDOFF_MANIFEST).read_text(encoding="utf-8")
    )
    record = yaml.safe_load(
        (handoff / publication.REGISTRATION_TEMPLATE).read_text(encoding="utf-8")
    )

    with pytest.raises(ValueError, match="not published"):
        publication._validate_publication_record(record, manifest)


@pytest.mark.parametrize(
    "tag",
    ["v0.1.0", "latest", "main", "nightly", "snapshot"],
)
def test_record_rejects_software_or_mutable_release_tags(handoff, tag):
    manifest = yaml.safe_load(
        (handoff / publication.HANDOFF_MANIFEST).read_text(encoding="utf-8")
    )
    record = _published_record(handoff)
    record["release_tag"] = tag
    record["immutable_identifier"] = f"github:{REPOSITORY}@{tag}"
    for asset in record["assets"].values():
        asset["url"] = (
            f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
            f"{asset['filename']}"
        )

    with pytest.raises(ValueError, match="dedicated immutable tag"):
        publication._validate_publication_record(record, manifest)


def test_record_rejects_asset_url_mismatch(handoff):
    manifest = yaml.safe_load(
        (handoff / publication.HANDOFF_MANIFEST).read_text(encoding="utf-8")
    )
    record = _published_record(handoff)
    record["assets"]["archive"]["url"] = record["assets"]["release_index"]["url"]

    with pytest.raises(ValueError, match="does not match"):
        publication._validate_publication_record(record, manifest)


def test_offline_record_verification_does_not_claim_remote_evidence(
    handoff, tmp_path
):
    record_path = tmp_path / "record.yaml"
    _write_yaml(record_path, _published_record(handoff))

    result = publication.verify_publication_record(
        record_path,
        publication.DEFAULT_COLLECTION_RELEASE,
    )

    assert result["status"] == "pass"
    assert result["publication_record_valid"]
    assert not result["remote_publication_verified"]
    assert not result["eligible_for_collection_invitation_launch"]


def test_offline_record_verification_rejects_hash_drift(handoff, tmp_path):
    record = _published_record(handoff)
    record["assets"]["archive"]["sha256"] = "0" * 64
    record_path = tmp_path / "record-drift.yaml"
    _write_yaml(record_path, record)

    result = publication.verify_publication_record(
        record_path,
        publication.DEFAULT_COLLECTION_RELEASE,
    )

    assert result["status"] == "fail"
    assert not result["publication_record_valid"]


def test_remote_verification_retains_and_rechecks_exact_assets(
    handoff, tmp_path, monkeypatch
):
    record_path = tmp_path / "record.yaml"
    _write_yaml(record_path, _published_record(handoff))
    monkeypatch.setattr(
        publication,
        "_download_public_artifact",
        _fake_download_factory(handoff),
    )
    out = tmp_path / "remote"

    result = publication.verify_remote(
        handoff,
        record_path,
        out,
        retrieved_at=TIMESTAMP,
    )
    integrity = publication.verify_remote_result(out)

    assert result["status"] == "pass"
    assert integrity["result_integrity_passed"]
    assert integrity["eligible_for_collection_invitation_launch"]
    assert (out / publication.PUBLIC_EVIDENCE).is_file()


def test_remote_hash_mismatch_fails_without_publication_evidence(
    handoff, tmp_path, monkeypatch
):
    record_path = tmp_path / "record.yaml"
    _write_yaml(record_path, _published_record(handoff))
    monkeypatch.setattr(
        publication,
        "_download_public_artifact",
        _fake_download_factory(handoff, tamper=publication.ARCHIVE_NAME),
    )
    out = tmp_path / "remote-fail"

    result = publication.verify_remote(
        handoff,
        record_path,
        out,
        retrieved_at=TIMESTAMP,
    )
    integrity = publication.verify_remote_result(out)

    assert result["status"] == "fail"
    assert not result["eligible_for_collection_invitation_launch"]
    assert integrity["result_integrity_passed"]
    assert not integrity["eligible_for_collection_invitation_launch"]
    assert not (out / publication.PUBLIC_EVIDENCE).exists()


def test_resealed_false_success_is_rejected(handoff, tmp_path, monkeypatch):
    record_path = tmp_path / "record.yaml"
    _write_yaml(record_path, _published_record(handoff))
    monkeypatch.setattr(
        publication,
        "_download_public_artifact",
        _fake_download_factory(handoff),
    )
    out = tmp_path / "remote-tampered"
    publication.verify_remote(
        handoff,
        record_path,
        out,
        retrieved_at=TIMESTAMP,
    )
    result_path = out / publication.REMOTE_RESULT
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["collection_verification"]["payload_file_count"] = 999
    _reseal_result(out, result)

    integrity = publication.verify_remote_result(out)

    assert integrity["status"] == "fail"
    assert not integrity["eligible_for_collection_invitation_launch"]
    assert "collection verification result binding drift" in integrity["issues"]
