from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BENCHMARK_MANIFEST = (
    PROJECT_ROOT / "benchmark_manifests" / "v1" / "manifest.yaml"
)
BENCHMARK_MANIFEST_SCHEMA_VERSION = "1.0.0"

PrimaryPartition = Literal[
    "development_supported",
    "held_out_supported",
    "negative_ood",
    "candidate_extension",
    "readability",
]
FreezeStatus = Literal["draft", "frozen"]
ClaimClass = Literal[
    "known_theory_derivation",
    "negative_safety",
    "candidate_routing",
    "accessible_explanation",
]
GoldVisibility = Literal["public", "blinded", "none"]
LeakageStatus = Literal[
    "development_exposed",
    "held_out_blinded",
    "not_applicable",
]
SourceType = Literal[
    "internal_development",
    "primary_literature",
    "external_contribution",
]

PRIMARY_PARTITIONS: tuple[str, ...] = (
    "development_supported",
    "held_out_supported",
    "negative_ood",
    "candidate_extension",
    "readability",
)

PARTITION_CLAIM_CLASSES: dict[str, str] = {
    "development_supported": "known_theory_derivation",
    "held_out_supported": "known_theory_derivation",
    "negative_ood": "negative_safety",
    "candidate_extension": "candidate_routing",
    "readability": "accessible_explanation",
}


class SourceProvenance(BaseModel):
    source_type: SourceType
    locator: str = Field(min_length=1)
    citation: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class RepetitionPolicy(BaseModel):
    deterministic_runs: int = Field(ge=1)
    stochastic_runs: int = Field(ge=1)
    aggregation: Literal["exact_single_run", "mean_and_confidence_interval"]


class BenchmarkManifestCase(BaseModel):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    task_fingerprint: str = Field(pattern=r"^[a-z0-9_]+$")
    case_path: str = Field(min_length=1)
    source_provenance: SourceProvenance
    claim_class: ClaimClass
    gold_visibility: GoldVisibility
    leakage_status: LeakageStatus
    scorer: str = Field(min_length=1)
    allowed_tools: list[str] = Field(min_length=1)
    repetition_policy: RepetitionPolicy
    gold_artifact: str | None = None
    gold_mutable: bool
    gold_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_gold_contract(self) -> "BenchmarkManifestCase":
        if self.gold_visibility == "none" and self.gold_artifact is not None:
            raise ValueError("gold_visibility=none cannot declare a gold artifact")
        if self.gold_visibility != "none" and not self.gold_artifact:
            raise ValueError("Visible or blinded gold requires a gold artifact locator")
        return self


class BenchmarkPartitionManifest(BaseModel):
    schema_version: str
    benchmark_id: str
    benchmark_version: str
    primary_partition: PrimaryPartition
    freeze_status: FreezeStatus
    cases: list[BenchmarkManifestCase] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_partition(self) -> "BenchmarkPartitionManifest":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Case IDs must be unique within a benchmark partition")
        if self.freeze_status == "frozen":
            for case in self.cases:
                if case.gold_mutable:
                    raise ValueError(
                        f"Frozen partition contains mutable gold for {case.case_id}"
                    )
                if case.gold_visibility != "none" and not case.gold_sha256:
                    raise ValueError(
                        f"Frozen partition lacks a gold SHA-256 for {case.case_id}"
                    )
                if not case.source_provenance.sha256:
                    raise ValueError(
                        f"Frozen partition lacks a source SHA-256 for {case.case_id}"
                    )
        return self


class PartitionReference(BaseModel):
    primary_partition: PrimaryPartition
    path: str = Field(min_length=1)


class BenchmarkSuiteManifest(BaseModel):
    schema_version: str
    benchmark_id: str
    benchmark_version: str
    freeze_status: FreezeStatus
    scorer_registry_version: str
    registered_case_roots: list[str] = Field(default_factory=list)
    partitions: list[PartitionReference]

    @model_validator(mode="after")
    def validate_partition_index(self) -> "BenchmarkSuiteManifest":
        partition_ids = [item.primary_partition for item in self.partitions]
        if len(partition_ids) != len(set(partition_ids)):
            raise ValueError("Primary partition references must be unique")
        if set(partition_ids) != set(PRIMARY_PARTITIONS):
            raise ValueError(
                "Manifest must reference exactly the five primary partitions"
            )
        return self


def _load_yaml(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return payload


def _resolve_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BenchmarkManifestRegistry:
    def __init__(self, path: str | Path = DEFAULT_BENCHMARK_MANIFEST):
        self.path = _resolve_path(path)
        self.suite = BenchmarkSuiteManifest.model_validate(_load_yaml(self.path))
        if self.suite.schema_version != BENCHMARK_MANIFEST_SCHEMA_VERSION:
            raise ValueError("Unsupported benchmark manifest schema version")

        self.partitions: dict[str, BenchmarkPartitionManifest] = {}
        for reference in self.suite.partitions:
            partition_path = _resolve_path(reference.path)
            partition = BenchmarkPartitionManifest.model_validate(
                _load_yaml(partition_path)
            )
            self._validate_partition_reference(reference, partition)
            self.partitions[reference.primary_partition] = partition
        self._validate_cross_partition_contract()

    @property
    def cases(self) -> list[BenchmarkManifestCase]:
        return [
            case
            for partition in PRIMARY_PARTITIONS
            for case in self.partitions[partition].cases
        ]

    def _validate_partition_reference(
        self,
        reference: PartitionReference,
        partition: BenchmarkPartitionManifest,
    ) -> None:
        if partition.schema_version != self.suite.schema_version:
            raise ValueError(f"Schema mismatch in {reference.path}")
        if partition.benchmark_id != self.suite.benchmark_id:
            raise ValueError(f"Benchmark ID mismatch in {reference.path}")
        if partition.benchmark_version != self.suite.benchmark_version:
            raise ValueError(f"Benchmark version mismatch in {reference.path}")
        if partition.primary_partition != reference.primary_partition:
            raise ValueError(f"Primary partition mismatch in {reference.path}")
        if self.suite.freeze_status == "frozen" and partition.freeze_status != "frozen":
            raise ValueError("A frozen suite cannot reference a draft partition")

    def _validate_cross_partition_contract(self) -> None:
        case_locations: dict[str, str] = {}
        artifact_locations: dict[Path, str] = {}
        for partition_id, partition in self.partitions.items():
            for case in partition.cases:
                if case.case_id in case_locations:
                    raise ValueError(
                        f"Duplicate case ID {case.case_id} in {case_locations[case.case_id]} "
                        f"and {partition_id}"
                    )
                case_locations[case.case_id] = partition_id
                case_path = _resolve_path(case.case_path).resolve()
                if case_path in artifact_locations:
                    raise ValueError(
                        f"Case artifact {case.case_path} is registered in both "
                        f"{artifact_locations[case_path]} and {partition_id}"
                    )
                artifact_locations[case_path] = partition_id
                self._validate_partition_case_semantics(partition_id, case)
                self._validate_case_artifacts(case, partition.freeze_status)

        development_fingerprints = {
            case.task_fingerprint
            for case in self.partitions["development_supported"].cases
        }
        held_out_fingerprints = {
            case.task_fingerprint
            for case in self.partitions["held_out_supported"].cases
        }
        overlap = sorted(development_fingerprints & held_out_fingerprints)
        if overlap:
            raise ValueError(
                "Development/held-out task fingerprint overlap: " + ", ".join(overlap)
            )

        registered_paths = {
            str(_resolve_path(case.case_path).resolve()) for case in self.cases
        }
        discovered_paths = {
            str(path.resolve())
            for root in self.suite.registered_case_roots
            for path in _resolve_path(root).glob("*.yaml")
        }
        unregistered = sorted(discovered_paths - registered_paths)
        if unregistered:
            raise ValueError(
                "Benchmark case roots contain unregistered cases: "
                + ", ".join(unregistered)
            )

    def _validate_partition_case_semantics(
        self,
        partition_id: str,
        case: BenchmarkManifestCase,
    ) -> None:
        expected_claim_class = PARTITION_CLAIM_CLASSES[partition_id]
        if case.claim_class != expected_claim_class:
            raise ValueError(
                f"Partition {partition_id} requires claim_class={expected_claim_class}; "
                f"{case.case_id} declares {case.claim_class}"
            )
        if case.scorer != self.suite.scorer_registry_version:
            raise ValueError(
                f"Case {case.case_id} uses unregistered scorer {case.scorer}"
            )
        if len(case.allowed_tools) != len(set(case.allowed_tools)):
            raise ValueError(f"Case {case.case_id} declares duplicate allowed tools")
        if partition_id == "development_supported" and (
            case.leakage_status != "development_exposed"
        ):
            raise ValueError(
                f"Development case {case.case_id} must be marked development_exposed"
            )
        if partition_id == "held_out_supported":
            if case.leakage_status != "held_out_blinded":
                raise ValueError(
                    f"Held-out case {case.case_id} must be marked held_out_blinded"
                )
            if case.gold_visibility != "blinded":
                raise ValueError(f"Held-out case {case.case_id} must use blinded gold")
            if case.source_provenance.source_type == "internal_development":
                raise ValueError(
                    f"Held-out case {case.case_id} cannot use internal development provenance"
                )

    def _validate_case_artifacts(
        self,
        case: BenchmarkManifestCase,
        freeze_status: FreezeStatus,
    ) -> None:
        case_path = _resolve_path(case.case_path)
        if not case_path.exists():
            raise ValueError(f"Missing benchmark case artifact: {case.case_path}")
        case_payload = _load_yaml(case_path)
        if case_payload.get("case_id") != case.case_id:
            raise ValueError(f"Case ID does not match artifact {case.case_path}")

        source_locator = case.source_provenance.locator
        if source_locator.startswith(("https://", "http://")):
            source_path = None
        else:
            source_path = _resolve_path(source_locator)
            if not source_path.exists():
                raise ValueError(f"Missing source locator: {source_locator}")

        gold_path = _resolve_path(case.gold_artifact) if case.gold_artifact else None
        if gold_path is not None and not gold_path.exists():
            raise ValueError(f"Missing gold artifact: {case.gold_artifact}")

        if freeze_status == "frozen":
            if source_path is not None and _sha256(source_path) != case.source_provenance.sha256:
                raise ValueError(f"Source SHA-256 mismatch for {case.case_id}")
            if gold_path is not None and _sha256(gold_path) != case.gold_sha256:
                raise ValueError(f"Gold SHA-256 mismatch for {case.case_id}")

    def require_release_ready(self) -> None:
        if self.suite.freeze_status != "frozen":
            raise ValueError("Benchmark suite is not frozen")
        for partition in PRIMARY_PARTITIONS:
            if not self.partitions[partition].cases:
                raise ValueError(f"Release benchmark partition is empty: {partition}")

    def to_record(self) -> dict[str, object]:
        partition_records = []
        for partition_id in PRIMARY_PARTITIONS:
            partition = self.partitions[partition_id]
            partition_records.append(
                {
                    "primary_partition": partition_id,
                    "freeze_status": partition.freeze_status,
                    "case_count": len(partition.cases),
                    "case_ids": [case.case_id for case in partition.cases],
                    "gold_visibility_counts": {
                        visibility: sum(
                            case.gold_visibility == visibility
                            for case in partition.cases
                        )
                        for visibility in ("public", "blinded", "none")
                    },
                    "leakage_status_counts": {
                        status: sum(case.leakage_status == status for case in partition.cases)
                        for status in (
                            "development_exposed",
                            "held_out_blinded",
                            "not_applicable",
                        )
                    },
                }
            )
        return {
            "schema_version": self.suite.schema_version,
            "benchmark_id": self.suite.benchmark_id,
            "benchmark_version": self.suite.benchmark_version,
            "freeze_status": self.suite.freeze_status,
            "scorer_registry_version": self.suite.scorer_registry_version,
            "release_ready": self._release_ready(),
            "case_count": len(self.cases),
            "partitions": partition_records,
        }

    def _release_ready(self) -> bool:
        try:
            self.require_release_ready()
        except ValueError:
            return False
        return True

    def to_json(self) -> str:
        return json.dumps(self.to_record(), ensure_ascii=False, indent=2)
