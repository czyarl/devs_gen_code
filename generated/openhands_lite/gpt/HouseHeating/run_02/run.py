#!/usr/bin/env python3
import argparse
import bisect
import json
import sys
from dataclasses import dataclass

import simpy


def _parse_hh_mm_ss(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    h, m, sec = (int(p) for p in parts)
    if h < 0 or m < 0 or m >= 60 or sec < 0 or sec >= 60:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    return h * 3600 + m * 60 + sec


@dataclass(frozen=True)
class OutdoorSchedule:
    times: list[int]
    temps: list[float]

    @classmethod
    def from_stdin(cls) -> "OutdoorSchedule":
        readings: list[tuple[int, float]] = []
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                raise ValueError(f"Invalid schedule line: {raw!r}")
            t_sec = _parse_hh_mm_ss(parts[0])
            temp = float(parts[1])
            readings.append((t_sec, temp))

        if not readings:
            return cls(times=[], temps=[])

        readings.sort(key=lambda x: x[0])
        times: list[int] = []
        temps: list[float] = []

        # If multiple readings share the same timestamp, keep the last one.
        for t_sec, temp in readings:
            if times and times[-1] == t_sec:
                temps[-1] = temp
            else:
                times.append(t_sec)
                temps.append(temp)

        return cls(times=times, temps=temps)

    def at(self, t_sec: int) -> float:
        idx = bisect.bisect_right(self.times, t_sec) - 1
        if idx < 0:
            return 25.0
        return self.temps[idx]


class HeatingSimulation:
    def __init__(self, env: simpy.Environment, schedule: OutdoorSchedule, steps: int):
        self.env = env
        self.schedule = schedule
        self.steps = steps

        self.prev_room_temp = 25.0
        self.prev_control_signal = 0

    def run(self):
        for step in range(1, self.steps + 1):
            yield self.env.timeout(1)

            prev_t = step - 1
            scheduled_outdoor = self.schedule.at(prev_t)
            effective_outdoor = min(scheduled_outdoor, self.prev_room_temp)

            heat_loss_temp = self.prev_room_temp - 0.1 * (self.prev_room_temp - effective_outdoor)
            heater_output = 0.5 if self.prev_control_signal == 1 else 0.0
            room_temp = heat_loss_temp + heater_output

            control_signal = 1 if room_temp < 24.9 else 0

            obs = {
                "time_sec": step,
                "room_temp_c": room_temp,
                "heat_loss_temp_c": heat_loss_temp,
                "control_signal": int(control_signal),
                "heater_output_c": heater_output,
            }
            sys.stdout.write(json.dumps(obs) + "\n")

            self.prev_room_temp = room_temp
            self.prev_control_signal = control_signal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args(argv)

    steps = int(args.simulate_time)
    if steps <= 0:
        return 0

    try:
        schedule = OutdoorSchedule.from_stdin()
    except Exception as e:
        print(f"Failed to parse outdoor schedule: {e}", file=sys.stderr)
        return 2

    env = simpy.Environment()
    sim = HeatingSimulation(env=env, schedule=schedule, steps=steps)
    env.process(sim.run())
    env.run(until=steps + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
