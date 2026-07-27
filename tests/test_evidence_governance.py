from spintexture_agent.capabilities import CapabilityRegistry
from spintexture_agent.evidence_governance import (
    derive_legacy_knowledge_status,
    evaluate_claim_eligibility,
)


def _status():
    route = next(
        route
        for route in CapabilityRegistry().routes
        if route.route_id == "afm_stripe_sot_full"
    )
    return route.resolved_evidence_status("1.0.0")


def test_pending_external_review_does_not_block_known_theory_benchmark():
    status = _status()
    benchmarked = status.model_copy(
        update={
            "benchmark": status.benchmark.model_copy(
                update={"status": "passed", "artifact_refs": ["benchmark.json"]}
            )
        }
    )

    decision = evaluate_claim_eligibility(
        "known_theory_benchmark",
        support_level="full_derivation",
        evidence_status=benchmarked,
    )

    assert benchmarked.external_review.status == "pending"
    assert decision.eligible
    assert derive_legacy_knowledge_status("full_derivation", benchmarked) == "benchmarked"


def test_pending_external_review_does_not_block_software_release_evidence():
    status = _status()
    released = status.model_copy(
        update={
            "public_release": status.public_release.model_copy(
                update={"status": "passed", "artifact_refs": ["release.json"]}
            )
        }
    )

    decision = evaluate_claim_eligibility(
        "software_release",
        support_level="full_derivation",
        evidence_status=released,
    )

    assert released.external_review.status == "pending"
    assert decision.eligible
    assert derive_legacy_knowledge_status("full_derivation", released) == "released"


def test_unsupported_novel_material_claim_cannot_be_promoted():
    status = _status().model_copy(
        update={"claim_class": "novel_material_specific"}
    )

    decision = evaluate_claim_eligibility(
        "novel_material_specific",
        support_level="review_only",
        evidence_status=status,
    )

    assert not decision.eligible
    assert "full_derivation_support" in decision.blocking_reasons
    assert "external_review" in decision.blocking_reasons
    assert derive_legacy_knowledge_status("review_only", status) == "candidate"


def test_registered_benchmark_is_not_a_passed_benchmark():
    status = _status()

    decision = evaluate_claim_eligibility(
        "known_theory_benchmark",
        support_level="full_derivation",
        evidence_status=status,
    )

    assert status.benchmark.status == "registered"
    assert not decision.eligible
    assert decision.blocking_reasons == ["benchmark"]
