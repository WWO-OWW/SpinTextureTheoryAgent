import json

from spintexture_agent.baseline import PROXY_WARNING, load_baseline_profiles, run_baseline_profiles


def test_load_baseline_profiles():
    profiles = load_baseline_profiles()
    profile_ids = {profile.profile_id for profile in profiles}

    assert "full_agent" in profile_ids
    assert "llm_only_proxy" in profile_ids
    assert "naive_llm_wolfram_proxy" in profile_ids


def test_run_baseline_profiles(tmp_path):
    run = run_baseline_profiles(
        out_dir=tmp_path / "baseline",
        bundle_out=tmp_path / "bundles",
    )

    assert run.csv_path.exists()
    assert run.json_path.exists()
    assert run.notes_path.exists()

    payload = json.loads(run.json_path.read_text(encoding="utf-8"))
    profiles = {profile["profile_id"]: profile for profile in payload["profiles"]}
    assert payload["warning"] == PROXY_WARNING
    assert profiles["full_agent"]["case_pass_rate"] == 1.0
    assert profiles["full_agent"]["score_rate"] == 1.0
    assert profiles["llm_only_proxy"]["score_rate"] < profiles["full_agent"]["score_rate"]
    assert (
        profiles["naive_llm_wolfram_proxy"]["score_rate"]
        < profiles["full_agent"]["score_rate"]
    )
    llm_a4 = next(
        case
        for case in profiles["llm_only_proxy"]["cases"]
        if case["case_id"] == "A4_afm_stripe_sot"
    )
    dimensions = {dimension["name"]: dimension for dimension in llm_a4["dimensions"]}
    assert not dimensions["wolfram_execution"]["passed"]
    assert not dimensions["wolfram_result_keys"]["passed"]
    assert not dimensions["wolfram_result_content"]["passed"]
