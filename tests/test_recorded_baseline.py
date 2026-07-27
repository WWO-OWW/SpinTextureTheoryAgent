import json

from spintexture_agent.recorded_baseline import (
    RECORDED_BASELINE_NOTE,
    evaluate_recorded_baselines,
    load_recorded_baseline_methods,
)


def test_load_recorded_baseline_methods():
    methods = load_recorded_baseline_methods()
    method_ids = {method.method_id for method in methods}

    assert "llm_only" in method_ids
    assert "prompted_llm" in method_ids
    assert "naive_llm_wolfram" in method_ids


def test_evaluate_recorded_baselines(tmp_path):
    run = evaluate_recorded_baselines(
        out_dir=tmp_path / "recorded_baseline",
        cases_dir="benchmark_case_sets/core_3",
        bundle_out=tmp_path / "bundles",
    )

    assert run.csv_path.exists()
    assert run.json_path.exists()
    assert run.notes_path.exists()

    payload = json.loads(run.json_path.read_text(encoding="utf-8"))
    profiles = {profile["profile_id"]: profile for profile in payload["profiles"]}
    assert payload["warning"] == RECORDED_BASELINE_NOTE
    assert profiles["full_agent"]["case_pass_rate"] == 1.0
    assert profiles["llm_only"]["score_rate"] < profiles["prompted_llm"]["score_rate"]
    assert profiles["naive_llm_wolfram"]["score_rate"] < profiles["full_agent"]["score_rate"]

    prompted_a4 = next(
        case
        for case in profiles["prompted_llm"]["cases"]
        if case["case_id"] == "A4_afm_stripe_sot"
    )
    dimensions = {dimension["name"]: dimension for dimension in prompted_a4["dimensions"]}
    assert not dimensions["wolfram_execution"]["passed"]
    assert not dimensions["wolfram_result_keys"]["passed"]
    assert not dimensions["wolfram_result_content"]["passed"]
