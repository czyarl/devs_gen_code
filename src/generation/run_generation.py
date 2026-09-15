#!/usr/bin/env python3
"""Run one published generation method on one benchmark scenario.

Usage:
    python run_generation.py --framework devs_gen --model MODEL_ID \
        --benchmark ABP --workspace /tmp/ws
    python run_generation.py --list-frameworks
    python run_generation.py --list-benchmarks
"""
import argparse
import gzip
import json
import os
import re
import signal
import sys
import time
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


GENERATION_LOG_LIMIT_BYTES = 5 * 1024 * 1024
DIAGNOSTIC_ARCHIVE_SUFFIXES = {".txt", ".jsonl", ".log"}


class _BoundedTailCapture:
    """Drain a stream without allowing verbose generators to fill the disk."""

    def __init__(self, limit_bytes: int = GENERATION_LOG_LIMIT_BYTES):
        if limit_bytes <= 0:
            raise ValueError("capture limit must be positive")
        self.limit_bytes = limit_bytes
        self.observed_bytes = 0
        self.retained = bytearray()

    @property
    def truncated(self) -> bool:
        return self.observed_bytes > len(self.retained)

    def feed(self, chunk: bytes) -> None:
        self.observed_bytes += len(chunk)
        if len(chunk) >= self.limit_bytes:
            self.retained[:] = chunk[-self.limit_bytes :]
            return
        overflow = len(self.retained) + len(chunk) - self.limit_bytes
        if overflow > 0:
            del self.retained[:overflow]
        self.retained.extend(chunk)

    def text(self) -> str:
        return bytes(self.retained).decode("utf-8", errors="replace")


def _drain_capture(stream, capture: _BoundedTailCapture) -> None:
    try:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            capture.feed(chunk)
    finally:
        stream.close()


def _write_bounded_log(path: Path, capture: _BoundedTailCapture) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as archive:
            archive.write(bytes(capture.retained))
    marker = Path(f"{path}.truncation.json")
    if capture.truncated:
        marker.write_text(
            json.dumps(
                {
                    "retention": "tail",
                    "observed_bytes": capture.observed_bytes,
                    "retained_bytes": len(capture.retained),
                    "limit_bytes": capture.limit_bytes,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif marker.exists():
        marker.unlink()


def _archive_generation_diagnostics(workspace_dir: Path) -> dict[str, int]:
    """Deterministically gzip verbose post-run diagnostics in place.

    Generated source, plans, manifests, and JSON metadata stay directly
    readable.  Only text transcripts below a generator-owned
    ``_analysis_logs`` directory are archived after the child process exits.
    """
    archived_files = 0
    source_bytes = 0
    archive_bytes = 0
    for log_root in workspace_dir.rglob("_analysis_logs"):
        if not log_root.is_dir() or log_root.is_symlink():
            continue
        for source in sorted(log_root.rglob("*")):
            if (
                not source.is_file()
                or source.is_symlink()
                or source.suffix not in DIAGNOSTIC_ARCHIVE_SUFFIXES
            ):
                continue
            target = Path(f"{source}.gz")
            temporary = Path(f"{target}.tmp")
            original_size = source.stat().st_size
            with source.open("rb") as input_stream, temporary.open("wb") as raw:
                with gzip.GzipFile(
                    filename="", mode="wb", fileobj=raw, mtime=0
                ) as archive:
                    while chunk := input_stream.read(64 * 1024):
                        archive.write(chunk)
            temporary.replace(target)
            source.unlink()
            archived_files += 1
            source_bytes += original_size
            archive_bytes += target.stat().st_size
    return {
        "archived_files": archived_files,
        "source_bytes": source_bytes,
        "archive_bytes": archive_bytes,
    }

# ── Paths ────────────────────────────────────────────────────────────────────
GENERATION_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT  = GENERATION_DIR.parent.parent
BENCHMARK_DIR = PACKAGE_ROOT / "benchmark"

# Load .env so API keys are available to child processes
try:
    from dotenv import dotenv_values
    _ef = PACKAGE_ROOT / ".env"
    if _ef.exists():
        for _k, _v in dotenv_values(_ef).items():
            if _k not in os.environ:
                os.environ[_k] = _v
except Exception:
    pass

# ── Benchmark auto-discovery ─────────────────────────────────────────────────
def discover_benchmarks():
    bms = {}
    if not BENCHMARK_DIR.exists():
        return bms
    for d in sorted(BENCHMARK_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        yamls = list(d.glob("*.yaml"))
        configs = list(d.glob("*config*.json"))
        if yamls and configs:
            bms[d.name] = {
                "gen_config":     str(yamls[0]),
                "test_config":    str(configs[0]),
            }
    return bms

BENCHMARKS = discover_benchmarks()

# ── Framework registry ───────────────────────────────────────────────────────
#
# Fields per framework:
#   group      – runner category (see groups below)
#   python_role – interpreter role; resolved by python_for_role below
#   cwd        – subprocess working dir; relative to GENERATION_DIR if not absolute
#   script     – path to the runner script (relative to GENERATION_DIR)
#   mode       – for devs_native: --mode value
#   args       – extra flags appended to the command
#   extra_cfg  – free-form dict (fw_choice, skill_mode, skill_fw, etc.)
#
# Groups:
#   devs_native     → python -m devs_app.run --mode ...
#   baseline_single → python devs_baseline/single_*.py
#   baseline_runner → python devs_baseline/<runner_dir>/<script>
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_cwd(cwd_raw: str) -> str:
    """Return absolute cwd. Relative paths are resolved against GENERATION_DIR."""
    p = Path(cwd_raw)
    if p.is_absolute():
        return str(p)
    return str(GENERATION_DIR / p)


FRAMEWORK_REGISTRY: dict[str, dict] = {
    "devs_gen": {
        "group": "devs_native", "mode": "tool_debug",
        "args": ["--disable_check", "--concur_generate", "--concur_num", "8",
                 "--construct_variant", "recon_consensus_repair2",
                 "--enable_quick_smoke_repair"],
        "desc": "DEVS-Gen", "python_role": "devs", "cwd": ".",
    },
    "openhands": {
        "group": "baseline_runner",
        "script": "devs_baseline/openhands_run/run_openhands.py",
        "desc": "OpenHands",
        "python_role": "openhands", "cwd": "devs_baseline/openhands_run",
    },
    "openhands_lite": {
        "group": "baseline_runner",
        "script": "devs_baseline/openhands_run/run_openhands_fast.py",
        "desc": "OpenHands-Lite",
        "python_role": "openhands", "cwd": "devs_baseline/openhands_run",
    },
    "swe_agent": {
        "group": "baseline_runner",
        "script": "devs_baseline/swe_agent_run/run_swe_agent.py",
        "desc": "SWE-Agent",
        "python_role": "sweagent", "cwd": "devs_baseline/swe_agent_run",
    },
    "swe_agent_lite": {
        "group": "baseline_runner",
        "script": "devs_baseline/swe_agent_run/run_swe_agent_fast.py",
        "desc": "SWE-Agent-Lite",
        "python_role": "sweagent", "cwd": "devs_baseline/swe_agent_run",
    },
    "single_simpy": {
        "group": "baseline_single",
        "script": "devs_baseline/single_simpy.py",
        "desc": "Single-shot SimPy", "python_role": "devs", "cwd": ".",
    },
    "single_xdevs": {
        "group": "baseline_single",
        "script": "devs_baseline/single_xdevs.py",
        "desc": "Single-shot xDEVS", "python_role": "devs", "cwd": ".",
    },
}


# ── Logging ──────────────────────────────────────────────────────────────────
def log(tag, msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] [{tag}] {msg}", flush=True)


_ACTIVE_GENERATION_PROCESSES: set[subprocess.Popen] = set()
_ACTIVE_GENERATION_LOCK = threading.Lock()
_GENERATION_CANCEL_EVENT = threading.Event()


def _kill_generation_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def cancel_active_generations() -> None:
    """Prevent new generation children and kill every registered process group."""
    _GENERATION_CANCEL_EVENT.set()
    with _ACTIVE_GENERATION_LOCK:
        active = list(_ACTIVE_GENERATION_PROCESSES)
    for process in active:
        _kill_generation_process(process)


def reset_generation_cancellation() -> None:
    _GENERATION_CANCEL_EVENT.clear()


def _extract_generation_handshake(output: str) -> tuple[dict | None, str | None]:
    """Return the final typed adapter handshake and a diagnostic on failure."""
    matches = re.findall(
        r"<<<GENERATION_RESULT>>>\s*(.*?)\s*<<<GENERATION_RESULT>>>",
        output,
        re.DOTALL,
    )
    if not matches:
        return None, "generator did not emit a GENERATION_RESULT handshake"
    try:
        payload = json.loads(matches[-1])
    except json.JSONDecodeError as exc:
        return None, f"generator emitted invalid handshake JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "generator handshake must be a JSON object"
    if payload.get("status") != "success":
        return payload, str(payload.get("error") or "generator reported failure")
    if not isinstance(payload.get("sim_cwd"), str) or not payload["sim_cwd"].strip():
        return payload, "successful handshake omitted sim_cwd"
    if not isinstance(payload.get("sim_entry"), str) or not payload["sim_entry"].strip():
        return payload, "successful handshake omitted sim_entry"
    return payload, None


def _validate_handshake_artifact(
    payload: dict, workspace_dir: Path
) -> tuple[Path | None, Path | None, str | None]:
    """Resolve and validate the artifact named by a successful handshake."""
    workspace = workspace_dir.resolve()
    sim_cwd = Path(payload["sim_cwd"]).resolve()
    try:
        sim_cwd.relative_to(workspace)
    except ValueError:
        return None, None, f"sim_cwd escapes the requested workspace: {sim_cwd}"
    entry = (sim_cwd / payload["sim_entry"]).resolve()
    try:
        entry.relative_to(sim_cwd)
    except ValueError:
        return None, None, f"sim_entry escapes sim_cwd: {entry}"
    if not sim_cwd.is_dir():
        return None, None, f"sim_cwd does not exist: {sim_cwd}"
    if not entry.is_file():
        return None, None, f"sim_entry does not exist: {entry}"
    try:
        if entry.stat().st_size == 0:
            return None, None, f"sim_entry is empty: {entry}"
        compile(entry.read_text(encoding="utf-8"), str(entry), "exec")
    except (OSError, UnicodeError, SyntaxError) as exc:
        return None, None, f"sim_entry is not valid Python: {exc}"
    return sim_cwd, entry, None


# ── Python runtimes ───────────────────────────────────────────────────────────
PYTHON_ROLES = {
    "devs": ("DEVS_GEN_PYTHON", ".venvs/devs-gen"),
    "openhands": ("DEVS_OPENHANDS_PYTHON", ".venvs/openhands"),
    "sweagent": ("DEVS_SWEAGENT_PYTHON", ".venvs/sweagent"),
}


def python_for_role(role: str) -> Path:
    """Use the documented local venv or an explicitly selected interpreter."""
    variable, folder = PYTHON_ROLES[role]
    executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    configured = os.environ.get(variable)
    path = Path(configured).expanduser() if configured else PACKAGE_ROOT / folder / executable
    if not path.is_absolute():
        path = PACKAGE_ROOT / path
    # Keep a venv's python symlink intact: resolving it would bypass pyvenv.cfg.
    path = path.absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(
            f"{role} Python not found or not executable: {path}. "
            f"Create {folder} as described in README.md, or set {variable}."
        )
    return path


# ── Build generation command ─────────────────────────────────────────────────
def build_gen_cmd(
    fw_name: str,
    model_id: str,
    benchmark_name: str,
    workspace_dir: Path,
    root_plan_draft_count: int | None = None,
    concur_num: int | None = None,
) -> tuple[list[str], str]:
    """Build the full command to run generation for the given framework.

    Returns (command, cwd), with cwd as an absolute working directory.
    """
    cfg = FRAMEWORK_REGISTRY[fw_name]
    bm  = BENCHMARKS[benchmark_name]
    group = cfg["group"]
    python = str(python_for_role(cfg["python_role"]))
    cwd   = _resolve_cwd(cfg.get("cwd", "."))

    # ── Group: devs_native ───────────────────────────────────────────────
    if group == "devs_native":
        cmd = [python] + [
            "-m", "devs_app.run",
            "--mode",           cfg["mode"],
            "--debug_args_file", bm["gen_config"],
            "--target_tool",    "devs_construct_tree",
            "--working_directory", str(workspace_dir),
            "--model_id",       model_id,
            "--model_id_strong", model_id,
        ] + cfg.get("args", [])
        if root_plan_draft_count is not None:
            cmd += ["--root_plan_draft_count", str(root_plan_draft_count)]
        if concur_num is not None:
            if concur_num < 1:
                raise ValueError("concur_num must be positive")
            # argparse intentionally accepts repeated options and keeps the
            # last value.  Appending preserves the named framework profile
            # while allowing a run to respect a smaller provider budget.
            cmd += ["--concur_num", str(concur_num)]
        return cmd, cwd

    # ── Group: baseline_single ─────────────────────────────────────────
    if group == "baseline_single":
        # Direct API call scripts — flat workspace, need --benchmark
        script = GENERATION_DIR / cfg["script"]
        cmd = [python, str(script),
            "--config",     bm["gen_config"],
            "--workspace",  str(workspace_dir),
            "--model_id",   model_id,
            "--benchmark",  benchmark_name,
        ]
        return cmd, cwd

    # ── Group: baseline_runner ───────────────────────────────────────────
    if group == "baseline_runner":
        script = GENERATION_DIR / cfg["script"]
        cmd = [python, str(script),
            "--config",    bm["gen_config"],
            "--workspace", str(workspace_dir / "devs_project"),
            "--model_id",  model_id,
        ]
        return cmd, cwd

    raise ValueError(f"Unknown group for {fw_name!r}: {group!r}")


# ── Run single generation ────────────────────────────────────────────────────
def run_generation(
    fw_name: str,
    model_id: str,
    benchmark_name: str,
    workspace_dir: Path,
    timeout: int = 1800,
    verbose: bool = True,
    root_plan_draft_count: int | None = None,
    openrouter_only_providers: str | None = None,
    openrouter_ignore_providers: str | None = None,
    max_output_tokens: int | None = None,
    concur_num: int | None = None,
) -> dict:
    """Run one generation task.  Returns metadata dict."""
    cfg = FRAMEWORK_REGISTRY.get(fw_name)
    if not cfg:
        return {"status": "unknown_fw", "error": f"Framework {fw_name!r} not found"}
    if benchmark_name not in BENCHMARKS:
        return {"status": "unknown_bm", "error": f"Benchmark {benchmark_name!r} not found"}

    tag = f"{fw_name}/{benchmark_name}"
    log(tag, f"Starting (fw={fw_name}, model={model_id})")

    try:
        cmd, run_cwd = build_gen_cmd(
            fw_name,
            model_id,
            benchmark_name,
            workspace_dir,
            root_plan_draft_count,
            concur_num,
        )
        if max_output_tokens is not None and cfg["group"] == "devs_native":
            cmd += ["--max_output_tokens", str(max_output_tokens)]
    except Exception as e:
        log(tag, f"Cmd build failed: {e}", "ERROR")
        return {"status": "cmd_error", "error": str(e)}

    workspace_dir.mkdir(parents=True, exist_ok=True)
    stdout_p = workspace_dir / "gen_stdout.log.gz"
    stderr_p = workspace_dir / "gen_stderr.log.gz"
    meta_p   = workspace_dir / "gen_meta.json"

    started_at = datetime.now().isoformat()
    start = time.time()
    log(tag, f"CWD: {run_cwd}")
    if verbose:
        log(tag, f"CMD: {' '.join(cmd)}")

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    env["PATH"] = str(Path(cmd[0]).parent) + os.pathsep + env.get("PATH", "")
    if openrouter_only_providers is not None:
        env["DEVS_OPENROUTER_ONLY_PROVIDERS"] = openrouter_only_providers
    if openrouter_ignore_providers is not None:
        env["DEVS_OPENROUTER_IGNORE_PROVIDERS"] = openrouter_ignore_providers
    provider_policy = {
        "only": [
            item.strip()
            for item in env.get("DEVS_OPENROUTER_ONLY_PROVIDERS", "").split(",")
            if item.strip()
        ],
        "ignore": [
            item.strip()
            for item in env.get("DEVS_OPENROUTER_IGNORE_PROVIDERS", "novita").split(",")
            if item.strip()
        ],
        "allow_fallbacks": not bool(env.get("DEVS_OPENROUTER_ONLY_PROVIDERS", "").strip()),
    }
    try:
        stdout_capture = _BoundedTailCapture()
        stderr_capture = _BoundedTailCapture()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=run_cwd,
            env=env,
            start_new_session=(os.name == "posix"),
        )
        stdout_thread = threading.Thread(
            target=_drain_capture,
            args=(proc.stdout, stdout_capture),
            name="generation-stdout-drain",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_drain_capture,
            args=(proc.stderr, stderr_capture),
            name="generation-stderr-drain",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        timed_out = False
        with _ACTIVE_GENERATION_LOCK:
            _ACTIVE_GENERATION_PROCESSES.add(proc)
        try:
            if _GENERATION_CANCEL_EVENT.is_set():
                _kill_generation_process(proc)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_generation_process(proc)
                proc.wait()
            except KeyboardInterrupt:
                # Do not orphan a costly generator/API process when the outer
                # matrix or an operator interrupts this runner.
                _kill_generation_process(proc)
                raise
        finally:
            with _ACTIVE_GENERATION_LOCK:
                _ACTIVE_GENERATION_PROCESSES.discard(proc)
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            _write_bounded_log(stdout_p, stdout_capture)
            _write_bounded_log(stderr_p, stderr_capture)
        if timed_out:
            raise subprocess.TimeoutExpired(cmd, timeout)
        dur = round(time.time() - start, 2)

        # Parse handshake signal from stdout+stderr
        output = stdout_capture.text() + "\n" + stderr_capture.text()
        sim_cwd = entry_file = None
        token_usage = {}
        handshake, contract_error = _extract_generation_handshake(output)
        if handshake is not None:
            token_usage = handshake.get("token_usage", {})
        if contract_error is None and handshake is not None:
            resolved_cwd, resolved_entry, contract_error = _validate_handshake_artifact(
                handshake, workspace_dir
            )
            if contract_error is None:
                sim_cwd = str(resolved_cwd)
                entry_file = str(resolved_entry.relative_to(resolved_cwd))

        ok = proc.returncode == 0 and contract_error is None
        status = "success" if ok else "failed"

        meta = {
            "status":       status,
            "returncode":   proc.returncode,
            "duration_sec": dur,
            "start_time":   started_at,
            "sim_cwd":      sim_cwd,
            "entry_file":   entry_file,
            "token_usage":  token_usage,
            "framework":    fw_name,
            "model_id":     model_id,
            "benchmark":    benchmark_name,
            "command":      cmd,
            "run_cwd":      run_cwd,
            "contract_error": contract_error,
            "handshake": handshake,
            "openrouter_provider_policy": provider_policy,
            "max_output_tokens": max_output_tokens or 8192,
            "concur_num_override": concur_num,
        }
        meta["diagnostic_archive"] = _archive_generation_diagnostics(workspace_dir)
        meta_p.write_text(json.dumps(meta, indent=2))
        log(tag, f"Done ({status}) in {dur}s, sim_cwd={sim_cwd}")
        return meta

    except subprocess.TimeoutExpired:
        dur = round(time.time() - start, 2)
        log(tag, f"TIMEOUT after {dur}s", "ERROR")
        meta = {
            "status": "timeout",
            "duration_sec": dur,
            "start_time": started_at,
            "framework": fw_name,
            "model_id": model_id,
            "benchmark": benchmark_name,
            "command": cmd,
            "run_cwd": run_cwd,
            "openrouter_provider_policy": provider_policy,
            "max_output_tokens": max_output_tokens or 8192,
            "concur_num_override": concur_num,
        }
        meta["diagnostic_archive"] = _archive_generation_diagnostics(workspace_dir)
        meta_p.write_text(json.dumps(meta, indent=2))
        return meta
    except Exception as e:
        dur = round(time.time() - start, 2)
        log(tag, f"CRASH: {e}", "ERROR")
        meta = {
            "status": "crash",
            "duration_sec": dur,
            "start_time": started_at,
            "framework": fw_name,
            "model_id": model_id,
            "benchmark": benchmark_name,
            "command": cmd,
            "run_cwd": run_cwd,
            "error": str(e),
            "openrouter_provider_policy": provider_policy,
            "max_output_tokens": max_output_tokens or 8192,
            "concur_num_override": concur_num,
        }
        meta["diagnostic_archive"] = _archive_generation_diagnostics(workspace_dir)
        meta_p.write_text(json.dumps(meta, indent=2))
        return meta


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="Run a generation method on a DEVS benchmark scenario",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--framework", type=str)
    p.add_argument("--model", type=str, default=None)
    p.add_argument("--benchmark", type=str, default=None)
    p.add_argument("--workspace", type=str, default=None)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument(
        "--root-plan-draft-count",
        type=int,
        default=None,
        help="Override root planning: 0=one-shot, 1=draft+final, 2+=parallel drafts+final.",
    )
    p.add_argument(
        "--openrouter-only-providers",
        default=None,
        help="Comma-separated OpenRouter provider allowlist; disables fallback outside it.",
    )
    p.add_argument(
        "--openrouter-ignore-providers",
        default=None,
        help="Comma-separated OpenRouter provider denylist (default in recon: novita).",
    )
    p.add_argument(
        "--max-output-tokens",
        type=int,
        default=None,
        help="Per-call output cap for DEVS-native generation (default in recon: 8192).",
    )
    p.add_argument(
        "--concur-num",
        type=int,
        default=None,
        help="Override DEVS-native intra-run LLM concurrency for provider budgets.",
    )
    p.add_argument("--verbose", action="store_true", default=True, dest="verbose")
    p.add_argument("--silent", action="store_false", dest="verbose")
    p.add_argument("--list-frameworks", action="store_true")
    p.add_argument("--list-benchmarks", action="store_true")
    args = p.parse_args()

    if args.list_frameworks:
        print("Frameworks:")
        for n, i in FRAMEWORK_REGISTRY.items():
            try:
                python = str(python_for_role(i["python_role"]))
            except FileNotFoundError as exc:
                python = str(exc)
            print(f"  {n:20s} {i['desc']:20s} Python: {python}")
        return
    if args.list_benchmarks:
        print("Benchmarks:")
        for n in BENCHMARKS:
            print(f"  {n}")
        return

    if not args.framework or not args.model or not args.benchmark:
        p.error("--framework, --model, --benchmark required")
    if args.framework not in FRAMEWORK_REGISTRY:
        p.error(f"Unknown framework: {args.framework}")
    if args.benchmark not in BENCHMARKS:
        p.error(f"Unknown benchmark: {args.benchmark}")

    ws = Path(args.workspace) if args.workspace else \
         (GENERATION_DIR / "generated" / "_gen_workspace")
    ws = ws.resolve()

    result = run_generation(
        args.framework,
        args.model,
        args.benchmark,
        ws,
        args.timeout,
        args.verbose,
        args.root_plan_draft_count,
        args.openrouter_only_providers,
        args.openrouter_ignore_providers,
        args.max_output_tokens,
        args.concur_num,
    )
    print(json.dumps(result, indent=2))
    if result.get("status") != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
