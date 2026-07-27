from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .ablation import run_ablation_profiles
from .assertion_coverage import run_assertion_coverage
from .baseline import run_baseline_profiles
from .benchmark_authoring import (
    generate_authoring_packet,
    verify_authoring_packet,
)
from .benchmark_collection import (
    launch_external_collection_round,
    verify_collection_release,
)
from .benchmark_intake import (
    generate_freeze_preview,
    stage_authoring_packet,
    verify_intake_stage,
)
from .benchmark_manifest import BenchmarkManifestRegistry
from .benchmark_materialization import (
    ReleaseManagerApproval,
    create_system_freeze_package,
    generate_custodian_handoff_template,
    generate_registration_candidate,
    verify_custodian_handoff,
    verify_system_freeze_package,
)
from .benchmark_operator import (
    DEFAULT_PUBLICATION_EVIDENCE,
    DEFAULT_PUBLICATION_RECORD,
    initialize_private_ledger,
    plan_or_record_event,
    verify_private_ledger,
    verify_publication_gate,
)
from .benchmark_outreach import (
    DEFAULT_HANDOFF as DEFAULT_OUTREACH_HANDOFF,
    DEFAULT_HANDOFF_ID as DEFAULT_OUTREACH_HANDOFF_ID,
    create_outreach_handoff,
    verify_outreach_handoff,
)
from .capabilities import CapabilityRegistry, render_claim_evidence_matrix
from .checker import check_task
from .cross_engine import run_cross_engine_suite, verify_cross_engine_result
from .cross_engine_extended import (
    run_extended_cross_engine_suite,
    verify_extended_cross_engine_result,
)
from .distribution_bundle import (
    DEFAULT_BUNDLE_ID,
    create_distribution_bundle,
    verify_distribution_bundle,
)
from .evaluator import evaluate_benchmark_cases
from .evidence import run_evidence_cards
from .expert_review import generate_review_packet, verify_review_packet
from .generator import generate_task_bundle
from .ir import build_physics_ir
from .kb import KnowledgeBase
from .machine_audit import run_machine_audit_suite
from .nl import PromptParseError, parse_natural_language_task, task_to_yaml
from .nl_benchmark import evaluate_nl_benchmark_cases
from .recorded_baseline import evaluate_recorded_baselines
from .readability import generate_readability_packet, run_readability_study
from .release_candidate import (
    DEFAULT_CANDIDATE_ID,
    create_release_candidate,
    verify_release_candidate,
)
from .schema import TheoryTask
from .selector import select_template
from .wolfram import execute_wolfram_script, update_wolfram_execution_record

console = Console()


def _prepare(task: TheoryTask):
    kb = KnowledgeBase()
    template = select_template(task, kb)
    physics_ir = build_physics_ir(task, template, kb)
    report = check_task(task, template, kb, physics_ir)
    return task, kb, template, physics_ir, report


def _load(config: str):
    return _prepare(TheoryTask.from_yaml(config))


def _prompt_text(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    raise SystemExit("Provide a prompt argument or --prompt-file.")


def _generate_paths(
    task: TheoryTask,
    template,
    physics_ir,
    report,
    args: argparse.Namespace,
) -> dict[str, Path]:
    paths = generate_task_bundle(task, template, report, Path(args.out), physics_ir=physics_ir)
    if getattr(args, "execute_wolfram", False):
        log_dir = Path(args.out) / "wolfram_logs"
        execution = execute_wolfram_script(
            paths["wolfram"],
            log_dir,
            timeout_seconds=args.wolfram_timeout,
        )
        update_wolfram_execution_record(paths["record"], execution)
        console.print(f"[bold]Wolfram execution:[/] {execution.status}")
        if execution.reason:
            console.print(f"- reason: {execution.reason}")
    return paths


def cmd_validate(args: argparse.Namespace) -> None:
    task, _, template, physics_ir, report = _load(args.config)
    console.print(f"[bold]Task:[/] {task.task_name}")
    console.print(f"[bold]Selected template:[/] {template.name}")
    console.print(f"[bold]Physics IR topology field:[/] {physics_ir.order_parameter.topology_field}")
    console.print(f"[bold]Support level:[/] {physics_ir.support_level}")
    console.print(f"[bold]Knowledge status:[/] {physics_ir.knowledge_status}")
    console.print(f"[bold]Capability route:[/] {physics_ir.capability_route_id}")
    for item in report.items:
        label = "CHECK"
        style = "green"
        if item.severity == "warning":
            label = "WARNING"
            style = "yellow"
        elif item.severity == "error":
            label = "ERROR"
            style = "red"
        console.print(f"[{style}]{label}[/] {item.id}: {item.message}")
    if report.ok:
        console.print("[bold green]Validation passed.[/]")
    else:
        console.print("[bold yellow]Validation completed with warnings.[/]")


def cmd_plan(args: argparse.Namespace) -> None:
    task, _, template, physics_ir, report = _load(args.config)
    table = Table(title=f"Plan for {task.task_name}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Material", task.material)
    table.add_row("Texture", task.texture)
    table.add_row("Drive", str(task.drive))
    table.add_row("Dynamics", template.dynamics)
    table.add_row("Order parameters", ", ".join(template.order_parameters))
    table.add_row("Topology field", str(physics_ir.order_parameter.topology_field))
    table.add_row("Ansatz", template.ansatz)
    table.add_row("Reduced model", str(template.reduced_model))
    table.add_row("Capability route", str(physics_ir.capability_route_id))
    table.add_row("Support level", physics_ir.support_level)
    table.add_row("Knowledge status", physics_ir.knowledge_status)
    table.add_row("Limit checks", str(len(physics_ir.limit_checks)))
    table.add_row("Human review", str(physics_ir.confidence.requires_human_review))
    table.add_row("Warnings", str(len(report.warnings)))
    console.print(table)


def cmd_run(args: argparse.Namespace) -> None:
    task, _, template, physics_ir, report = _load(args.config)
    paths = _generate_paths(task, template, physics_ir, report, args)
    console.print("[bold green]Generated task bundle:[/]")
    for label, path in paths.items():
        console.print(f"- {label}: {path}")


def cmd_parse(args: argparse.Namespace) -> None:
    try:
        parsed = parse_natural_language_task(_prompt_text(args), task_name=args.task_name)
    except PromptParseError as exc:
        raise SystemExit(str(exc)) from exc

    yaml_text = task_to_yaml(parsed.task)
    if args.out_config:
        out_config = Path(args.out_config)
        out_config.parent.mkdir(parents=True, exist_ok=True)
        out_config.write_text(yaml_text, encoding="utf-8")
        console.print(f"[bold green]Parsed config:[/] {out_config}")
    else:
        console.print(yaml_text.rstrip())

    if parsed.matched_aliases:
        console.print("[bold]Matched aliases:[/]")
        for field, alias in parsed.matched_aliases.items():
            console.print(f"- {field}: {alias}")
    for warning in parsed.warnings:
        console.print(f"[yellow]WARNING[/] {warning}")

    if args.show_plan:
        _, _, template, physics_ir, report = _prepare(parsed.task)
        console.print(f"[bold]Selected template:[/] {template.name}")
        console.print(f"[bold]Dynamics:[/] {physics_ir.dynamics.type}")
        console.print(f"[bold]Equation type:[/] {physics_ir.dynamics.expected_equation_type}")
        console.print(f"[bold]Human review:[/] {physics_ir.confidence.requires_human_review}")
        console.print(f"[bold]Validator warnings:[/] {len(report.warnings)}")


def cmd_run_prompt(args: argparse.Namespace) -> None:
    try:
        parsed = parse_natural_language_task(_prompt_text(args), task_name=args.task_name)
    except PromptParseError as exc:
        raise SystemExit(str(exc)) from exc

    if args.save_config:
        save_config = Path(args.save_config)
        save_config.parent.mkdir(parents=True, exist_ok=True)
        save_config.write_text(task_to_yaml(parsed.task), encoding="utf-8")
        console.print(f"[bold]Saved parsed config:[/] {save_config}")

    task, _, template, physics_ir, report = _prepare(parsed.task)
    console.print(f"[bold]Parsed task:[/] {task.task_name}")
    console.print(f"[bold]Selected template:[/] {template.name}")
    if parsed.warnings:
        for warning in parsed.warnings:
            console.print(f"[yellow]WARNING[/] {warning}")
    paths = _generate_paths(task, template, physics_ir, report, args)
    console.print("[bold green]Generated task bundle:[/]")
    for label, path in paths.items():
        console.print(f"- {label}: {path}")


def cmd_benchmark(args: argparse.Namespace) -> None:
    run = evaluate_benchmark_cases(
        args.cases,
        args.out,
        args.bundle_out,
        args.archive,
        execute_wolfram=args.execute_wolfram,
        wolfram_timeout=args.wolfram_timeout,
    )
    table = Table(title="Benchmark scores")
    table.add_column("Case")
    table.add_column("Support")
    table.add_column("Score")
    table.add_column("Status")
    for case in run.cases:
        table.add_row(case.case_id, case.support_level, f"{case.score}/{case.max_score}", case.status)
    console.print(table)
    console.print(
        f"[bold]Summary:[/] {run.passed_cases}/{len(run.cases)} cases satisfied their declared support level, "
        f"{run.total_score}/{run.max_score} checks passed"
    )
    console.print(f"[bold]CSV:[/] {run.csv_path}")
    console.print(f"[bold]JSON:[/] {run.json_path}")
    if run.archive_dir:
        console.print(f"[bold]Archive:[/] {run.archive_dir}")


def cmd_benchmark_manifest(args: argparse.Namespace) -> None:
    registry = BenchmarkManifestRegistry(args.manifest)
    if args.require_release_ready:
        try:
            registry.require_release_ready()
        except ValueError as exc:
            raise SystemExit(f"Benchmark release gate failed: {exc}") from exc
    record = registry.to_record()
    if args.json:
        print(registry.to_json())
        return

    table = Table(title="SpinTextureDynamicsBench manifest")
    table.add_column("Primary partition")
    table.add_column("Freeze")
    table.add_column("Cases", justify="right")
    table.add_column("Gold visibility")
    table.add_column("Leakage")
    for partition in record["partitions"]:
        gold = ", ".join(
            f"{key}={value}"
            for key, value in partition["gold_visibility_counts"].items()
            if value
        )
        leakage = ", ".join(
            f"{key}={value}"
            for key, value in partition["leakage_status_counts"].items()
            if value
        )
        table.add_row(
            partition["primary_partition"],
            partition["freeze_status"],
            str(partition["case_count"]),
            gold or "none",
            leakage or "none",
        )
    console.print(table)
    console.print(f"[bold]Benchmark:[/] {record['benchmark_id']}")
    console.print(f"[bold]Version:[/] {record['benchmark_version']}")
    console.print(f"[bold]Suite freeze:[/] {record['freeze_status']}")
    console.print(f"[bold]Registered cases:[/] {record['case_count']}")
    console.print(f"[bold]Release ready:[/] {str(record['release_ready']).lower()}")


def cmd_benchmark_authoring_packet(args: argparse.Namespace) -> None:
    try:
        packet = generate_authoring_packet(args.out, args.benchmark_manifest)
    except (FileExistsError, ValueError) as exc:
        raise SystemExit(f"Benchmark authoring packet failed: {exc}") from exc
    console.print(f"[bold green]Authoring packet:[/] {packet.packet_dir}")
    console.print(f"[bold]Manifest:[/] {packet.manifest_path}")
    console.print(f"[bold]Operator guide:[/] {packet.guide_path}")
    console.print(f"[bold]Templates:[/] {len(packet.template_paths)}")


def cmd_benchmark_authoring_verify(args: argparse.Namespace) -> None:
    try:
        result = verify_authoring_packet(args.packet, args.benchmark_manifest)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Benchmark authoring verification failed: {exc}") from exc
    if args.json:
        print(result.to_json())
    else:
        table = Table(title="Benchmark case authoring verification")
        table.add_column("Case")
        table.add_column("Partition")
        table.add_column("Status")
        table.add_column("Issues")
        for case in result.cases:
            table.add_row(
                case.case_id,
                case.primary_partition,
                "passed" if case.passed else "failed",
                "; ".join(case.issues) or "none",
            )
        console.print(table)
        for issue in result.packet_issues:
            console.print(f"[yellow]PACKET[/] {issue}")
        console.print(f"[bold]Cases:[/] {result.passed_cases}/{result.case_count}")
        console.print(
            f"[bold]Ready for intake:[/] {str(result.ready_for_intake).lower()}"
        )
    if args.require_ready and not result.ready_for_intake:
        raise SystemExit("Benchmark authoring packet is not ready for intake")


def cmd_benchmark_collection_launch(args: argparse.Namespace) -> None:
    try:
        result = launch_external_collection_round(
            args.out,
            benchmark_manifest=args.benchmark_manifest,
            capability_registry=args.capability_registry,
            scorer_registry=args.scorer_registry,
            frozen_at=args.frozen_at,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Benchmark collection launch failed: {exc}") from exc
    console.print(f"[bold green]Collection release:[/] {result.release_dir}")
    console.print(f"[bold]Frozen plan:[/] {result.plan_path}")
    console.print(f"[bold]Empty ledger:[/] {result.ledger_path}")
    console.print(f"[bold]Archive:[/] {result.archive_path}")
    console.print(f"[bold]Archive SHA-256:[/] {result.archive_sha256}")
    console.print(f"[bold]Release-index SHA-256:[/] {result.release_index_sha256}")
    console.print("[bold]Participant identities:[/] 0")
    console.print("[bold]Submitted cases:[/] 0")
    console.print("[bold]Real manifests modified:[/] false")


def cmd_benchmark_collection_verify(args: argparse.Namespace) -> None:
    try:
        result = verify_collection_release(args.release)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Benchmark collection verification failed: {exc}") from exc
    if args.json:
        print(result.to_json())
    else:
        console.print(f"[bold]Collection ID:[/] {result.collection_id}")
        console.print(
            "[bold]Ready for distribution:[/] "
            f"{str(result.ready_for_distribution).lower()}"
        )
        console.print(
            "[bold]Byte-for-byte reconstruction:[/] "
            f"{str(result.byte_for_byte_reconstruction).lower()}"
        )
        console.print(f"[bold]Payload files:[/] {result.payload_file_count}")
        console.print(f"[bold]Participant identities:[/] {result.invited_identity_count}")
        console.print(f"[bold]Submitted cases:[/] {result.submitted_case_count}")
        if result.issues:
            console.print("[bold red]Issues:[/] " + "; ".join(result.issues))
    if args.require_ready and not result.ready_for_distribution:
        raise SystemExit("Benchmark collection release is not ready for distribution")


def _operator_result(result: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
        return
    console.print(f"[bold]Status:[/] {result['status']}")
    for field in (
        "operation",
        "ledger_id",
        "event_id",
        "event_type",
        "invitation_id",
        "resulting_state",
        "preview_sha256",
        "head_snapshot_manifest_sha256",
    ):
        if result.get(field) is not None:
            console.print(f"[bold]{field}:[/] {result[field]}")
    for field in (
        "write_performed",
        "publication_gate_passed",
        "ledger_valid",
        "participant_identity_count",
        "invitation_entry_count",
        "submitted_case_count",
        "human_rating_count",
        "real_manifests_modified",
    ):
        if field in result:
            console.print(f"[bold]{field}:[/] {result[field]}")
    if result.get("issues"):
        console.print("[bold red]Issues:[/] " + "; ".join(result["issues"]))


def cmd_benchmark_operator_gate(args: argparse.Namespace) -> None:
    result = verify_publication_gate(
        args.publication_evidence,
        args.publication_record,
        args.collection_release,
    )
    _operator_result(result, as_json=args.json)
    if args.require_pass and not result["publication_gate_passed"]:
        raise SystemExit("Round-01 publication gate did not pass")


def cmd_benchmark_operator_initialize(args: argparse.Namespace) -> None:
    try:
        result = initialize_private_ledger(
            args.out,
            ledger_id=args.ledger_id,
            operator_id=args.operator_id,
            created_at=args.created_at,
            publication_evidence=args.publication_evidence,
            publication_record=args.publication_record,
            collection_release=args.collection_release,
            commit=args.commit,
            preview_sha256=args.preview_sha256,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Private operator-ledger initialization failed: {exc}") from exc
    _operator_result(result, as_json=args.json)


def cmd_benchmark_operator_record(args: argparse.Namespace) -> None:
    try:
        result = plan_or_record_event(
            args.ledger,
            args.request,
            commit=args.commit,
            preview_sha256=args.preview_sha256,
            confirm_real_event=args.confirm_real_event,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Private operator event failed: {exc}") from exc
    _operator_result(result, as_json=args.json)


def cmd_benchmark_operator_verify(args: argparse.Namespace) -> None:
    try:
        result = verify_private_ledger(args.ledger)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Private operator-ledger verification failed: {exc}") from exc
    _operator_result(result, as_json=args.json)
    if args.require_valid and not result["ledger_valid"]:
        raise SystemExit("Private operator ledger did not pass verification")


def _outreach_result(result: dict, *, as_json: bool) -> None:
    if as_json:
        console.print_json(json.dumps(result))
        return
    color = "green" if result.get("handoff_ready") else "red"
    console.print(f"[bold {color}]Outreach handoff:[/] {result.get('status')}")
    for field in (
        "handoff_id",
        "manifest_sha256",
        "outreach_opening_at",
        "messages_sent",
        "participation_confirmed",
        "participant_identity_count",
        "invitation_event_count",
        "submitted_case_count",
        "human_rating_count",
    ):
        if field in result:
            console.print(f"[bold]{field}:[/] {result[field]}")
    if result.get("issues"):
        console.print("[bold red]Issues:[/] " + "; ".join(result["issues"]))


def cmd_benchmark_outreach_create(args: argparse.Namespace) -> None:
    try:
        result = create_outreach_handoff(
            args.out,
            handoff_id=args.handoff_id,
            created_at=args.created_at,
            publication_evidence=args.publication_evidence,
            publication_record=args.publication_record,
            collection_release=args.collection_release,
            ledger_protocol=args.ledger_protocol,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Outreach handoff creation failed: {exc}") from exc
    _outreach_result(result, as_json=args.json)


def cmd_benchmark_outreach_verify(args: argparse.Namespace) -> None:
    try:
        result = verify_outreach_handoff(
            args.handoff,
            collection_release=args.collection_release,
            ledger_protocol=args.ledger_protocol,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Outreach handoff verification failed: {exc}") from exc
    _outreach_result(result, as_json=args.json)
    if args.require_ready and not result["handoff_ready"]:
        raise SystemExit("Outreach handoff did not pass verification")


def cmd_release_candidate_create(args: argparse.Namespace) -> None:
    try:
        result = create_release_candidate(
            args.out,
            candidate_id=args.candidate_id,
            created_at=args.created_at,
            capability_registry=args.capability_registry,
            pytest_timeout=args.pytest_timeout,
            command_timeout=args.command_timeout,
            wolfram_timeout=args.wolfram_timeout,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Release-candidate creation failed: {exc}") from exc
    console.print(f"[bold green]Release candidate:[/] {result.candidate_dir}")
    console.print(f"[bold]Manifest:[/] {result.manifest_path}")
    console.print(f"[bold]Manifest SHA-256:[/] {result.manifest_sha256}")
    console.print(
        "[bold]Software candidate ready:[/] "
        f"{str(result.software_release_candidate_ready).lower()}"
    )
    console.print("[bold]Capability public_release mutated:[/] false")
    console.print("[bold]Paper benchmark result claimed:[/] false")
    if args.require_ready and not result.software_release_candidate_ready:
        raise SystemExit("Release candidate is not ready")


def cmd_release_candidate_verify(args: argparse.Namespace) -> None:
    try:
        result = verify_release_candidate(args.candidate)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Release-candidate verification failed: {exc}") from exc
    if args.json:
        print(result.to_json())
    else:
        console.print(f"[bold]Candidate:[/] {result.candidate_id}")
        console.print(f"[bold]Status:[/] {result.status}")
        console.print(
            "[bold]Software candidate ready:[/] "
            f"{str(result.software_release_candidate_ready).lower()}"
        )
        console.print(
            "[bold]Held-out benchmark cases:[/] "
            f"{result.benchmark_state.held_out_case_count}"
        )
        console.print(
            "[bold]External review:[/] "
            f"{result.external_review_state.passed_route_count} passed, "
            f"{result.external_review_state.pending_route_count} pending"
        )
        console.print(
            "[bold]Material applicability:[/] "
            f"{result.material_applicability_state.material_complete_routes} complete, "
            f"{result.material_applicability_state.material_incomplete_routes} incomplete"
        )
        console.print("[bold]Public-release badge registration ready:[/] false")
        if result.issues:
            console.print("[bold red]Issues:[/] " + "; ".join(result.issues))
    if args.require_ready and not result.software_release_candidate_ready:
        raise SystemExit("Release candidate is not ready")


def cmd_distribution_bundle_create(args: argparse.Namespace) -> None:
    try:
        result = create_distribution_bundle(
            args.release_candidate,
            args.out,
            bundle_id=args.bundle_id,
            created_at=args.created_at,
            command_timeout=args.command_timeout,
            wolfram_timeout=args.wolfram_timeout,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        raise SystemExit(f"Distribution-bundle creation failed: {exc}") from exc
    console.print(f"[bold green]Distribution bundle:[/] {result.bundle_dir}")
    console.print(f"[bold]Manifest:[/] {result.manifest_path}")
    console.print(f"[bold]Manifest SHA-256:[/] {result.manifest_sha256}")
    console.print(f"[bold]Distribution ready:[/] {str(result.distribution_ready).lower()}")
    console.print("[bold]Public-release badge registration ready:[/] false")
    console.print("[bold]Paper benchmark result claimed:[/] false")
    if args.require_ready and not result.distribution_ready:
        raise SystemExit("Distribution bundle is not ready")


def cmd_distribution_bundle_verify(args: argparse.Namespace) -> None:
    try:
        result = verify_distribution_bundle(args.bundle)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise SystemExit(f"Distribution-bundle verification failed: {exc}") from exc
    if args.json:
        print(result.to_json())
    else:
        console.print(f"[bold]Bundle:[/] {result.bundle_id}")
        console.print(f"[bold]Status:[/] {result.status}")
        console.print(
            f"[bold]Distribution ready:[/] {str(result.distribution_ready).lower()}"
        )
        console.print(
            "[bold]Source reconstruction:[/] "
            f"{str(result.source_reconstruction_passed).lower()}"
        )
        console.print(
            f"[bold]Clean install:[/] {str(result.clean_install_passed).lower()}"
        )
        console.print(
            f"[bold]Wolfram load:[/] {str(result.wolfram_load_passed).lower()}"
        )
        console.print("[bold]Public-release badge registration ready:[/] false")
        if result.issues:
            console.print("[bold red]Issues:[/] " + "; ".join(result.issues))
    if args.require_ready and not result.distribution_ready:
        raise SystemExit("Distribution bundle is not ready")


def cmd_readability_packet(args: argparse.Namespace) -> None:
    try:
        packet = generate_readability_packet(args.out)
    except FileExistsError as exc:
        raise SystemExit(f"Readability packet failed: {exc}") from exc
    console.print(f"[bold green]Readability study packet:[/] {packet.study_dir}")
    console.print(f"[bold]Manifest:[/] {packet.manifest_path}")
    console.print(f"[bold]Frozen rubric:[/] {packet.rubric_path}")
    console.print(f"[bold]Rater guide:[/] {packet.guide_path}")


def cmd_readability_score(args: argparse.Namespace) -> None:
    try:
        result = run_readability_study(args.study, args.out)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Readability scoring failed: {exc}") from exc
    if args.json:
        print(result.to_json())
    else:
        table = Table(title="Readability v1 scores")
        table.add_column("Case")
        table.add_column("Blind ID")
        table.add_column("Status")
        table.add_column("Eligible raters")
        table.add_column("Adjudication")
        for case in result.cases:
            table.add_row(
                case.case_id,
                case.blind_response_id,
                case.status,
                str(case.eligible_rater_count),
                case.adjudication_status,
            )
        console.print(table)
        console.print(f"[bold]Study status:[/] {result.status}")
        console.print(f"[bold]JSON:[/] {result.report_json}")
        console.print(f"[bold]Markdown:[/] {result.report_markdown}")
    if args.require_complete and result.status not in {"passed", "failed"}:
        raise SystemExit(
            f"Readability study is not complete: status={result.status}"
        )


def cmd_benchmark_intake_stage(args: argparse.Namespace) -> None:
    try:
        result = stage_authoring_packet(args.packet, args.out)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Benchmark intake staging failed: {exc}") from exc
    console.print(f"[bold green]Intake stage:[/] {result.stage_dir}")
    console.print(f"[bold]Manifest:[/] {result.stage_manifest}")
    console.print(f"[bold]Review forms:[/] {len(result.review_forms)}")
    console.print(f"[bold]Guide:[/] {result.guide_path}")


def cmd_benchmark_intake_verify(args: argparse.Namespace) -> None:
    try:
        result = verify_intake_stage(args.stage)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Benchmark intake verification failed: {exc}") from exc
    if args.json:
        print(result.to_json())
    else:
        table = Table(title="Benchmark intake verification")
        table.add_column("Case")
        table.add_column("Partition")
        table.add_column("Decision")
        table.add_column("Integrity")
        table.add_column("Reasons")
        for case in result.cases:
            table.add_row(
                case.case_id,
                case.primary_partition,
                case.decision,
                "passed" if case.integrity_valid else "failed",
                "; ".join(case.reasons) or "none",
            )
        console.print(table)
        console.print(f"[bold]Stage status:[/] {result.status}")
        console.print(
            f"[bold]Freeze preview ready:[/] {str(result.freeze_preview_ready).lower()}"
        )
    if args.require_freeze_ready and not result.freeze_preview_ready:
        raise SystemExit("Benchmark intake stage is not ready for a freeze preview")


def cmd_benchmark_intake_freeze_preview(args: argparse.Namespace) -> None:
    try:
        result = generate_freeze_preview(args.stage, args.out)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Benchmark freeze preview failed: {exc}") from exc
    console.print(f"[bold]Freeze preview status:[/] {result.status}")
    console.print(f"[bold]Accepted cases:[/] {len(result.accepted_case_ids)}")
    console.print(f"[bold]Rejected cases:[/] {len(result.rejected_case_ids)}")
    console.print(f"[bold]JSON:[/] {result.report_json}")
    console.print(f"[bold]Markdown:[/] {result.report_markdown}")
    console.print("[bold]Real manifests modified:[/] false")
    if not result.blind_split_freeze_ready:
        raise SystemExit("Benchmark freeze preview is blocked by intake gates")


def cmd_benchmark_materialization_freeze(args: argparse.Namespace) -> None:
    approval = ReleaseManagerApproval(
        manager_id=args.manager_id,
        name=args.manager_name,
        affiliation=args.manager_affiliation,
        signed_at=args.signed_at,
    )
    try:
        result = create_system_freeze_package(
            args.stage,
            args.preview,
            args.system_artifact,
            args.out,
            approval,
            scorer_registry_path=args.scorer_registry,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Benchmark system freeze failed: {exc}") from exc
    console.print(f"[bold green]System-freeze package:[/] {result.freeze_dir}")
    console.print(f"[bold]Record:[/] {result.freeze_record}")
    console.print(f"[bold]Verification:[/] {result.verification_report}")
    console.print("[bold]Private gold opened:[/] false")


def cmd_benchmark_materialization_verify_freeze(args: argparse.Namespace) -> None:
    try:
        result = verify_system_freeze_package(args.freeze)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Benchmark system-freeze verification failed: {exc}") from exc
    if args.json:
        print(result.to_json())
    else:
        console.print(f"[bold]Freeze ID:[/] {result.freeze_id}")
        console.print(
            "[bold]Ready for custodian handoff:[/] "
            f"{str(result.ready_for_custodian_handoff).lower()}"
        )
        console.print(f"[bold]Accepted cases:[/] {len(result.accepted_case_ids)}")
        if result.issues:
            console.print("[bold red]Issues:[/] " + "; ".join(result.issues))
    if args.require_ready and not result.ready_for_custodian_handoff:
        raise SystemExit("System-freeze package is not ready for custodian handoff")


def cmd_benchmark_materialization_handoff_template(args: argparse.Namespace) -> None:
    try:
        result = generate_custodian_handoff_template(args.freeze, args.out)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Custodian handoff-template generation failed: {exc}") from exc
    console.print(f"[bold green]Custodian handoff template:[/] {result.handoff_dir}")
    console.print(f"[bold]Manifest:[/] {result.handoff_manifest}")
    console.print(f"[bold]Guide:[/] {result.guide_path}")
    console.print("[bold]Plaintext gold included:[/] false")


def cmd_benchmark_materialization_verify_handoff(args: argparse.Namespace) -> None:
    try:
        result = verify_custodian_handoff(args.freeze, args.handoff)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Custodian handoff verification failed: {exc}") from exc
    if args.json:
        print(result.to_json())
    else:
        table = Table(title="Custodian materialization handoff")
        table.add_column("Case")
        table.add_column("Status")
        table.add_column("Issues")
        for case in result.cases:
            table.add_row(
                case.case_id,
                "passed" if case.passed else "failed",
                "; ".join(case.issues) or "none",
            )
        console.print(table)
        console.print(
            "[bold]Ready for registration candidate:[/] "
            f"{str(result.ready_for_registration_candidate).lower()}"
        )
    if args.require_ready and not result.ready_for_registration_candidate:
        raise SystemExit("Custodian handoff is not ready for registration-candidate generation")


def cmd_benchmark_materialization_registration_candidate(
    args: argparse.Namespace,
) -> None:
    try:
        result = generate_registration_candidate(args.freeze, args.handoff, args.out)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Registration-candidate generation failed: {exc}") from exc
    console.print(f"[bold green]Registration candidate:[/] {result.candidate_dir}")
    console.print(f"[bold]Index:[/] {result.candidate_index}")
    console.print(f"[bold]Cases:[/] {len(result.case_ids)}")
    console.print(f"[bold]Checksums:[/] {result.checksums}")
    console.print("[bold]Real manifests modified:[/] false")


def cmd_nl_benchmark(args: argparse.Namespace) -> None:
    run = evaluate_nl_benchmark_cases(
        args.cases,
        args.out,
        args.bundle_out,
        args.archive,
        execute_wolfram=args.execute_wolfram,
        wolfram_timeout=args.wolfram_timeout,
    )
    table = Table(title="Natural-language benchmark scores")
    table.add_column("Case")
    table.add_column("Support")
    table.add_column("Score")
    table.add_column("Status")
    for case in run.cases:
        table.add_row(case.case_id, case.support_level, f"{case.score}/{case.max_score}", case.status)
    console.print(table)
    console.print(
        f"[bold]Summary:[/] {run.passed_cases}/{len(run.cases)} cases satisfied their declared support level, "
        f"{run.total_score}/{run.max_score} checks passed"
    )
    console.print(f"[bold]CSV:[/] {run.csv_path}")
    console.print(f"[bold]JSON:[/] {run.json_path}")
    console.print(f"[bold]Notes:[/] {run.notes_path}")
    if run.archive_dir:
        console.print(f"[bold]Archive:[/] {run.archive_dir}")


def cmd_capabilities(args: argparse.Namespace) -> None:
    registry = CapabilityRegistry(args.registry)
    drive_filter_set = args.drive is not None
    drive = None if args.drive in {"none", "null"} else args.drive
    routes = registry.filter_routes(
        material=args.material,
        texture=args.texture,
        drive=drive,
        drive_filter_set=drive_filter_set,
        geometry=args.geometry,
        support_level=args.support_level,
        knowledge_status=args.knowledge_status,
    )

    if args.claim_matrix:
        claim_matrix_path = Path(args.claim_matrix)
        claim_matrix_path.parent.mkdir(parents=True, exist_ok=True)
        claim_matrix_path.write_text(
            render_claim_evidence_matrix(registry), encoding="utf-8"
        )
        if not args.json:
            console.print(f"[bold green]Claim-evidence matrix:[/] {claim_matrix_path}")

    if args.json:
        payload = json.dumps(
            {
                "schema_version": registry.data.schema_version,
                "evidence_status_schema_version": (
                    registry.data.evidence_status_schema_version
                ),
                "knowledge_lifecycle": registry.data.knowledge_lifecycle,
                "knowledge_lifecycle_role": "derived_compatibility_summary",
                "routes": [route.model_dump() for route in routes],
            },
            ensure_ascii=False,
            indent=2,
        )
        console.file.write(f"{payload}\n")
        return

    table = Table(title=f"Capability registry v{registry.data.schema_version}")
    table.add_column("Route")
    table.add_column("Material")
    table.add_column("Texture")
    table.add_column("Drive")
    table.add_column("Geometry")
    table.add_column("Support")
    table.add_column("Knowledge (derived)")
    table.add_column("Review")
    for route in routes:
        table.add_row(
            route.route_id,
            route.material,
            route.texture,
            str(route.drive),
            str(route.geometry),
            route.support_level,
            route.knowledge_status,
            str(route.requires_human_review),
        )
    console.print(table)
    if not routes:
        console.print(
            "[bold yellow]No registered route matches this query.[/] "
            "Treat the task as an unsupported candidate until its missing evidence is reviewed."
        )
    else:
        console.print(f"[bold]Matched routes:[/] {len(routes)}")


def cmd_evidence(args: argparse.Namespace) -> None:
    runs = run_evidence_cards(
        args.cards,
        args.out,
        wolfram_timeout=args.wolfram_timeout,
    )
    table = Table(title="Independent analytic evidence")
    table.add_column("Card")
    table.add_column("Route")
    table.add_column("Generated CAS")
    table.add_column("Gold CAS")
    table.add_column("Checks")
    table.add_column("Expert")
    table.add_column("Status")
    for run in runs:
        passed_checks = sum(check.passed for check in run.checks)
        table.add_row(
            run.card_id,
            run.route_id,
            run.generated_execution_status,
            run.gold_execution_status,
            f"{passed_checks}/{len(run.checks)}",
            run.expert_review_status,
            "passed" if run.passed else "failed",
        )
    console.print(table)
    console.print(f"[bold]Evidence output:[/] {Path(args.out)}")
    if not runs or not all(run.passed for run in runs):
        raise SystemExit(1)


def cmd_expert_review_packet(args: argparse.Namespace) -> None:
    packet = generate_review_packet(args.cards, args.evidence_runs, args.out)
    console.print(f"[bold green]Expert review packet:[/] {packet.packet_path}")
    console.print(f"[bold]Manifest:[/] {packet.manifest_path}")
    console.print(f"[bold]Pending review forms:[/] {len(packet.review_forms)}")


def cmd_expert_review_verify(args: argparse.Namespace) -> None:
    result = verify_review_packet(args.packet)
    table = Table(title="Expert review verification")
    table.add_column("Review")
    table.add_column("Route")
    table.add_column("Decision")
    table.add_column("Integrity")
    table.add_column("Eligible")
    for review in result.reviews:
        table.add_row(
            review.review_id,
            review.route_id,
            review.status,
            "passed" if review.integrity_valid else "failed",
            "yes" if review.eligible_for_expert_validation else "no",
        )
    console.print(table)
    console.print(f"[bold]Eligible routes:[/] {len(result.eligible_routes)}")
    console.print(f"[bold]Verification report:[/] {result.report_markdown}")
    if not result.manifest_integrity_valid or not result.all_records_integrity_valid:
        raise SystemExit(1)
    if args.require_all_approved and len(result.eligible_routes) != len(result.reviews):
        raise SystemExit(1)


def cmd_machine_audit(args: argparse.Namespace) -> None:
    result = run_machine_audit_suite(args.specs, args.evidence_runs, args.out)
    table = Table(title="Machine physics audit")
    table.add_column("Case")
    table.add_column("Route")
    table.add_column("Formal")
    table.add_column("Material")
    table.add_column("Overall")
    for audit in result.results:
        table.add_row(
            audit.case_id,
            audit.route_id,
            audit.formal_route_status,
            audit.material_applicability_status,
            audit.overall_status,
        )
    console.print(table)
    console.print(f"[bold]Suite status:[/] {result.suite_status}")
    console.print(f"[bold]Audit summary:[/] {result.summary_markdown}")
    if any(audit.formal_route_status != "pass" for audit in result.results):
        raise SystemExit(1)
    if args.require_material_complete and any(
        audit.material_applicability_status != "pass" for audit in result.results
    ):
        raise SystemExit(1)


def cmd_assertion_coverage(args: argparse.Namespace) -> None:
    run = run_assertion_coverage(
        registry_path=args.registry,
        evidence_roots=args.evidence_runs,
        out_dir=args.out,
    )
    table = Table(title="Full-route assertion coverage")
    table.add_column("Route")
    table.add_column("Keys")
    table.add_column("Resolution")
    table.add_column("Dimension")
    table.add_column("Sign")
    table.add_column("Boundary")
    table.add_column("Limit")
    table.add_column("Overall")
    for route in run.routes:
        axes = {axis.axis: axis.status for axis in route.axes}
        table.add_row(
            route.route_id,
            f"{route.classified_key_count}/{route.expected_key_count}",
            route.resolution_status,
            axes["dimension"],
            axes["sign"],
            axes["boundary"],
            axes["limit"],
            route.overall_status,
        )
    console.print(table)
    console.print(f"[bold]Suite status:[/] {run.suite_status}")
    console.print(f"[bold]Coverage report:[/] {run.report_markdown}")
    if run.suite_status == "fail":
        raise SystemExit(1)
    if args.require_complete and run.suite_status != "pass":
        raise SystemExit(1)


def cmd_cross_engine_run(args: argparse.Namespace) -> None:
    try:
        if args.suite == "extended":
            result = run_extended_cross_engine_suite(args.specs, args.out)
        else:
            result = run_cross_engine_suite(args.specs, args.out)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Cross-engine validation failed: {exc}") from exc
    table = Table(title=f"{args.suite.title()} cross-engine validation")
    table.add_column("Route")
    table.add_column("Status")
    table.add_column("Passed")
    table.add_column("Failed")
    table.add_column("N/A")
    for route in result.routes:
        table.add_row(
            route.route_id,
            route.execution_status,
            str(route.passed_check_count),
            str(route.failed_check_count),
            str(route.not_applicable_check_count),
        )
    console.print(table)
    console.print(
        f"[bold]Routes:[/] {result.passed_route_count}/{result.route_count} passed"
    )
    console.print(
        f"[bold]Checks:[/] {result.passed_check_count} passed, "
        f"{result.failed_check_count} failed, "
        f"{result.not_applicable_check_count} not applicable"
    )
    console.print(f"[bold]Suite record:[/] {result.result_path}")
    if args.require_pass and not result.passed:
        raise SystemExit(1)


def cmd_cross_engine_verify(args: argparse.Namespace) -> None:
    try:
        if args.suite == "extended":
            result = verify_extended_cross_engine_result(
                args.result,
                expected_route_id=args.route,
            )
        else:
            result = verify_cross_engine_result(
                args.result,
                expected_route_id=args.route,
            )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Cross-engine verification failed: {exc}") from exc
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        console.print(f"[bold]Route:[/] {result.route_id}")
        console.print(
            "[bold]Eligible for cross-engine pass:[/] "
            f"{str(result.eligible_for_cross_engine_pass).lower()}"
        )
        console.print(f"[bold]Passed checks:[/] {result.passed_check_count}")
        console.print(f"[bold]N/A checks:[/] {result.not_applicable_check_count}")
        for issue in result.issues:
            console.print(f"[red]ISSUE[/] {issue}")
    if args.require_eligible and not result.eligible_for_cross_engine_pass:
        raise SystemExit(1)


def cmd_ablate(args: argparse.Namespace) -> None:
    run = run_ablation_profiles(
        profiles_dir=args.profiles,
        out_dir=args.out,
        benchmark_cases_dir=args.cases,
        bundle_out=args.bundle_out,
        wolfram_timeout=args.wolfram_timeout,
    )
    table = Table(title="Ablation profile scores")
    table.add_column("Profile")
    table.add_column("Case Pass Rate")
    table.add_column("Rule Score Rate")
    for profile in run.profiles:
        table.add_row(
            profile.profile.profile_id,
            f"{profile.case_pass_rate:.1%}",
            f"{profile.score_rate:.1%}",
        )
    console.print(table)
    console.print(f"[bold]CSV:[/] {run.csv_path}")
    console.print(f"[bold]JSON:[/] {run.json_path}")
    console.print(f"[bold]Notes:[/] {run.notes_path}")


def cmd_baseline(args: argparse.Namespace) -> None:
    run = run_baseline_profiles(
        profiles_dir=args.profiles,
        out_dir=args.out,
        benchmark_cases_dir=args.cases,
        bundle_out=args.bundle_out,
    )
    table = Table(title="Proxy baseline scores")
    table.add_column("Baseline")
    table.add_column("Type")
    table.add_column("Case Pass Rate")
    table.add_column("Rule Score Rate")
    for profile in run.profiles:
        table.add_row(
            profile.profile.profile_id,
            profile.profile.baseline_type,
            f"{profile.case_pass_rate:.1%}",
            f"{profile.score_rate:.1%}",
        )
    console.print(table)
    console.print("[bold yellow]Note:[/] proxy baselines are simulated, not real LLM runs.")
    console.print(f"[bold]CSV:[/] {run.csv_path}")
    console.print(f"[bold]JSON:[/] {run.json_path}")
    console.print(f"[bold]Notes:[/] {run.notes_path}")


def cmd_baseline_eval(args: argparse.Namespace) -> None:
    run = evaluate_recorded_baselines(
        outputs_dir=args.outputs,
        out_dir=args.out,
        cases_dir=args.cases,
        bundle_out=args.bundle_out,
        include_agent_reference=not args.no_agent_reference,
    )
    table_title = (
        "Independent baselines vs full agent"
        if run.has_independent_outputs and run.has_agent_reference
        else "Independent baseline scores"
        if run.has_independent_outputs
        else "Recorded baseline scores"
    )
    table = Table(title=table_title)
    table.add_column("Baseline")
    table.add_column("Type")
    table.add_column("Case Pass Rate")
    table.add_column("Rule Score Rate")
    for method in run.methods:
        table.add_row(
            method.method.method_id,
            method.method.source_type,
            f"{method.case_pass_rate:.1%}",
            f"{method.score_rate:.1%}",
        )
    console.print(table)
    if run.has_independent_outputs and run.has_agent_reference:
        console.print(
            "[bold yellow]Note:[/] scores combine independent external transcripts "
            "with a full local agent reference."
        )
    elif run.has_independent_outputs:
        console.print(
            "[bold yellow]Note:[/] scores are computed from independent external transcripts "
            "stored as recorded output files."
        )
    else:
        console.print("[bold yellow]Note:[/] scores are computed from recorded baseline output files.")
    console.print(f"[bold]CSV:[/] {run.csv_path}")
    console.print(f"[bold]JSON:[/] {run.json_path}")
    console.print(f"[bold]Notes:[/] {run.notes_path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SpinTextureTheoryAgent CLI")
    sub = parser.add_subparsers(required=True)

    validate = sub.add_parser("validate", help="Validate a theory-task config")
    validate.add_argument("config")
    validate.set_defaults(func=cmd_validate)

    plan = sub.add_parser("plan", help="Print selected derivation plan")
    plan.add_argument("config")
    plan.set_defaults(func=cmd_plan)

    run = sub.add_parser("run", help="Generate derivation files")
    run.add_argument("config")
    run.add_argument("--out", default="outputs")
    run.add_argument("--execute-wolfram", action="store_true")
    run.add_argument("--wolfram-timeout", type=int, default=120)
    run.set_defaults(func=cmd_run)

    parse = sub.add_parser("parse", help="Parse a controlled natural-language prompt to YAML")
    parse.add_argument("prompt", nargs="?", help="Natural-language physics task")
    parse.add_argument("--prompt-file", default=None)
    parse.add_argument("--task-name", default=None)
    parse.add_argument("--out-config", default=None)
    parse.add_argument("--show-plan", action="store_true")
    parse.set_defaults(func=cmd_parse)

    run_prompt = sub.add_parser("run-prompt", help="Parse a prompt and generate derivation files")
    run_prompt.add_argument("prompt", nargs="?", help="Natural-language physics task")
    run_prompt.add_argument("--prompt-file", default=None)
    run_prompt.add_argument("--task-name", default=None)
    run_prompt.add_argument("--save-config", default=None)
    run_prompt.add_argument("--out", default="outputs")
    run_prompt.add_argument("--execute-wolfram", action="store_true")
    run_prompt.add_argument("--wolfram-timeout", type=int, default=120)
    run_prompt.set_defaults(func=cmd_run_prompt)

    benchmark = sub.add_parser("benchmark", help="Run rule-based benchmark cases")
    benchmark.add_argument("--cases", default="benchmark_cases")
    benchmark.add_argument("--out", default="results")
    benchmark.add_argument("--bundle-out", default="outputs/benchmark_runs")
    benchmark.add_argument("--archive", default=None)
    benchmark.add_argument("--execute-wolfram", action="store_true")
    benchmark.add_argument("--wolfram-timeout", type=int, default=120)
    benchmark.set_defaults(func=cmd_benchmark)

    benchmark_manifest = sub.add_parser(
        "benchmark-manifest",
        help="Validate and summarize the benchmark partition contract",
    )
    benchmark_manifest.add_argument(
        "--manifest", default="benchmark_manifests/v1/manifest.yaml"
    )
    benchmark_manifest.add_argument("--json", action="store_true")
    benchmark_manifest.add_argument("--require-release-ready", action="store_true")
    benchmark_manifest.set_defaults(func=cmd_benchmark_manifest)

    benchmark_authoring = sub.add_parser(
        "benchmark-authoring",
        help="Generate or verify external benchmark case-authoring packets",
    )
    benchmark_authoring_sub = benchmark_authoring.add_subparsers(required=True)
    authoring_packet = benchmark_authoring_sub.add_parser(
        "packet",
        help="Generate a non-overwriting empty external-authoring packet",
    )
    authoring_packet.add_argument(
        "--out", default="benchmark_authoring_packets/v1_template"
    )
    authoring_packet.add_argument(
        "--benchmark-manifest", default="benchmark_manifests/v1/manifest.yaml"
    )
    authoring_packet.set_defaults(func=cmd_benchmark_authoring_packet)

    authoring_verify = benchmark_authoring_sub.add_parser(
        "verify",
        help="Verify case provenance, leakage, custody, and sealed-artifact hashes",
    )
    authoring_verify.add_argument("--packet", required=True)
    authoring_verify.add_argument("--benchmark-manifest", default=None)
    authoring_verify.add_argument("--json", action="store_true")
    authoring_verify.add_argument("--require-ready", action="store_true")
    authoring_verify.set_defaults(func=cmd_benchmark_authoring_verify)

    benchmark_collection = sub.add_parser(
        "benchmark-collection",
        help="Launch or verify an immutable external benchmark collection release",
    )
    benchmark_collection_sub = benchmark_collection.add_subparsers(required=True)
    collection_launch = benchmark_collection_sub.add_parser(
        "launch",
        help="Generate the non-overwriting round-01 collection packet and deterministic archive",
    )
    collection_launch.add_argument(
        "--out", default="benchmark_collection_releases/v1/round_01"
    )
    collection_launch.add_argument(
        "--benchmark-manifest", default="benchmark_manifests/v1/manifest.yaml"
    )
    collection_launch.add_argument(
        "--capability-registry", default="knowledge_base/capabilities.yaml"
    )
    collection_launch.add_argument(
        "--scorer-registry", default="knowledge_base/benchmark_scorers.yaml"
    )
    collection_launch.add_argument(
        "--frozen-at", default="2026-07-27T12:00:00+08:00"
    )
    collection_launch.set_defaults(func=cmd_benchmark_collection_launch)

    collection_verify = benchmark_collection_sub.add_parser(
        "verify",
        help="Verify release hashes, launch policy, and byte-for-byte ZIP reconstruction",
    )
    collection_verify.add_argument("--release", required=True)
    collection_verify.add_argument("--json", action="store_true")
    collection_verify.add_argument("--require-ready", action="store_true")
    collection_verify.set_defaults(func=cmd_benchmark_collection_verify)

    operator_ledger = sub.add_parser(
        "benchmark-operator-ledger",
        help="Verify publication and maintain a private append-only invitation ledger",
    )
    operator_sub = operator_ledger.add_subparsers(required=True)
    operator_gate = operator_sub.add_parser(
        "gate",
        help="Verify durable Round-01 publication before creating a private ledger",
    )
    operator_gate.add_argument(
        "--publication-evidence", default=str(DEFAULT_PUBLICATION_EVIDENCE)
    )
    operator_gate.add_argument(
        "--publication-record", default=str(DEFAULT_PUBLICATION_RECORD)
    )
    operator_gate.add_argument(
        "--collection-release", default="benchmark_collection_releases/v1/round_01"
    )
    operator_gate.add_argument("--json", action="store_true")
    operator_gate.add_argument("--require-pass", action="store_true")
    operator_gate.set_defaults(func=cmd_benchmark_operator_gate)

    operator_initialize = operator_sub.add_parser(
        "initialize",
        help="Preview or initialize a non-overwriting private working ledger",
    )
    operator_initialize.add_argument("--out", required=True)
    operator_initialize.add_argument("--ledger-id", required=True)
    operator_initialize.add_argument("--operator-id", required=True)
    operator_initialize.add_argument("--created-at", required=True)
    operator_initialize.add_argument(
        "--publication-evidence", default=str(DEFAULT_PUBLICATION_EVIDENCE)
    )
    operator_initialize.add_argument(
        "--publication-record", default=str(DEFAULT_PUBLICATION_RECORD)
    )
    operator_initialize.add_argument(
        "--collection-release", default="benchmark_collection_releases/v1/round_01"
    )
    operator_initialize.add_argument("--commit", action="store_true")
    operator_initialize.add_argument("--preview-sha256", default=None)
    operator_initialize.add_argument("--json", action="store_true")
    operator_initialize.set_defaults(func=cmd_benchmark_operator_initialize)

    operator_record = operator_sub.add_parser(
        "record",
        help="Preview or append an explicitly confirmed real invitation event",
    )
    operator_record.add_argument("--ledger", required=True)
    operator_record.add_argument("--request", required=True)
    operator_record.add_argument("--commit", action="store_true")
    operator_record.add_argument("--preview-sha256", default=None)
    operator_record.add_argument("--confirm-real-event", action="store_true")
    operator_record.add_argument("--json", action="store_true")
    operator_record.set_defaults(func=cmd_benchmark_operator_record)

    operator_verify = operator_sub.add_parser(
        "verify",
        help="Verify permissions, hashes, replay, and publication binding",
    )
    operator_verify.add_argument("--ledger", required=True)
    operator_verify.add_argument("--json", action="store_true")
    operator_verify.add_argument("--require-valid", action="store_true")
    operator_verify.set_defaults(func=cmd_benchmark_operator_verify)

    outreach_handoff = sub.add_parser(
        "benchmark-outreach-handoff",
        help="Create or verify the public-data-only Round-01 no-send outreach handoff",
    )
    outreach_sub = outreach_handoff.add_subparsers(required=True)
    outreach_create = outreach_sub.add_parser(
        "create",
        help="Create a non-overwriting operator handoff with no-send role drafts",
    )
    outreach_create.add_argument("--out", default=str(DEFAULT_OUTREACH_HANDOFF))
    outreach_create.add_argument(
        "--handoff-id", default=DEFAULT_OUTREACH_HANDOFF_ID
    )
    outreach_create.add_argument("--created-at", default=None)
    outreach_create.add_argument(
        "--publication-evidence", default=str(DEFAULT_PUBLICATION_EVIDENCE)
    )
    outreach_create.add_argument(
        "--publication-record", default=str(DEFAULT_PUBLICATION_RECORD)
    )
    outreach_create.add_argument(
        "--collection-release", default="benchmark_collection_releases/v1/round_01"
    )
    outreach_create.add_argument(
        "--ledger-protocol", default="docs/BENCHMARK_PRIVATE_OPERATOR_LEDGER.md"
    )
    outreach_create.add_argument("--json", action="store_true")
    outreach_create.set_defaults(func=cmd_benchmark_outreach_create)

    outreach_verify = outreach_sub.add_parser(
        "verify",
        help="Verify hashes, immutable publication bindings, privacy, and claim boundaries",
    )
    outreach_verify.add_argument("--handoff", required=True)
    outreach_verify.add_argument(
        "--collection-release", default="benchmark_collection_releases/v1/round_01"
    )
    outreach_verify.add_argument(
        "--ledger-protocol", default="docs/BENCHMARK_PRIVATE_OPERATOR_LEDGER.md"
    )
    outreach_verify.add_argument("--json", action="store_true")
    outreach_verify.add_argument("--require-ready", action="store_true")
    outreach_verify.set_defaults(func=cmd_benchmark_outreach_verify)

    release_candidate = sub.add_parser(
        "release-candidate",
        help="Create or verify a hash-bound Project 1 software release candidate",
    )
    release_candidate_sub = release_candidate.add_subparsers(required=True)
    release_create = release_candidate_sub.add_parser(
        "create",
        help="Run verification commands and create a non-overwriting candidate",
    )
    release_create.add_argument(
        "--out", default="analysis/release_candidates/project1_v0.1.0_rc01"
    )
    release_create.add_argument("--candidate-id", default=DEFAULT_CANDIDATE_ID)
    release_create.add_argument("--created-at", default=None)
    release_create.add_argument(
        "--capability-registry", default="knowledge_base/capabilities.yaml"
    )
    release_create.add_argument("--pytest-timeout", type=int, default=1800)
    release_create.add_argument("--command-timeout", type=int, default=300)
    release_create.add_argument("--wolfram-timeout", type=int, default=120)
    release_create.add_argument("--require-ready", action="store_true")
    release_create.set_defaults(func=cmd_release_candidate_create)

    release_verify = release_candidate_sub.add_parser(
        "verify",
        help="Verify candidate hashes, evidence, environment, and claim boundaries",
    )
    release_verify.add_argument("--candidate", required=True)
    release_verify.add_argument("--json", action="store_true")
    release_verify.add_argument("--require-ready", action="store_true")
    release_verify.set_defaults(func=cmd_release_candidate_verify)

    distribution_bundle = sub.add_parser(
        "distribution-bundle",
        help="Create or verify a frozen Project 1 distribution and clean install",
    )
    distribution_sub = distribution_bundle.add_subparsers(required=True)
    distribution_create = distribution_sub.add_parser(
        "create",
        help="Build wheel, sdist, offline wheelhouse, and clean-install evidence",
    )
    distribution_create.add_argument(
        "--release-candidate",
        default="analysis/release_candidates/project1_v0.1.0_rc04",
    )
    distribution_create.add_argument(
        "--out",
        default=f"analysis/distribution_bundles/{DEFAULT_BUNDLE_ID}",
    )
    distribution_create.add_argument("--bundle-id", default=DEFAULT_BUNDLE_ID)
    distribution_create.add_argument("--created-at", default=None)
    distribution_create.add_argument("--command-timeout", type=int, default=600)
    distribution_create.add_argument("--wolfram-timeout", type=int, default=120)
    distribution_create.add_argument("--require-ready", action="store_true")
    distribution_create.set_defaults(func=cmd_distribution_bundle_create)

    distribution_verify = distribution_sub.add_parser(
        "verify",
        help="Verify candidate binding, checksums, packages, and clean-install logs",
    )
    distribution_verify.add_argument("--bundle", required=True)
    distribution_verify.add_argument("--json", action="store_true")
    distribution_verify.add_argument("--require-ready", action="store_true")
    distribution_verify.set_defaults(func=cmd_distribution_bundle_verify)

    readability = sub.add_parser(
        "readability",
        help="Generate or score blinded accessible-view readability studies",
    )
    readability_sub = readability.add_subparsers(required=True)
    readability_packet = readability_sub.add_parser(
        "packet",
        help="Generate a non-overwriting empty readability study packet",
    )
    readability_packet.add_argument(
        "--out", default="readability_studies/v1_template"
    )
    readability_packet.set_defaults(func=cmd_readability_packet)

    readability_score = readability_sub.add_parser(
        "score",
        help="Aggregate blinded ratings, uncertainty, and adjudication",
    )
    readability_score.add_argument("--study", required=True)
    readability_score.add_argument(
        "--out", default="analysis/readability_runs/latest"
    )
    readability_score.add_argument("--json", action="store_true")
    readability_score.add_argument("--require-complete", action="store_true")
    readability_score.set_defaults(func=cmd_readability_score)

    benchmark_intake = sub.add_parser(
        "benchmark-intake",
        help="Stage, review, and preview-freeze verified external benchmark cases",
    )
    benchmark_intake_sub = benchmark_intake.add_subparsers(required=True)
    intake_stage = benchmark_intake_sub.add_parser(
        "stage",
        help="Create a non-overwriting hashed snapshot of a verified authoring packet",
    )
    intake_stage.add_argument("--packet", required=True)
    intake_stage.add_argument("--out", required=True)
    intake_stage.set_defaults(func=cmd_benchmark_intake_stage)

    intake_verify = benchmark_intake_sub.add_parser(
        "verify",
        help="Verify staged hashes and pending/accepted/rejected intake decisions",
    )
    intake_verify.add_argument("--stage", required=True)
    intake_verify.add_argument("--json", action="store_true")
    intake_verify.add_argument("--require-freeze-ready", action="store_true")
    intake_verify.set_defaults(func=cmd_benchmark_intake_verify)

    intake_freeze = benchmark_intake_sub.add_parser(
        "freeze-preview",
        help="Generate preview-only partition entries without modifying real manifests",
    )
    intake_freeze.add_argument("--stage", required=True)
    intake_freeze.add_argument("--out", required=True)
    intake_freeze.set_defaults(func=cmd_benchmark_intake_freeze_preview)

    materialization = sub.add_parser(
        "benchmark-materialization",
        help="Freeze evaluation contracts and validate custodian materialization handoffs",
    )
    materialization_sub = materialization.add_subparsers(required=True)
    system_freeze = materialization_sub.add_parser(
        "freeze",
        help="Create a pre-unseal system/scorer/split freeze package",
    )
    system_freeze.add_argument("--stage", required=True)
    system_freeze.add_argument("--preview", required=True)
    system_freeze.add_argument("--system-artifact", required=True)
    system_freeze.add_argument("--out", required=True)
    system_freeze.add_argument("--manager-id", required=True)
    system_freeze.add_argument("--manager-name", required=True)
    system_freeze.add_argument("--manager-affiliation", required=True)
    system_freeze.add_argument("--signed-at", required=True)
    system_freeze.add_argument(
        "--scorer-registry",
        default="knowledge_base/benchmark_scorers.yaml",
    )
    system_freeze.set_defaults(func=cmd_benchmark_materialization_freeze)

    verify_freeze = materialization_sub.add_parser(
        "verify-freeze",
        help="Verify frozen system, scorer, split, and policy hashes",
    )
    verify_freeze.add_argument("--freeze", required=True)
    verify_freeze.add_argument("--json", action="store_true")
    verify_freeze.add_argument("--require-ready", action="store_true")
    verify_freeze.set_defaults(func=cmd_benchmark_materialization_verify_freeze)

    handoff_template = materialization_sub.add_parser(
        "handoff-template",
        help="Generate a non-overwriting custodian handoff template with no plaintext gold",
    )
    handoff_template.add_argument("--freeze", required=True)
    handoff_template.add_argument("--out", required=True)
    handoff_template.set_defaults(func=cmd_benchmark_materialization_handoff_template)

    verify_handoff = materialization_sub.add_parser(
        "verify-handoff",
        help="Validate a custodian-produced post-freeze materialization handoff",
    )
    verify_handoff.add_argument("--freeze", required=True)
    verify_handoff.add_argument("--handoff", required=True)
    verify_handoff.add_argument("--json", action="store_true")
    verify_handoff.add_argument("--require-ready", action="store_true")
    verify_handoff.set_defaults(func=cmd_benchmark_materialization_verify_handoff)

    registration_candidate = materialization_sub.add_parser(
        "registration-candidate",
        help="Generate candidate-only frozen partition entries without editing real manifests",
    )
    registration_candidate.add_argument("--freeze", required=True)
    registration_candidate.add_argument("--handoff", required=True)
    registration_candidate.add_argument("--out", required=True)
    registration_candidate.set_defaults(
        func=cmd_benchmark_materialization_registration_candidate
    )

    nl_benchmark = sub.add_parser(
        "nl-benchmark",
        help="Run prompt-to-derivation natural-language benchmark cases",
    )
    nl_benchmark.add_argument("--cases", default="nl_benchmark_cases")
    nl_benchmark.add_argument("--out", default="analysis/nl_benchmark_runs/latest")
    nl_benchmark.add_argument("--bundle-out", default="outputs/nl_benchmark_runs")
    nl_benchmark.add_argument("--archive", default=None)
    nl_benchmark.add_argument("--execute-wolfram", action="store_true")
    nl_benchmark.add_argument("--wolfram-timeout", type=int, default=120)
    nl_benchmark.set_defaults(func=cmd_nl_benchmark)

    ablate = sub.add_parser("ablate", help="Run ablation profiles over benchmark scores")
    ablate.add_argument("--profiles", default="ablation_profiles")
    ablate.add_argument("--cases", default="benchmark_cases")
    ablate.add_argument("--out", default="analysis/ablation_runs/latest")
    ablate.add_argument("--bundle-out", default="outputs/ablation_runs")
    ablate.add_argument("--wolfram-timeout", type=int, default=300)
    ablate.set_defaults(func=cmd_ablate)

    baseline = sub.add_parser("baseline", help="Run proxy baseline profiles over benchmark scores")
    baseline.add_argument("--profiles", default="baseline_profiles")
    baseline.add_argument("--cases", default="benchmark_cases")
    baseline.add_argument("--out", default="analysis/baseline_runs/latest")
    baseline.add_argument("--bundle-out", default="outputs/baseline_runs")
    baseline.set_defaults(func=cmd_baseline)

    baseline_eval = sub.add_parser(
        "baseline-eval",
        help="Evaluate recorded baseline outputs against benchmark cases",
    )
    baseline_eval.add_argument("--outputs", default="baseline_outputs")
    baseline_eval.add_argument("--cases", default="benchmark_cases")
    baseline_eval.add_argument("--out", default="analysis/baseline_actual_runs/latest")
    baseline_eval.add_argument("--bundle-out", default="outputs/baseline_actual_runs")
    baseline_eval.add_argument("--no-agent-reference", action="store_true")
    baseline_eval.set_defaults(func=cmd_baseline_eval)

    capabilities = sub.add_parser(
        "capabilities",
        help="List auditable symbolic-derivation capability routes",
    )
    capabilities.add_argument("--registry", default="knowledge_base/capabilities.yaml")
    capabilities.add_argument("--material", default=None)
    capabilities.add_argument("--texture", default=None)
    capabilities.add_argument(
        "--drive",
        default=None,
        help="Drive key; use 'none' for topology-only routes",
    )
    capabilities.add_argument("--geometry", default=None)
    capabilities.add_argument(
        "--support-level",
        choices=["full_derivation", "scaffold", "review_only", "unsupported"],
        default=None,
    )
    capabilities.add_argument(
        "--knowledge-status",
        choices=[
            "candidate",
            "symmetry_checked",
            "cas_validated",
            "expert_validated",
            "benchmarked",
            "released",
        ],
        default=None,
    )
    capabilities.add_argument("--json", action="store_true")
    capabilities.add_argument(
        "--claim-matrix",
        default=None,
        help="Write the full registry-derived manuscript claim-evidence matrix",
    )
    capabilities.set_defaults(func=cmd_capabilities)

    evidence = sub.add_parser(
        "evidence",
        help="Run generated and independent Wolfram paths for evidence cards",
    )
    evidence.add_argument("--cards", default="evidence_cards/core3")
    evidence.add_argument("--out", default="analysis/evidence_runs/core3_latest")
    evidence.add_argument("--wolfram-timeout", type=int, default=180)
    evidence.set_defaults(func=cmd_evidence)

    machine_audit = sub.add_parser(
        "machine-audit",
        help="Run deterministic symmetry, literature, and falsification audits",
    )
    machine_audit.add_argument("--specs", default="machine_audit_specs/core3")
    machine_audit.add_argument(
        "--evidence-runs", default="analysis/evidence_runs/core3_latest"
    )
    machine_audit.add_argument("--out", default="analysis/machine_audit/core3_latest")
    machine_audit.add_argument("--require-material-complete", action="store_true")
    machine_audit.set_defaults(func=cmd_machine_audit)

    assertion_coverage = sub.add_parser(
        "assertion-coverage",
        help="Audit resolution, dimension, sign, boundary, and limit assertions",
    )
    assertion_coverage.add_argument(
        "--registry", default="knowledge_base/assertion_coverage.yaml"
    )
    assertion_coverage.add_argument(
        "--evidence-runs",
        nargs="+",
        default=[
            "analysis/evidence_runs/core3_latest",
            "analysis/evidence_runs/extended_literature_01",
        ],
    )
    assertion_coverage.add_argument(
        "--out", default="analysis/assertion_coverage/latest"
    )
    assertion_coverage.add_argument("--require-complete", action="store_true")
    assertion_coverage.set_defaults(func=cmd_assertion_coverage)

    cross_engine = sub.add_parser(
        "cross-engine",
        help="Run or verify independent SymPy and high-precision numeric checks",
    )
    cross_engine_sub = cross_engine.add_subparsers(required=True)
    cross_engine_run = cross_engine_sub.add_parser(
        "run",
        help="Execute a frozen cross-engine suite",
    )
    cross_engine_run.add_argument(
        "--suite", choices=["core3", "extended"], default="core3"
    )
    cross_engine_run.add_argument("--specs", default="cross_engine_specs/core3")
    cross_engine_run.add_argument(
        "--out", default="analysis/cross_engine/core3_latest"
    )
    cross_engine_run.add_argument("--require-pass", action="store_true")
    cross_engine_run.set_defaults(func=cmd_cross_engine_run)

    cross_engine_verify = cross_engine_sub.add_parser(
        "verify",
        help="Verify one route result, its hashes, convergence, and N/A semantics",
    )
    cross_engine_verify.add_argument("--result", required=True)
    cross_engine_verify.add_argument(
        "--suite", choices=["core3", "extended"], default="core3"
    )
    cross_engine_verify.add_argument("--route", default=None)
    cross_engine_verify.add_argument("--json", action="store_true")
    cross_engine_verify.add_argument("--require-eligible", action="store_true")
    cross_engine_verify.set_defaults(func=cmd_cross_engine_verify)

    expert_review = sub.add_parser(
        "expert-review",
        help="Generate or verify frozen expert-review packets",
    )
    expert_review_sub = expert_review.add_subparsers(required=True)
    review_packet = expert_review_sub.add_parser(
        "packet",
        help="Generate a non-overwriting review packet from Evidence Cards and runs",
    )
    review_packet.add_argument("--cards", default="evidence_cards/core3")
    review_packet.add_argument(
        "--evidence-runs", default="analysis/evidence_runs/core3_latest"
    )
    review_packet.add_argument("--out", default="analysis/expert_review/core3_packet")
    review_packet.set_defaults(func=cmd_expert_review_packet)

    review_verify = expert_review_sub.add_parser(
        "verify",
        help="Verify packet hashes, review completeness, and promotion eligibility",
    )
    review_verify.add_argument("--packet", default="analysis/expert_review/core3_packet")
    review_verify.add_argument("--require-all-approved", action="store_true")
    review_verify.set_defaults(func=cmd_expert_review_verify)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
