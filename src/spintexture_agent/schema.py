from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class TheoryTask(BaseModel):
    task_name: str
    material: str
    texture: str
    drive: str | None = None
    geometry: str | None = None
    goals: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    parameters: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TheoryTask":
        with Path(path).open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)
        return cls(**data)


class OrderParameterIR(BaseModel):
    primary: str
    auxiliary: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    topology_field: str | None = None


class DynamicsIR(BaseModel):
    type: str
    inertial_term: bool = False
    gyrotropic_term: str | None = None
    expected_equation_type: str


class AnsatzIR(BaseModel):
    type: str
    collective_coordinates: list[str] = Field(default_factory=list)
    validity: list[str] = Field(default_factory=list)


class ConfidenceIR(BaseModel):
    model_selection: float
    ansatz_validity: float
    topology_definition: float
    requires_human_review: bool = False


class DimensionContractIR(BaseModel):
    basis: list[str] = Field(default_factory=list)
    convention: str
    assignments: dict[str, str] = Field(default_factory=dict)
    expected_equation_dimensions: dict[str, str] = Field(default_factory=dict)


EvidenceAxisStatus = Literal[
    "not_applicable",
    "missing",
    "pending",
    "registered",
    "passed",
    "failed",
]
EvidenceClaimClass = Literal[
    "known_theory",
    "candidate_extension",
    "novel_material_specific",
]


class EvidenceAxisIR(BaseModel):
    status: EvidenceAxisStatus
    artifact_refs: list[str] = Field(default_factory=list)


class EvidenceStatusIR(BaseModel):
    schema_version: str
    scope: Literal["capability_route"] = "capability_route"
    claim_class: EvidenceClaimClass
    cas_execution: EvidenceAxisIR
    analytic_reproduction: EvidenceAxisIR
    literature_reproduction: EvidenceAxisIR
    assertion_coverage: EvidenceAxisIR
    benchmark: EvidenceAxisIR
    cross_engine: EvidenceAxisIR
    external_review: EvidenceAxisIR
    public_release: EvidenceAxisIR
    compatibility_knowledge_status: str


class PhysicsIR(BaseModel):
    task_name: str
    material_class: str
    texture_class: str
    drive: str | None = None
    geometry: str | None = None
    support_level: str
    knowledge_status: str
    evidence_status: EvidenceStatusIR
    permitted_claim: str
    blocked_claims: list[str] = Field(default_factory=list)
    capability_route_id: str | None = None
    capability_registry_version: str
    evidence_refs: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    promotion_requirements: list[str] = Field(default_factory=list)
    capability_limitations: list[str] = Field(default_factory=list)
    dimension_contract: DimensionContractIR | None = None
    order_parameter: OrderParameterIR
    energy_terms: list[str] = Field(default_factory=list)
    dynamics: DynamicsIR
    ansatz: AnsatzIR
    analysis: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    validity_limits: list[str] = Field(default_factory=list)
    limit_checks: list[str] = Field(default_factory=list)
    confidence: ConfidenceIR
