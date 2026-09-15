#!/usr/bin/env python3
import argparse
import bisect
import json
import sys
from dataclasses import dataclass
from typing import List, Optional, TextIO, Tuple

import simpy


def _parse_hhmmss_to_seconds(hhmmss: str) -> int:
    parts = hhmmss.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {hhmmss!r}")
    hh, mm, ss = (int(p) for p in parts)
    if hh < 0 or mm < 0 or mm > 59 or ss < 0 or ss > 59:
        raise ValueError(f"Invalid timestamp values: {hhmmss!r}")
    return hh * 3600 + mm * 60 + ss


@dataclass(frozen=True)
class OutdoorSchedule:
    times_sec: List[int]
    temps_c: List[float]

    @classmethod
    def from_stdin(cls, stdin: TextIO) -> "OutdoorSchedule":
        entries: List[Tuple[int, float]] = []
        for line_no, raw in enumerate(stdin, start=1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"Invalid schedule line {line_no}: {raw.rstrip()!r}")
            t_sec = _parse_hhmmss_to_seconds(parts[0])
            temp_c = float(parts[1])
            entries.append((t_sec, temp_c))

        entries.sort(key=lambda x: x[0])
        times = [t for t, _ in entries]
        temps = [v for _, v in entries]
        return cls(times_sec=times, temps_c=temps)

    def temp_at(self, t_sec: int) -> float:
        """Return last known outdoor temp at or before t_sec; default 25.0."""
        if not self.times_sec:
            return 25.0
        idx = bisect.bisect_right(self.times_sec, t_sec) - 1
        if idx < 0:
            return 25.0
        return self.temps_c[idx]


def simulation_process(
    env: simpy.Environment,
    schedule: OutdoorSchedule,
    steps: int,
    stdout: TextIO,
) -> "simpy.events.Event":
    room_temp = 25.0
    prev_control = 0

    for t in range(1, steps + 1):
        outdoor = schedule.temp_at(t - 1)
        outdoor_eff = outdoor if outdoor <= room_temp else room_temp

        heat_loss_temp = room_temp - 0.1 * (room_temp - outdoor_eff)
        heater_output = 0.5 if prev_control == 1 else 0.0
        new_room_temp = heat_loss_temp + heater_output

        control = 1 if new_room_temp < 24.9 else 0

        yield env.timeout(1)

        record = {
            "time_sec": int(env.now),
            "room_temp_c": float(new_room_temp),
            "heat_loss_temp_c": float(heat_loss_temp),
            "control_signal": int(control),
            "heater_output_c": float(heater_output),
        }
        stdout.write(json.dumps(record) + "\n")

        room_temp = new_room_temp
        prev_control = control


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--simulate_time",
        type=float,
        required=True,
        help="Total simulation duration in seconds; integer part is used.",
    )
    args = parser.parse_args(argv)

    steps = int(args.simulate_time)
    if steps < 0:
        print("--simulate_time must be non-negative", file=sys.stderr)
        return 2

    try:
        schedule = OutdoorSchedule.from_stdin(sys.stdin)
    except Exception as e:
        print(f"Failed to parse outdoor schedule: {e}", file=sys.stderr)
        return 2

    env = simpy.Environment(initial_time=0)
    env.process(simulation_process(env, schedule, steps, sys.stdout))
    env.run(until=steps)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
