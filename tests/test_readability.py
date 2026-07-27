import hashlib
import json
from pathlib import Path

import pytest
import yaml

from spintexture_agent.cli import build_parser
from spintexture_agent.readability import (
    ADJUDICATION_ATTESTATION,
    RATING_ATTESTATION,
    READABILITY_SCHEMA_VERSION,
    RUBRIC_DEFINITIONS,
    AdjudicationSignature,
    CriterionRating,
    CriterionResolution,
    FrozenStudyArtifact,
    RatingSignature,
    RaterProfile,
    ReadabilityAdjudicationRecord,
    ReadabilityRatingRecord,
    ReadabilityStudyCase,
    ReadabilityStudyManifest,
    default_readability_rubric,
    evaluate_readability_study,
    generate_readability_packet,
    run_readability_study,
)


TIMESTAMP = "2026-07-26T13:00:00+08:00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload) -> None:
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _study_with_case(tmp_path: Path) -> Path:
    study_dir = tmp_path / "study"
    generate_readability_packet(study_dir)
    record_id = "stta-readability-test"
    record_path = study_dir / "views" / "record.json"
    report_path = study_dir / "views" / "layered_report.md"
    accessible_path = study_dir / "views" / "accessible_view.md"
    formal_path = study_dir / "views" / "formal_reference.md"
    record_path.write_text(
        json.dumps(
            {
                "record_id": record_id,
                "physics_ir": {
                    "support_level": "full_derivation",
                    "dynamics": {"expected_equation_type": "thiele_equation"},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    accessible = """## Accessible view

The rigid texture follows a first-order collective equation under the stated assumptions.
"""
    formal = """## Formal view

G cross Rdot + alpha D Rdot = F under the rigid-texture approximation.

## Assumptions and validity

- rigid texture
- fixed helicity
"""
    report_path.write_text(
        f"# Test report\n\n- Authoritative record ID: `{record_id}`\n\n{accessible}{formal}",
        encoding="utf-8",
    )
    accessible_path.write_text(accessible, encoding="utf-8")
    formal_path.write_text(formal, encoding="utf-8")

    manifest_path = study_dir / "study_manifest.yaml"
    payload = _load_yaml(manifest_path)
    payload["study_status"] = "frozen"
    payload["cases"] = [
        ReadabilityStudyCase(
            case_id="R1_test_explanation",
            blind_response_id="response_017",
            audience="experimental magnetism researcher",
            record_id=record_id,
            authoritative_record=FrozenStudyArtifact(
                path=str(record_path.relative_to(study_dir)), sha256=_sha256(record_path)
            ),
            layered_report=FrozenStudyArtifact(
                path=str(report_path.relative_to(study_dir)), sha256=_sha256(report_path)
            ),
            accessible_view=FrozenStudyArtifact(
                path=str(accessible_path.relative_to(study_dir)),
                sha256=_sha256(accessible_path),
            ),
            formal_reference=FrozenStudyArtifact(
                path=str(formal_path.relative_to(study_dir)), sha256=_sha256(formal_path)
            ),
        ).model_dump(mode="json")
    ]
    _write_yaml(manifest_path, payload)
    return study_dir


def _profile(rater_id: str, **changes) -> RaterProfile:
    payload = {
        "rater_id": rater_id,
        "role": "experimental magnetism researcher",
        "affiliation": "Independent Laboratory",
        "target_audience_match": True,
        "independent_of_system_development": True,
        "involved_in_response_generation": False,
        "method_identity_seen": False,
        "conflict_declared": False,
        "conflict_details": "",
    }
    payload.update(changes)
    return RaterProfile.model_validate(payload)


def _add_rating(
    study_dir: Path,
    rater_id: str,
    scores: dict[str, int] | None = None,
    omissions: set[str] | None = None,
    profile_changes: dict | None = None,
    status: str = "complete",
) -> Path:
    scores = scores or {str(item["criterion_id"]): 5 for item in RUBRIC_DEFINITIONS}
    omissions = omissions or set()
    manifest_path = study_dir / "study_manifest.yaml"
    manifest = ReadabilityStudyManifest.model_validate(_load_yaml(manifest_path))
    criteria = []
    for item in RUBRIC_DEFINITIONS:
        criterion_id = str(item["criterion_id"])
        omitted = criterion_id in omissions
        score = scores[criterion_id] if status == "complete" else None
        criteria.append(
            CriterionRating(
                criterion_id=criterion_id,
                score=score,
                critical_omission=omitted if status == "complete" else None,
                comment="Critical physics content is omitted." if omitted else "",
            )
        )
    rating = ReadabilityRatingRecord(
        schema_version=READABILITY_SCHEMA_VERSION,
        rating_id=f"rating_{rater_id}",
        study_id=manifest.study_id,
        study_manifest_sha256=_sha256(manifest_path),
        case_id=manifest.cases[0].case_id,
        blind_response_id=manifest.cases[0].blind_response_id,
        status=status,
        rater=_profile(rater_id, **(profile_changes or {})),
        criteria=criteria,
        completed_at=TIMESTAMP if status == "complete" else None,
        signature=RatingSignature(
            signed_by=rater_id if status == "complete" else "",
            signed_at=TIMESTAMP if status == "complete" else None,
            attestation=RATING_ATTESTATION,
        ),
    )
    path = study_dir / "ratings" / f"{rating.rating_id}.yaml"
    _write_yaml(path, rating)
    return path


def _add_adjudication(study_dir: Path, final_formula_score: int = 4) -> Path:
    manifest_path = study_dir / "study_manifest.yaml"
    manifest = ReadabilityStudyManifest.model_validate(_load_yaml(manifest_path))
    resolutions = []
    for item in RUBRIC_DEFINITIONS:
        criterion_id = str(item["criterion_id"])
        resolutions.append(
            CriterionResolution(
                criterion_id=criterion_id,
                final_score=(
                    final_formula_score if criterion_id == "formula_fidelity" else 5
                ),
                critical_omission_confirmed=False,
                rationale="Resolved against the frozen formal reference.",
            )
        )
    adjudication = ReadabilityAdjudicationRecord(
        schema_version=READABILITY_SCHEMA_VERSION,
        adjudication_id="adjudication_01",
        study_id=manifest.study_id,
        study_manifest_sha256=_sha256(manifest_path),
        case_id=manifest.cases[0].case_id,
        blind_response_id=manifest.cases[0].blind_response_id,
        status="complete",
        adjudicator=_profile("adjudicator_01"),
        resolutions=resolutions,
        completed_at=TIMESTAMP,
        signature=AdjudicationSignature(
            signed_by="adjudicator_01",
            signed_at=TIMESTAMP,
            attestation=ADJUDICATION_ATTESTATION,
        ),
    )
    path = study_dir / "adjudications" / "adjudication_01.yaml"
    _write_yaml(path, adjudication)
    return path


def test_empty_readability_packet_has_valid_frozen_rubric_and_forms(tmp_path):
    packet = generate_readability_packet(tmp_path / "study")
    study_dir = Path(packet.study_dir)
    rubric = default_readability_rubric()
    manifest = ReadabilityStudyManifest.model_validate(
        _load_yaml(Path(packet.manifest_path))
    )

    assert manifest.study_status == "template"
    assert manifest.cases == []
    assert _sha256(Path(packet.rubric_path)) == manifest.rubric.sha256
    assert [item.criterion_id for item in rubric.criteria] == [
        "formula_fidelity",
        "assumptions_and_validity",
        "warning_and_certainty_preservation",
        "symbol_clarity",
        "task_comprehension",
    ]
    ReadabilityRatingRecord.model_validate(
        _load_yaml(study_dir / "forms" / "rating_form_template.yaml")
    )
    ReadabilityAdjudicationRecord.model_validate(
        _load_yaml(study_dir / "forms" / "adjudication_form_template.yaml")
    )

    result = evaluate_readability_study(study_dir)
    assert result.status == "missing"
    assert result.case_count == 0


def test_readability_packet_is_non_overwriting(tmp_path):
    study_dir = tmp_path / "study"
    generate_readability_packet(study_dir)

    with pytest.raises(FileExistsError, match="never overwritten"):
        generate_readability_packet(study_dir)


def test_case_with_no_ratings_is_missing(tmp_path):
    result = evaluate_readability_study(_study_with_case(tmp_path))

    assert result.status == "missing"
    assert result.cases[0].status == "missing"


def test_case_with_one_complete_rating_is_incomplete(tmp_path):
    study_dir = _study_with_case(tmp_path)
    _add_rating(study_dir, "rater_01")
    result = evaluate_readability_study(study_dir)

    assert result.status == "incomplete"
    assert result.cases[0].eligible_rater_count == 1
    assert "requires at least 2 eligible independent raters" in result.cases[0].issues


def test_two_independent_raters_produce_pass_and_uncertainty(tmp_path):
    study_dir = _study_with_case(tmp_path)
    scores_1 = {str(item["criterion_id"]): 4 for item in RUBRIC_DEFINITIONS}
    scores_2 = {str(item["criterion_id"]): 5 for item in RUBRIC_DEFINITIONS}
    _add_rating(study_dir, "rater_01", scores=scores_1)
    _add_rating(study_dir, "rater_02", scores=scores_2)
    result = evaluate_readability_study(study_dir)

    assert result.status == "passed"
    case = result.cases[0]
    assert case.status == "passed"
    formula = next(item for item in case.criteria if item.criterion_id == "formula_fidelity")
    assert formula.mean_score == 4.5
    assert formula.standard_error > 0
    assert formula.approximate_ci95_low < formula.mean_score
    assert formula.passed


def test_critical_omission_cannot_be_averaged_away_by_high_style_scores(tmp_path):
    study_dir = _study_with_case(tmp_path)
    omissions = {"formula_fidelity"}
    _add_rating(study_dir, "rater_01", omissions=omissions)
    _add_rating(study_dir, "rater_02", omissions=omissions)
    result = evaluate_readability_study(study_dir)

    assert result.status == "failed"
    formula = next(
        item for item in result.cases[0].criteria if item.criterion_id == "formula_fidelity"
    )
    clarity = next(
        item for item in result.cases[0].criteria if item.criterion_id == "symbol_clarity"
    )
    assert formula.mean_score == 5
    assert not formula.passed
    assert clarity.passed


def test_large_rater_disagreement_requires_adjudication(tmp_path):
    study_dir = _study_with_case(tmp_path)
    low = {str(item["criterion_id"]): 5 for item in RUBRIC_DEFINITIONS}
    low["formula_fidelity"] = 3
    _add_rating(study_dir, "rater_01", scores=low)
    _add_rating(study_dir, "rater_02")
    result = evaluate_readability_study(study_dir)

    assert result.status == "needs_adjudication"
    assert result.cases[0].adjudication_status == "missing"


def test_blinded_adjudication_resolves_disagreement_without_erasing_uncertainty(tmp_path):
    study_dir = _study_with_case(tmp_path)
    low = {str(item["criterion_id"]): 5 for item in RUBRIC_DEFINITIONS}
    low["formula_fidelity"] = 3
    _add_rating(study_dir, "rater_01", scores=low)
    _add_rating(study_dir, "rater_02")
    _add_adjudication(study_dir, final_formula_score=4)
    result = evaluate_readability_study(study_dir)

    assert result.status == "passed"
    assert result.cases[0].adjudication_status == "complete"
    formula = next(
        item for item in result.cases[0].criteria if item.criterion_id == "formula_fidelity"
    )
    assert formula.score_range == 2
    assert formula.disagreement
    assert formula.final_score == 4


def test_conflicted_or_unblinded_rater_is_excluded(tmp_path):
    study_dir = _study_with_case(tmp_path)
    _add_rating(study_dir, "rater_01")
    _add_rating(
        study_dir,
        "rater_02",
        profile_changes={"method_identity_seen": True, "conflict_declared": True},
    )
    result = evaluate_readability_study(study_dir)

    assert result.status == "incomplete"
    case = result.cases[0]
    assert case.eligible_rater_count == 1
    assert "rating_rater_02" in case.excluded_ratings
    assert "rater saw the method identity" in case.excluded_ratings["rating_rater_02"]


def test_tampered_accessible_view_makes_case_incomplete(tmp_path):
    study_dir = _study_with_case(tmp_path)
    _add_rating(study_dir, "rater_01")
    _add_rating(study_dir, "rater_02")
    (study_dir / "views" / "accessible_view.md").write_text(
        "## Accessible view\n\nTampered content.\n", encoding="utf-8"
    )
    result = evaluate_readability_study(study_dir)

    assert result.status == "incomplete"
    assert any("SHA-256 mismatch" in issue for issue in result.cases[0].issues)


def test_complete_rating_requires_exact_frozen_criteria():
    payload = {
        "schema_version": READABILITY_SCHEMA_VERSION,
        "rating_id": "invalid_rating",
        "study_id": "study",
        "study_manifest_sha256": "0" * 64,
        "case_id": "case",
        "blind_response_id": "blind",
        "status": "complete",
        "rater": _profile("rater_01").model_dump(),
        "criteria": [
            {
                "criterion_id": "symbol_clarity",
                "score": 5,
                "critical_omission": False,
                "comment": "",
            }
        ],
        "completed_at": TIMESTAMP,
        "signature": {
            "signed_by": "rater_01",
            "signed_at": TIMESTAMP,
            "attestation": RATING_ATTESTATION,
        },
    }

    with pytest.raises(ValueError, match="exactly the frozen rubric criteria"):
        ReadabilityRatingRecord.model_validate(payload)


def test_readability_run_writes_machine_and_human_reports(tmp_path):
    study_dir = _study_with_case(tmp_path)
    _add_rating(study_dir, "rater_01")
    _add_rating(study_dir, "rater_02")
    result = run_readability_study(study_dir, tmp_path / "results")

    assert result.status == "passed"
    assert (tmp_path / "results" / "readability_scores.json").exists()
    assert (tmp_path / "results" / "readability_scores.md").exists()


def test_cli_registers_readability_packet_and_score_commands():
    parser = build_parser()
    packet_args = parser.parse_args(["readability", "packet"])
    score_args = parser.parse_args(["readability", "score", "--study", "study"])

    assert packet_args.func.__name__ == "cmd_readability_packet"
    assert score_args.func.__name__ == "cmd_readability_score"
