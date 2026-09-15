#!/usr/bin/env python3
"""House heating temperature control simulation.

Implements the specification described in the PR description:
- Python 3.10+
- Discrete-event simulation using simpy
- Reads outdoor temperature schedule from stdin
- Outputs JSONL observations to stdout for each integer second 1..int(simulate_time)
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
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {s!r}")
    h, m, sec = (int(p) for p in parts)
    if not (0 <= m < 60 and 0 <= sec < 60 and h >= 0):
        raise ValueError(f"Invalid timestamp (out of range): {s!r}")
    return h * 3600 + m * 60 + sec


def read_outdoor_schedule(stdin) -> List[Tuple[int, float]]:
    """Read schedule lines: 'HH:MM:SS temp'. Returns sorted list of (time_sec, temp)."""
    schedule: List[Tuple[int, float]] = []
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        # allow extra whitespace
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"Invalid schedule line (expected 'HH:MM:SS temp'): {line!r}")
        t = _parse_hhmmss_to_seconds(parts[0])
        try:
            temp = float(parts[1])
        except ValueError as e:
            raise ValueError(f"Invalid temperature in line: {line!r}") from e
        schedule.append((t, temp))

    schedule.sort(key=lambda x: x[0])
    return schedule


@dataclass
class OutdoorSchedule:
    readings: List[Tuple[int, float]]

    def __post_init__(self) -> None:
        self._idx = 0
        self._current = 25.0

    def update_to_time(self, t: int) -> None:
        # advance pointer while next reading time <= t
        while self._idx < len(self.readings) and self.readings[self._idx][0] <= t:
            self._current = float(self.readings[self._idx][1])
            self._idx += 1

    def get_for_time(self, t: int) -> float:
        # ensure current reflects greatest timestamp <= t
        self.update_to_time(t)
        return self._current


class HouseHeaterSim:
    def __init__(self, env: simpy.Environment, outdoor: OutdoorSchedule):
        self.env = env
        self.outdoor = outdoor

        # state at time 0
        self.room_temp_c = 25.0
        self.control_signal = 0  # control_signal[0]

    def step(self, t: int) -> dict:
        """Advance one second from t-1 to t and return observation at time t."""
        prev_room = self.room_temp_c
        prev_control = int(self.control_signal)

        # effective outdoor temperature from previous second (t-1)
        scheduled_outdoor = self.outdoor.get_for_time(t - 1)
        effective_outdoor = min(scheduled_outdoor, prev_room)

        # heat loss: lose 10% of gap
        heat_loss_temp = prev_room - 0.1 * (prev_room - effective_outdoor)

        # heater gain delayed by one step
        heater_output = 0.5 if prev_control == 1 else 0.0
        new_room = heat_loss_temp + heater_output

        # controller sets next control signal based on new room temp
        next_control = 1 if new_room < 24.9 else 0

        # commit state
        self.room_temp_c = new_room
        self.control_signal = next_control

        return {
            "time_sec": int(t),
            "room_temp_c": float(new_room),
            "heat_loss_temp_c": float(heat_loss_temp),
            "control_signal": int(next_control),
            "heater_output_c": float(heater_output),
        }


def simulation_process(env: simpy.Environment, sim: HouseHeaterSim, duration_int: int):
    # Observations required for t=1..duration_int
    for t in range(1, duration_int + 1):
        # wait until next integer second
        yield env.timeout(1)
        obs = sim.step(t)
        print(json.dumps(obs, separators=(",", ":")), flush=False)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="House heating temperature control simulation")
    parser.add_argument("--simulate_time", type=float, required=True, help="Total simulation duration in seconds")
    args = parser.parse_args(argv)

    duration_int = int(args.simulate_time)
    if duration_int < 0:
        raise SystemExit("--simulate_time must be non-negative")

    schedule = read_outdoor_schedule(sys.stdin)
    outdoor = OutdoorSchedule(schedule)

    env = simpy.Environment()
    sim = HouseHeaterSim(env, outdoor)

    env.process(simulation_process(env, sim, duration_int))
    env.run(until=duration_int + 1)  # run enough to emit last observation

    # ensure stdout flush
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
