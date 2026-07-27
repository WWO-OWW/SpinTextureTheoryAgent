from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .evidence import EvidenceCard, EvidenceRunResult
from .literature import (
    LiteratureReproductionRecord,
    LiteratureReproductionResult,
    evaluate_literature_record,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

AuditStatus = Literal["pass", "fail", "incomplete"]
OverallAuditStatus = Literal["pass", "conditional_pass", "fail", "incomplete"]
AuditSource = Literal[
    "physics_ir",
    "task",
    "wolfram",
    "evidence",
    "symmetry_record",
    "literature_record",
]
AuditOperator = Literal[
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "true",
    "false",
    "present",
]
AuditScope = Literal["formal_route", "material_applicability"]
OnMissing = Literal["fail", "incomplete"]


class AuditCheckSpec(BaseModel):
    check_id: str = Field(pattern=r"^[a-z0-9_]+$")
    axis: Literal["symmetry", "literature", "falsification"]
    badge: str = Field(pattern=r"^[a-z0-9_]+$")
    scope: AuditScope
    description: str
    source: AuditSource
    path: str
    operator: AuditOperator
    expected: object | None = None
    on_missing: OnMissing = "fail"
    critical: bool = True
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("operator", mode="before")
    @classmethod
    def normalize_yaml_boolean_operator(cls, value: object) -> object:
        if value is True:
            return "true"
        if value is False:
            return "false"
        return value

    @model_validator(mode="after")
    def validate_literature_sources(self) -> "AuditCheckSpec":
        if self.axis == "literature" and not self.source_ids:
            raise ValueError(f"Literature check {self.check_id} needs source_ids.")
        if self.operator in {"equals", "not_equals", "contains", "not_contains"}:
            if self.expected is None:
                raise ValueError(f"Audit check {self.check_id} needs an expected value.")
        return self


class AuditMutationSpec(BaseModel):
    mutation_id: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str
    source: AuditSource
    path: str
    replacement: object
    must_fail_checks: list[str] = Field(min_length=1)


class MaterialSymmetryRecord(BaseModel):
    schema_version: str
    record_id: str = Field(pattern=r"^[a-z0-9_]+$")
    material_name: str
    structure_identifier: str
    magnetic_space_group: str
    source_kind: Literal["spglib", "bilbao", "primary_literature"]
    source_version: str
    source_reference: str
    source_artifact: str
    source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    allowed_dmi_families: list[str] = Field(min_length=1)
    allowed_sot_tensor_forms: list[str] = Field(min_length=1)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MaterialSymmetryRecord":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


class MachineAuditSpec(BaseModel):
    schema_version: str
    audit_id: str = Field(pattern=r"^[a-z0-9_]+$")
    card_id: str
    case_id: str
    route_id: str
    evidence_card: str
    literature_reproduction_record: str | None = None
    material_symmetry_record: str | None = None
    claim_scope: str
    checks: list[AuditCheckSpec]
    mutations: list[AuditMutationSpec]

    @model_validator(mode="after")
    def validate_spec(self) -> "MachineAuditSpec":
        check_ids = [check.check_id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError(f"Machine-audit check IDs must be unique in {self.audit_id}.")
        mutation_ids = [mutation.mutation_id for mutation in self.mutations]
        if len(mutation_ids) != len(set(mutation_ids)):
            raise ValueError(f"Mutation IDs must be unique in {self.audit_id}.")
        known = set(check_ids)
        for mutation in self.mutations:
            unknown = set(mutation.must_fail_checks) - known
            if unknown:
                raise ValueError(
                    f"Mutation {mutation.mutation_id} cites unknown checks: {sorted(unknown)}"
                )
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MachineAuditSpec":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


class AuditCheckResult(BaseModel):
    check_id: str
    axis: str
    badge: str
    scope: AuditScope
    status: AuditStatus
    critical: bool
    description: str
    actual: object | None = None
    expected: object | None = None
    detail: str
    source_ids: list[str]


class AuditMutationResult(BaseModel):
    mutation_id: str
    status: AuditStatus
    description: str
    must_fail_checks: list[str]
    observed_statuses: dict[str, AuditStatus]
    detail: str


class AuditBadgeResult(BaseModel):
    badge: str
    status: AuditStatus
    check_ids: list[str]


class MachineAuditResult(BaseModel):
    audit_id: str
    card_id: str
    case_id: str
    route_id: str
    overall_status: OverallAuditStatus
    formal_route_status: AuditStatus
    material_applicability_status: AuditStatus
    checks: list[AuditCheckResult]
    mutations: list[AuditMutationResult]
    verification_badges: list[AuditBadgeResult]
    literature_reproduction: LiteratureReproductionResult | None
    primary_sources: list[dict[str, object]]
    limitations: list[str]
    input_artifacts: dict[str, str]
    result_path: str
    summary_path: str


class MachineAuditSuiteResult(BaseModel):
    suite_status: OverallAuditStatus
    formal_routes_passed: int
    conditional_routes: int
    failed_routes: int
    incomplete_routes: int
    results: list[MachineAuditResult]
    summary_json: str
    summary_markdown: str


_MISSING = object()


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_true(value: object) -> bool:
    return value is True or str(value).strip() == "True"


def _is_false(value: object) -> bool:
    return value is False or str(value).strip() == "False"


def _get_path(source: dict[str, object], path: str) -> object:
    current: object = source
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_path(source: dict[str, object], path: str, value: object) -> None:
    parts = path.split(".")
    current: dict[str, object] = source
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _evaluate_operator(actual: object, check: AuditCheckSpec) -> bool:
    if check.operator == "equals":
        return actual == check.expected
    if check.operator == "not_equals":
        return actual != check.expected
    if check.operator == "contains":
        return check.expected in actual if isinstance(actual, (str, list, dict)) else False
    if check.operator == "not_contains":
        return check.expected not in actual if isinstance(actual, (str, list, dict)) else True
    if check.operator == "true":
        return _is_true(actual)
    if check.operator == "false":
        return _is_false(actual)
    return actual not in (None, "", [], {})


def _evaluate_check(
    check: AuditCheckSpec,
    context: dict[str, dict[str, object]],
) -> AuditCheckResult:
    actual = _get_path(context[check.source], check.path)
    if actual is _MISSING:
        status: AuditStatus = check.on_missing
        detail = f"missing {check.source}.{check.path}"
        display_actual = None
    else:
        passed = _evaluate_operator(actual, check)
        status = "pass" if passed else "fail"
        detail = "declared condition satisfied" if passed else "declared condition violated"
        display_actual = actual
    return AuditCheckResult(
        check_id=check.check_id,
        axis=check.axis,
        badge=check.badge,
        scope=check.scope,
        status=status,
        critical=check.critical,
        description=check.description,
        actual=display_actual,
        expected=check.expected,
        detail=detail,
        source_ids=check.source_ids,
    )


def _aggregate(statuses: list[AuditStatus]) -> AuditStatus:
    if not statuses:
        return "incomplete"
    if "fail" in statuses:
        return "fail"
    if "incomplete" in statuses:
        return "incomplete"
    return "pass"


def _mutation_results(
    spec: MachineAuditSpec,
    context: dict[str, dict[str, object]],
) -> list[AuditMutationResult]:
    checks_by_id = {check.check_id: check for check in spec.checks}
    results: list[AuditMutationResult] = []
    for mutation in spec.mutations:
        mutated = copy.deepcopy(context)
        _set_path(mutated[mutation.source], mutation.path, mutation.replacement)
        observed = {
            check_id: _evaluate_check(checks_by_id[check_id], mutated).status
            for check_id in mutation.must_fail_checks
        }
        detected = all(status == "fail" for status in observed.values())
        results.append(
            AuditMutationResult(
                mutation_id=mutation.mutation_id,
                status="pass" if detected else "fail",
                description=mutation.description,
                must_fail_checks=mutation.must_fail_checks,
                observed_statuses=observed,
                detail=(
                    "all designated checks rejected the counterfactual"
                    if detected
                    else "one or more designated checks failed to reject the counterfactual"
                ),
            )
        )
    return results


def _badge_results(
    checks: list[AuditCheckResult],
    mutations: list[AuditMutationResult],
) -> list[AuditBadgeResult]:
    badges: dict[str, list[tuple[str, AuditStatus]]] = {}
    for check in checks:
        badges.setdefault(check.badge, []).append((check.check_id, check.status))
    if mutations:
        badges.setdefault("adversarial_falsification", []).extend(
            (mutation.mutation_id, mutation.status) for mutation in mutations
        )
    return [
        AuditBadgeResult(
            badge=badge,
            status=_aggregate([status for _, status in entries]),
            check_ids=[check_id for check_id, _ in entries],
        )
        for badge, entries in sorted(badges.items())
    ]


def _render_result(result: MachineAuditResult) -> str:
    lines = [
        f"# Machine physics audit: {result.case_id}",
        "",
        f"- Route: `{result.route_id}`",
        f"- Overall: `{result.overall_status}`",
        f"- Formal route: `{result.formal_route_status}`",
        f"- Material applicability: `{result.material_applicability_status}`",
        "- This is machine-audited evidence, not an expert-validation decision.",
        "",
        "## Verification badges",
        "",
        "| Badge | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for badge in result.verification_badges:
        lines.append(
            f"| `{badge.badge}` | `{badge.status}` | "
            f"{', '.join(f'`{item}`' for item in badge.check_ids)} |"
        )
    lines.extend(
        [
            "",
            "## Checks",
            "",
            "| Check | Axis | Scope | Status | Description |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for check in result.checks:
        lines.append(
            f"| `{check.check_id}` | `{check.axis}` | `{check.scope}` | "
            f"`{check.status}` | {check.description} |"
        )
    lines.extend(
        [
            "",
            "## Counterfactual mutations",
            "",
            "| Mutation | Status | Rejected by |",
            "| --- | --- | --- |",
        ]
    )
    for mutation in result.mutations:
        lines.append(
            f"| `{mutation.mutation_id}` | `{mutation.status}` | "
            f"{', '.join(f'`{item}`' for item in mutation.must_fail_checks)} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in result.limitations)
    if result.literature_reproduction:
        lines.extend(["", "## Literature reproduction", ""])
        lines.append(
            f"- Record: `{result.literature_reproduction.record_id}`"
        )
        lines.append(
            f"- Bounded-claim status: `{result.literature_reproduction.status}`"
        )
        lines.append(
            f"- Independent preparation declared: "
            f"`{result.literature_reproduction.independence_declared}`"
        )
        lines.append("")
        lines.append("| Claim | Coverage | Reproduction class | Status | Uncovered terms |")
        lines.append("| --- | --- | --- | --- | --- |")
        for claim in result.literature_reproduction.claims:
            uncovered = "; ".join(claim.uncovered_terms) or "none"
            lines.append(
                f"| `{claim.claim_id}` | `{claim.coverage}` | "
                f"`{claim.reproduction_class}` | `{claim.status}` | "
                f"{uncovered} |"
            )
    lines.extend(["", "## Primary sources", ""])
    for source in result.primary_sources:
        doi = f" DOI: `{source.get('doi')}`." if source.get("doi") else ""
        lines.append(f"- `{source['source_id']}`: {source['citation']}{doi}")
    return "\n".join(lines).rstrip() + "\n"


def _load_symmetry_context(
    spec: MachineAuditSpec,
) -> tuple[dict[str, object], dict[str, str]]:
    if not spec.material_symmetry_record:
        return {}, {}
    record_path = _project_path(spec.material_symmetry_record)
    record = MaterialSymmetryRecord.from_yaml(record_path)
    artifact_path = _project_path(record.source_artifact)
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Material symmetry source artifact is missing: {artifact_path}")
    provenance_valid = _sha256(artifact_path) == record.source_artifact_sha256
    context = record.model_dump()
    context["provenance_valid"] = provenance_valid
    artifacts = {
        "material_symmetry_record": f"{record_path}:{_sha256(record_path)}",
        "material_symmetry_source": f"{artifact_path}:{_sha256(artifact_path)}",
    }
    return context, artifacts


def _render_suite(result: MachineAuditSuiteResult) -> str:
    lines = [
        "# Machine physics audit suite",
        "",
        f"- Suite status: `{result.suite_status}`",
        f"- Formal routes passed: `{result.formal_routes_passed}`",
        f"- Conditional routes: `{result.conditional_routes}`",
        f"- Failed routes: `{result.failed_routes}`",
        f"- Incomplete routes: `{result.incomplete_routes}`",
        "",
        "| Case | Route | Overall | Formal | Material applicability |",
        "| --- | --- | --- | --- | --- |",
    ]
    for audit in result.results:
        lines.append(
            f"| `{audit.case_id}` | `{audit.route_id}` | `{audit.overall_status}` | "
            f"`{audit.formal_route_status}` | `{audit.material_applicability_status}` |"
        )
    lines.extend(
        [
            "",
            "`conditional_pass` means the registered formal model passed while material-specific symmetry or coupling evidence remains incomplete.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_machine_audit_spec(
    spec_path: str | Path,
    evidence_run_root: str | Path,
    out_dir: str | Path,
) -> MachineAuditResult:
    resolved_spec = _project_path(spec_path)
    spec = MachineAuditSpec.from_yaml(resolved_spec)
    card_path = _project_path(spec.evidence_card)
    card = EvidenceCard.from_yaml(card_path)
    evidence_path = _project_path(evidence_run_root) / spec.card_id / "evidence_result.json"
    run = EvidenceRunResult.model_validate(json.loads(evidence_path.read_text(encoding="utf-8")))
    record_path = _project_path(run.generated_record)
    record = json.loads(record_path.read_text(encoding="utf-8"))

    if (card.card_id, card.case_id, card.route_id) != (
        spec.card_id,
        spec.case_id,
        spec.route_id,
    ):
        raise ValueError(f"Machine-audit spec and Evidence Card disagree: {spec.audit_id}")
    if (run.card_id, run.case_id, run.route_id) != (
        spec.card_id,
        spec.case_id,
        spec.route_id,
    ):
        raise ValueError(f"Machine-audit spec and evidence run disagree: {spec.audit_id}")

    evidence_checks = {check.check_id: check.model_dump() for check in run.checks}
    symmetry_context, symmetry_artifacts = _load_symmetry_context(spec)
    base_context: dict[str, dict[str, object]] = {
        "physics_ir": record["physics_ir"],
        "task": record["task"],
        "wolfram": record.get("wolfram_results", {}).get("results", {}),
        "evidence": {
            "passed": run.passed,
            "generated_execution_status": run.generated_execution_status,
            "gold_execution_status": run.gold_execution_status,
            "checks": evidence_checks,
        },
        "symmetry_record": symmetry_context,
    }
    literature_result: LiteratureReproductionResult | None = None
    literature_artifacts: dict[str, str] = {}
    if spec.literature_reproduction_record:
        literature_path = _project_path(spec.literature_reproduction_record)
        literature_record = LiteratureReproductionRecord.from_yaml(literature_path)
        if (
            literature_record.card_id,
            literature_record.case_id,
            literature_record.route_id,
        ) != (spec.card_id, spec.case_id, spec.route_id):
            raise ValueError(
                f"Literature record and machine-audit spec disagree: {spec.audit_id}"
            )
        literature_result = evaluate_literature_record(
            literature_record, base_context
        )
        literature_context = literature_result.model_dump()
        literature_context["claims"] = {
            claim.claim_id: claim.model_dump() for claim in literature_result.claims
        }
        base_context["literature_record"] = literature_context
        literature_artifacts = {
            "literature_reproduction_record": (
                f"{literature_path}:{_sha256(literature_path)}"
            )
        }
    else:
        base_context["literature_record"] = {}
    context = base_context
    source_ids = {source.source_id for source in card.sources}
    if spec.literature_reproduction_record:
        locator_source_ids = {
            locator.source_id for locator in literature_record.locators
        }
        unknown_locator_sources = locator_source_ids - source_ids
        if unknown_locator_sources:
            raise ValueError(
                "Literature record cites sources absent from the Evidence Card: "
                f"{sorted(unknown_locator_sources)}"
            )
    for check in spec.checks:
        unknown = set(check.source_ids) - source_ids
        if unknown:
            raise ValueError(
                f"Audit check {check.check_id} cites sources absent from the Evidence Card: "
                f"{sorted(unknown)}"
            )

    checks = [_evaluate_check(check, context) for check in spec.checks]
    mutations = _mutation_results(spec, context)
    badges = _badge_results(checks, mutations)
    formal_statuses = [
        check.status for check in checks if check.scope == "formal_route" and check.critical
    ] + [mutation.status for mutation in mutations]
    material_statuses = [
        check.status
        for check in checks
        if check.scope == "material_applicability" and check.critical
    ]
    formal_status = _aggregate(formal_statuses)
    material_status = _aggregate(material_statuses)
    if formal_status == "fail" or material_status == "fail":
        overall: OverallAuditStatus = "fail"
    elif formal_status == "incomplete":
        overall = "incomplete"
    elif material_status == "pass":
        overall = "pass"
    else:
        overall = "conditional_pass"

    output_dir = _project_path(out_dir) / spec.card_id
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "machine_audit.json"
    summary_path = output_dir / "machine_audit.md"
    primary_sources = [
        source.model_dump()
        for source in card.sources
        if source.source_type == "primary_literature"
    ]
    limitations = [
        "Machine checks establish consistency with the registered formal model, not empirical adequacy for a named material.",
        "Material-specific symmetry, coupling, and boundary/profile evidence are absent unless supplied as explicit provenance.",
        "LLM or multi-agent agreement is not used as a pass criterion.",
    ]
    if literature_result:
        limitations.extend(literature_result.limitations)
        limitations.extend(
            f"Literature-uncovered project extension: {item}"
            for item in literature_result.known_extensions
        )
    result = MachineAuditResult(
        audit_id=spec.audit_id,
        card_id=spec.card_id,
        case_id=spec.case_id,
        route_id=spec.route_id,
        overall_status=overall,
        formal_route_status=formal_status,
        material_applicability_status=material_status,
        checks=checks,
        mutations=mutations,
        verification_badges=badges,
        literature_reproduction=literature_result,
        primary_sources=primary_sources,
        limitations=limitations,
        input_artifacts={
            "spec": f"{resolved_spec}:{_sha256(resolved_spec)}",
            "evidence_card": f"{card_path}:{_sha256(card_path)}",
            "evidence_result": f"{evidence_path}:{_sha256(evidence_path)}",
            "generated_record": f"{record_path}:{_sha256(record_path)}",
            **literature_artifacts,
            **symmetry_artifacts,
        },
        result_path=str(result_path),
        summary_path=str(summary_path),
    )
    result_path.write_text(
        json.dumps(result.model_dump(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(_render_result(result), encoding="utf-8")
    return result


def run_machine_audit_suite(
    specs_path: str | Path,
    evidence_run_root: str | Path,
    out_dir: str | Path,
) -> MachineAuditSuiteResult:
    resolved_specs = _project_path(specs_path)
    spec_paths = [resolved_specs] if resolved_specs.is_file() else sorted(resolved_specs.glob("*.yaml"))
    if not spec_paths:
        raise ValueError(f"No machine-audit specs found under {resolved_specs}")
    results = [
        run_machine_audit_spec(spec_path, evidence_run_root, out_dir)
        for spec_path in spec_paths
    ]
    overall_statuses = [result.overall_status for result in results]
    if "fail" in overall_statuses:
        suite_status: OverallAuditStatus = "fail"
    elif "incomplete" in overall_statuses:
        suite_status = "incomplete"
    elif "conditional_pass" in overall_statuses:
        suite_status = "conditional_pass"
    else:
        suite_status = "pass"
    output_dir = _project_path(out_dir)
    summary_json = output_dir / "machine_audit_summary.json"
    summary_markdown = output_dir / "machine_audit_summary.md"
    suite = MachineAuditSuiteResult(
        suite_status=suite_status,
        formal_routes_passed=sum(result.formal_route_status == "pass" for result in results),
        conditional_routes=sum(result.overall_status == "conditional_pass" for result in results),
        failed_routes=sum(result.overall_status == "fail" for result in results),
        incomplete_routes=sum(result.overall_status == "incomplete" for result in results),
        results=results,
        summary_json=str(summary_json),
        summary_markdown=str(summary_markdown),
    )
    summary_json.write_text(
        json.dumps(suite.model_dump(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_markdown.write_text(_render_suite(suite), encoding="utf-8")
    return suite
