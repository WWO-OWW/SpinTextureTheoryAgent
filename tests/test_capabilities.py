import json
from pathlib import Path

import pytest
import yaml

from spintexture_agent.capabilities import (
    EVIDENCE_STATUS_SCHEMA_VERSION,
    KNOWLEDGE_LIFECYCLE,
    CapabilityRegistry,
    render_claim_evidence_matrix,
)
from spintexture_agent.cli import build_parser, cmd_capabilities
from spintexture_agent.ir import build_physics_ir
from spintexture_agent.kb import KnowledgeBase
from spintexture_agent.schema import TheoryTask
from spintexture_agent.selector import select_template


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_registry_loads_auditable_routes_and_existing_evidence():
    registry = CapabilityRegistry()

    assert registry.data.schema_version == "2.0.0"
    assert (
        registry.data.evidence_status_schema_version
        == EVIDENCE_STATUS_SCHEMA_VERSION
    )
    assert tuple(registry.data.knowledge_lifecycle) == KNOWLEDGE_LIFECYCLE
    assert len(registry.routes) == 12
    assert len({route.route_id for route in registry.routes}) == len(registry.routes)

    package_text = (PROJECT_ROOT / "mathematica/SpinTextureTheory.wl").read_text(
        encoding="utf-8"
    )
    for route in registry.routes:
        assert (PROJECT_ROOT / route.evidence.config).exists()
        for benchmark_case in route.evidence.benchmark_cases:
            assert (PROJECT_ROOT / benchmark_case).exists()
        if route.evidence.evidence_card:
            assert (PROJECT_ROOT / route.evidence.evidence_card).exists()
        if route.evidence.independent_gold_script:
            assert (PROJECT_ROOT / route.evidence.independent_gold_script).exists()
        if route.evidence.machine_audit_spec:
            assert (PROJECT_ROOT / route.evidence.machine_audit_spec).exists()
        if route.evidence.assertion_coverage_registry:
            assert (PROJECT_ROOT / route.evidence.assertion_coverage_registry).exists()
        for record in route.evidence.cas_execution_records:
            assert (PROJECT_ROOT / record).exists()
        for record in route.evidence.analytic_reproduction_records:
            assert (PROJECT_ROOT / record).exists()
        for record in route.evidence.assertion_coverage_records:
            assert (PROJECT_ROOT / record).exists()
        if route.evidence.literature_reproduction_record:
            assert (
                PROJECT_ROOT / route.evidence.literature_reproduction_record
            ).exists()
        for review_record in route.evidence.expert_review_records:
            assert (PROJECT_ROOT / review_record).exists()
        for record in route.evidence.benchmark_result_records:
            assert (PROJECT_ROOT / record).exists()
        for record in route.evidence.cross_engine_records:
            assert (PROJECT_ROOT / record).exists()
        for record in route.evidence.public_release_records:
            assert (PROJECT_ROOT / record).exists()
        for function_name in route.evidence.wolfram_functions:
            assert f"{function_name}::usage" in package_text


def test_every_shipped_config_matches_registry_and_physics_ir():
    registry = CapabilityRegistry()
    kb = KnowledgeBase()

    for config_path in sorted((PROJECT_ROOT / "configs").glob("*.yaml")):
        task = TheoryTask.from_yaml(config_path)
        route = registry.match_task(task)
        assert route is not None, f"Unregistered config: {config_path.name}"

        template = select_template(task, kb)
        physics_ir = build_physics_ir(task, template, kb)
        assert physics_ir.capability_route_id == route.route_id
        assert physics_ir.support_level == route.support_level
        assert physics_ir.knowledge_status == route.knowledge_status
        assert (
            physics_ir.evidence_status.compatibility_knowledge_status
            == route.knowledge_status
        )
        assert physics_ir.permitted_claim == route.permitted_claim
        assert physics_ir.blocked_claims == route.blocked_claims
        assert physics_ir.confidence.requires_human_review == route.requires_human_review


def test_unregistered_task_is_downgraded_to_candidate():
    task = TheoryTask(
        task_name="unregistered_fm_stripe",
        material="ferromagnet",
        texture="stripe_domain",
        drive="spin_orbit_torque",
        geometry="thin_film_2d",
        goals=["derive_collective_coordinate_equation"],
    )
    kb = KnowledgeBase()
    template = select_template(task, kb)
    physics_ir = build_physics_ir(task, template, kb)

    assert physics_ir.capability_route_id is None
    assert physics_ir.knowledge_status == "candidate"
    assert physics_ir.support_level != "full_derivation"
    assert physics_ir.missing_evidence
    assert physics_ir.promotion_requirements
    assert physics_ir.blocked_claims
    assert physics_ir.confidence.requires_human_review is True


def test_registry_filters_topology_only_routes():
    routes = CapabilityRegistry().filter_routes(
        material="ferromagnet",
        drive=None,
        drive_filter_set=True,
        support_level="full_derivation",
    )

    assert {route.texture for route in routes} == {"meron", "bimeron", "vortex"}


def test_current_full_routes_keep_independent_evidence_states():
    registry = CapabilityRegistry()
    full_routes = [
        route for route in registry.routes if route.support_level == "full_derivation"
    ]

    assert len(full_routes) == 7
    for route in full_routes:
        status = route.resolved_evidence_status(
            registry.data.evidence_status_schema_version
        )
        assert status.cas_execution.status == "passed"
        assert status.analytic_reproduction.status == "passed"
        assert status.assertion_coverage.status == "passed"
        assert status.benchmark.status == "registered"
        assert status.cross_engine.status == "passed"
        assert status.external_review.status == "pending"
        assert status.public_release.status == "passed"
        assert status.compatibility_knowledge_status == "released"

    assert sum(
        route.evidence_status.literature_reproduction == "passed"
        for route in full_routes
    ) == 7
    assert sum(
        route.evidence_status.cross_engine == "passed" for route in full_routes
    ) == 7


def test_literature_pass_rejects_a_registered_but_false_executable_result(tmp_path):
    registry_payload = yaml.safe_load(
        (PROJECT_ROOT / "knowledge_base/capabilities.yaml").read_text(
            encoding="utf-8"
        )
    )
    route = next(
        item
        for item in registry_payload["routes"]
        if item["route_id"] == "fm_meron_topology_full"
    )
    evidence_path = PROJECT_ROOT / route["evidence"][
        "analytic_reproduction_records"
    ][0]
    evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    generated_path = Path(evidence_payload["generated_record"])
    generated_payload = json.loads(generated_path.read_text(encoding="utf-8"))
    generated_payload["wolfram_results"]["results"][
        "literature_meron_exact_regression"
    ] = "False"

    false_generated_path = tmp_path / "false_generated_record.json"
    false_generated_path.write_text(
        json.dumps(generated_payload, indent=2), encoding="utf-8"
    )
    evidence_payload["generated_record"] = str(false_generated_path)
    false_evidence_path = tmp_path / "false_evidence_result.json"
    false_evidence_path.write_text(
        json.dumps(evidence_payload, indent=2), encoding="utf-8"
    )
    route["evidence"]["analytic_reproduction_records"] = [
        str(false_evidence_path)
    ]

    registry_path = tmp_path / "capabilities.yaml"
    registry_path.write_text(
        yaml.safe_dump(registry_payload, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(
        ValueError, match="no executable passing literature-reproduction result"
    ):
        CapabilityRegistry(registry_path)


def test_runtime_registry_mode_keeps_structure_without_source_evidence_access(
    tmp_path,
):
    registry_payload = yaml.safe_load(
        (PROJECT_ROOT / "knowledge_base/capabilities.yaml").read_text(
            encoding="utf-8"
        )
    )
    route = next(
        item
        for item in registry_payload["routes"]
        if item["route_id"] == "afm_stripe_sot_full"
    )
    route["evidence"]["cross_engine_records"] = ["missing/cross_engine.json"]
    route["evidence"]["literature_reproduction_record"] = "missing/literature.yaml"
    registry_path = tmp_path / "runtime_capabilities.yaml"
    registry_path.write_text(
        yaml.safe_dump(registry_payload, sort_keys=False), encoding="utf-8"
    )

    registry = CapabilityRegistry(registry_path, verify_artifacts=False)

    assert registry.verify_artifacts is False
    assert len(registry.routes) == 12
    assert registry.data.schema_version == "2.0.0"


def test_custom_registry_still_verifies_evidence_by_default(tmp_path):
    registry_payload = yaml.safe_load(
        (PROJECT_ROOT / "knowledge_base/capabilities.yaml").read_text(
            encoding="utf-8"
        )
    )
    route = next(
        item
        for item in registry_payload["routes"]
        if item["route_id"] == "afm_stripe_sot_full"
    )
    route["evidence"]["cross_engine_records"] = ["missing/cross_engine.json"]
    registry_path = tmp_path / "development_capabilities.yaml"
    registry_path.write_text(
        yaml.safe_dump(registry_payload, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(FileNotFoundError, match="Cross-engine result does not exist"):
        CapabilityRegistry(registry_path)


def test_public_release_pass_requires_eligible_remote_result(tmp_path):
    registry_payload = yaml.safe_load(
        (PROJECT_ROOT / "knowledge_base/capabilities.yaml").read_text(
            encoding="utf-8"
        )
    )
    route = next(
        item
        for item in registry_payload["routes"]
        if item["route_id"] == "afm_stripe_sot_full"
    )
    fake_evidence = tmp_path / "public_release_evidence_record.yaml"
    fake_evidence.write_text(
        yaml.safe_dump(
            {
                "evidence_axis": "public_release",
                "status": "passed",
                "scope": "software_distribution",
            }
        ),
        encoding="utf-8",
    )
    route["evidence"]["public_release_records"] = [str(fake_evidence)]
    registry_path = tmp_path / "capabilities.yaml"
    registry_path.write_text(
        yaml.safe_dump(registry_payload, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="no eligible public-release result"):
        CapabilityRegistry(registry_path)


def test_capabilities_cli_supports_machine_readable_output(capsys):
    parser = build_parser()
    args = parser.parse_args(
        [
            "capabilities",
            "--material",
            "collinear_antiferromagnet",
            "--texture",
            "stripe_domain",
            "--json",
        ]
    )
    cmd_capabilities(args)
    output = capsys.readouterr().out
    payload = json.loads(output)

    assert payload["schema_version"] == "2.0.0"
    assert payload["evidence_status_schema_version"] == "1.0.0"
    assert payload["knowledge_lifecycle_role"] == "derived_compatibility_summary"
    assert {route["route_id"] for route in payload["routes"]} == {
        "afm_stripe_sot_full",
        "afm_stripe_unspecified_dmi_review",
    }


def test_claim_evidence_matrix_is_registry_derived():
    registry = CapabilityRegistry()
    matrix = render_claim_evidence_matrix(registry)

    assert "Capability registry version: `2.0.0`" in matrix
    assert "cas_execution=passed" in matrix
    assert "benchmark=registered" in matrix
    for route in registry.routes:
        assert f"`{route.route_id}`" in matrix
        assert route.permitted_claim in matrix


def test_legacy_status_cannot_be_promoted_independently_of_evidence_axes(tmp_path):
    source = PROJECT_ROOT / "knowledge_base/capabilities.yaml"
    registry_data = source.read_text(encoding="utf-8").replace(
        "    support_level: full_derivation\n",
        "    support_level: full_derivation\n"
        "    knowledge_status: expert_validated\n",
        1,
    )
    registry_path = tmp_path / "capabilities.yaml"
    registry_path.write_text(registry_data, encoding="utf-8")

    try:
        CapabilityRegistry(registry_path)
    except ValueError as exc:
        assert "knowledge_status" in str(exc)
        assert "Extra inputs are not permitted" in str(exc)
    else:
        raise AssertionError("legacy status drift loaded without an evidence-axis change")
