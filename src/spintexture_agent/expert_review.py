from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .evidence import EvidenceCard, EvidenceRunResult, load_evidence_cards


PROJECT_ROOT = Path(__file__).resolve().parents[2]

ReviewDecisionStatus = Literal["pending", "approved", "revision_required", "rejected"]
CriterionVerdict = Literal["pending", "approved", "revision_required", "rejected"]

REVIEW_ATTESTATION = (
    "I reviewed the frozen evidence identified by this record and confirm that "
    "the decision, comments, and disclosed conflicts are my own."
)

REVIEW_CRITERIA: tuple[tuple[str, str], ...] = (
    (
        "model_and_order_parameter",
        "The material class, order parameter, constraints, and dynamics class are appropriate.",
    ),
    (
        "assumptions_and_validity",
        "The assumptions and validity limits are complete, visible, and physically defensible.",
    ),
    (
        "sign_and_coordinate_conventions",
        "Coordinate, topology, torque, gyrotropic, and sign conventions are internally consistent.",
    ),
    (
        "boundary_conditions",
        "Boundary conditions and discarded boundary terms are explicit and justified.",
    ),
    (
        "symbolic_derivation",
        "The generated and independent symbolic paths implement the declared derivation correctly.",
    ),
    (
        "terminal_equation",
        "The terminal collective-coordinate equation follows from the declared projections.",
    ),
    (
        "literature_alignment",
        "The result is consistent with the cited primary literature within the declared conventions.",
    ),
    (
        "literature_reproduction_scope",
        "Equation locators, blinded symbol mappings, convention transforms, and structural-versus-exact coverage labels support the bounded literature claims.",
    ),
    (
        "claim_scope",
        "The permitted claim and blocked claims match the actual evidence and limitations.",
    ),
)


class FrozenArtifact(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReviewCaseManifest(BaseModel):
    card_id: str
    case_id: str
    route_id: str
    claim_scope: str
    required_expertise: list[str]
    artifacts: dict[str, FrozenArtifact]


class ReviewPacketManifest(BaseModel):
    schema_version: str
    packet_id: str
    created_at: str
    evidence_run_root: str
    cases: list[ReviewCaseManifest]

    @model_validator(mode="after")
    def validate_cases(self) -> "ReviewPacketManifest":
        card_ids = [case.card_id for case in self.cases]
        if len(card_ids) != len(set(card_ids)):
            raise ValueError("Review packet card IDs must be unique.")
        return self


class ReviewerIdentity(BaseModel):
    name: str = ""
    affiliation: str = ""
    orcid: str | None = None
    independence: Literal["internal", "external"] | None = None
    qualified_for: list[str] = Field(default_factory=list)


class ConflictDisclosure(BaseModel):
    declared: bool = False
    details: str = ""


class ReviewCriterion(BaseModel):
    criterion_id: str
    prompt: str
    verdict: CriterionVerdict = "pending"
    comment: str = ""


class OpenQuestionResponse(BaseModel):
    question: str
    response: str = ""


class ReviewDecision(BaseModel):
    status: ReviewDecisionStatus = "pending"
    reviewed_at: str | None = None
    criteria: list[ReviewCriterion]
    open_question_responses: list[OpenQuestionResponse]
    required_revisions: list[str] = Field(default_factory=list)
    limitations_to_add: list[str] = Field(default_factory=list)


class ReviewSignature(BaseModel):
    method: Literal["typed_name"] = "typed_name"
    signed_name: str = ""
    signed_at: str | None = None
    attestation: str = REVIEW_ATTESTATION


class ExpertReviewRecord(BaseModel):
    schema_version: str
    review_id: str
    packet_manifest: str
    reviewed_evidence_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    card_id: str
    case_id: str
    route_id: str
    reviewer: ReviewerIdentity
    conflict_of_interest: ConflictDisclosure
    decision: ReviewDecision
    signature: ReviewSignature

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ExpertReviewRecord":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.model_validate(yaml.safe_load(handle))


class ReviewVerification(BaseModel):
    review_id: str
    card_id: str
    route_id: str
    status: ReviewDecisionStatus
    integrity_valid: bool
    eligible_for_expert_validation: bool
    reasons: list[str]
    record_path: str


class ReviewPacketResult(BaseModel):
    packet_dir: str
    manifest_path: str
    packet_path: str
    review_forms: list[str]


class ReviewPacketVerification(BaseModel):
    packet_id: str
    manifest_integrity_valid: bool
    all_records_integrity_valid: bool
    eligible_routes: list[str]
    reviews: list[ReviewVerification]
    report_json: str
    report_markdown: str


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else PROJECT_ROOT / value


def _stored_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen(path: str | Path) -> FrozenArtifact:
    resolved = _project_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Review artifact does not exist: {resolved}")
    return FrozenArtifact(path=_stored_path(resolved), sha256=_sha256(resolved))


def _read_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _case_artifacts(
    card_path: Path,
    card: EvidenceCard,
    evidence_result_path: Path,
    run: EvidenceRunResult,
) -> dict[str, FrozenArtifact]:
    generated_record = _project_path(run.generated_record)
    record = _read_json(generated_record)
    artifact_contract = record.get("artifact_contract", {})
    if not isinstance(artifact_contract, dict):
        raise ValueError(f"Generated record has no artifact contract: {generated_record}")

    artifacts: dict[str, FrozenArtifact] = {
        "evidence_card": _frozen(card_path),
        "generated_config": _frozen(card.generated_config),
        "benchmark_case": _frozen(card.benchmark_case),
        "gold_derivation_doc": _frozen(card.gold_derivation_doc),
        "independent_gold_script": _frozen(card.independent_gold_script),
        "evidence_result": _frozen(evidence_result_path),
        "generated_record": _frozen(generated_record),
    }
    from .capabilities import CapabilityRegistry

    route = next(
        (
            item
            for item in CapabilityRegistry().routes
            if item.route_id == card.route_id
        ),
        None,
    )
    if route is None:
        raise ValueError(f"No capability route registered for review: {card.route_id}")
    if route.evidence.machine_audit_spec:
        artifacts["machine_audit_spec"] = _frozen(
            route.evidence.machine_audit_spec
        )
    if route.evidence.literature_reproduction_record:
        artifacts["literature_reproduction_record"] = _frozen(
            route.evidence.literature_reproduction_record
        )
    for key, label in (
        ("wolfram_script", "generated_wolfram_script"),
        ("human_report", "generated_human_report"),
    ):
        value = artifact_contract.get(key)
        if not isinstance(value, str):
            raise ValueError(f"Generated record is missing artifact_contract.{key}")
        artifacts[label] = _frozen(value)
    if not run.gold_result:
        raise ValueError(f"Evidence run has no independent gold result: {card.card_id}")
    artifacts["independent_gold_result"] = _frozen(run.gold_result)
    return artifacts


def _review_form(
    card: EvidenceCard,
    manifest_path: Path,
    manifest_sha256: str,
) -> ExpertReviewRecord:
    return ExpertReviewRecord(
        schema_version="1.0.0",
        review_id=f"{card.card_id}_review_01",
        packet_manifest=_stored_path(manifest_path),
        reviewed_evidence_manifest_sha256=manifest_sha256,
        card_id=card.card_id,
        case_id=card.case_id,
        route_id=card.route_id,
        reviewer=ReviewerIdentity(),
        conflict_of_interest=ConflictDisclosure(),
        decision=ReviewDecision(
            criteria=[
                ReviewCriterion(criterion_id=criterion_id, prompt=prompt)
                for criterion_id, prompt in REVIEW_CRITERIA
            ],
            open_question_responses=[
                OpenQuestionResponse(question=question)
                for question in card.expert_review.open_questions
            ],
        ),
        signature=ReviewSignature(),
    )


def _render_packet(
    manifest: ReviewPacketManifest,
    cards: dict[str, EvidenceCard],
    manifest_sha256: str,
) -> str:
    lines = [
        "# Core-three expert review packet",
        "",
        f"- Packet: `{manifest.packet_id}`",
        f"- Created: `{manifest.created_at}`",
        f"- Manifest SHA-256: `{manifest_sha256}`",
        "- Current lifecycle target: `expert_validated`",
        "- Signature method: typed-name attestation; this is auditable but not cryptographic identity proof.",
        "",
        "## Reviewer instructions",
        "",
        "1. Inspect every frozen artifact listed for the assigned case.",
        "2. Fill reviewer identity, independence, and qualified expertise in the YAML review form.",
        "3. Set every criterion verdict and answer every open question.",
        "4. Select `approved`, `revision_required`, or `rejected` and record an ISO-8601 review time.",
        "5. Type the same reviewer name in `signature.signed_name` and add the signing time.",
        "6. For an additional reviewer, duplicate the case form with the next `_review_NN.yaml` suffix and use a unique `review_id`.",
        "7. Run `python -m spintexture_agent.cli expert-review verify --packet <packet-dir>`.",
        "",
        "An approval does not change the capability registry automatically. It only makes the route eligible for a separately reviewed lifecycle promotion.",
        "",
        "## Cases",
        "",
    ]
    for case in manifest.cases:
        card = cards[case.card_id]
        lines.extend(
            [
                f"### {case.case_id}: `{case.route_id}`",
                "",
                card.claim_scope,
                "",
                "Required expertise:",
                "",
                *[f"- {item}" for item in case.required_expertise],
                "",
                "Assumptions:",
                "",
                *[f"- `{item}`" for item in card.assumptions],
                "",
                "Declared comparisons:",
                "",
                "| Check | Category | Comparison |",
                "| --- | --- | --- |",
                *[
                    f"| `{check.check_id}` | `{check.category}` | `{check.comparison}` |"
                    for check in card.checks
                ],
                "",
                "Open questions:",
                "",
                *[f"- {question}" for question in card.expert_review.open_questions],
                "",
                "Frozen artifacts:",
                "",
                *[
                    f"- `{label}`: `{artifact.path}` (`{artifact.sha256}`)"
                    for label, artifact in case.artifacts.items()
                ],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def generate_review_packet(
    cards_path: str | Path,
    evidence_run_root: str | Path,
    out_dir: str | Path,
) -> ReviewPacketResult:
    cards_with_paths = load_evidence_cards(cards_path)
    evidence_root = _project_path(evidence_run_root)
    packet_dir = _project_path(out_dir)
    if packet_dir.exists():
        raise FileExistsError(
            f"Review packet directory already exists: {packet_dir}. Use a new path to avoid overwriting reviews."
        )
    reviews_dir = packet_dir / "reviews"
    reviews_dir.mkdir(parents=True)

    cases: list[ReviewCaseManifest] = []
    cards_by_id: dict[str, EvidenceCard] = {}
    for card_path, card in cards_with_paths:
        evidence_result_path = evidence_root / card.card_id / "evidence_result.json"
        if not evidence_result_path.is_file():
            raise FileNotFoundError(
                f"Evidence result is missing for {card.card_id}: {evidence_result_path}"
            )
        run = EvidenceRunResult.model_validate(_read_json(evidence_result_path))
        if run.card_id != card.card_id or run.route_id != card.route_id:
            raise ValueError(f"Evidence result identity mismatch for {card.card_id}.")
        if not run.passed:
            raise ValueError(f"Cannot review a failed evidence run: {card.card_id}")
        expected_check_ids = {check.check_id for check in card.checks}
        actual_check_ids = {check.check_id for check in run.checks}
        if actual_check_ids != expected_check_ids or not all(
            check.passed for check in run.checks
        ):
            raise ValueError(
                f"Evidence result does not contain a complete passing check set: {card.card_id}"
            )
        cards_by_id[card.card_id] = card
        cases.append(
            ReviewCaseManifest(
                card_id=card.card_id,
                case_id=card.case_id,
                route_id=card.route_id,
                claim_scope=card.claim_scope,
                required_expertise=card.expert_review.required_expertise,
                artifacts=_case_artifacts(card_path, card, evidence_result_path, run),
            )
        )

    manifest = ReviewPacketManifest(
        schema_version="1.0.0",
        packet_id="core3_expert_review_packet",
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        evidence_run_root=_stored_path(evidence_root),
        cases=cases,
    )
    manifest_path = packet_dir / "packet_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_sha256 = _sha256(manifest_path)

    review_forms: list[str] = []
    for _, card in cards_with_paths:
        form = _review_form(card, manifest_path, manifest_sha256)
        form_path = reviews_dir / f"{card.card_id}_review_01.yaml"
        form_path.write_text(
            yaml.safe_dump(
                form.model_dump(mode="json"),
                sort_keys=False,
                allow_unicode=False,
                width=100,
            ),
            encoding="utf-8",
        )
        review_forms.append(str(form_path))

    packet_path = packet_dir / "CORE3_EXPERT_REVIEW_PACKET.md"
    packet_path.write_text(
        _render_packet(manifest, cards_by_id, manifest_sha256), encoding="utf-8"
    )
    return ReviewPacketResult(
        packet_dir=str(packet_dir),
        manifest_path=str(manifest_path),
        packet_path=str(packet_path),
        review_forms=review_forms,
    )


def _parse_timestamp(value: str | None, label: str, reasons: list[str]) -> datetime | None:
    if not value:
        reasons.append(f"{label} is required")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        reasons.append(f"{label} must be ISO-8601")
        return None
    if parsed.tzinfo is None:
        reasons.append(f"{label} must include a timezone")
        return None
    return parsed


def _verify_artifacts(case: ReviewCaseManifest, reasons: list[str]) -> bool:
    valid = True
    for label, artifact in case.artifacts.items():
        path = _project_path(artifact.path)
        if not path.is_file():
            reasons.append(f"frozen artifact missing: {label}")
            valid = False
        elif _sha256(path) != artifact.sha256:
            reasons.append(f"frozen artifact hash mismatch: {label}")
            valid = False
    return valid


def verify_review_record(
    review_path: str | Path,
    manifest_path: str | Path | None = None,
) -> ReviewVerification:
    resolved_review = _project_path(review_path)
    record = ExpertReviewRecord.from_yaml(resolved_review)
    resolved_manifest = _project_path(manifest_path or record.packet_manifest)
    manifest = ReviewPacketManifest.model_validate(_read_json(resolved_manifest))
    reasons: list[str] = []

    manifest_hash = _sha256(resolved_manifest)
    manifest_integrity = manifest_hash == record.reviewed_evidence_manifest_sha256
    if not manifest_integrity:
        reasons.append("packet manifest hash mismatch")

    case = next((item for item in manifest.cases if item.card_id == record.card_id), None)
    if case is None:
        reasons.append("review card is not present in the packet manifest")
        artifact_integrity = False
    else:
        if case.case_id != record.case_id or case.route_id != record.route_id:
            reasons.append("review identity does not match the packet manifest")
        artifact_integrity = _verify_artifacts(case, reasons)

    integrity_valid = manifest_integrity and artifact_integrity and not any(
        "identity does not match" in reason for reason in reasons
    )
    if record.decision.status == "pending":
        reasons.append("expert decision is pending")
    elif record.decision.status != "approved":
        reasons.append(f"expert decision is {record.decision.status}")

    if record.decision.status == "approved" and case is not None:
        if not record.reviewer.name.strip():
            reasons.append("reviewer name is required")
        if not record.reviewer.affiliation.strip():
            reasons.append("reviewer affiliation is required")
        if record.reviewer.independence is None:
            reasons.append("reviewer independence must be declared")
        missing_expertise = sorted(
            set(case.required_expertise) - set(record.reviewer.qualified_for)
        )
        if missing_expertise:
            reasons.append(f"reviewer qualification missing: {', '.join(missing_expertise)}")
        if record.conflict_of_interest.declared:
            reasons.append("declared conflict of interest blocks automatic promotion")

        expected_criteria = {criterion_id for criterion_id, _ in REVIEW_CRITERIA}
        actual_criteria = {criterion.criterion_id for criterion in record.decision.criteria}
        if actual_criteria != expected_criteria:
            reasons.append("review criteria do not match the required set")
        for criterion in record.decision.criteria:
            if criterion.verdict != "approved":
                reasons.append(f"criterion not approved: {criterion.criterion_id}")

        expected_questions = {
            response.question for response in record.decision.open_question_responses
        }
        card_path = _project_path(case.artifacts["evidence_card"].path)
        card = EvidenceCard.from_yaml(card_path)
        if expected_questions != set(card.expert_review.open_questions):
            reasons.append("open-question set does not match the Evidence Card")
        for response in record.decision.open_question_responses:
            if not response.response.strip():
                reasons.append(f"open question is unanswered: {response.question}")
        if record.decision.required_revisions:
            reasons.append("approved review cannot retain required revisions")

        reviewed_at = _parse_timestamp(
            record.decision.reviewed_at, "decision.reviewed_at", reasons
        )
        signed_at = _parse_timestamp(record.signature.signed_at, "signature.signed_at", reasons)
        if reviewed_at and signed_at and signed_at < reviewed_at:
            reasons.append("signature time precedes review time")
        if record.signature.signed_name.strip() != record.reviewer.name.strip():
            reasons.append("signature name does not match reviewer name")
        if record.signature.attestation != REVIEW_ATTESTATION:
            reasons.append("signature attestation text was changed")

    eligible = integrity_valid and record.decision.status == "approved" and not reasons
    return ReviewVerification(
        review_id=record.review_id,
        card_id=record.card_id,
        route_id=record.route_id,
        status=record.decision.status,
        integrity_valid=integrity_valid,
        eligible_for_expert_validation=eligible,
        reasons=reasons,
        record_path=str(resolved_review),
    )


def _render_verification(result: ReviewPacketVerification) -> str:
    lines = [
        "# Expert review verification",
        "",
        f"- Packet: `{result.packet_id}`",
        f"- Manifest integrity: `{'pass' if result.manifest_integrity_valid else 'fail'}`",
        f"- Record integrity: `{'pass' if result.all_records_integrity_valid else 'fail'}`",
        f"- Eligible routes: {len(result.eligible_routes)}",
        "",
        "| Review | Route | Decision | Integrity | Eligible | Reasons |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for review in result.reviews:
        reasons = "; ".join(review.reasons) or "None"
        lines.append(
            f"| `{review.review_id}` | `{review.route_id}` | `{review.status}` | "
            f"`{'pass' if review.integrity_valid else 'fail'}` | "
            f"`{'yes' if review.eligible_for_expert_validation else 'no'}` | {reasons} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def verify_review_packet(packet_dir: str | Path) -> ReviewPacketVerification:
    resolved_packet = _project_path(packet_dir)
    manifest_path = resolved_packet / "packet_manifest.json"
    manifest = ReviewPacketManifest.model_validate(_read_json(manifest_path))
    reviews: list[ReviewVerification] = []
    for case in manifest.cases:
        review_paths = sorted(
            (resolved_packet / "reviews").glob(f"{case.card_id}_review_*.yaml")
        )
        legacy_review_path = (
            resolved_packet / "reviews" / f"{case.card_id}_review.yaml"
        )
        if legacy_review_path.is_file():
            review_paths.insert(0, legacy_review_path)
        if not review_paths:
            reviews.append(
                ReviewVerification(
                    review_id=f"{case.card_id}_review_missing",
                    card_id=case.card_id,
                    route_id=case.route_id,
                    status="pending",
                    integrity_valid=False,
                    eligible_for_expert_validation=False,
                    reasons=["review record is missing"],
                    record_path=str(
                        resolved_packet / "reviews" / f"{case.card_id}_review_01.yaml"
                    ),
                )
            )
        else:
            reviews.extend(
                verify_review_record(review_path, manifest_path)
                for review_path in review_paths
            )

    present_records = [item for item in reviews if Path(item.record_path).is_file()]
    reviewed_card_ids = {item.card_id for item in reviews if Path(item.record_path).is_file()}
    manifest_integrity = reviewed_card_ids == {
        case.card_id for case in manifest.cases
    } and all(
        review.reviewed_evidence_manifest_sha256 == _sha256(manifest_path)
        for review in (
            ExpertReviewRecord.from_yaml(item.record_path) for item in present_records
        )
    )
    report_json = resolved_packet / "review_verification.json"
    report_markdown = resolved_packet / "review_verification.md"
    result = ReviewPacketVerification(
        packet_id=manifest.packet_id,
        manifest_integrity_valid=manifest_integrity,
        all_records_integrity_valid=all(review.integrity_valid for review in reviews),
        eligible_routes=sorted(
            {
                review.route_id
                for review in reviews
                if review.eligible_for_expert_validation
            }
        ),
        reviews=reviews,
        report_json=str(report_json),
        report_markdown=str(report_markdown),
    )
    report_json.write_text(
        json.dumps(result.model_dump(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    report_markdown.write_text(_render_verification(result), encoding="utf-8")
    return result


def copy_approved_review_record(review_path: str | Path, destination: str | Path) -> Path:
    verification = verify_review_record(review_path)
    if not verification.eligible_for_expert_validation:
        raise ValueError(
            "Review is not eligible for expert validation: " + "; ".join(verification.reasons)
        )
    destination_dir = _project_path(destination)
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / Path(review_path).name
    if target.exists():
        raise FileExistsError(f"Approved review record already exists: {target}")
    shutil.copy2(_project_path(review_path), target)
    return target
