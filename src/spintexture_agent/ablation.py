from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .evaluator import CaseScore, DimensionScore, evaluate_benchmark_cases, summarize_dimensions
from .generator import PROJECT_ROOT


DEFAULT_PROFILES_DIR = PROJECT_ROOT / "ablation_profiles"
DEFAULT_ABLATION_DIR = PROJECT_ROOT / "analysis" / "ablation_runs"
DEFAULT_ABLATION_BUNDLE_DIR = PROJECT_ROOT / "outputs" / "ablation_runs"


@dataclass(frozen=True)
class AblationProfile:
    profile_id: str
    description: str
    disabled_dimensions: list[str]
    expected_failure_cases: list[str]


@dataclass(frozen=True)
class AblationCaseScore:
    case_id: str
    score: int
    max_score: int
    passed: bool
    dimensions: list[DimensionScore]

    def to_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "score": self.score,
            "max_score": self.max_score,
            "passed": self.passed,
            "dimensions": [dimension.to_record() for dimension in self.dimensions],
        }


@dataclass(frozen=True)
class AblationProfileScore:
    profile: AblationProfile
    cases: list[AblationCaseScore]

    @property
    def passed_cases(self) -> int:
        return sum(1 for case in self.cases if case.passed)

    @property
    def total_score(self) -> int:
        return sum(case.score for case in self.cases)

    @property
    def max_score(self) -> int:
        return sum(case.max_score for case in self.cases)

    @property
    def score_rate(self) -> float:
        return self.total_score / self.max_score if self.max_score else 0.0

    @property
    def case_pass_rate(self) -> float:
        return self.passed_cases / len(self.cases) if self.cases else 0.0

    def to_record(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile.profile_id,
            "description": self.profile.description,
            "disabled_dimensions": self.profile.disabled_dimensions,
            "expected_failure_cases": self.profile.expected_failure_cases,
            "passed_cases": self.passed_cases,
            "case_count": len(self.cases),
            "total_score": self.total_score,
            "max_score": self.max_score,
            "score_rate": self.score_rate,
            "case_pass_rate": self.case_pass_rate,
            "cases": [case.to_record() for case in self.cases],
        }


@dataclass(frozen=True)
class AblationRun:
    profiles: list[AblationProfileScore]
    csv_path: Path
    json_path: Path
    notes_path: Path

    def to_record(self) -> dict[str, Any]:
        return {
            "summary": {
                "profile_count": len(self.profiles),
                "profiles": [
                    {
                        "profile_id": profile.profile.profile_id,
                        "score_rate": profile.score_rate,
                        "case_pass_rate": profile.case_pass_rate,
                    }
                    for profile in self.profiles
                ],
            },
            "profiles": [profile.to_record() for profile in self.profiles],
        }


def _project_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Ablation profile must be a mapping: {path}")
    return data


def load_ablation_profiles(profiles_dir: str | Path = DEFAULT_PROFILES_DIR) -> list[AblationProfile]:
    profiles = []
    for path in sorted(_project_path(profiles_dir).glob("*.yaml")):
        data = _load_yaml(path)
        profiles.append(
            AblationProfile(
                profile_id=str(data["profile_id"]),
                description=str(data.get("description", "")),
                disabled_dimensions=list(data.get("disabled_dimensions", [])),
                expected_failure_cases=list(data.get("expected_failure_cases", [])),
            )
        )
    preferred = {
        "full": 0,
        "no_physics_ir": 1,
        "no_validator": 2,
        "no_negative_checks": 3,
        "no_gold_answer": 4,
        "no_wolfram_execution": 5,
        "no_result_key_check": 6,
        "no_physics_structure_check": 7,
    }
    return sorted(profiles, key=lambda profile: preferred.get(profile.profile_id, 100))


def _apply_profile_to_case(case: CaseScore, profile: AblationProfile) -> AblationCaseScore:
    disabled = set(profile.disabled_dimensions)
    affected_cases = set(profile.expected_failure_cases)
    affected = not affected_cases or case.case_id in affected_cases
    dimensions: list[DimensionScore] = []
    for dimension in case.dimensions:
        if affected and dimension.applicable and dimension.name in disabled:
            dimensions.append(
                DimensionScore(
                    name=dimension.name,
                    passed=False,
                    detail=(
                        f"ablated by {profile.profile_id}; original_passed={dimension.passed}; "
                        f"original_detail={dimension.detail}"
                    ),
                )
            )
        else:
            dimensions.append(dimension)

    expected_failure = case.case_id in affected_cases
    dimensions.append(
        DimensionScore(
            name="profile_expected_failure",
            passed=not expected_failure,
            detail=(
                "simulated profile failure"
                if expected_failure
                else "no expected failure for this profile"
            ),
        )
    )
    score, max_score = summarize_dimensions(dimensions)
    return AblationCaseScore(
        case_id=case.case_id,
        score=score,
        max_score=max_score,
        passed=score == max_score,
        dimensions=dimensions,
    )


def _score_profile(cases: list[CaseScore], profile: AblationProfile) -> AblationProfileScore:
    return AblationProfileScore(
        profile=profile,
        cases=[_apply_profile_to_case(case, profile) for case in cases],
    )


def _write_csv(path: Path, profiles: list[AblationProfileScore]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "profile_id",
                "passed_cases",
                "case_count",
                "case_pass_rate",
                "total_score",
                "max_score",
                "score_rate",
                "disabled_dimensions",
                "expected_failure_cases",
            ],
        )
        writer.writeheader()
        for profile in profiles:
            writer.writerow(
                {
                    "profile_id": profile.profile.profile_id,
                    "passed_cases": profile.passed_cases,
                    "case_count": len(profile.cases),
                    "case_pass_rate": f"{profile.case_pass_rate:.6f}",
                    "total_score": profile.total_score,
                    "max_score": profile.max_score,
                    "score_rate": f"{profile.score_rate:.6f}",
                    "disabled_dimensions": ";".join(profile.profile.disabled_dimensions),
                    "expected_failure_cases": ";".join(profile.profile.expected_failure_cases),
                }
            )


def _write_notes(path: Path, profiles: list[AblationProfileScore]) -> None:
    lines = [
        "# Ablation Run",
        "",
        "Ablation profile scores simulated from the rule-based benchmark output.",
        "",
        "| Profile | Case pass rate | Rule score rate | Disabled dimensions |",
        "| --- | ---: | ---: | --- |",
    ]
    for profile in profiles:
        lines.append(
            f"| `{profile.profile.profile_id}` | {profile.case_pass_rate:.2%} | "
            f"{profile.score_rate:.2%} | {', '.join(profile.profile.disabled_dimensions) or 'none'} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_ablation_profiles(
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
    out_dir: str | Path = DEFAULT_ABLATION_DIR,
    *,
    benchmark_cases_dir: str | Path = "benchmark_cases",
    bundle_out: str | Path = DEFAULT_ABLATION_BUNDLE_DIR,
    wolfram_timeout: int = 300,
) -> AblationRun:
    out_dir = _project_path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    benchmark = evaluate_benchmark_cases(
        cases_dir=benchmark_cases_dir,
        results_dir=out_dir / "_benchmark_reference",
        bundle_out=bundle_out,
        execute_wolfram=True,
        wolfram_timeout=wolfram_timeout,
    )
    profiles = [_score_profile(benchmark.cases, profile) for profile in load_ablation_profiles(profiles_dir)]

    csv_path = out_dir / "ablation_scores.csv"
    json_path = out_dir / "ablation_scores.json"
    notes_path = out_dir / "notes.md"
    run = AblationRun(profiles=profiles, csv_path=csv_path, json_path=json_path, notes_path=notes_path)
    _write_csv(csv_path, profiles)
    json_path.write_text(json.dumps(run.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")
    _write_notes(notes_path, profiles)
    return run
