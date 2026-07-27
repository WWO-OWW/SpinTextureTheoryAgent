from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


RESULT_BEGIN = "SPINTEXTURE_AGENT_RESULT_JSON_BEGIN"
RESULT_END = "SPINTEXTURE_AGENT_RESULT_JSON_END"
MAX_EXCERPT_CHARS = 4000
KNOWN_WOLFRAM_KERNEL_PATHS = [
    Path("/Applications/Wolfram.app/Contents/MacOS/WolframKernel"),
    Path("/Applications/Mathematica.app/Contents/MacOS/WolframKernel"),
]


@dataclass(frozen=True)
class WolframExecution:
    status: str
    reason: str | None = None
    command: list[str] | None = None
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    result_path: str | None = None
    result: dict[str, object] | None = None
    duration_seconds: float | None = None

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def not_run_execution() -> WolframExecution:
    return WolframExecution(
        status="not_run",
        reason="Generated script only; Wolfram execution was not requested.",
    )


def _excerpt(text: str | None) -> str | None:
    if not text:
        return None
    if len(text) <= MAX_EXCERPT_CHARS:
        return text
    return text[:MAX_EXCERPT_CHARS] + "\n...[truncated]"


def _extract_result(stdout: str) -> dict[str, object] | None:
    if RESULT_BEGIN not in stdout or RESULT_END not in stdout:
        return None
    start = stdout.find(RESULT_BEGIN) + len(RESULT_BEGIN)
    end = stdout.find(RESULT_END, start)
    if end < 0:
        return None
    payload = stdout[start:end].strip()
    if not payload:
        return None
    try:
        result = json.loads(payload)
    except json.JSONDecodeError:
        return {"parse_error": payload}
    return result if isinstance(result, dict) else {"result": result}


def _valid_result(result: dict[str, object] | None) -> bool:
    return isinstance(result, dict) and "parse_error" not in result


def _wolfram_string(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def _kernel_command(kernel_path: Path, wolfram_path: Path) -> list[str]:
    return [
        str(kernel_path),
        "-noprompt",
        "-run",
        f'Get["{_wolfram_string(wolfram_path)}"];Quit[]',
    ]


def _resolve_wolfram_command(
    wolfram_path: Path,
    executable: str,
) -> tuple[list[str] | None, str | None]:
    resolved_executable = shutil.which(executable)
    if resolved_executable is not None:
        return [resolved_executable, "-file", str(wolfram_path)], None

    if executable == "wolframscript":
        resolved_kernel = shutil.which("WolframKernel")
        if resolved_kernel is not None:
            return _kernel_command(Path(resolved_kernel), wolfram_path), None
        for kernel_path in KNOWN_WOLFRAM_KERNEL_PATHS:
            if kernel_path.exists():
                return _kernel_command(kernel_path, wolfram_path), None

    return None, f"{executable} not found"


def execute_wolfram_script(
    wolfram_path: str | Path,
    log_dir: str | Path,
    *,
    executable: str = "wolframscript",
    timeout_seconds: int = 120,
) -> WolframExecution:
    wolfram_path = Path(wolfram_path)
    log_dir = Path(log_dir)
    command, missing_reason = _resolve_wolfram_command(wolfram_path, executable)
    if command is None:
        return WolframExecution(
            status="skipped",
            reason=missing_reason,
            command=[executable, "-file", str(wolfram_path)],
            duration_seconds=0.0,
        )

    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{wolfram_path.stem}_stdout.txt"
    stderr_path = log_dir / f"{wolfram_path.stem}_stderr.txt"

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        duration_seconds = time.perf_counter() - started
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        return WolframExecution(
            status="failed",
            reason=f"Execution timed out after {timeout_seconds} seconds",
            command=command,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stdout_excerpt=_excerpt(stdout),
            stderr_excerpt=_excerpt(stderr),
            duration_seconds=duration_seconds,
        )

    duration_seconds = time.perf_counter() - started
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    result = _extract_result(completed.stdout)
    result_path = None
    if result is not None:
        result_json_path = log_dir / f"{wolfram_path.stem}_result.json"
        result_json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result_path = str(result_json_path)
    status = "passed" if completed.returncode == 0 or _valid_result(result) else "failed"
    reason = None
    if completed.returncode != 0 and _valid_result(result):
        reason = f"Process exited with code {completed.returncode} after emitting result JSON."
    return WolframExecution(
        status=status,
        reason=reason,
        command=command,
        exit_code=completed.returncode,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        stdout_excerpt=_excerpt(completed.stdout),
        stderr_excerpt=_excerpt(completed.stderr),
        result_path=result_path,
        result=result,
        duration_seconds=duration_seconds,
    )


def update_wolfram_execution_record(
    record_path: str | Path,
    execution: WolframExecution,
) -> None:
    record_path = Path(record_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["wolfram_execution"] = execution.to_record()
    expected_keys = record.get("wolfram_results", {}).get("expected_keys", [])
    record["wolfram_results"] = {
        "status": execution.status,
        "expected_keys": expected_keys,
        "result_path": execution.result_path,
        "results": execution.result,
    }
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
