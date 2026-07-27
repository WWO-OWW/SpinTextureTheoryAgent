from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FULL_DEVELOPMENT_SENTINEL = PROJECT_ROOT / "benchmark_manifests" / "v1" / "manifest.yaml"
PUBLIC_PORTABLE_TEST_MODULES = {
    "test_benchmark_operator.py",
    "test_benchmark_outreach.py",
    "test_public_release_snapshot.py",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep compact public snapshots honest without publishing development fixtures."""
    if FULL_DEVELOPMENT_SENTINEL.is_file():
        return
    reason = (
        "requires development-only fixtures omitted from the compact public main; "
        "not counted as a pass or as physics evidence"
    )
    marker = pytest.mark.skip(reason=reason)
    for item in items:
        if Path(str(item.fspath)).name not in PUBLIC_PORTABLE_TEST_MODULES:
            item.add_marker(marker)
