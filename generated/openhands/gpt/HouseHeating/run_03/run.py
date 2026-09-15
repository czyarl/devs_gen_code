#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass
from typing import Dict, List

import simpy


TARGET_TEMP_C = 24.9
DEFAULT_OUTDOOR_TEMP_C = 25.0
HEAT_LOSS_FRACTION = 0.10
HEATER_GAIN_C = 0.5


def _time_str_to_seconds(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    h, m, sec = (int(p) for p in parts)
    if h < 0 or m < 0 or sec < 0 or m >= 60 or sec >= 60:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    return h * 3600 + m * 60 + sec


@dataclass
class OutdoorSchedule:
    times_sec: List[int]
    temps_c: List[float]

    _idx: int = -1

    @classmethod
    def from_stdin(cls, stdin) -> "OutdoorSchedule":
        latest_by_time: Dict[int, float] = {}
        for line_no, raw in enumerate(stdin, start=1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"Invalid schedule line {line_no}: {raw!r}")
            t = _time_str_to_seconds(parts[0])
            try:
                temp = float(parts[1])
            except ValueError as e:
                raise ValueError(f"Invalid temperature at line {line_no}: {raw!r}") from e
            latest_by_time[t] = temp

        if not latest_by_time:
            return cls(times_sec=[], temps_c=[])

        times = sorted(latest_by_time.keys())
        temps = [latest_by_time[t] for t in times]
        return cls(times_sec=times, temps_c=temps)

    def temp_at(self, t_sec: int) -> float:
        if not self.times_sec:
            return DEFAULT_OUTDOOR_TEMP_C

        if self._idx < 0:
            if t_sec < self.times_sec[0]:
                return DEFAULT_OUTDOOR_TEMP_C
            self._idx = 0

        while self._idx + 1 < len(self.times_sec) and self.times_sec[self._idx + 1] <= t_sec:
            self._idx += 1

        if t_sec < self.times_sec[0]:
            return DEFAULT_OUTDOOR_TEMP_C
        return self.temps_c[self._idx]


def simulate(simulate_time_sec: float, schedule: OutdoorSchedule) -> None:
    steps = int(simulate_time_sec)
    if steps <= 0:
        return

    env = simpy.Environment()

    room_temp = 25.0
    control_signal_prev = 0

    def process():
        nonlocal room_temp, control_signal_prev

        for _ in range(steps):
            yield env.timeout(1)
            t = int(env.now)

            outdoor_raw = schedule.temp_at(t - 1)
            outdoor_eff = outdoor_raw if outdoor_raw <= room_temp else room_temp

            heat_loss_temp = room_temp - HEAT_LOSS_FRACTION * (room_temp - outdoor_eff)

            heater_output = HEATER_GAIN_C if control_signal_prev == 1 else 0.0
            new_room_temp = heat_loss_temp + heater_output

            control_signal_next = 1 if new_room_temp < TARGET_TEMP_C else 0

            obs = {
                "time_sec": t,
                "room_temp_c": float(new_room_temp),
                "heat_loss_temp_c": float(heat_loss_temp),
                "control_signal": int(control_signal_next),
                "heater_output_c": float(heater_output),
            }
            sys.stdout.write(json.dumps(obs, separators=(",", ":")) + "\n")

            room_temp = new_room_temp
            control_signal_prev = control_signal_next

    env.process(process())
    env.run()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--simulate_time",
        required=True,
        type=float,
        help="Total simulation duration in seconds (integer part used).",
    )
    args = parser.parse_args(argv)

    try:
        schedule = OutdoorSchedule.from_stdin(sys.stdin)
    except Exception as e:
        print(f"Error parsing outdoor temperature schedule: {e}", file=sys.stderr)
        return 2

    if args.simulate_time < 0:
        print("--simulate_time must be non-negative", file=sys.stderr)
        return 2

    simulate(args.simulate_time, schedule)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
