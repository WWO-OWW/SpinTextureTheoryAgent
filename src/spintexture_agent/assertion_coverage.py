from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .capabilities import CapabilityRegistry


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSERTION_REGISTRY = (
    PROJECT_ROOT / "knowledge_base" / "assertion_coverage.yaml"
)
DEFAULT_EVIDENCE_ROOTS = (
    PROJECT_ROOT / "analysis" / "evidence_runs" / "core3_latest",
    PROJECT_ROOT / "analysis" / "evidence_runs" / "extended_literature_01",
)
DEFAULT_ASSERTION_OUT = PROJECT_ROOT / "analysis" / "assertion_coverage" / "latest"

ResultClass = Literal["must_resolve", "symbolic_by_design", "metadata"]
CoverageStatus = Literal["pass", "fail", "missing", "not_applicable"]
RouteStatus = Literal["pass", "fail", "incomplete"]
AssertionAxis = Literal["dimension", "sign", "boundary", "limit"]

FATAL_SENTINEL_RE = re.compile(
    r"(?:\$Failed|\$Aborted|\bIndeterminate\b|\bComplexInfinity\b|"
    r"\bDirectedInfinity\b|\bOverflow\b|\bUnderflow\b|"
    r"\bFailure\[|\bMissing\[)",
)
UNRESOLVED_HEAD_RE = re.compile(
    r"\b(?:Integrate|NIntegrate|Sum|NSum|Solve|NSolve|DSolve|NDSolve|"
    r"Reduce|FindRoot|Inactive|HoldForm)\[",
)


class ResultKeyClasses(BaseModel):
    must_resolve: list[str] = Field(default_factory=list)
    symbolic_by_design: list[str] = Field(default_factory=list)
    metadata: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_key_classes(self) -> "ResultKeyClasses":
        all_keys = self.all_keys
        if not all_keys:
            raise ValueError("At least one Wolfram result key must be classified.")
        if len(all_keys) != len(set(all_keys)):
            raise ValueError("Each Wolfram result key must have exactly one class.")
        return self

    @property
    def all_keys(self) -> list[str]:
        return [*self.must_resolve, *self.symbolic_by_design, *self.metadata]

    def classification_map(self) -> dict[str, ResultClass]:
        return {
            **{key: "must_resolve" for key in self.must_resolve},
            **{key: "symbolic_by_design" for key in self.symbolic_by_design},
            **{key: "metadata" for key in self.metadata},
        }


class AxisContract(BaseModel):
    keys: list[str] = Field(default_factory=list)
    not_applicable_reason: str | None = None

    @model_validator(mode="after")
    def validate_axis(self) -> "AxisContract":
        if self.keys and self.not_applicable_reason:
            raise ValueError("An assertion axis cannot have keys and be not applicable.")
        if len(self.keys) != len(set(self.keys)):
            raise ValueError("Assertion keys must be unique within an axis.")
        return self


class AssertionAxes(BaseModel):
    dimension: AxisContract
    sign: AxisContract
    boundary: AxisContract
    limit: AxisContract

    def as_dict(self) -> dict[AssertionAxis, AxisContract]:
        return {
            "dimension": self.dimension,
            "sign": self.sign,
            "boundary": self.boundary,
            "limit": self.limit,
        }


class AssertionGap(BaseModel):
    gap_id: str = Field(pattern=r"^[a-z0-9_]+$")
    axis: AssertionAxis
    description: str
    next_action: str


class RouteAssertionContract(BaseModel):
    route_id: str = Field(pattern=r"^[a-z0-9_]+$")
    evidence_card: str
    result_keys: ResultKeyClasses
    assertions: AssertionAxes
    known_gaps: list[AssertionGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_route_contract(self) -> "RouteAssertionContract":
        classified = set(self.result_keys.all_keys)
        for axis, contract in self.assertions.as_dict().items():
            unknown = sorted(set(contract.keys) - classified)
            if unknown:
                raise ValueError(
                    f"Assertion axis {axis} references unclassified keys: {unknown}"
                )
        gap_ids = [gap.gap_id for gap in self.known_gaps]
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError(f"Known gap IDs must be unique for {self.route_id}.")
        missing_axes = {
            axis
            for axis, contract in self.assertions.as_dict().items()
            if not contract.keys and not contract.not_applicable_reason
        }
        gap_axes = {gap.axis for gap in self.known_gaps}
        if missing_axes != gap_axes:
            raise ValueError(
                f"Missing assertion axes {sorted(missing_axes)} must match registered "
                f"gap axes {sorted(gap_axes)} for {self.route_id}."
            )
        return self


class AssertionCoverageData(BaseModel):
    schema_version: str
    routes: list[RouteAssertionContract]

    @model_validator(mode="after")
    def validate_registry(self) -> "AssertionCoverageData":
        route_ids = [route.route_id for route in self.routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("Assertion-coverage route IDs must be unique.")
        return self


class AssertionCoverageRegistry:
    def __init__(self, path: str | Path = DEFAULT_ASSERTION_REGISTRY):
        self.path = _project_path(path)
        with self.path.open("r", encoding="utf-8") as handle:
            self.data = AssertionCoverageData.model_validate(yaml.safe_load(handle))

    @property
    def routes(self) -> list[RouteAssertionContract]:
        return self.data.routes

    def validate_capability_coverage(self) -> None:
        full_routes = {
            route.route_id
            for route in CapabilityRegistry().routes
            if route.support_level == "full_derivation"
        }
        contract_routes = {route.route_id for route in self.routes}
        if contract_routes != full_routes:
            missing = sorted(full_routes - contract_routes)
            extra = sorted(contract_routes - full_routes)
            raise ValueError(
                f"Assertion registry must cover every full route; missing={missing}, "
                f"extra={extra}."
            )


class ResultKeyCoverage(BaseModel):
    key: str
    classification: ResultClass | Literal["unclassified"]
    status: CoverageStatus
    detail: str


class AxisCoverage(BaseModel):
    axis: AssertionAxis
    status: CoverageStatus
    keys: list[str] = Field(default_factory=list)
    detail: str


class RouteAssertionCoverage(BaseModel):
    route_id: str
    evidence_card: str
    evidence_result: str | None
    generated_record: str | None
    execution_status: str
    resolution_status: CoverageStatus
    classified_key_count: int
    expected_key_count: int
    result_key_checks: list[ResultKeyCoverage]
    axes: list[AxisCoverage]
    known_gaps: list[AssertionGap]
    overall_status: RouteStatus


class AssertionCoverageRun(BaseModel):
    suite_status: RouteStatus
    routes_passed: int
    routes_incomplete: int
    routes_failed: int
    key_status_counts: dict[str, int]
    axis_status_counts: dict[str, int]
    routes: list[RouteAssertionCoverage]
    registry_path: str
    result_json: str
    report_markdown: str


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


def _value_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _is_true(value: object) -> bool:
    return value is True or str(value).strip() == "True"


def _check_result_key(
    key: str,
    classification: ResultClass,
    results: dict[str, object],
) -> ResultKeyCoverage:
    if key not in results or results[key] is None or _value_text(results[key]).strip() == "":
        return ResultKeyCoverage(
            key=key,
            classification=classification,
            status="missing",
            detail="declared result value is absent",
        )
    text = _value_text(results[key])
    sentinel = FATAL_SENTINEL_RE.search(text)
    if sentinel:
        return ResultKeyCoverage(
            key=key,
            classification=classification,
            status="fail",
            detail=f"fatal Wolfram sentinel detected: {sentinel.group(0)}",
        )
    if classification == "must_resolve":
        unresolved = UNRESOLVED_HEAD_RE.search(text)
        if unresolved:
            return ResultKeyCoverage(
                key=key,
                classification=classification,
                status="fail",
                detail=f"unresolved Wolfram head detected: {unresolved.group(0)}",
            )
    return ResultKeyCoverage(
        key=key,
        classification=classification,
        status="pass",
        detail="present and satisfies its resolution contract",
    )


def _check_axis(
    axis: AssertionAxis,
    contract: AxisContract,
    results: dict[str, object],
) -> AxisCoverage:
    if contract.not_applicable_reason:
        return AxisCoverage(
            axis=axis,
            status="not_applicable",
            detail=contract.not_applicable_reason,
        )
    if not contract.keys:
        return AxisCoverage(
            axis=axis,
            status="missing",
            detail="no executable assertion is registered for this applicable axis",
        )
    missing = [key for key in contract.keys if key not in results]
    if missing:
        return AxisCoverage(
            axis=axis,
            status="missing",
            keys=contract.keys,
            detail=f"assertion result keys are absent: {missing}",
        )
    failed = [key for key in contract.keys if not _is_true(results[key])]
    if failed:
        return AxisCoverage(
            axis=axis,
            status="fail",
            keys=contract.keys,
            detail=f"assertions did not evaluate to True: {failed}",
        )
    return AxisCoverage(
        axis=axis,
        status="pass",
        keys=contract.keys,
        detail=f"{len(contract.keys)}/{len(contract.keys)} assertions evaluated to True",
    )


def evaluate_route_contract(
    contract: RouteAssertionContract,
    evidence_payload: dict[str, object] | None,
    generated_record: dict[str, object] | None,
    *,
    evidence_result_path: str | None = None,
    generated_record_path: str | None = None,
) -> RouteAssertionCoverage:
    execution_status = "missing"
    expected_keys: list[str] = []
    results: dict[str, object] = {}
    evidence_failed = False
    if evidence_payload is not None:
        execution_status = str(evidence_payload.get("generated_execution_status", "missing"))
        evidence_failed = evidence_payload.get("passed") is not True
    if generated_record is not None:
        wolfram = generated_record.get("wolfram_results", {})
        if isinstance(wolfram, dict):
            expected = wolfram.get("expected_keys", [])
            actual = wolfram.get("results", {})
            expected_keys = [str(key) for key in expected] if isinstance(expected, list) else []
            results = actual if isinstance(actual, dict) else {}
            execution_status = str(wolfram.get("status", execution_status))

    classifications = contract.result_keys.classification_map()
    expected_set = set(expected_keys)
    classified_set = set(classifications)
    checks = [
        _check_result_key(key, classifications[key], results)
        for key in contract.result_keys.all_keys
        if key in expected_set
    ]
    for key in sorted(expected_set - classified_set):
        checks.append(
            ResultKeyCoverage(
                key=key,
                classification="unclassified",
                status="missing",
                detail="declared Wolfram result key has no resolution class",
            )
        )
    for key in sorted(classified_set - expected_set):
        checks.append(
            ResultKeyCoverage(
                key=key,
                classification=classifications[key],
                status="fail",
                detail="registry key is not declared by the generated record",
            )
        )
    for key in sorted(set(results) - expected_set):
        checks.append(
            ResultKeyCoverage(
                key=key,
                classification="unclassified",
                status="fail",
                detail="Wolfram emitted an undeclared result key",
            )
        )

    if generated_record is None or evidence_payload is None:
        resolution_status: CoverageStatus = "missing"
    elif execution_status != "passed" or evidence_failed:
        resolution_status = "fail"
    elif any(check.status == "fail" for check in checks):
        resolution_status = "fail"
    elif any(check.status == "missing" for check in checks):
        resolution_status = "missing"
    else:
        resolution_status = "pass"

    axes = [
        _check_axis(axis, axis_contract, results)
        for axis, axis_contract in contract.assertions.as_dict().items()
    ]
    if resolution_status == "fail" or any(axis.status == "fail" for axis in axes):
        overall: RouteStatus = "fail"
    elif resolution_status == "missing" or any(axis.status == "missing" for axis in axes):
        overall = "incomplete"
    else:
        overall = "pass"

    return RouteAssertionCoverage(
        route_id=contract.route_id,
        evidence_card=contract.evidence_card,
        evidence_result=evidence_result_path,
        generated_record=generated_record_path,
        execution_status=execution_status,
        resolution_status=resolution_status,
        classified_key_count=len(classified_set),
        expected_key_count=len(expected_set),
        result_key_checks=checks,
        axes=axes,
        known_gaps=contract.known_gaps,
        overall_status=overall,
    )


def _load_evidence_results(
    evidence_roots: list[str | Path] | tuple[str | Path, ...],
) -> dict[str, tuple[Path, dict[str, object]]]:
    found: dict[str, tuple[Path, dict[str, object]]] = {}
    for root_value in evidence_roots:
        root = _project_path(root_value)
        paths = [root] if root.is_file() else sorted(root.rglob("evidence_result.json"))
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            route_id = str(payload.get("route_id", ""))
            if not route_id:
                continue
            if route_id in found:
                raise ValueError(f"Duplicate evidence results found for route {route_id}.")
            found[route_id] = (path, payload)
    return found


def _load_generated_record(
    evidence_path: Path,
    evidence_payload: dict[str, object],
) -> tuple[Path | None, dict[str, object] | None]:
    registered = evidence_payload.get("generated_record")
    candidates: list[Path] = []
    if registered:
        candidates.append(_project_path(str(registered)))
    candidates.extend(sorted((evidence_path.parent / "generated" / "records").glob("*.json")))
    for path in candidates:
        if path.exists():
            return path, json.loads(path.read_text(encoding="utf-8"))
    return None, None


def _render_report(run: AssertionCoverageRun) -> str:
    lines = [
        "# Project 1 assertion coverage",
        "",
        "> Resolution success means the registered result was evaluated without forbidden "
        "failure sentinels or undeclared unresolved heads. It does not by itself prove the "
        "physical model.",
        "",
        f"- Suite status: `{run.suite_status}`",
        f"- Routes: {len(run.routes)}",
        f"- Passed: {run.routes_passed}",
        f"- Incomplete: {run.routes_incomplete}",
        f"- Failed: {run.routes_failed}",
        "",
        "## Route summary",
        "",
        "| Route | Keys | Resolution | Dimension | Sign | Boundary | Limit | Overall |",
        "| --- | ---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for route in run.routes:
        axes = {axis.axis: axis.status for axis in route.axes}
        lines.append(
            f"| `{route.route_id}` | {route.classified_key_count}/{route.expected_key_count} | "
            f"`{route.resolution_status}` | `{axes['dimension']}` | `{axes['sign']}` | "
            f"`{axes['boundary']}` | `{axes['limit']}` | `{route.overall_status}` |"
        )
    lines.extend(["", "## Registered gaps", ""])
    gaps = [(route.route_id, gap) for route in run.routes for gap in route.known_gaps]
    if not gaps:
        lines.append("No assertion gaps are registered.")
    else:
        for route_id, gap in gaps:
            lines.extend(
                [
                    f"### `{gap.gap_id}`",
                    "",
                    f"- Route: `{route_id}`",
                    f"- Axis: `{gap.axis}`",
                    f"- Gap: {gap.description}",
                    f"- Next action: {gap.next_action}",
                    "",
                ]
            )
    lines.extend(
        [
            "## Status semantics",
            "",
            "- `pass`: executable assertions passed for the applicable scope.",
            "- `not_applicable`: the axis is excluded with a registered reason.",
            "- `missing`: an applicable assertion or result classification is absent.",
            "- `fail`: execution, a Boolean assertion, or a resolution contract failed.",
            "",
            "`symbolic_by_design` permits explicitly declared held integrals or definitions. "
            "Ordinary `Derivative[...]` terms in terminal symbolic equations are not treated "
            "as unresolved CAS operations.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def run_assertion_coverage(
    registry_path: str | Path = DEFAULT_ASSERTION_REGISTRY,
    evidence_roots: list[str | Path] | tuple[str | Path, ...] = DEFAULT_EVIDENCE_ROOTS,
    out_dir: str | Path = DEFAULT_ASSERTION_OUT,
) -> AssertionCoverageRun:
    registry = AssertionCoverageRegistry(registry_path)
    registry.validate_capability_coverage()
    evidence = _load_evidence_results(evidence_roots)
    routes: list[RouteAssertionCoverage] = []
    for contract in registry.routes:
        item = evidence.get(contract.route_id)
        if item is None:
            routes.append(evaluate_route_contract(contract, None, None))
            continue
        evidence_path, payload = item
        record_path, record = _load_generated_record(evidence_path, payload)
        routes.append(
            evaluate_route_contract(
                contract,
                payload,
                record,
                evidence_result_path=str(evidence_path),
                generated_record_path=str(record_path) if record_path else None,
            )
        )

    if any(route.overall_status == "fail" for route in routes):
        suite_status: RouteStatus = "fail"
    elif any(route.overall_status == "incomplete" for route in routes):
        suite_status = "incomplete"
    else:
        suite_status = "pass"
    key_counts = {
        status: sum(
            check.status == status
            for route in routes
            for check in route.result_key_checks
        )
        for status in ("pass", "fail", "missing", "not_applicable")
    }
    axis_counts = {
        status: sum(axis.status == status for route in routes for axis in route.axes)
        for status in ("pass", "fail", "missing", "not_applicable")
    }
    out = _project_path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "assertion_coverage.json"
    markdown_path = out / "assertion_coverage.md"
    run = AssertionCoverageRun(
        suite_status=suite_status,
        routes_passed=sum(route.overall_status == "pass" for route in routes),
        routes_incomplete=sum(route.overall_status == "incomplete" for route in routes),
        routes_failed=sum(route.overall_status == "fail" for route in routes),
        key_status_counts=key_counts,
        axis_status_counts=axis_counts,
        routes=routes,
        registry_path=str(registry.path),
        result_json=str(json_path),
        report_markdown=str(markdown_path),
    )
    json_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    markdown_path.write_text(_render_report(run), encoding="utf-8")
    return run
