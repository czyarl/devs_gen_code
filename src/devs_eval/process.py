"""Bounded subprocess runner that records failures without conflating them with scores."""

from __future__ import annotations

import os
import signal
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from devs_eval.errors import InfrastructureError
from devs_eval.models import ExecutionStatus


DEFAULT_MAX_STDOUT_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_STDERR_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_WORKSPACE_GROWTH_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class ProcessCapture:
    execution: ExecutionStatus
    stdout: str
    stderr: str
    stdout_sha256: str
    stderr_sha256: str


def _read_and_hash(handle, max_bytes: int) -> tuple[str, bool, bool, int, str]:
    import hashlib

    handle.seek(0)
    digest = hashlib.sha256()
    total = 0
    retained = bytearray()
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
        if len(retained) < max_bytes:
            retained.extend(chunk[: max_bytes - len(retained)])
    retained_bytes = bytes(retained)
    try:
        decoded = retained_bytes.decode("utf-8", errors="strict")
        utf8_valid = True
    except UnicodeDecodeError:
        decoded = retained_bytes.decode("utf-8", errors="replace")
        utf8_valid = False
    return (
        decoded,
        total > max_bytes,
        utf8_valid,
        total,
        digest.hexdigest(),
    )


def _regular_file_bytes(root: Path) -> int:
    """Return regular-file bytes without following generated symlinks."""
    total = 0
    for directory, _, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            try:
                metadata = os.stat(
                    Path(directory) / filename,
                    follow_symlinks=False,
                )
            except OSError:
                continue
            if stat.S_ISREG(metadata.st_mode):
                total += metadata.st_size
    return total


def _kill_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


def run_simulator(
    command: Sequence[str],
    *,
    cwd: str | Path,
    stdin_text: str = "",
    timeout_sec: float = 60.0,
    max_stdout_bytes: int = DEFAULT_MAX_STDOUT_BYTES,
    max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
    max_workspace_growth_bytes: int = DEFAULT_MAX_WORKSPACE_GROWTH_BYTES,
    environment: Mapping[str, str] | None = None,
) -> ProcessCapture:
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise InfrastructureError("simulator command must contain non-empty strings")
    if (
        timeout_sec <= 0
        or max_stdout_bytes <= 0
        or max_stderr_bytes <= 0
        or max_workspace_growth_bytes <= 0
    ):
        raise InfrastructureError("runner limits must be positive")
    working_directory = Path(cwd)
    if not working_directory.is_dir():
        raise InfrastructureError(f"simulator working directory does not exist: {cwd}")
    start = time.monotonic()
    try:
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            timed_out = False
            workspace_limit_exceeded = False
            initial_workspace_bytes = _regular_file_bytes(working_directory)
            peak_workspace_growth = 0
            monitor_stop = threading.Event()
            monitor_triggered = threading.Event()
            return_code: int | None
            process = subprocess.Popen(
                list(command),
                cwd=working_directory,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                env=dict(environment) if environment is not None else None,
                start_new_session=(os.name == "posix"),
            )

            def monitor_workspace() -> None:
                nonlocal peak_workspace_growth
                while not monitor_stop.wait(0.05):
                    current = _regular_file_bytes(working_directory)
                    growth = max(0, current - initial_workspace_bytes)
                    peak_workspace_growth = max(peak_workspace_growth, growth)
                    if growth > max_workspace_growth_bytes:
                        monitor_triggered.set()
                        _kill_process_group(process)
                        return

            monitor = threading.Thread(
                target=monitor_workspace,
                name="hamlet-workspace-limit",
                daemon=True,
            )
            monitor.start()
            try:
                process.communicate(
                    input=stdin_text.encode("utf-8"), timeout=timeout_sec
                )
                return_code = process.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                return_code = None
                _kill_process_group(process)
                process.communicate()
            finally:
                monitor_stop.set()
                monitor.join(timeout=1)
                workspace_limit_exceeded = monitor_triggered.is_set()
                peak_workspace_growth = max(
                    peak_workspace_growth,
                    max(0, _regular_file_bytes(working_directory) - initial_workspace_bytes),
                )
                workspace_limit_exceeded = (
                    workspace_limit_exceeded
                    or peak_workspace_growth > max_workspace_growth_bytes
                )
            duration = time.monotonic() - start
            (
                stdout,
                stdout_truncated,
                stdout_utf8_valid,
                stdout_bytes,
                stdout_sha256,
            ) = _read_and_hash(stdout_file, max_stdout_bytes)
            (
                stderr,
                stderr_truncated,
                _,
                stderr_bytes,
                stderr_sha256,
            ) = _read_and_hash(stderr_file, max_stderr_bytes)
        return ProcessCapture(
            execution=ExecutionStatus(
                return_code=return_code,
                timed_out=timed_out,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
                stdout_utf8_valid=stdout_utf8_valid,
                stdout_bytes=stdout_bytes,
                stderr_bytes=stderr_bytes,
                workspace_limit_exceeded=workspace_limit_exceeded,
                workspace_growth_bytes=peak_workspace_growth,
                duration_sec=duration,
            ),
            stdout=stdout,
            stderr=stderr,
            stdout_sha256=stdout_sha256,
            stderr_sha256=stderr_sha256,
        )
    except OSError as exc:
        raise InfrastructureError(f"failed to launch simulator: {exc}") from exc
