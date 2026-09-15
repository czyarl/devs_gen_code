#!/usr/bin/env python3
import argparse
import sys

from house_heating.schedule import OutdoorTempSchedule
from house_heating.sim import SimulationConfig, run_simulation


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="House heating DES simulation")
    parser.add_argument(
        "--simulate_time",
        type=float,
        required=True,
        help="Total simulation duration in seconds (integer part is used)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    steps = int(args.simulate_time)

    schedule = OutdoorTempSchedule.from_stream(sys.stdin)
    cfg = SimulationConfig(total_seconds=steps)

    for record in run_simulation(cfg=cfg, schedule=schedule, debug_stream=sys.stderr):
        sys.stdout.write(record + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
