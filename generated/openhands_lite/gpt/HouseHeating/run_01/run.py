#!/usr/bin/env python3
import argparse
import bisect
import json
import sys
from dataclasses import dataclass
from typing import List, TextIO, Tuple

import simpy


def _parse_hhmmss(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {value!r}")
    h, m, s = (int(p) for p in parts)
    if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
        raise ValueError(f"Invalid timestamp (out of range): {value!r}")
    return h * 3600 + m * 60 + s


@dataclass(frozen=True)
class OutdoorSchedule:
    times_sec: List[int]
    temps_c: List[float]

    @classmethod
    def from_stdin(cls, stdin: TextIO) -> "OutdoorSchedule":
        pairs: List[Tuple[int, float]] = []
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                raise ValueError(f"Invalid schedule line (expected 'HH:MM:SS temp'): {line!r}")
            t = _parse_hhmmss(parts[0])
            temp = float(parts[1])
            pairs.append((t, temp))

        pairs.sort(key=lambda x: x[0])
        times = [t for t, _ in pairs]
        temps = [v for _, v in pairs]
        return cls(times, temps)

    def at(self, t_sec: int, default: float = 25.0) -> float:
        idx = bisect.bisect_right(self.times_sec, t_sec) - 1
        if idx < 0:
            return default
        return self.temps_c[idx]


def _simulate_process(
    env: simpy.Environment,
    horizon_sec: int,
    schedule: OutdoorSchedule,
    stdout: TextIO,
) -> "simpy.events.Event":
    room_temp = 25.0
    control_signal = 0  # applies to next step

    for t in range(1, horizon_sec + 1):
        yield env.timeout(1)

        outdoor = schedule.at(t - 1, default=25.0)
        effective_outdoor = min(outdoor, room_temp)

        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor)
        heater_output = 0.5 if control_signal == 1 else 0.0
        room_temp = heat_loss_temp + heater_output

        control_signal = 1 if room_temp < 24.9 else 0

        record = {
            "time_sec": int(t),
            "room_temp_c": float(room_temp),
            "heat_loss_temp_c": float(heat_loss_temp),
            "control_signal": int(control_signal),
            "heater_output_c": float(heater_output),
        }
        stdout.write(json.dumps(record, separators=(",", ":")) + "\n")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="House heating bang-bang controller simulation")
    parser.add_argument(
        "--simulate_time",
        required=True,
        type=float,
        help="Total simulation duration in seconds (observations for 1..int(simulate_time)).",
    )
    args = parser.parse_args(argv)

    horizon_sec = int(args.simulate_time)
    if horizon_sec < 0:
        print("simulate_time must be non-negative", file=sys.stderr)
        return 2

    try:
        schedule = OutdoorSchedule.from_stdin(sys.stdin)
    except Exception as e:
        print(f"Failed to parse outdoor schedule: {e}", file=sys.stderr)
        return 2

    env = simpy.Environment()
    env.process(_simulate_process(env, horizon_sec, schedule, sys.stdout))
    env.run(until=horizon_sec + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
