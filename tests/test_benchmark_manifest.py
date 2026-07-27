import json
import shutil
from pathlib import Path

import pytest
import yaml

from spintexture_agent.benchmark_manifest import (
    DEFAULT_BENCHMARK_MANIFEST,
    PRIMARY_PARTITIONS,
    BenchmarkManifestRegistry,
)
from spintexture_agent.cli import build_parser, cmd_benchmark_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _copy_manifest(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    source_dir = PROJECT_ROOT / "benchmark_manifests" / "v1"
    target_dir = tmp_path / "manifest"
    shutil.copytree(source_dir, target_dir)
    partition_paths = {
        partition: target_dir / f"{partition}.yaml" for partition in PRIMARY_PARTITIONS
    }
    master = _load_yaml(target_dir / "manifest.yaml")
    master["registered_case_roots"] = []
    for reference in master["partitions"]:
        reference["path"] = str(partition_paths[reference["primary_partition"]])
    master_path = target_dir / "manifest.yaml"
    _write_yaml(master_path, master)
    return master_path, partition_paths


def test_default_manifest_registers_all_current_cases_as_development_data():
    registry = BenchmarkManifestRegistry(DEFAULT_BENCHMARK_MANIFEST)
    record = registry.to_record()
    counts = {
        partition["primary_partition"]: partition["case_count"]
        for partition in record["partitions"]
    }

    assert counts == {
        "development_supported": 7,
        "held_out_supported": 0,
        "negative_ood": 3,
        "candidate_extension": 1,
        "readability": 0,
    }
    assert record["case_count"] == 11
    assert not record["release_ready"]
    assert all(case.leakage_status == "development_exposed" for case in registry.cases)
    assert all(case.gold_visibility == "public" for case in registry.cases)
    assert all(case.gold_mutable for case in registry.cases)

    artifact_ids = {
        _load_yaml(path)["case_id"]
        for path in (PROJECT_ROOT / "benchmark_cases").glob("*.yaml")
    }
    assert {case.case_id for case in registry.cases} == artifact_ids


def test_benchmark_manifest_cli_emits_machine_readable_summary(capsys):
    args = build_parser().parse_args(["benchmark-manifest", "--json"])
    cmd_benchmark_manifest(args)
    payload = json.loads(capsys.readouterr().out)

    assert payload["benchmark_id"] == "spintexture_dynamics_bench"
    assert payload["case_count"] == 11
    assert payload["release_ready"] is False


def test_manifest_rejects_duplicate_case_ids(tmp_path):
    master_path, partitions = _copy_manifest(tmp_path)
    development = _load_yaml(partitions["development_supported"])
    negative = _load_yaml(partitions["negative_ood"])
    negative["cases"].append(development["cases"][0])
    _write_yaml(partitions["negative_ood"], negative)

    with pytest.raises(ValueError, match="Duplicate case ID"):
        BenchmarkManifestRegistry(master_path)


def test_manifest_rejects_development_held_out_overlap(tmp_path):
    master_path, partitions = _copy_manifest(tmp_path)
    development = _load_yaml(partitions["development_supported"])
    held_out = _load_yaml(partitions["held_out_supported"])
    case_path = tmp_path / "H1_overlap.yaml"
    gold_path = tmp_path / "H1_overlap_gold.yaml"
    _write_yaml(case_path, {"case_id": "H1_overlap"})
    _write_yaml(gold_path, {"equation": "held-out"})
    held_out["cases"].append(
        {
            "case_id": "H1_overlap",
            "task_fingerprint": development["cases"][0]["task_fingerprint"],
            "case_path": str(case_path),
            "source_provenance": {
                "source_type": "external_contribution",
                "locator": str(case_path),
            },
            "claim_class": "known_theory_derivation",
            "gold_visibility": "blinded",
            "leakage_status": "held_out_blinded",
            "scorer": "structured_rule_scorer_v1",
            "allowed_tools": ["python_orchestrator", "wolfram_kernel"],
            "repetition_policy": {
                "deterministic_runs": 1,
                "stochastic_runs": 3,
                "aggregation": "mean_and_confidence_interval",
            },
            "gold_artifact": str(gold_path),
            "gold_mutable": True,
        }
    )
    _write_yaml(partitions["held_out_supported"], held_out)

    with pytest.raises(ValueError, match="Development/held-out task fingerprint overlap"):
        BenchmarkManifestRegistry(master_path)


def test_manifest_rejects_missing_source_locator(tmp_path):
    master_path, partitions = _copy_manifest(tmp_path)
    development = _load_yaml(partitions["development_supported"])
    development["cases"][0]["source_provenance"]["locator"] = str(
        tmp_path / "missing-source.yaml"
    )
    _write_yaml(partitions["development_supported"], development)

    with pytest.raises(ValueError, match="Missing source locator"):
        BenchmarkManifestRegistry(master_path)


def test_manifest_rejects_mutable_gold_in_frozen_partition(tmp_path):
    master_path, partitions = _copy_manifest(tmp_path)
    development = _load_yaml(partitions["development_supported"])
    development["freeze_status"] = "frozen"
    _write_yaml(partitions["development_supported"], development)

    with pytest.raises(ValueError, match="Frozen partition contains mutable gold"):
        BenchmarkManifestRegistry(master_path)


def test_manifest_rejects_unblinded_held_out_case(tmp_path):
    master_path, partitions = _copy_manifest(tmp_path)
    held_out = _load_yaml(partitions["held_out_supported"])
    case_path = tmp_path / "H1_unblinded.yaml"
    _write_yaml(case_path, {"case_id": "H1_unblinded"})
    held_out["cases"].append(
        {
            "case_id": "H1_unblinded",
            "task_fingerprint": "held_out_unblinded_control",
            "case_path": str(case_path),
            "source_provenance": {
                "source_type": "external_contribution",
                "locator": str(case_path),
            },
            "claim_class": "known_theory_derivation",
            "gold_visibility": "public",
            "leakage_status": "held_out_blinded",
            "scorer": "structured_rule_scorer_v1",
            "allowed_tools": ["python_orchestrator", "wolfram_kernel"],
            "repetition_policy": {
                "deterministic_runs": 1,
                "stochastic_runs": 3,
                "aggregation": "mean_and_confidence_interval",
            },
            "gold_artifact": str(case_path),
            "gold_mutable": True,
        }
    )
    _write_yaml(partitions["held_out_supported"], held_out)

    with pytest.raises(ValueError, match="must use blinded gold"):
        BenchmarkManifestRegistry(master_path)


def test_release_gate_rejects_draft_empty_evaluation_partitions():
    registry = BenchmarkManifestRegistry(DEFAULT_BENCHMARK_MANIFEST)

    with pytest.raises(ValueError, match="not frozen"):
        registry.require_release_ready()


def test_benchmark_manifest_cli_reports_release_gate_failure():
    args = build_parser().parse_args(
        ["benchmark-manifest", "--require-release-ready"]
    )

    with pytest.raises(SystemExit, match="Benchmark release gate failed.*not frozen"):
        cmd_benchmark_manifest(args)
