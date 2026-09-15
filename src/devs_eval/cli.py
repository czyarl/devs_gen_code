"""Command-line interface for manifest validation and scenario execution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from devs_eval.errors import DevsEvalError
from devs_eval.manifest import load_checker, load_manifest
from devs_eval.pipeline import run_scenario
from devs_eval.serialization import dumps_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DEVS benchmark evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-manifest")
    validate.add_argument("manifest")

    run = subparsers.add_parser("run-scenario")
    run.add_argument("--manifest", required=True)
    run.add_argument("--simulator-directory", required=True)
    run.add_argument("--simulator-entry", default="run.py")
    run.add_argument("--output-directory", required=True)
    run.add_argument("--python-executable", default=sys.executable)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        rules = load_checker(manifest, args.manifest)
        if args.command == "validate-manifest":
            print(
                dumps_json(
                    {
                        "valid": True,
                        "scenario_id": manifest.scenario_id,
                        "protocol_version": manifest.protocol_version,
                        "benchmark_version": manifest.benchmark_version,
                    }
                )
            )
            return 0
        result = run_scenario(
            manifest,
            rules,
            simulator_directory=args.simulator_directory,
            simulator_entry=args.simulator_entry,
            output_directory=args.output_directory,
            python_executable=args.python_executable,
            resource_directory=Path(args.manifest).resolve().parent,
        )
        print(dumps_json(result))
        return 0
    except DevsEvalError as exc:
        print(f"devs-eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
