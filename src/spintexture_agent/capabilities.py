from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    model_validator,
)

from .evidence_governance import derive_legacy_knowledge_status
from .resources import PACKAGE_ROOT, resource_dir
from .schema import (
    EvidenceAxisIR,
    EvidenceAxisStatus,
    EvidenceClaimClass,
    EvidenceStatusIR,
    TheoryTask,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = resource_dir("knowledge_base") / "capabilities.yaml"

SupportLevel = Literal["full_derivation", "scaffold", "review_only", "unsupported"]
KnowledgeStatus = Literal[
    "candidate",
    "symmetry_checked",
    "cas_validated",
    "expert_validated",
    "benchmarked",
    "released",
]

KNOWLEDGE_LIFECYCLE: tuple[str, ...] = (
    "candidate",
    "symmetry_checked",
    "cas_validated",
    "expert_validated",
    "benchmarked",
    "released",
)
EVIDENCE_STATUS_SCHEMA_VERSION = "1.0.0"


class CapabilityEvidenceStatus(BaseModel):
    claim_class: EvidenceClaimClass
    cas_execution: EvidenceAxisStatus
    analytic_reproduction: EvidenceAxisStatus
    literature_reproduction: EvidenceAxisStatus
    assertion_coverage: EvidenceAxisStatus
    benchmark: EvidenceAxisStatus
    cross_engine: EvidenceAxisStatus
    external_review: EvidenceAxisStatus
    public_release: EvidenceAxisStatus


class CapabilityEvidence(BaseModel):
    config: str
    benchmark_cases: list[str] = Field(default_factory=list)
    evidence_card: str | None = None
    independent_gold_script: str | None = None
    machine_audit_spec: str | None = None
    assertion_coverage_registry: str | None = None
    cas_execution_records: list[str] = Field(default_factory=list)
    analytic_reproduction_records: list[str] = Field(default_factory=list)
    assertion_coverage_records: list[str] = Field(default_factory=list)
    literature_reproduction_record: str | None = None
    benchmark_result_records: list[str] = Field(default_factory=list)
    cross_engine_records: list[str] = Field(default_factory=list)
    expert_review_records: list[str] = Field(default_factory=list)
    public_release_records: list[str] = Field(default_factory=list)
    wolfram_functions: list[str] = Field(default_factory=list)
    validator_checks: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class CapabilityRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str = Field(pattern=r"^[a-z0-9_]+$")
    material: str
    texture: str
    drive: str | None = None
    geometry: str | None = None
    required_goals: list[str] = Field(default_factory=list)
    required_assumptions: list[str] = Field(default_factory=list)
    support_level: SupportLevel
    evidence_status: CapabilityEvidenceStatus
    requires_human_review: bool
    permitted_claim: str
    blocked_claims: list[str] = Field(default_factory=list)
    evidence: CapabilityEvidence
    missing_evidence: list[str] = Field(default_factory=list)
    promotion_requirements: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def knowledge_status(self) -> KnowledgeStatus:
        return self.resolved_evidence_status(
            EVIDENCE_STATUS_SCHEMA_VERSION
        ).compatibility_knowledge_status

    @staticmethod
    def _compact_refs(*groups: list[str]) -> list[str]:
        return list(dict.fromkeys(item for group in groups for item in group if item))

    def resolved_evidence_status(self, schema_version: str) -> EvidenceStatusIR:
        evidence = self.evidence
        axis_refs = {
            "cas_execution": self._compact_refs(evidence.cas_execution_records),
            "analytic_reproduction": self._compact_refs(
                [evidence.evidence_card or ""],
                [evidence.independent_gold_script or ""],
                evidence.analytic_reproduction_records,
            ),
            "literature_reproduction": self._compact_refs(
                [evidence.literature_reproduction_record or ""]
            ),
            "assertion_coverage": self._compact_refs(
                [evidence.assertion_coverage_registry or ""],
                evidence.assertion_coverage_records,
            ),
            "benchmark": self._compact_refs(
                evidence.benchmark_cases,
                evidence.benchmark_result_records,
            ),
            "cross_engine": self._compact_refs(evidence.cross_engine_records),
            "external_review": self._compact_refs(evidence.expert_review_records),
            "public_release": self._compact_refs(evidence.public_release_records),
        }
        status = EvidenceStatusIR(
            schema_version=schema_version,
            claim_class=self.evidence_status.claim_class,
            compatibility_knowledge_status="candidate",
            **{
                axis: EvidenceAxisIR(
                    status=getattr(self.evidence_status, axis),
                    artifact_refs=refs,
                )
                for axis, refs in axis_refs.items()
            },
        )
        derived = derive_legacy_knowledge_status(self.support_level, status)
        return status.model_copy(
            update={"compatibility_knowledge_status": derived}
        )

    def all_evidence_refs(self) -> list[str]:
        status = self.resolved_evidence_status(EVIDENCE_STATUS_SCHEMA_VERSION)
        return self._compact_refs(
            [self.evidence.config],
            self.evidence.benchmark_cases,
            [self.evidence.machine_audit_spec or ""],
            *[
                getattr(status, axis).artifact_refs
                for axis in (
                    "cas_execution",
                    "analytic_reproduction",
                    "literature_reproduction",
                    "assertion_coverage",
                    "benchmark",
                    "cross_engine",
                    "external_review",
                    "public_release",
                )
            ],
            self.evidence.references,
        )

    def matches(self, task: TheoryTask) -> bool:
        task_goals = set(task.goals)
        task_assumptions = set(task.assumptions)
        return (
            self.material == task.material
            and self.texture == task.texture
            and self.drive == task.drive
            and self.geometry == task.geometry
            and set(self.required_goals).issubset(task_goals)
            and set(self.required_assumptions).issubset(task_assumptions)
        )


class CapabilityRegistryData(BaseModel):
    schema_version: str
    evidence_status_schema_version: str
    knowledge_lifecycle: list[str]
    routes: list[CapabilityRoute]

    @model_validator(mode="after")
    def validate_registry(self, info: ValidationInfo) -> "CapabilityRegistryData":
        verify_artifacts = bool((info.context or {}).get("verify_artifacts", True))
        route_ids = [route.route_id for route in self.routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("Capability route IDs must be unique.")
        if tuple(self.knowledge_lifecycle) != KNOWLEDGE_LIFECYCLE:
            raise ValueError("Capability registry knowledge lifecycle is invalid or out of order.")
        if self.evidence_status_schema_version != EVIDENCE_STATUS_SCHEMA_VERSION:
            raise ValueError("Capability registry evidence-status schema version is unsupported.")
        for route in self.routes:
            evidence_status = route.resolved_evidence_status(
                self.evidence_status_schema_version
            )
            if route.support_level == "full_derivation":
                required_passed_axes = {
                    "cas_execution",
                    "analytic_reproduction",
                    "assertion_coverage",
                }
                incomplete_axes = sorted(
                    axis
                    for axis in required_passed_axes
                    if getattr(evidence_status, axis).status != "passed"
                )
                if incomplete_axes:
                    raise ValueError(
                        f"Full route {route.route_id} lacks passed evidence axes: "
                        + ", ".join(incomplete_axes)
                    )
                if not route.evidence.benchmark_cases:
                    raise ValueError(
                        f"Full route {route.route_id} must cite at least one benchmark case."
                    )
                if not route.evidence.assertion_coverage_registry:
                    raise ValueError(
                        f"Full route {route.route_id} must register assertion coverage."
                    )
            passed_axes = {
                axis
                for axis in (
                    "cas_execution",
                    "analytic_reproduction",
                    "literature_reproduction",
                    "assertion_coverage",
                    "benchmark",
                    "cross_engine",
                    "external_review",
                    "public_release",
                )
                if getattr(evidence_status, axis).status == "passed"
            }
            passed_artifact_requirements = {
                "cas_execution": route.evidence.cas_execution_records,
                "analytic_reproduction": route.evidence.analytic_reproduction_records,
                "literature_reproduction": [
                    route.evidence.literature_reproduction_record or ""
                ],
                "assertion_coverage": route.evidence.assertion_coverage_records,
                "benchmark": route.evidence.benchmark_result_records,
                "cross_engine": route.evidence.cross_engine_records,
                "external_review": route.evidence.expert_review_records,
                "public_release": route.evidence.public_release_records,
            }
            for axis in passed_axes:
                if not any(passed_artifact_requirements[axis]):
                    raise ValueError(
                        f"Route {route.route_id} marks {axis} passed without a "
                        "passed-result artifact."
                    )
            if evidence_status.benchmark.status == "registered" and not (
                route.evidence.benchmark_cases
            ):
                raise ValueError(
                    f"Route {route.route_id} registers benchmark evidence without a case."
                )
            if verify_artifacts and evidence_status.external_review.status == "passed":
                if not route.evidence.expert_review_records:
                    raise ValueError(
                        f"Route {route.route_id} marks external review passed but has no "
                        "expert-review record."
                    )
                from .expert_review import verify_review_record

                verified = [
                    verify_review_record(PROJECT_ROOT / review_path)
                    for review_path in route.evidence.expert_review_records
                ]
                if not any(
                    review.route_id == route.route_id
                    and review.eligible_for_expert_validation
                    for review in verified
                ):
                    raise ValueError(
                        f"Route {route.route_id} has no eligible signed expert-review record."
                    )
            if verify_artifacts and evidence_status.cross_engine.status == "passed":
                from .cross_engine import verify_cross_engine_result
                from .cross_engine_extended import (
                    EXPECTED_CHECK_IDS as EXTENDED_CROSS_ENGINE_ROUTES,
                )
                from .cross_engine_extended import verify_extended_cross_engine_result

                verifier = (
                    verify_extended_cross_engine_result
                    if route.route_id in EXTENDED_CROSS_ENGINE_ROUTES
                    else verify_cross_engine_result
                )
                verified_cross_engine = [
                    verifier(PROJECT_ROOT / result_path)
                    for result_path in route.evidence.cross_engine_records
                ]
                if not any(
                    result.route_id == route.route_id
                    and result.eligible_for_cross_engine_pass
                    for result in verified_cross_engine
                ):
                    raise ValueError(
                        f"Route {route.route_id} has no eligible cross-engine result."
                    )
            if verify_artifacts and evidence_status.literature_reproduction.status == "passed":
                from .literature import (
                    LiteratureReproductionRecord,
                    evaluate_literature_record,
                )

                literature_path = PROJECT_ROOT / (
                    route.evidence.literature_reproduction_record or ""
                )
                literature_record = LiteratureReproductionRecord.from_yaml(
                    literature_path
                )
                if literature_record.route_id != route.route_id:
                    raise ValueError(
                        f"Route {route.route_id} cites a literature record for "
                        f"{literature_record.route_id}."
                    )
                eligible_literature_result = False
                for evidence_ref in route.evidence.analytic_reproduction_records:
                    evidence_path = PROJECT_ROOT / evidence_ref
                    evidence_payload = json.loads(
                        evidence_path.read_text(encoding="utf-8")
                    )
                    generated_path = Path(evidence_payload["generated_record"])
                    if not generated_path.is_absolute():
                        generated_path = PROJECT_ROOT / generated_path
                    generated_record = json.loads(
                        generated_path.read_text(encoding="utf-8")
                    )
                    evidence_checks = {
                        item["check_id"]: item
                        for item in evidence_payload.get("checks", [])
                    }
                    result = evaluate_literature_record(
                        literature_record,
                        {
                            "physics_ir": generated_record["physics_ir"],
                            "task": generated_record["task"],
                            "wolfram": generated_record.get(
                                "wolfram_results", {}
                            ).get("results", {}),
                            "evidence": {
                                "passed": evidence_payload.get("passed", False),
                                "checks": evidence_checks,
                            },
                        },
                    )
                    if result.status == "pass":
                        eligible_literature_result = True
                        break
                if not eligible_literature_result:
                    raise ValueError(
                        f"Route {route.route_id} has no executable passing "
                        "literature-reproduction result."
                    )
            if route.support_level != "full_derivation" and not route.promotion_requirements:
                raise ValueError(
                    f"Non-full route {route.route_id} must state promotion requirements."
                )
        return self


class CapabilityRegistry:
    def __init__(
        self,
        path: str | Path = DEFAULT_REGISTRY_PATH,
        *,
        verify_artifacts: bool | None = None,
    ):
        self.path = Path(path)
        if verify_artifacts is None:
            try:
                self.path.resolve().relative_to(PACKAGE_ROOT.resolve())
            except ValueError:
                verify_artifacts = True
            else:
                verify_artifacts = False
        self.verify_artifacts = verify_artifacts
        with self.path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        self.data = CapabilityRegistryData.model_validate(
            data,
            context={"verify_artifacts": verify_artifacts},
        )

    @property
    def routes(self) -> list[CapabilityRoute]:
        return self.data.routes

    def match_task(self, task: TheoryTask) -> CapabilityRoute | None:
        matches = [route for route in self.routes if route.matches(task)]
        if not matches:
            return None
        support_rank = {
            "full_derivation": 3,
            "scaffold": 2,
            "review_only": 1,
            "unsupported": 0,
        }
        return max(
            matches,
            key=lambda route: (
                support_rank[route.support_level],
                len(route.required_assumptions),
                len(route.required_goals),
            ),
        )

    def filter_routes(
        self,
        *,
        material: str | None = None,
        texture: str | None = None,
        drive: str | None = None,
        drive_filter_set: bool = False,
        geometry: str | None = None,
        support_level: str | None = None,
        knowledge_status: str | None = None,
    ) -> list[CapabilityRoute]:
        routes = self.routes
        if material is not None:
            routes = [route for route in routes if route.material == material]
        if texture is not None:
            routes = [route for route in routes if route.texture == texture]
        if drive_filter_set:
            routes = [route for route in routes if route.drive == drive]
        if geometry is not None:
            routes = [route for route in routes if route.geometry == geometry]
        if support_level is not None:
            routes = [route for route in routes if route.support_level == support_level]
        if knowledge_status is not None:
            routes = [route for route in routes if route.knowledge_status == knowledge_status]
        return routes


def render_claim_evidence_matrix(registry: CapabilityRegistry) -> str:
    def cell(items: list[str]) -> str:
        if not items:
            return "None declared"
        return "<br>".join(item.replace("|", "\\|") for item in items)

    lines = [
        "# Project 1 claim-evidence matrix",
        "",
        "> Generated from `knowledge_base/capabilities.yaml`. Do not edit route rows manually.",
        "",
        f"Capability registry version: `{registry.data.schema_version}`",
        "",
        "| Route | Support / derived knowledge | Evidence badges | Permitted claim | Registered evidence | "
        "Missing evidence | Limitations |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for route in registry.routes:
        status = route.resolved_evidence_status(
            registry.data.evidence_status_schema_version
        )
        evidence = route.all_evidence_refs() + [
            f"WL: {name}" for name in route.evidence.wolfram_functions
        ]
        badge_items = [
            f"{axis}={getattr(status, axis).status}"
            for axis in (
                "cas_execution",
                "analytic_reproduction",
                "literature_reproduction",
                "assertion_coverage",
                "benchmark",
                "cross_engine",
                "external_review",
                "public_release",
            )
        ]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{route.route_id}`",
                    f"`{route.support_level}` / `{route.knowledge_status}`",
                    cell(badge_items),
                    route.permitted_claim.replace("|", "\\|"),
                    cell(evidence),
                    cell(route.missing_evidence),
                    cell(route.limitations),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Claim rules",
            "",
            "- A benchmark pass is interpreted only within the route's declared support level.",
            "- `candidate`, `scaffold`, and `review_only` outputs cannot be cited as completed derivations.",
            "- Benchmark, external-review, and public-release badges are independent; none is inferred from another.",
            "- The displayed knowledge status is a compatibility summary derived from the badges, not an evidence axis.",
            "- Blocked claims remain blocked even when an LLM assigns high confidence.",
            "",
            "## Blocked claims by route",
            "",
        ]
    )
    for route in registry.routes:
        lines.append(f"### `{route.route_id}`")
        lines.append("")
        if route.blocked_claims:
            lines.extend(f"- {claim}" for claim in route.blocked_claims)
        else:
            lines.append("- No route-specific blocked claim beyond the registered limitations.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
