import csv
import importlib.util
from pathlib import Path

from spintexture_agent.recorded_baseline import evaluate_recorded_baselines


def _load_failure_table_module():
    path = Path("analysis/scripts/build_baseline_failure_table.py")
    spec = importlib.util.spec_from_file_location("build_baseline_failure_table", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_failure_heatmap_module():
    path = Path("analysis/scripts/plot_baseline_failure_heatmap.py")
    spec = importlib.util.spec_from_file_location("plot_baseline_failure_heatmap", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_baseline_failure_table_writes_outputs(tmp_path):
    run = evaluate_recorded_baselines(
        out_dir=tmp_path / "recorded_baseline_run",
        cases_dir="benchmark_case_sets/core_3",
        bundle_out=tmp_path / "bundles",
    )
    module = _load_failure_table_module()
    paths = module.write_failure_tables(run.json_path.parent)

    assert paths["csv"].exists()
    assert paths["markdown"].exists()
    assert paths["matrix"].exists()

    rows = list(csv.DictReader(paths["csv"].open("r", encoding="utf-8")))
    assert len(rows) == 15

    llm_afm = next(
        row
        for row in rows
        if row["method_id"] == "llm_only" and row["case_id"] == "B2_afm_skyrmion_sot"
    )
    assert "dynamics_selection" in llm_afm["failure_categories"]
    assert "topology_definition" in llm_afm["failure_categories"]

    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Core-3 Baseline Error Analysis" in markdown
    assert "Incorrect or incomplete dynamics/equation selection" in markdown


def test_plot_baseline_failure_heatmap_writes_figure_files(tmp_path):
    run = evaluate_recorded_baselines(
        out_dir=tmp_path / "recorded_baseline_run",
        cases_dir="benchmark_case_sets/core_3",
        bundle_out=tmp_path / "bundles",
    )
    table_module = _load_failure_table_module()
    table_module.write_failure_tables(run.json_path.parent)

    heatmap_module = _load_failure_heatmap_module()
    paths = heatmap_module.write_figures(run.json_path.parent, tmp_path)

    assert paths["baseline_failure_category_heatmap_png"].exists()
    assert paths["baseline_failure_category_heatmap_pdf"].exists()
    assert paths["baseline_failure_category_heatmap_svg"].exists()
    svg_text = paths["baseline_failure_category_heatmap_svg"].read_text(encoding="utf-8")
    assert "Core-3 baseline failure categories" in svg_text
    assert "Failed dimensions" in svg_text
