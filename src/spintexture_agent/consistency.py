from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConsistencyIssue:
    field: str
    artifact: str
    expected: str


@dataclass(frozen=True)
class ConsistencyReport:
    issues: tuple[ConsistencyIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


def check_generated_bundle(
    record_path: str | Path,
    summary_path: str | Path,
    wolfram_path: str | Path,
) -> ConsistencyReport:
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    summary = Path(summary_path).read_text(encoding="utf-8")
    wolfram = Path(wolfram_path).read_text(encoding="utf-8")
    physics_ir = record.get("physics_ir") or {}
    task = record.get("task") or {}

    issues: list[ConsistencyIssue] = []

    def require(field: str, artifact: str, fragment: str, content: str) -> None:
        if fragment not in content:
            issues.append(
                ConsistencyIssue(field=field, artifact=artifact, expected=fragment)
            )

    record_id = str(record.get("record_id"))
    require("record_id", "summary", f"`{record_id}`", summary)
    require("record_id", "wolfram", f"Authoritative record ID: {record_id}", wolfram)

    mirrored_fields = {
        "support_level": str(physics_ir.get("support_level")),
        "knowledge_status": str(physics_ir.get("knowledge_status")),
        "capability_route_id": str(physics_ir.get("capability_route_id")),
        "expected_equation_type": str(
            (physics_ir.get("dynamics") or {}).get("expected_equation_type")
        ),
        "topology_field": str(
            (physics_ir.get("order_parameter") or {}).get("topology_field")
        ),
        "requires_human_review": str(
            (physics_ir.get("confidence") or {}).get("requires_human_review")
        ),
        "permitted_claim": str(physics_ir.get("permitted_claim")),
    }
    for field, value in mirrored_fields.items():
        require(field, "summary", value, summary)
        require(field, "wolfram", value, wolfram)

    evidence_status = physics_ir.get("evidence_status") or {}
    require(
        "evidence_status.schema_version",
        "summary",
        str(evidence_status.get("schema_version")),
        summary,
    )
    require(
        "evidence_status.claim_class",
        "summary",
        str(evidence_status.get("claim_class")),
        summary,
    )
    for axis in (
        "cas_execution",
        "analytic_reproduction",
        "literature_reproduction",
        "assertion_coverage",
        "benchmark",
        "cross_engine",
        "external_review",
        "public_release",
    ):
        axis_status = str((evidence_status.get(axis) or {}).get("status"))
        require(
            f"evidence_status.{axis}",
            "summary",
            f"`{axis}` | `{axis_status}`",
            summary,
        )
        require(
            f"evidence_status.{axis}",
            "wolfram",
            f"Physics IR evidence {axis}: {axis_status}",
            wolfram,
        )

    for assumption in task.get("assumptions", []):
        require("assumptions", "summary", f"`{assumption}`", summary)
        require("assumptions", "wolfram", assumption, wolfram)

    for blocked_claim in physics_ir.get("blocked_claims", []):
        require("blocked_claims", "summary", blocked_claim, summary)

    for item in (record.get("validation") or {}).get("items", []):
        require("validation", "summary", str(item.get("id")), summary)

    return ConsistencyReport(issues=tuple(issues))


def assert_generated_bundle_consistent(
    record_path: str | Path,
    summary_path: str | Path,
    wolfram_path: str | Path,
) -> None:
    report = check_generated_bundle(record_path, summary_path, wolfram_path)
    if report.ok:
        return
    details = "; ".join(
        f"{issue.artifact}:{issue.field} missing {issue.expected!r}"
        for issue in report.issues
    )
    raise ValueError(f"Generated artifact consistency check failed: {details}")
