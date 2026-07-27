import json
import subprocess
from types import SimpleNamespace

from spintexture_agent.wolfram import (
    RESULT_BEGIN,
    RESULT_END,
    execute_wolfram_script,
    update_wolfram_execution_record,
)


def test_execute_wolfram_script_skips_when_executable_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.wolfram.shutil.which", lambda _: None)
    monkeypatch.setattr("spintexture_agent.wolfram.KNOWN_WOLFRAM_KERNEL_PATHS", [])
    wolfram_path = tmp_path / "task.wl"
    wolfram_path.write_text('Print["hello"]', encoding="utf-8")

    execution = execute_wolfram_script(wolfram_path, tmp_path / "logs")

    assert execution.status == "skipped"
    assert execution.reason == "wolframscript not found"


def test_update_wolfram_execution_record(tmp_path):
    record_path = tmp_path / "record.json"
    record_path.write_text(
        json.dumps(
            {
                "wolfram_execution": {"status": "not_run"},
                "wolfram_results": {"expected_keys": ["collective_mass_matrix"]},
            }
        ),
        encoding="utf-8",
    )
    execution = execute_wolfram_script(tmp_path / "missing.wl", tmp_path / "logs", executable="missing")

    update_wolfram_execution_record(record_path, execution)

    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["wolfram_execution"]["status"] == "skipped"
    assert payload["wolfram_results"]["status"] == "skipped"
    assert payload["wolfram_results"]["expected_keys"] == ["collective_mass_matrix"]


def test_execute_wolfram_script_extracts_agent_result(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.wolfram.shutil.which", lambda _: "/bin/wolframscript")

    def fake_run(*args, **kwargs):
        stdout = f"header\n{RESULT_BEGIN}\n{{\"collective_mass_matrix\":\"{{{{2 chi/Delta,0}}}}\"}}\n{RESULT_END}\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("spintexture_agent.wolfram.subprocess.run", fake_run)
    wolfram_path = tmp_path / "task.wl"
    wolfram_path.write_text('Print["hello"]', encoding="utf-8")

    execution = execute_wolfram_script(wolfram_path, tmp_path / "logs")

    assert execution.status == "passed"
    assert execution.result == {"collective_mass_matrix": "{{2 chi/Delta,0}}"}
    assert execution.result_path is not None


def test_execute_wolfram_script_accepts_result_with_exit_warning(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.wolfram.shutil.which", lambda _: "/bin/wolframscript")

    def fake_run(*args, **kwargs):
        stdout = f"{RESULT_BEGIN}\n{{\"thiele_equation\":\"G cross Rdot == F\"}}\n{RESULT_END}\n"
        return SimpleNamespace(returncode=-11, stdout=stdout, stderr="")

    monkeypatch.setattr("spintexture_agent.wolfram.subprocess.run", fake_run)
    wolfram_path = tmp_path / "task.wl"
    wolfram_path.write_text('Print["hello"]', encoding="utf-8")

    execution = execute_wolfram_script(wolfram_path, tmp_path / "logs")

    assert execution.status == "passed"
    assert execution.exit_code == -11
    assert "after emitting result JSON" in execution.reason
    assert execution.result == {"thiele_equation": "G cross Rdot == F"}


def test_execute_wolfram_script_uses_kernel_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "spintexture_agent.wolfram.shutil.which",
        lambda name: "/Applications/Wolfram.app/Contents/MacOS/WolframKernel"
        if name == "WolframKernel"
        else None,
    )

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        stdout = f"{RESULT_BEGIN}\n{{\"ok\":\"true\"}}\n{RESULT_END}\n"
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("spintexture_agent.wolfram.subprocess.run", fake_run)
    wolfram_path = tmp_path / "task.wl"
    wolfram_path.write_text('Print["hello"]', encoding="utf-8")

    execution = execute_wolfram_script(wolfram_path, tmp_path / "logs")

    assert execution.status == "passed"
    assert captured["cmd"][1:3] == ["-noprompt", "-run"]
    assert execution.result == {"ok": "true"}


def test_execute_wolfram_script_decodes_timeout_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr("spintexture_agent.wolfram.shutil.which", lambda _: "/bin/wolframscript")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["wolframscript"],
            timeout=1,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr("spintexture_agent.wolfram.subprocess.run", fake_run)
    wolfram_path = tmp_path / "task.wl"
    wolfram_path.write_text('Print["hello"]', encoding="utf-8")

    execution = execute_wolfram_script(wolfram_path, tmp_path / "logs", timeout_seconds=1)

    assert execution.status == "failed"
    assert execution.reason == "Execution timed out after 1 seconds"
    assert "partial stdout" in execution.stdout_excerpt
    assert "partial stderr" in execution.stderr_excerpt
    assert (tmp_path / "logs" / "task_stdout.txt").read_text(encoding="utf-8") == "partial stdout"
