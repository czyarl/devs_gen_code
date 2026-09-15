#!/usr/bin/env python3
"""House heating temperature control simulation (DES).

Reads an outdoor temperature schedule from stdin and prints JSONL
observations to stdout for each integer simulation second.

Implements the specification in the PR description using a deterministic
SimPy discrete-event simulation.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import List, Tuple

import simpy


def _parse_hhmmss_to_seconds(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp '{s}', expected HH:MM:SS")
    h, m, sec = (int(p) for p in parts)
    if h < 0 or m < 0 or m >= 60 or sec < 0 or sec >= 60:
        raise ValueError(f"Invalid timestamp '{s}', expected HH:MM:SS")
    return h * 3600 + m * 60 + sec


@dataclass(frozen=True)
class OutdoorSchedule:
    """Piecewise-constant outdoor temperature schedule."""

    readings: List[Tuple[int, float]]  # sorted by time_sec

    @staticmethod
    def from_stdin(stdin: object) -> "OutdoorSchedule":
        readings: List[Tuple[int, float]] = []
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                ts_str, temp_str = line.split(maxsplit=1)
            except ValueError as e:
                raise ValueError(f"Invalid schedule line: {raw!r}") from e
            t = _parse_hhmmss_to_seconds(ts_str)
            try:
                temp = float(temp_str)
            except ValueError as e:
                raise ValueError(f"Invalid temperature in line: {raw!r}") from e
            readings.append((t, temp))

        readings.sort(key=lambda x: x[0])
        return OutdoorSchedule(readings=readings)

    def temp_at(self, t: int) -> float:
        """Return scheduled outdoor temperature at simulation time t (seconds).

        Uses the reading with greatest timestamp <= t. If none, returns 25.0.
        """
        # Linear scan is fine for typical small schedules; keep deterministic.
        # If needed, could be replaced with bisect.
        last: float | None = None
        for ts, temp in self.readings:
            if ts <= t:
                last = temp
            else:
                break
        return 25.0 if last is None else last


@dataclass
class RoomState:
    room_temp_c: float = 25.0
    control_signal: int = 0  # control_signal[0] = 0


def simulate(simulate_time: float, schedule: OutdoorSchedule) -> None:
    """Run the DES simulation and emit JSONL observations to stdout."""

    horizon = int(simulate_time)
    env = simpy.Environment()
    state = RoomState()

    def step_process() -> simpy.events.Event:
        # Observations are required for seconds 1..horizon.
        for t in range(1, horizon + 1):
            # Advance simulation time to the next integer second.
            yield env.timeout(1)

            prev_room = state.room_temp_c
            prev_control = state.control_signal

            # Outdoor temperature from previous second (t-1), capped.
            outdoor = schedule.temp_at(t - 1)
            effective_outdoor = outdoor if outdoor <= prev_room else prev_room

            # Heat loss: lose 10% of the gap to effective outdoor.
            heat_loss_temp = prev_room - 0.1 * (prev_room - effective_outdoor)

            # Heater gain delayed by one step.
            heater_output = 0.5 if prev_control == 1 else 0.0
            new_room = heat_loss_temp + heater_output

            # Controller sets next control signal based on new room temp.
            next_control = 1 if new_room < 24.9 else 0

            # Update state.
            state.room_temp_c = new_room
            state.control_signal = next_control

            # Emit observation at time t.
            record = {
                "time_sec": t,
                "room_temp_c": float(new_room),
                "heat_loss_temp_c": float(heat_loss_temp),
                "control_signal": int(next_control),
                "heater_output_c": float(heater_output),
            }
            sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")

    env.process(step_process())
    env.run(until=horizon + 1)  # run through the last timeout


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
        schedule = OutdoorSchedule.from_stdin(sys.stdin)
    except Exception as e:
        print(f"Error parsing outdoor temperature schedule: {e}", file=sys.stderr)
        return 2

    simulate(args.simulate_time, schedule)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
