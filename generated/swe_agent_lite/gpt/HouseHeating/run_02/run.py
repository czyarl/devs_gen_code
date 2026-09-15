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
    h, m, s = (int(p) for p in parts)
    if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
        raise ValueError(f"Invalid timestamp values: {token!r}")
    return h * 3600 + m * 60 + s


@dataclass(frozen=True)
class OutdoorSchedule:
    """Piecewise-constant outdoor temperature schedule."""

    readings: List[Tuple[int, float]]  # sorted by time_sec

    @staticmethod
    def from_stdin(stdin: object = sys.stdin) -> "OutdoorSchedule":
        readings: List[Tuple[int, float]] = []
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(
                    f"Invalid schedule line (expected 'HH:MM:SS temp'): {line!r}"
                )
            t = _parse_hhmmss_to_seconds(parts[0])
            temp = float(parts[1])
            readings.append((t, temp))

        readings.sort(key=lambda x: x[0])
        return OutdoorSchedule(readings=readings)

    def temp_at(self, t_sec: int) -> float:
        """Return scheduled outdoor temperature at simulation time t_sec.

        Uses the reading with greatest timestamp <= t_sec. If none, 25.0.
        """
        if not self.readings:
            return 25.0

        # Binary search for rightmost reading with time <= t_sec
        lo, hi = 0, len(self.readings) - 1
        if t_sec < self.readings[0][0]:
            return 25.0
        if t_sec >= self.readings[hi][0]:
            return self.readings[hi][1]

        while lo <= hi:
            mid = (lo + hi) // 2
            tm, _ = self.readings[mid]
            if tm <= t_sec:
                lo = mid + 1
            else:
                hi = mid - 1
        # hi is now index of rightmost <= t_sec
        return self.readings[hi][1]


@dataclass
class State:
    room_temp_c: float = 25.0
    control_signal: int = 0  # control_signal[0] = 0


def simulate(simulate_time: float, schedule: OutdoorSchedule) -> None:
    """Run simulation and emit JSONL observations to stdout."""

    horizon = int(simulate_time)
    env = simpy.Environment()
    state = State()

    def process() -> simpy.events.Event:
        # Observations required for seconds 1..horizon.
        for t in range(1, horizon + 1):
            # Advance simulation time by 1 second.
            yield env.timeout(1)

            prev_room = state.room_temp_c
            prev_control = state.control_signal

            # Effective outdoor temperature from previous second (t-1)
            outdoor = schedule.temp_at(t - 1)
            effective_outdoor = outdoor if outdoor <= prev_room else prev_room

            # Heat loss: lose 10% of gap to effective outdoor
            heat_loss_temp = prev_room - 0.1 * (prev_room - effective_outdoor)

            # Heater gain delayed by one step
            heater_output = 0.5 if prev_control == 1 else 0.0
            new_room = heat_loss_temp + heater_output

            # Next control signal based on new room temperature
            next_control = 1 if new_room < 24.9 else 0

            # Update state
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
    env.run(until=horizon + 1)


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
        print(f"Failed to parse outdoor temperature schedule: {e}", file=sys.stderr)
        return 2

    simulate(args.simulate_time, schedule)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
