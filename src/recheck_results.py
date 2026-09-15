"""Re-evaluate bundled programs without retaining their execution logs."""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from pathlib import Path

from devs_eval.manifest import load_checker, load_manifest
from devs_eval.pipeline import run_scenario


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("task_results.csv", "single_ablations.csv")
FIELDS = (
    "source", "task_id", "method", "model", "scenario", "run", "status",
    "reported_score_ope", "rechecked_score_ope", "reported_score_beh",
    "rechecked_score_beh", "reported_fully_operational",
    "rechecked_fully_operational", "scores_match",
)


def _rows():
    for source in SOURCES:
        with (ROOT / "results" / source).open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                yield source, row


def _program_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT / "generated"):
        raise ValueError(f"generated_code escapes the generated directory: {relative}")
    if not (path / "run.py").is_file():
        raise ValueError(f"generated_code has no run.py: {relative}")
    return path


def _recheck(row: dict[str, str], python_executable: str):
    manifest_path = ROOT / "benchmark" / row["scenario"] / "manifest.json"
    manifest = load_manifest(manifest_path)
    if manifest.scenario_id != row["scenario"]:
        raise ValueError(f"scenario mismatch in {manifest_path}")
    program = _program_path(row["generated_code"])
    with tempfile.TemporaryDirectory(prefix="devs_recheck_") as temporary:
        return run_scenario(
            manifest,
            load_checker(manifest, manifest_path),
            simulator_directory=program,
            simulator_entry="run.py",
            output_directory=Path(temporary) / "evaluation",
            python_executable=python_executable,
            resource_directory=manifest_path.parent,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New comparison CSV; never overwritten")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--method")
    parser.add_argument("--model")
    parser.add_argument("--scenario")
    parser.add_argument("--task-id")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    selected = matched = differing = missing = 0
    try:
        handle = output.open("x", newline="", encoding="utf-8")
    except FileExistsError:
        parser.error(f"output already exists: {output}")
    with handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for source, row in _rows():
            if any(value is not None and row[key] != value for key, value in (
                ("method", args.method), ("model", args.model),
                ("scenario", args.scenario), ("task_id", args.task_id),
            )):
                continue
            if args.limit is not None and selected >= args.limit:
                break
            selected += 1
            result_row = {
                "source": source,
                **{key: row[key] for key in ("task_id", "method", "model", "scenario", "run")},
                "reported_score_ope": row["score_ope"],
                "reported_score_beh": row["score_beh"],
                "reported_fully_operational": row["fully_operational"],
            }
            if not row["generated_code"]:
                result_row["status"] = "no_program"
                missing += 1
            else:
                result = _recheck(row, args.python_executable)
                same = (
                    abs(result.operational_score - float(row["score_ope"])) < 1e-6
                    and abs(result.behavioral_score - float(row["score_beh"])) < 1e-6
                    and result.fully_operational == (row["fully_operational"] == "1")
                )
                result_row.update({
                    "status": "scored_stochastic" if row["scenario"] in {"IOBS", "OTrain"} else "scored",
                    "rechecked_score_ope": result.operational_score,
                    "rechecked_score_beh": result.behavioral_score,
                    "rechecked_fully_operational": int(result.fully_operational),
                    "scores_match": int(same),
                })
                matched += same
                differing += not same
            writer.writerow(result_row)
            handle.flush()
    print(f"selected={selected} matched={matched} differing={differing} no_program={missing}")
    print(f"Wrote {output}")
    return 0 if selected else 2


if __name__ == "__main__":
    raise SystemExit(main())
