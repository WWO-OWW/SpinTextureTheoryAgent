import json

from spintexture_agent.ablation import load_ablation_profiles, run_ablation_profiles


def test_load_ablation_profiles():
    profiles = load_ablation_profiles()
    profile_ids = {profile.profile_id for profile in profiles}

    assert "full" in profile_ids
    assert "no_validator" in profile_ids
    assert "no_physics_ir" in profile_ids
    assert "no_wolfram_execution" in profile_ids
    assert "no_result_key_check" in profile_ids
    assert "no_physics_structure_check" in profile_ids


def test_ablation_cli_uses_cas_stable_timeout():
    from spintexture_agent.cli import build_parser

    args = build_parser().parse_args(["ablate"])

    assert args.wolfram_timeout == 300


def test_run_ablation_profiles(tmp_path):
    run = run_ablation_profiles(
        out_dir=tmp_path / "ablation",
        bundle_out=tmp_path / "bundles",
    )

    assert run.csv_path.exists()
    assert run.json_path.exists()
    assert run.notes_path.exists()

    payload = json.loads(run.json_path.read_text(encoding="utf-8"))
    profiles = {profile["profile_id"]: profile for profile in payload["profiles"]}
    assert profiles["full"]["case_pass_rate"] == 1.0
    assert profiles["full"]["score_rate"] == 1.0
    assert profiles["no_physics_ir"]["score_rate"] < profiles["full"]["score_rate"]
    assert profiles["no_negative_checks"]["case_pass_rate"] < profiles["full"]["case_pass_rate"]
    assert profiles["no_wolfram_execution"]["case_pass_rate"] < profiles["full"]["case_pass_rate"]
    assert profiles["no_physics_structure_check"]["score_rate"] < profiles["full"]["score_rate"]
