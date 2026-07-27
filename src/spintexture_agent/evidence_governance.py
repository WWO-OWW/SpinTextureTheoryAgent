from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .schema import EvidenceStatusIR


LegacyKnowledgeStatus = Literal[
    "candidate",
    "symmetry_checked",
    "cas_validated",
    "expert_validated",
    "benchmarked",
    "released",
]
ClaimPolicy = Literal[
    "known_theory_benchmark",
    "software_release",
    "novel_material_specific",
]


class ClaimEligibility(BaseModel):
    policy: ClaimPolicy
    eligible: bool
    satisfied_requirements: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)


def derive_legacy_knowledge_status(
    support_level: str,
    evidence_status: EvidenceStatusIR,
) -> LegacyKnowledgeStatus:
    """Derive the compatibility label without treating evidence axes as ordered."""
    if support_level != "full_derivation":
        return "candidate"
    if evidence_status.public_release.status == "passed":
        return "released"
    if evidence_status.benchmark.status == "passed":
        return "benchmarked"
    if evidence_status.external_review.status == "passed":
        return "expert_validated"
    if evidence_status.cas_execution.status == "passed":
        return "cas_validated"
    return "candidate"


def evaluate_claim_eligibility(
    policy: ClaimPolicy,
    *,
    support_level: str,
    evidence_status: EvidenceStatusIR,
) -> ClaimEligibility:
    requirements: dict[ClaimPolicy, tuple[str, ...]] = {
        "known_theory_benchmark": (
            "full_derivation_support",
            "cas_execution",
            "analytic_reproduction",
            "assertion_coverage",
            "benchmark",
        ),
        "software_release": ("public_release",),
        "novel_material_specific": (
            "full_derivation_support",
            "novel_material_specific_claim_class",
            "cas_execution",
            "analytic_reproduction",
            "assertion_coverage",
            "external_review",
        ),
    }
    satisfied: list[str] = []
    blocked: list[str] = []

    for requirement in requirements[policy]:
        if requirement == "full_derivation_support":
            passed = support_level == "full_derivation"
        elif requirement == "novel_material_specific_claim_class":
            passed = evidence_status.claim_class == "novel_material_specific"
        else:
            passed = getattr(evidence_status, requirement).status == "passed"
        if passed:
            satisfied.append(requirement)
        else:
            blocked.append(requirement)

    return ClaimEligibility(
        policy=policy,
        eligible=not blocked,
        satisfied_requirements=satisfied,
        blocking_reasons=blocked,
    )
