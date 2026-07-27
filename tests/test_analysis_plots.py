import importlib.util
import json
import sys
from pathlib import Path

from spintexture_agent.baseline import run_baseline_profiles
from spintexture_agent.recorded_baseline import evaluate_recorded_baselines


def _load_plot_module():
    path = Path("analysis/scripts/plot_benchmark_scores.py")
    spec = importlib.util.spec_from_file_location("plot_benchmark_scores", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_ablation_plot_module():
    path = Path("analysis/scripts/plot_ablation_scores.py")
    spec = importlib.util.spec_from_file_location("plot_ablation_scores", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_baseline_plot_module():
    path = Path("analysis/scripts/plot_baseline_scores.py")
    spec = importlib.util.spec_from_file_location("plot_baseline_scores", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_negative_plot_module():
    path = Path("analysis/scripts/plot_negative_benchmark_detection.py")
    spec = importlib.util.spec_from_file_location("plot_negative_benchmark_detection", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_reproducibility_plot_module():
    path = Path("analysis/scripts/plot_reproducibility_metrics.py")
    spec = importlib.util.spec_from_file_location("plot_reproducibility_metrics", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_maturity_report_module():
    path = Path("analysis/scripts/build_maturity_report.py")
    spec = importlib.util.spec_from_file_location("build_maturity_report", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["build_maturity_report"] = module
    spec.loader.exec_module(module)
    return module


def test_plot_benchmark_scores_writes_svg_files(tmp_path):
    module = _load_plot_module()
    paths = module.write_figures(
        "analysis/benchmark_runs/2026-06-28_initial_10_cases",
        tmp_path,
    )

    assert paths["case_scores_png"].exists()
    assert paths["case_scores_pdf"].exists()
    assert paths["case_scores_svg"].exists()
    assert paths["dimension_heatmap_png"].exists()
    assert paths["dimension_heatmap_pdf"].exists()
    assert paths["dimension_heatmap_svg"].exists()
    assert "<svg" in paths["case_scores_svg"].read_text(encoding="utf-8")
    assert "Benchmark case scores" in paths["case_scores_svg"].read_text(encoding="utf-8")
    assert "Benchmark dimension pass map" in paths["dimension_heatmap_svg"].read_text(
        encoding="utf-8"
    )


def test_plot_negative_benchmark_detection_writes_figure_files(tmp_path):
    module = _load_negative_plot_module()
    paths = module.write_figures(
        "analysis/benchmark_runs/2026-06-28_initial_10_cases",
        tmp_path,
    )

    assert paths["negative_benchmark_detection_heatmap_png"].exists()
    assert paths["negative_benchmark_detection_heatmap_pdf"].exists()
    assert paths["negative_benchmark_detection_heatmap_svg"].exists()
    svg_text = paths["negative_benchmark_detection_heatmap_svg"].read_text(encoding="utf-8")
    assert "Figure 6. Negative benchmark error-detection map" in svg_text
    assert "E1 AFM skyrmion" in svg_text


def test_plot_reproducibility_metrics_writes_tables_and_figures(tmp_path):
    module = _load_reproducibility_plot_module()
    run_dir = tmp_path / "run"
    bundle_dir = tmp_path / "bundle" / "A4_afm_stripe_sot"
    notebook = bundle_dir / "notebooks" / "case.wl"
    summary = bundle_dir / "summaries" / "case_summary.md"
    record = bundle_dir / "records" / "case_record.json"
    result = bundle_dir / "wolfram_logs" / "case_result.json"
    for path in [notebook, summary, record, result]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    record.write_text(
        '{"wolfram_execution":{"status":"passed","duration_seconds":1.2},'
        '"wolfram_results":{"result_path":"'
        + str(result)
        + '","results":{"ok":true}}}',
        encoding="utf-8",
    )
    run_dir.mkdir(parents=True)
    (run_dir / "benchmark_scores.json").write_text(
        json.dumps(
            {
                "summary": {"case_count": 1, "passed_cases": 1, "total_score": 1, "max_score": 1},
                "cases": [
                    {
                        "case_id": "A4_afm_stripe_sot",
                        "score": 1,
                        "max_score": 1,
                        "passed": True,
                        "duration_seconds": 1.5,
                        "dimensions": [],
                        "bundle_paths": {
                            "wolfram": str(notebook),
                            "summary": str(summary),
                            "record": str(record),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    paths = module.write_outputs(run_dir, tmp_path)

    assert paths["csv"].exists()
    assert paths["summary"].exists()
    assert paths["figure_png"].exists()
    assert paths["figure_pdf"].exists()
    assert paths["figure_svg"].exists()
    svg_text = paths["figure_svg"].read_text(encoding="utf-8")
    assert "Figure 8. Reproducibility and runtime profile" in svg_text
    assert "Wolfram runtime" in svg_text


def test_build_maturity_report_writes_tables_report_and_figure(tmp_path):
    module = _load_maturity_report_module()
    out_dir = tmp_path / "maturity"
    figure_dir = tmp_path / "figures"

    paths = module.write_outputs(out_dir=out_dir, figure_dir=figure_dir)

    assert paths["json"].exists()
    assert paths["suite_csv"].exists()
    assert paths["matrix_csv"].exists()
    assert paths["report"].exists()
    assert paths["figure_png"].exists()
    assert paths["figure_pdf"].exists()
    assert paths["figure_svg"].exists()
    report = paths["report"].read_text(encoding="utf-8")
    assert "Case evaluations: 25/25 passed" in report
    assert "Support levels:" in report
    assert "does not imply a full physical derivation" in report
    svg_text = paths["figure_svg"].read_text(encoding="utf-8")
    assert "Declared-capability check rates across benchmark suites" in svg_text
    assert "NL uncertainty" in svg_text


def test_plot_ablation_scores_writes_figure_files(tmp_path):
    module = _load_ablation_plot_module()
    paths = module.write_figures(
        "analysis/ablation_runs/2026-06-28_ablation_profiles",
        tmp_path,
    )

    assert paths["ablation_profile_scores_png"].exists()
    assert paths["ablation_profile_scores_pdf"].exists()
    assert paths["ablation_profile_scores_svg"].exists()
    assert "Ablation profile scores" in paths["ablation_profile_scores_svg"].read_text(
        encoding="utf-8"
    )


def test_plot_baseline_scores_writes_figure_files(tmp_path):
    run = run_baseline_profiles(
        out_dir=tmp_path / "baseline_run",
        bundle_out=tmp_path / "bundles",
    )
    module = _load_baseline_plot_module()
    paths = module.write_figures(run.json_path.parent, tmp_path)

    assert paths["baseline_profile_scores_png"].exists()
    assert paths["baseline_profile_scores_pdf"].exists()
    assert paths["baseline_profile_scores_svg"].exists()
    svg_text = paths["baseline_profile_scores_svg"].read_text(encoding="utf-8")
    assert "Proxy baseline comparison" in svg_text
    assert "Simulated proxy profiles" in svg_text


def test_plot_recorded_baseline_scores_writes_figure_files(tmp_path):
    run = evaluate_recorded_baselines(
        out_dir=tmp_path / "recorded_baseline_run",
        cases_dir="benchmark_case_sets/core_3",
        bundle_out=tmp_path / "bundles",
    )
    module = _load_baseline_plot_module()
    paths = module.write_figures(run.json_path.parent, tmp_path)

    assert paths["baseline_profile_scores_png"].exists()
    assert paths["baseline_profile_scores_pdf"].exists()
    assert paths["baseline_profile_scores_svg"].exists()
    svg_text = paths["baseline_profile_scores_svg"].read_text(encoding="utf-8")
    assert "Recorded baseline comparison" in svg_text
    assert "verify provenance before paper use" in svg_text


def test_plot_independent_baseline_scores_uses_independent_title(tmp_path):
    module = _load_baseline_plot_module()
    record = {
        "baseline_run_type": "recorded_output_evaluation",
        "profiles": [
            {
                "profile_id": "llm_only",
                "baseline_type": "independent_core3_llm_only",
                "case_pass_rate": 0.0,
                "score_rate": 0.56,
            },
            {
                "profile_id": "naive_llm_wolfram",
                "baseline_type": "independent_core3_naive_llm_wolfram",
                "case_pass_rate": 0.0,
                "score_rate": 0.64,
            },
        ],
    }
    paths = module.plot_baseline_scores(record, tmp_path)

    assert paths["svg"].exists()
    svg_text = paths["svg"].read_text(encoding="utf-8")
    assert "Independent baseline comparison" in svg_text
    assert "External Gemini 3.5 Flash transcripts" in svg_text


def test_plot_independent_baseline_scores_with_agent_uses_comparison_title(tmp_path):
    module = _load_baseline_plot_module()
    record = {
        "baseline_run_type": "recorded_output_evaluation",
        "profiles": [
            {
                "profile_id": "llm_only",
                "baseline_type": "independent_core3_llm_only",
                "case_pass_rate": 0.0,
                "score_rate": 0.56,
            },
            {
                "profile_id": "full_agent",
                "baseline_type": "implemented_agent",
                "case_pass_rate": 1.0,
                "score_rate": 1.0,
            },
        ],
    }
    paths = module.plot_baseline_scores(record, tmp_path)

    assert paths["svg"].exists()
    svg_text = paths["svg"].read_text(encoding="utf-8")
    assert "Independent baselines vs full agent" in svg_text
    assert "full SpinTextureTheoryAgent reference" in svg_text
