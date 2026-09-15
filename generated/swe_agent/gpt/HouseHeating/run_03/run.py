#!/usr/bin/env python3
"""House heating temperature control simulation.

Implements the specification in the PR description:
- Python 3.10+
- argparse CLI
- outdoor temperature schedule read from stdin
- JSONL observations to stdout
- debug to stderr
- deterministic discrete-event simulation using simpy
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import List, Tuple

import simpy


TARGET_TEMP_C = 24.9
INITIAL_ROOM_TEMP_C = 25.0
LOSS_FRACTION = 0.10
HEATER_GAIN_C = 0.5
DEFAULT_OUTDOOR_C = 25.0


def _hms_to_seconds(hms: str) -> int:
    parts = hms.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {hms!r}")
    h, m, s = (int(p) for p in parts)
    if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
        raise ValueError(f"Invalid timestamp (out of range): {hms!r}")
    return h * 3600 + m * 60 + s


@dataclass(frozen=True)
class OutdoorSchedule:
    # Sorted list of (time_sec, temp_c)
    readings: List[Tuple[int, float]]

    @classmethod
    def from_stdin(cls) -> "OutdoorSchedule":
        readings: List[Tuple[int, float]] = []
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                ts, temp = line.split(maxsplit=1)
            except ValueError as e:
                raise ValueError(f"Invalid schedule line (expected 'HH:MM:SS temp'): {line!r}") from e
            t = _hms_to_seconds(ts)
            try:
                temp_c = float(temp)
            except ValueError as e:
                raise ValueError(f"Invalid temperature value in line: {line!r}") from e
            readings.append((t, temp_c))

        readings.sort(key=lambda x: x[0])
        return cls(readings=readings)

    def outdoor_at(self, t: int) -> float:
        """Greatest timestamp <= t, else default."""
        # Linear scan is fine for typical small schedules; keep minimal.
        # If schedule is large, could binary search.
        best = None
        for ts, temp in self.readings:
            if ts <= t:
                best = temp
            else:
                break
        return DEFAULT_OUTDOOR_C if best is None else float(best)


class HouseModel:
    def __init__(self, env: simpy.Environment, schedule: OutdoorSchedule, simulate_time: int):
        self.env = env
        self.schedule = schedule
        self.simulate_time = simulate_time

        # State at observation time t
        self.room_temp_c = float(INITIAL_ROOM_TEMP_C)
        self.control_signal = 0  # control_signal[0]

        # Start process
        self.proc = env.process(self.run())

    def run(self):
        # Observations for t=1..simulate_time
        for t in range(1, self.simulate_time + 1):
            # Advance simulation time by 1 second
            yield self.env.timeout(1)

            prev_room = self.room_temp_c
            prev_control = self.control_signal

            # Effective outdoor temperature from previous second (t-1)
            outdoor = self.schedule.outdoor_at(t - 1)
            effective_outdoor = min(outdoor, prev_room)

            # Heat loss: lose 10% of gap
            heat_loss_temp = prev_room - LOSS_FRACTION * (prev_room - effective_outdoor)

            # Heater gain delayed by one step
            heater_output = HEATER_GAIN_C if prev_control == 1 else 0.0
            new_room = heat_loss_temp + heater_output

            # Next control signal based on new room temp
            next_control = 1 if new_room < TARGET_TEMP_C else 0

            # Update internal state
            self.room_temp_c = float(new_room)
            self.control_signal = int(next_control)

            # Emit observation
            obs = {
                "time_sec": int(t),
                "room_temp_c": float(self.room_temp_c),
                "heat_loss_temp_c": float(heat_loss_temp),
                "control_signal": int(self.control_signal),
                "heater_output_c": float(heater_output),
            }
            sys.stdout.write(json.dumps(obs, separators=(",", ":")) + "\n")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="House heating temperature control simulation")
    parser.add_argument(
        "--simulate_time",
        required=True,
        type=float,
        help="Total simulation duration in seconds (integer part used)",
    )
    args = parser.parse_args(argv)

    simulate_time_int = int(args.simulate_time)
    if simulate_time_int < 0:
        print("--simulate_time must be non-negative", file=sys.stderr)
        return 2

    try:
        schedule = OutdoorSchedule.from_stdin()
    except Exception as e:
        print(f"Failed to parse outdoor temperature schedule: {e}", file=sys.stderr)
        return 2

    env = simpy.Environment(initial_time=0)
    HouseModel(env, schedule=schedule, simulate_time=simulate_time_int)

    # Run until all events processed
    env.run(until=simulate_time_int + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
