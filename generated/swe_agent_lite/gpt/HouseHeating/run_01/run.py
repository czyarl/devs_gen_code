#!/usr/bin/env python3
"""House heating temperature control simulation (DES via simpy).

Reads an outdoor temperature schedule from stdin and prints JSONL
observations to stdout for each integer simulation second.

See PR description/spec for exact observable behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import List, Tuple

import simpy


def _parse_hhmmss_to_seconds(token: str) -> int:
    parts = token.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {token!r}")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


def read_outdoor_schedule(stdin_text: str) -> List[Tuple[int, float]]:
    """Parse stdin schedule lines into sorted (time_sec, temp_c) list."""
    readings: List[Tuple[int, float]] = []
    for raw in stdin_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Allow extra whitespace
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"Invalid schedule line: {raw!r}")
        t = _parse_hhmmss_to_seconds(parts[0])
        temp = float(parts[1])
        readings.append((t, temp))

    readings.sort(key=lambda x: x[0])
    return readings


@dataclass
class OutdoorSchedule:
    readings: List[Tuple[int, float]]

    def temp_at(self, t: int) -> float:
        """Return scheduled outdoor temperature at time t (seconds).

        Uses the reading with greatest timestamp <= t. If none, 25.0.
        """
        if not self.readings:
            return 25.0
        # Binary search for rightmost reading with time <= t
        lo, hi = 0, len(self.readings)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.readings[mid][0] <= t:
                lo = mid + 1
            else:
                hi = mid
        idx = lo - 1
        if idx < 0:
            return 25.0
        return float(self.readings[idx][1])


@dataclass
class State:
    room_temp_c: float = 25.0
    control_signal: int = 0  # control_signal[0] = 0


def simulate(simulate_time: float, schedule: OutdoorSchedule) -> None:
    """Run simulation and emit JSONL observations to stdout."""

    env = simpy.Environment(initial_time=0)
    state = State()

    # We observe at each integer second t=1..T where T=int(simulate_time)
    T = int(simulate_time)

    def process():
        # At time 0, initial state exists but is not output.
        # For each step t=1..T, update from previous observation at t-1.
        for t in range(1, T + 1):
            # Wait until next integer second in simulation time.
            yield env.timeout(1)

            prev_room = state.room_temp_c
            prev_control = state.control_signal

            # Effective outdoor temperature from previous second (t-1)
            outdoor = schedule.temp_at(t - 1)
            effective_outdoor = outdoor if outdoor <= prev_room else prev_room

            # Heat loss: lose 10% of gap between prev_room and effective_outdoor
            heat_loss_temp = prev_room - 0.1 * (prev_room - effective_outdoor)

            # Heater gain delayed by one step: depends on prev_control
            heater_output = 0.5 if prev_control == 1 else 0.0

            new_room = heat_loss_temp + heater_output

            # Controller sets next control signal based on new room temp
            next_control = 1 if new_room < 24.9 else 0

            # Update state for next step
            state.room_temp_c = new_room
            state.control_signal = next_control

            # Emit observation at time t
            obs = {
                "time_sec": int(t),
                "room_temp_c": float(new_room),
                "heat_loss_temp_c": float(heat_loss_temp),
                "control_signal": int(next_control),
                "heater_output_c": float(heater_output),
            }
            sys.stdout.write(json.dumps(obs, separators=(",", ":")) + "\n")

    env.process(process())
    env.run(until=T)  # process yields exactly T seconds


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="House heating DES simulation")
    parser.add_argument(
        "--simulate_time",
        required=True,
        type=float,
        help="Total simulation duration in seconds (observations for 1..int(simulate_time))",
    )
    args = parser.parse_args(argv)

    try:
        schedule_readings = read_outdoor_schedule(sys.stdin.read())
    except Exception as e:
        print(f"Failed to parse outdoor schedule: {e}", file=sys.stderr)
        return 2

    schedule = OutdoorSchedule(schedule_readings)

    try:
        simulate(args.simulate_time, schedule)
    except Exception as e:
        print(f"Simulation error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
