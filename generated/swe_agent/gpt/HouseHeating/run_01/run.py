#!/usr/bin/env python3
"""House heating temperature control simulation.

Reads an outdoor temperature schedule from stdin and prints JSONL
observations to stdout for each integer simulation second.

Implements the dynamics described in the PR description using a
(discrete-event) SimPy environment.
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
INITIAL_CONTROL_SIGNAL = 0
HEATER_GAIN_C = 0.5
LOSS_FRACTION = 0.10
DEFAULT_OUTDOOR_TEMP_C = 25.0


def _parse_hhmmss_to_seconds(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp '{s}', expected HH:MM:SS")
    h, m, sec = (int(p) for p in parts)
    return h * 3600 + m * 60 + sec


def read_schedule_from_stdin(stdin) -> List[Tuple[int, float]]:
    schedule: List[Tuple[int, float]] = []
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        ts_str, temp_str = line.split(maxsplit=1)
        t = _parse_hhmmss_to_seconds(ts_str)
        temp = float(temp_str)
        schedule.append((t, temp))
    schedule.sort(key=lambda x: x[0])
    return schedule


@dataclass
class OutdoorSchedule:
    readings: List[Tuple[int, float]]

    def __post_init__(self) -> None:
        self._idx = 0

    def get(self, t: int) -> float:
        # Advance index while next reading timestamp <= t
        while self._idx + 1 < len(self.readings) and self.readings[self._idx + 1][0] <= t:
            self._idx += 1
        if not self.readings or self.readings[0][0] > t:
            return DEFAULT_OUTDOOR_TEMP_C
        return self.readings[self._idx][1]


@dataclass
class State:
    room_temp_c: float = INITIAL_ROOM_TEMP_C
    control_signal: int = INITIAL_CONTROL_SIGNAL  # applied next step


def simulate(simulate_time: float, schedule: OutdoorSchedule, stdout, stderr) -> None:
    end_t = int(simulate_time)

    env = simpy.Environment(initial_time=0)
    state = State()

    def process():
        # Observations are for t=1..end_t inclusive.
        for t in range(1, end_t + 1):
            # Wait until next integer second.
            yield env.timeout(1)

            prev_room = state.room_temp_c
            prev_control = state.control_signal

            # Outdoor temperature from previous second (t-1)
            outdoor = schedule.get(t - 1)
            effective_outdoor = min(outdoor, prev_room)

            heat_loss_temp = prev_room - LOSS_FRACTION * (prev_room - effective_outdoor)

            heater_output = HEATER_GAIN_C if prev_control == 1 else 0.0
            new_room = heat_loss_temp + heater_output

            next_control = 1 if new_room < TARGET_TEMP_C else 0

            state.room_temp_c = new_room
            state.control_signal = next_control

            rec = {
                "time_sec": t,
                "room_temp_c": float(new_room),
                "heat_loss_temp_c": float(heat_loss_temp),
                "control_signal": int(next_control),
                "heater_output_c": float(heater_output),
            }
            stdout.write(json.dumps(rec) + "\n")

    env.process(process())
    env.run(until=end_t + 1)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args(argv)

    schedule_readings = read_schedule_from_stdin(sys.stdin)
    schedule = OutdoorSchedule(schedule_readings)

    simulate(args.simulate_time, schedule, sys.stdout, sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
