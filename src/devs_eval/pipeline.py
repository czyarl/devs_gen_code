"""End-to-end execution of one simulator artifact against one scenario."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from devs_eval.errors import InfrastructureError
from devs_eval.models import EvaluatedCase, ScenarioEvaluation, ScenarioManifest
from devs_eval.operational import evaluate_operational_output
from devs_eval.rules import BehavioralRule
from devs_eval.process import run_simulator
from devs_eval.scoring import evaluate_scenario
from devs_eval.serialization import write_json


_ARTIFACT_HASH_FORMAT = "hamlet-artifact-tree-v1"
_RESOURCE_HASH_FORMAT = "hamlet-resource-files-v1"
_ARTIFACT_IGNORED_DIRECTORIES = {".git", ".pytest_cache", "__pycache__"}
_ARTIFACT_IGNORED_SUFFIXES = {".pyc", ".pyo"}
_PERSISTED_STDOUT_BYTES = 1 * 1024 * 1024
_PERSISTED_STDERR_BYTES = 256 * 1024


def file_digest(path: str | Path) -> str:
    artifact = Path(path)
    if not artifact.is_file():
        raise InfrastructureError(f"artifact file does not exist: {artifact}")
    digest = hashlib.sha256()
    with artifact.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_inventory(path: str | Path) -> tuple[dict[str, Any], ...]:
    """Return the deterministic pre-execution inventory of a simulator tree."""
    artifact_root = Path(path)
    if not artifact_root.is_dir():
        raise InfrastructureError(f"simulator artifact directory does not exist: {artifact_root}")
    inventory: list[dict[str, Any]] = []
    candidates = sorted(
        artifact_root.rglob("*"), key=lambda item: item.relative_to(artifact_root).as_posix()
    )
    for candidate in candidates:
        relative = candidate.relative_to(artifact_root)
        if any(part in _ARTIFACT_IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if candidate.is_symlink():
            raise InfrastructureError(
                f"simulator artifact may not contain symbolic links: {relative}"
            )
        if candidate.suffix in _ARTIFACT_IGNORED_SUFFIXES or not candidate.is_file():
            continue
        inventory.append(
            {
                "path": relative.as_posix(),
                "size_bytes": candidate.stat().st_size,
                "sha256": file_digest(candidate),
            }
        )
    if not inventory:
        raise InfrastructureError(f"simulator artifact directory contains no files: {artifact_root}")
    return tuple(inventory)


def artifact_digest(path: str | Path) -> str:
    inventory = artifact_inventory(path)
    payload = json.dumps(
        {"format": _ARTIFACT_HASH_FORMAT, "files": inventory},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _copy_artifact_snapshot(
    source_root: Path,
    inventory: tuple[dict[str, Any], ...],
    destination_root: Path,
) -> None:
    """Materialize exactly the pre-hashed files for one isolated case run."""
    destination_root.mkdir(parents=True, exist_ok=False)
    for item in inventory:
        relative = Path(str(item["path"]))
        source = source_root / relative
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _argument_vector(sim_args: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for name, value in sim_args.items():
        if not isinstance(name, str) or not name:
            raise InfrastructureError("simulator argument names must be non-empty strings")
        if isinstance(value, (dict, list)) or value is None:
            raise InfrastructureError(
                f"simulator argument {name!r} must be a scalar value, got {type(value).__name__}"
            )
        if name.startswith("--"):
            if len(name) == 2:
                raise InfrastructureError("simulator argument name cannot be only '--'")
            option = name
        elif name.startswith("-"):
            raise InfrastructureError(
                f"simulator argument {name!r} must use a long --option name"
            )
        else:
            option = f"--{name}"
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        result.extend((option, rendered))
    return result


def _resolve_resource_args(
    sim_args: Mapping[str, Any], resource_directory: str | Path | None
) -> dict[str, Any]:
    """Resolve declared relative file arguments against the manifest directory."""
    resolved = dict(sim_args)
    if resource_directory is None:
        return resolved
    root = Path(resource_directory).resolve()
    for name, value in tuple(resolved.items()):
        normalized = name.lstrip("-")
        is_file_argument = normalized in {"input_file", "config_file"} or normalized.endswith(
            "_file"
        )
        if not is_file_argument or not isinstance(value, str):
            continue
        declared = Path(value)
        if declared.is_absolute():
            continue
        candidate = (root / declared).resolve()
        if candidate != root and root not in candidate.parents:
            raise InfrastructureError(
                f"simulator resource argument {name!r} escapes manifest directory: {value!r}"
            )
        if not candidate.is_file():
            raise InfrastructureError(
                f"simulator resource argument {name!r} does not exist: {candidate}"
            )
        resolved[name] = str(candidate)
    return resolved


def _is_file_argument(name: str) -> bool:
    normalized = name.lstrip("-")
    return normalized in {"input_file", "config_file"} or normalized.endswith("_file")


def _stage_resource_args(
    resolved_args: Mapping[str, Any], case_root: Path
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Copy declared file resources into the isolated per-case filesystem."""
    staged = dict(resolved_args)
    inventory: list[dict[str, Any]] = []
    resource_root = case_root / "resources"
    for index, (name, value) in enumerate(resolved_args.items()):
        if not _is_file_argument(name) or not isinstance(value, str):
            continue
        source = Path(value).resolve()
        if not source.is_file():
            raise InfrastructureError(
                f"simulator resource argument {name!r} does not exist: {source}"
            )
        destination = resource_root / f"{index:03d}_{source.name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_digest = file_digest(source)
        shutil.copy2(source, destination)
        staged_digest = file_digest(destination)
        if staged_digest != source_digest:
            raise InfrastructureError(
                f"simulator resource argument {name!r} changed while being staged"
            )
        staged[name] = str(destination)
        inventory.append(
            {
                "argument": name,
                "declared_value": value,
                "source_path": str(source),
                "size_bytes": destination.stat().st_size,
                "sha256": staged_digest,
            }
        )
    return staged, tuple(inventory)


def _sandboxed_command(
    command: list[str], *, case_root: Path, simulator_directory: Path
) -> tuple[list[str], dict[str, str]]:
    """Wrap untrusted simulator code in a networkless, minimal read filesystem."""
    unshare = Path("/usr/bin/unshare")
    bwrap = Path("/usr/bin/bwrap")
    prlimit = Path("/usr/bin/prlimit")
    if (
        os.name != "posix"
        or not unshare.is_file()
        or not bwrap.is_file()
        or not prlimit.is_file()
    ):
        raise InfrastructureError(
            "secure simulator isolation requires Linux with unshare, bwrap, and prlimit"
        )
    _verify_sandbox_capability()
    # Keep the executable's virtual-environment path. Resolving a venv's
    # python symlink to /usr/bin/python would hide its site-packages inside
    # the sandbox even though the caller selected that environment.
    python_path = Path(command[0]).absolute()
    if not python_path.is_file():
        raise InfrastructureError(f"python executable does not exist: {python_path}")
    isolated = [
        str(prlimit),
        "--as=4294967296",
        "--nproc=512",
        "--fsize=67108864",
        "--nofile=256",
        "--core=0",
        "--",
        str(unshare),
        "-Urn",
        str(bwrap),
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
        "--die-with-parent",
        "--new-session",
    ]
    for system_path in (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64")):
        if system_path.exists():
            isolated.extend(("--ro-bind", str(system_path), str(system_path)))
    isolated.extend(("--tmpfs", "/tmp"))
    python_prefix = python_path.parents[1]
    base_python_prefix = python_path.resolve().parents[1]
    for prefix in dict.fromkeys((python_prefix, base_python_prefix)):
        if not any(prefix == root or root in prefix.parents
                   for root in (Path("/usr"), Path("/bin"))):
            isolated.extend(("--ro-bind", str(prefix), str(prefix)))
    isolated.extend(
        (
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--bind",
            str(case_root),
            str(case_root),
            "--chdir",
            str(simulator_directory),
            str(python_path),
            *command[1:],
        )
    )
    environment = {
        "PATH": f"{python_prefix / 'bin'}:/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return isolated, environment


@lru_cache(maxsize=1)
def _verify_sandbox_capability() -> None:
    """Fail as infrastructure before scoring when namespace setup is unavailable."""
    command = [
        "/usr/bin/prlimit",
        "--as=4294967296",
        "--nproc=512",
        "--fsize=67108864",
        "--nofile=256",
        "--core=0",
        "--",
        "/usr/bin/unshare",
        "-Urn",
        "/usr/bin/bwrap",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/usr",
        "/usr",
    ]
    for system_path in ("/bin", "/lib", "/lib64"):
        if Path(system_path).exists():
            command.extend(("--ro-bind", system_path, system_path))
    command.extend(("--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "/usr/bin/true"))
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InfrastructureError(f"secure simulator isolation probe failed: {exc}") from exc
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise InfrastructureError(
            "secure simulator isolation is unavailable"
            + (f": {diagnostic}" if diagnostic else "")
        )


def _prepare_output_directory(path: str | Path) -> Path:
    output = Path(path)
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise InfrastructureError(
            f"output directory already exists; refusing to overwrite: {output}"
        ) from exc
    except OSError as exc:
        raise InfrastructureError(f"cannot create output directory {output}: {exc}") from exc
    return output


def _utf8_prefix(text: str, max_bytes: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _write_gzip_text(path: Path, content: str) -> None:
    """Write a deterministic gzip member so archived evidence remains hashable."""
    try:
        with path.open("wb") as raw_handle:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_handle,
                compresslevel=9,
                mtime=0,
            ) as gzip_handle:
                gzip_handle.write(content.encode("utf-8"))
    except OSError as exc:
        raise InfrastructureError(f"cannot write evaluation artifact {path}: {exc}") from exc


def run_scenario(
    manifest: ScenarioManifest,
    rules: Mapping[str, BehavioralRule],
    *,
    simulator_directory: str | Path,
    simulator_entry: str,
    output_directory: str | Path,
    python_executable: str = sys.executable,
    resource_directory: str | Path | None = None,
) -> ScenarioEvaluation:
    simulator_dir = Path(simulator_directory).resolve()
    if not simulator_dir.is_dir():
        raise InfrastructureError(f"simulator directory does not exist: {simulator_dir}")
    entry_path = (simulator_dir / simulator_entry).resolve()
    if entry_path.parent != simulator_dir and simulator_dir not in entry_path.parents:
        raise InfrastructureError("simulator entry must remain inside simulator_directory")
    entry_digest = file_digest(entry_path)
    entry_relative = entry_path.relative_to(simulator_dir)
    inventory = artifact_inventory(simulator_dir)
    digest_payload = json.dumps(
        {"format": _ARTIFACT_HASH_FORMAT, "files": inventory},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(digest_payload).hexdigest()
    output = _prepare_output_directory(output_directory)
    evaluated_cases: list[EvaluatedCase] = []
    case_resource_files: dict[str, tuple[dict[str, Any], ...]] = {}
    for test_case in manifest.test_cases:
        case_schema = manifest.trace_schema
        if test_case.allow_empty_trace is not None:
            case_schema = replace(
                case_schema, allow_empty_trace=test_case.allow_empty_trace
            )
        effective_sim_args = _resolve_resource_args(
            test_case.sim_args, resource_directory
        )
        case_output = output / test_case.case_id
        try:
            case_output.mkdir()
        except OSError as exc:
            raise InfrastructureError(f"cannot create case output {case_output}: {exc}") from exc
        with tempfile.TemporaryDirectory(prefix=f"hamlet-{test_case.case_id}-") as temp:
            case_root = Path(temp)
            case_simulator_dir = case_root / "artifact"
            _copy_artifact_snapshot(simulator_dir, inventory, case_simulator_dir)
            isolated_entry = case_simulator_dir / entry_relative
            staged_sim_args, resource_files = _stage_resource_args(
                effective_sim_args, case_root
            )
            case_resource_files[test_case.case_id] = resource_files
            raw_command = [
                python_executable,
                str(isolated_entry),
                *_argument_vector(staged_sim_args),
            ]
            command, environment = _sandboxed_command(
                raw_command,
                case_root=case_root,
                simulator_directory=case_simulator_dir,
            )
            capture = run_simulator(
                command,
                cwd=case_root,
                stdin_text=test_case.sim_stdin,
                timeout_sec=test_case.timeout_sec,
                environment=environment,
            )
        evaluated = evaluate_operational_output(
            case_id=test_case.case_id,
            entry_id=digest,
            config={
                "sim_args": dict(test_case.sim_args),
                "sim_stdin": test_case.sim_stdin,
                "checker_config": dict(test_case.checker_config),
            },
            execution=capture.execution,
            stdout=capture.stdout,
            schema=case_schema,
        )
        evaluated_cases.append(evaluated)
        persisted_stdout, stdout_archive_truncated = _utf8_prefix(
            capture.stdout, _PERSISTED_STDOUT_BYTES
        )
        persisted_stderr, stderr_archive_truncated = _utf8_prefix(
            capture.stderr, _PERSISTED_STDERR_BYTES
        )
        stdout_archive = case_output / "stdout.jsonl.gz"
        stderr_archive = case_output / "stderr.log.gz"
        _write_gzip_text(stdout_archive, persisted_stdout)
        _write_gzip_text(stderr_archive, persisted_stderr)
        write_json(
            case_output / "execution.json",
            {
                "entry_id": digest,
                "command": command,
                "raw_simulator_command": raw_command,
                "case_artifact_isolation": "fresh_copy_of_prehashed_tree",
                "declared_sim_args": dict(test_case.sim_args),
                "effective_sim_args": effective_sim_args,
                "sandbox_sim_args": staged_sim_args,
                "resource_hash_format": _RESOURCE_HASH_FORMAT,
                "resource_files": resource_files,
                "simulator_environment_keys": sorted(environment),
                "config": evaluated.config,
                "sim_stdin_sha256": hashlib.sha256(
                    test_case.sim_stdin.encode("utf-8")
                ).hexdigest(),
                "timeout_sec": test_case.timeout_sec,
                "trace_policy": {
                    "allow_empty_trace": case_schema.allow_empty_trace,
                },
                "stdout_path": str(stdout_archive),
                "stderr_path": str(stderr_archive),
                "stdout_compression": "gzip",
                "stderr_compression": "gzip",
                "stdout_stream_sha256": capture.stdout_sha256,
                "stderr_stream_sha256": capture.stderr_sha256,
                "stdout_persisted_sha256": hashlib.sha256(
                    persisted_stdout.encode("utf-8")
                ).hexdigest(),
                "stderr_persisted_sha256": hashlib.sha256(
                    persisted_stderr.encode("utf-8")
                ).hexdigest(),
                "stdout_archive_sha256": file_digest(stdout_archive),
                "stderr_archive_sha256": file_digest(stderr_archive),
                "stdout_persisted_bytes": len(persisted_stdout.encode("utf-8")),
                "stderr_persisted_bytes": len(persisted_stderr.encode("utf-8")),
                "stdout_persisted_truncated": stdout_archive_truncated,
                "stderr_persisted_truncated": stderr_archive_truncated,
                "execution": capture.execution,
                "operational": evaluated.operational,
            },
        )
    result = evaluate_scenario(manifest, evaluated_cases, rules)
    resource_payload = json.dumps(
        {
            "format": _RESOURCE_HASH_FORMAT,
            "cases": case_resource_files,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    write_json(
        output / "scenario_result.json",
        {
            "evaluator_version": "0.2.0",
            "simulator_entry": simulator_entry,
            "simulator_entry_sha256": entry_digest,
            "simulator_artifact_hash_format": _ARTIFACT_HASH_FORMAT,
            "simulator_artifact_sha256": digest,
            "simulator_artifact_files": inventory,
            "resource_hash_format": _RESOURCE_HASH_FORMAT,
            "resource_files_by_case": case_resource_files,
            "resource_files_sha256": hashlib.sha256(resource_payload).hexdigest(),
            "result": result,
        },
    )
    return result
