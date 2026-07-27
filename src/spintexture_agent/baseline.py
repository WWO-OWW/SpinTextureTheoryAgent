from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .evaluator import CaseScore, DimensionScore, evaluate_benchmark_cases, summarize_dimensions
from .generator import PROJECT_ROOT


DEFAULT_PROFILES_DIR = PROJECT_ROOT / "baseline_profiles"
DEFAULT_BASELINE_DIR = PROJECT_ROOT / "analysis" / "baseline_runs"
DEFAULT_BASELINE_BUNDLE_DIR = PROJECT_ROOT / "outputs" / "baseline_runs"
PROXY_WARNING = (
    "These baseline scores are simulated proxy profiles derived from rule-based benchmark "
    "dimensions. They are useful for early plotting and method design, but they are not a "
    "substitute for real LLM baseline experiments."
)


@dataclass(frozen=True)
class BaselineProfile:
    profile_id: str
    baseline_type: str
    description: str
    disabled_dimensions: list[str]
    affected_cases: list[str]
    expected_failure_cases: list[str]


@dataclass(frozen=True)
class BaselineCaseScore:
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
class BaselineProfileScore:
    profile: BaselineProfile
    cases: list[BaselineCaseScore]

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
            "baseline_type": self.profile.baseline_type,
            "description": self.profile.description,
            "disabled_dimensions": self.profile.disabled_dimensions,
            "affected_cases": self.profile.affected_cases,
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
class BaselineRun:
    profiles: list[BaselineProfileScore]
    csv_path: Path
    json_path: Path
    notes_path: Path

    def to_record(self) -> dict[str, Any]:
        return {
            "baseline_run_type": "simulated_proxy_comparison",
            "warning": PROXY_WARNING,
            "summary": {
                "profile_count": len(self.profiles),
                "profiles": [
                    {
                        "profile_id": profile.profile.profile_id,
                        "baseline_type": profile.profile.baseline_type,
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
        raise ValueError(f"Baseline profile must be a mapping: {path}")
    return data


def load_baseline_profiles(profiles_dir: str | Path = DEFAULT_PROFILES_DIR) -> list[BaselineProfile]:
    profiles = []
    for path in sorted(_project_path(profiles_dir).glob("*.yaml")):
        data = _load_yaml(path)
        profiles.append(
            BaselineProfile(
                profile_id=str(data["profile_id"]),
                baseline_type=str(data.get("baseline_type", "simulated_proxy")),
                description=str(data.get("description", "")),
                disabled_dimensions=list(data.get("disabled_dimensions", [])),
                affected_cases=list(data.get("affected_cases", [])),
                expected_failure_cases=list(data.get("expected_failure_cases", [])),
            )
        )
    preferred = {
        "llm_only_proxy": 0,
        "prompted_llm_proxy": 1,
        "template_only_proxy": 2,
        "naive_llm_wolfram_proxy": 3,
        "full_agent": 4,
    }
    return sorted(profiles, key=lambda profile: preferred.get(profile.profile_id, 100))


def _case_is_affected(case_id: str, profile: BaselineProfile) -> bool:
    if profile.affected_cases:
        return case_id in profile.affected_cases
    if profile.expected_failure_cases:
        return case_id in profile.expected_failure_cases
    return bool(profile.disabled_dimensions)


def _apply_profile_to_case(case: CaseScore, profile: BaselineProfile) -> BaselineCaseScore:
    disabled = set(profile.disabled_dimensions)
    affected = _case_is_affected(case.case_id, profile)
    expected_failure = case.case_id in set(profile.expected_failure_cases)

    dimensions: list[DimensionScore] = []
    for dimension in case.dimensions:
        if affected and dimension.applicable and dimension.name in disabled:
            dimensions.append(
                DimensionScore(
                    name=dimension.name,
                    passed=False,
                    detail=(
                        f"proxy baseline={profile.profile_id}; "
                        f"original_passed={dimension.passed}; original_detail={dimension.detail}"
                    ),
                )
            )
        else:
            dimensions.append(dimension)

    dimensions.append(
        DimensionScore(
            name="baseline_expected_failure",
            passed=not expected_failure,
            detail=(
                "expected proxy-baseline failure for this case"
                if expected_failure
                else "no expected proxy-baseline failure for this case"
            ),
        )
    )
    score, max_score = summarize_dimensions(dimensions)
    return BaselineCaseScore(
        case_id=case.case_id,
        score=score,
        max_score=max_score,
        passed=score == max_score,
        dimensions=dimensions,
    )


def _score_profile(cases: list[CaseScore], profile: BaselineProfile) -> BaselineProfileScore:
    return BaselineProfileScore(
        profile=profile,
        cases=[_apply_profile_to_case(case, profile) for case in cases],
    )


def _write_csv(path: Path, profiles: list[BaselineProfileScore]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "profile_id",
                "baseline_type",
                "passed_cases",
                "case_count",
                "case_pass_rate",
                "total_score",
                "max_score",
                "score_rate",
                "disabled_dimensions",
                "affected_cases",
                "expected_failure_cases",
            ],
        )
        writer.writeheader()
        for profile in profiles:
            writer.writerow(
                {
                    "profile_id": profile.profile.profile_id,
                    "baseline_type": profile.profile.baseline_type,
                    "passed_cases": profile.passed_cases,
                    "case_count": len(profile.cases),
                    "case_pass_rate": f"{profile.case_pass_rate:.6f}",
                    "total_score": profile.total_score,
                    "max_score": profile.max_score,
                    "score_rate": f"{profile.score_rate:.6f}",
                    "disabled_dimensions": ";".join(profile.profile.disabled_dimensions),
                    "affected_cases": ";".join(profile.profile.affected_cases),
                    "expected_failure_cases": ";".join(profile.profile.expected_failure_cases),
                }
            )


def _write_notes(path: Path, profiles: list[BaselineProfileScore]) -> None:
    lines = [
        "# Proxy Baseline Run",
        "",
        PROXY_WARNING,
        "",
        "| Baseline | Type | Case pass rate | Rule score rate | Expected failure cases |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for profile in profiles:
        lines.append(
            f"| `{profile.profile.profile_id}` | `{profile.profile.baseline_type}` | "
            f"{profile.case_pass_rate:.2%} | {profile.score_rate:.2%} | "
            f"{len(profile.profile.expected_failure_cases)} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_baseline_profiles(
    profiles_dir: str | Path = DEFAULT_PROFILES_DIR,
    out_dir: str | Path = DEFAULT_BASELINE_DIR,
    *,
    benchmark_cases_dir: str | Path = "benchmark_cases",
    bundle_out: str | Path = DEFAULT_BASELINE_BUNDLE_DIR,
) -> BaselineRun:
    out_dir = _project_path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    benchmark = evaluate_benchmark_cases(
        cases_dir=benchmark_cases_dir,
        results_dir=out_dir / "_benchmark_reference",
        bundle_out=bundle_out,
        execute_wolfram=True,
        wolfram_timeout=240,
    )
    profiles = [_score_profile(benchmark.cases, profile) for profile in load_baseline_profiles(profiles_dir)]

    csv_path = out_dir / "baseline_scores.csv"
    json_path = out_dir / "baseline_scores.json"
    notes_path = out_dir / "notes.md"
    run = BaselineRun(profiles=profiles, csv_path=csv_path, json_path=json_path, notes_path=notes_path)
    _write_csv(csv_path, profiles)
    json_path.write_text(json.dumps(run.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")
    _write_notes(notes_path, profiles)
    return run
