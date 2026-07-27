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


def _load_case_study_module():
    path = Path("analysis/scripts/build_core3_case_study_report.py")
    spec = importlib.util.spec_from_file_location("build_core3_case_study_report", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_core3_case_study_report_writes_markdown_and_latex(tmp_path):
    run = evaluate_recorded_baselines(
        out_dir=tmp_path / "recorded_baseline_run",
        cases_dir="benchmark_case_sets/core_3",
        bundle_out=tmp_path / "bundles",
    )
    failure_table = _load_failure_table_module()
    failure_table.write_failure_tables(run.json_path.parent)

    case_study = _load_case_study_module()
    paths = case_study.write_case_study_report(
        run.json_path.parent,
        tmp_path / "case_study",
    )

    assert paths["markdown"].exists()
    assert paths["latex"].exists()

    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Core-3 Case Study Report" in markdown
    assert "A4: AFM stripe domain driven by SOT" in markdown
    assert "B2: AFM skyrmion driven by SOT" in markdown
    assert "Forbidden template residue appears in the output" in markdown

    latex = paths["latex"].read_text(encoding="utf-8")
    assert r"\section{Core-3 Case Studies}" in latex
    assert "AFM skyrmion" in latex
