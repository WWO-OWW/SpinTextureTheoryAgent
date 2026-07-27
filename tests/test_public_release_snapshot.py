import shutil
from pathlib import Path

from release_tools.project1_publication import (
    PUBLIC_SNAPSHOT_SUMMARY,
    verify_public_evidence_snapshot,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = PROJECT_ROOT / "public_release_evidence" / "v0.1.0"


def test_checked_in_public_release_snapshot_passes_offline():
    result = verify_public_evidence_snapshot(SNAPSHOT)

    assert result["status"] == "pass"
    assert result["snapshot_integrity_passed"]
    assert result["remote_refetch"] == "not_requested"
    assert result["claim_scope"] == "software_distribution"
    assert not list(SNAPSHOT.rglob("*.tar.gz"))


def test_checked_in_public_release_snapshot_rejects_tampering(tmp_path):
    copied = tmp_path / "v0.1.0"
    shutil.copytree(SNAPSHOT, copied)
    (copied / PUBLIC_SNAPSHOT_SUMMARY).write_text("{}\n", encoding="utf-8")

    result = verify_public_evidence_snapshot(copied)

    assert result["status"] == "fail"
    assert not result["snapshot_integrity_passed"]
