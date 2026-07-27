from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


LiteratureStatus = Literal["pass", "fail", "incomplete"]
LiteratureSource = Literal["physics_ir", "task", "wolfram", "evidence"]
LiteratureOperator = Literal[
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "true",
    "false",
    "present",
]
LiteratureCoverage = Literal["exact", "structural", "partial"]
LiteratureReproductionClass = Literal[
    "exact_coefficient",
    "exact_normalized",
    "boundary_conditioned_exact",
    "structural_alignment",
    "partial_alignment",
]
ConventionOperation = Literal[
    "identity",
    "coefficient_redefinition",
    "global_sign_flip",
    "antisymmetric_index_swap",
    "component_expansion",
    "force_projection_rewrite",
    "topology_normalization",
    "torque_channel_restriction",
]


class LiteraturePreparation(BaseModel):
    method: str
    created_without_project_gold: bool
    prepared_from: list[str] = Field(min_length=1)
    prohibited_dependencies: list[str] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_independence_declaration(self) -> "LiteraturePreparation":
        if not self.created_without_project_gold:
            raise ValueError("Literature reproduction must declare project-gold independence.")
        prohibited = " ".join(self.prohibited_dependencies)
        for required in ("gold_answers/", "mathematica/gold/"):
            if required not in prohibited:
                raise ValueError(
                    f"Literature reproduction must prohibit dependency on {required!r}."
                )
        return self


class LiteratureSourceLocator(BaseModel):
    locator_id: str = Field(pattern=r"^[a-z0-9_]+$")
    source_id: str = Field(pattern=r"^[a-z0-9_]+$")
    publication_version: str
    printed_page: str
    equation_label: str | None = None
    section: str | None = None
    source_expression: str
    source_expression_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_expression_hash(self) -> "LiteratureSourceLocator":
        actual = hashlib.sha256(self.source_expression.encode("utf-8")).hexdigest()
        if actual != self.source_expression_sha256:
            raise ValueError(
                f"Source-expression hash mismatch for locator {self.locator_id}."
            )
        if not (self.equation_label or self.section):
            raise ValueError(
                f"Locator {self.locator_id} needs an equation label or section."
            )
        if self.printed_page.strip().lower() in {
            "",
            "unknown",
            "n/a",
            "na",
            "doi-only",
            "doi only",
        }:
            raise ValueError(
                f"Locator {self.locator_id} needs a printed page, not a DOI-only locator."
            )
        return self


class BlindedSymbolMapping(BaseModel):
    token: str = Field(pattern=r"^sym_[0-9]{2}$")
    source_symbol: str
    target_symbol: str
    relation: str


class ConventionTransformation(BaseModel):
    transformation_id: str = Field(pattern=r"^[a-z0-9_]+$")
    operation: ConventionOperation
    source_convention: str
    target_convention: str
    description: str


class ExecutableLiteratureTransform(BaseModel):
    source_expression_key: str = Field(pattern=r"^[a-z0-9_]+$")
    transformed_expression_key: str = Field(pattern=r"^[a-z0-9_]+$")
    target_expression_key: str = Field(pattern=r"^[a-z0-9_]+$")
    equivalence_regression_key: str = Field(pattern=r"^[a-z0-9_]+$")

    @model_validator(mode="after")
    def validate_distinct_expression_keys(self) -> "ExecutableLiteratureTransform":
        keys = {
            self.source_expression_key,
            self.transformed_expression_key,
            self.target_expression_key,
        }
        if len(keys) != 3:
            raise ValueError(
                "Executable literature source, transformed, and target keys must be distinct."
            )
        return self


class LiteratureAssertion(BaseModel):
    assertion_id: str = Field(pattern=r"^[a-z0-9_]+$")
    source: LiteratureSource
    path: str
    operator: LiteratureOperator
    expected: object | None = None
    on_missing: Literal["fail", "incomplete"] = "fail"

    @field_validator("operator", mode="before")
    @classmethod
    def normalize_yaml_boolean_operator(cls, value: object) -> object:
        if value is True:
            return "true"
        if value is False:
            return "false"
        return value

    @model_validator(mode="after")
    def validate_expected_value(self) -> "LiteratureAssertion":
        if self.operator in {"equals", "not_equals", "contains", "not_contains"}:
            if self.expected is None:
                raise ValueError(
                    f"Literature assertion {self.assertion_id} needs an expected value."
                )
        return self


class LiteratureClaim(BaseModel):
    claim_id: str = Field(pattern=r"^[a-z0-9_]+$")
    description: str
    coverage: LiteratureCoverage
    reproduction_class: LiteratureReproductionClass
    locator_ids: list[str] = Field(min_length=1)
    source_signature: list[str] = Field(min_length=1)
    target_signature: list[str] = Field(min_length=1)
    blinded_symbol_mappings: list[BlindedSymbolMapping] = Field(min_length=1)
    convention_transformations: list[ConventionTransformation] = Field(min_length=1)
    assertions: list[LiteratureAssertion] = Field(min_length=1)
    executable_regression_key: str | None = None
    executable_transform: ExecutableLiteratureTransform | None = None
    uncovered_terms: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_claim(self) -> "LiteratureClaim":
        tokens = [mapping.token for mapping in self.blinded_symbol_mappings]
        if len(tokens) != len(set(tokens)):
            raise ValueError(f"Blinded tokens must be unique in claim {self.claim_id}.")
        transformation_ids = [
            item.transformation_id for item in self.convention_transformations
        ]
        if len(transformation_ids) != len(set(transformation_ids)):
            raise ValueError(
                f"Convention transformation IDs must be unique in {self.claim_id}."
            )
        assertion_ids = [assertion.assertion_id for assertion in self.assertions]
        if len(assertion_ids) != len(set(assertion_ids)):
            raise ValueError(f"Assertion IDs must be unique in claim {self.claim_id}.")
        if self.coverage == "partial" and not self.uncovered_terms:
            raise ValueError(f"Partial claim {self.claim_id} must list uncovered terms.")
        class_by_coverage = {
            "exact": {
                "exact_coefficient",
                "exact_normalized",
                "boundary_conditioned_exact",
            },
            "structural": {"structural_alignment"},
            "partial": {"partial_alignment"},
        }
        if self.reproduction_class not in class_by_coverage[self.coverage]:
            raise ValueError(
                f"Claim {self.claim_id} has coverage={self.coverage!r} but "
                f"reproduction_class={self.reproduction_class!r}."
            )
        if self.coverage == "exact":
            if not self.executable_regression_key:
                raise ValueError(
                    f"Exact claim {self.claim_id} needs an executable regression key."
                )
            executable_assertion = any(
                assertion.source == "wolfram"
                and assertion.path == self.executable_regression_key
                and assertion.operator == "true"
                for assertion in self.assertions
            )
            if not executable_assertion:
                raise ValueError(
                    f"Exact claim {self.claim_id} must assert its Wolfram regression."
                )
            if self.uncovered_terms:
                raise ValueError(
                    f"Exact claim {self.claim_id} cannot declare uncovered terms."
                )
            if not self.executable_transform:
                raise ValueError(
                    f"Exact claim {self.claim_id} needs an executable transform contract."
                )
            if (
                self.executable_transform.equivalence_regression_key
                != self.executable_regression_key
            ):
                raise ValueError(
                    f"Exact claim {self.claim_id} has inconsistent executable regression keys."
                )
            asserted_paths = {
                (assertion.source, assertion.path, assertion.operator)
                for assertion in self.assertions
            }
            for expression_key in (
                self.executable_transform.source_expression_key,
                self.executable_transform.transformed_expression_key,
                self.executable_transform.target_expression_key,
            ):
                if ("wolfram", expression_key, "present") not in asserted_paths:
                    raise ValueError(
                        f"Exact claim {self.claim_id} must assert Wolfram key "
                        f"{expression_key!r} as present."
                    )
        return self


class LiteratureReproductionRecord(BaseModel):
    schema_version: str
    record_id: str = Field(pattern=r"^[a-z0-9_]+$")
    card_id: str
    case_id: str
    route_id: str
    claim_scope: str
    preparation: LiteraturePreparation
    locators: list[LiteratureSourceLocator] = Field(min_length=1)
    claims: list[LiteratureClaim] = Field(min_length=1)
    known_extensions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_record(self) -> "LiteratureReproductionRecord":
        locator_ids = [locator.locator_id for locator in self.locators]
        if len(locator_ids) != len(set(locator_ids)):
            raise ValueError(f"Locator IDs must be unique in {self.record_id}.")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError(f"Claim IDs must be unique in {self.record_id}.")
        known_locators = set(locator_ids)
        for claim in self.claims:
            unknown = set(claim.locator_ids) - known_locators
            if unknown:
                raise ValueError(
                    f"Claim {claim.claim_id} cites unknown locators: {sorted(unknown)}"
                )
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "LiteratureReproductionRecord":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


class LiteratureAssertionResult(BaseModel):
    assertion_id: str
    status: LiteratureStatus
    source: LiteratureSource
    path: str
    operator: LiteratureOperator
    actual: object | None = None
    expected: object | None = None
    detail: str


class LiteratureClaimResult(BaseModel):
    claim_id: str
    status: LiteratureStatus
    coverage: LiteratureCoverage
    reproduction_class: LiteratureReproductionClass
    locator_ids: list[str]
    assertions: list[LiteratureAssertionResult]
    executable_regression_key: str | None
    executable_transform: ExecutableLiteratureTransform | None
    uncovered_terms: list[str]


class LiteratureReproductionResult(BaseModel):
    record_id: str
    card_id: str
    case_id: str
    route_id: str
    status: LiteratureStatus
    independence_declared: bool
    locator_hashes_valid: bool
    claims: list[LiteratureClaimResult]
    known_extensions: list[str]
    limitations: list[str]


_MISSING = object()


def _get_path(source: dict[str, object], path: str) -> object:
    current: object = source
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _is_true(value: object) -> bool:
    return value is True or str(value).strip() == "True"


def _is_false(value: object) -> bool:
    return value is False or str(value).strip() == "False"


def _operator_passes(actual: object, assertion: LiteratureAssertion) -> bool:
    if assertion.operator == "equals":
        return actual == assertion.expected
    if assertion.operator == "not_equals":
        return actual != assertion.expected
    if assertion.operator == "contains":
        return (
            assertion.expected in actual
            if isinstance(actual, (str, list, dict))
            else False
        )
    if assertion.operator == "not_contains":
        return (
            assertion.expected not in actual
            if isinstance(actual, (str, list, dict))
            else True
        )
    if assertion.operator == "true":
        return _is_true(actual)
    if assertion.operator == "false":
        return _is_false(actual)
    return actual not in (None, "", [], {})


def _aggregate(statuses: list[LiteratureStatus]) -> LiteratureStatus:
    if "fail" in statuses:
        return "fail"
    if "incomplete" in statuses:
        return "incomplete"
    return "pass"


def evaluate_literature_record(
    record: LiteratureReproductionRecord,
    context: dict[str, dict[str, object]],
) -> LiteratureReproductionResult:
    claim_results: list[LiteratureClaimResult] = []
    for claim in record.claims:
        assertion_results: list[LiteratureAssertionResult] = []
        for assertion in claim.assertions:
            actual = _get_path(context[assertion.source], assertion.path)
            if actual is _MISSING:
                status: LiteratureStatus = assertion.on_missing
                detail = f"missing {assertion.source}.{assertion.path}"
                display_actual = None
            else:
                passed = _operator_passes(actual, assertion)
                status = "pass" if passed else "fail"
                detail = (
                    "literature-target assertion satisfied"
                    if passed
                    else "literature-target assertion violated"
                )
                display_actual = actual
            assertion_results.append(
                LiteratureAssertionResult(
                    assertion_id=assertion.assertion_id,
                    status=status,
                    source=assertion.source,
                    path=assertion.path,
                    operator=assertion.operator,
                    actual=display_actual,
                    expected=assertion.expected,
                    detail=detail,
                )
            )
        claim_results.append(
            LiteratureClaimResult(
                claim_id=claim.claim_id,
                status=_aggregate([result.status for result in assertion_results]),
                coverage=claim.coverage,
                reproduction_class=claim.reproduction_class,
                locator_ids=claim.locator_ids,
                assertions=assertion_results,
                executable_regression_key=claim.executable_regression_key,
                executable_transform=claim.executable_transform,
                uncovered_terms=claim.uncovered_terms,
            )
        )

    return LiteratureReproductionResult(
        record_id=record.record_id,
        card_id=record.card_id,
        case_id=record.case_id,
        route_id=record.route_id,
        status=_aggregate([claim.status for claim in claim_results]),
        independence_declared=record.preparation.created_without_project_gold,
        locator_hashes_valid=True,
        claims=claim_results,
        known_extensions=record.known_extensions,
        limitations=record.limitations,
    )
