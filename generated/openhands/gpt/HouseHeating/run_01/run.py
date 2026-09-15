#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass
from typing import List

import simpy


def _parse_hhmmss_to_seconds(hhmmss: str) -> int:
    parts = hhmmss.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {hhmmss!r}")
    h, m, s = (int(p) for p in parts)
    return h * 3600 + m * 60 + s


@dataclass
class OutdoorSchedule:
    default_temp_c: float = 25.0
    _times: List[int] = None
    _temps: List[float] = None
    _idx: int = 0

    @classmethod
    def from_stdin(cls, stdin_text: str, default_temp_c: float = 25.0) -> "OutdoorSchedule":
        latest_by_time: dict[int, float] = {}
        for raw in stdin_text.splitlines():
            line = raw.strip()
            if not line:
                continue
            ts_str, temp_str = line.split(maxsplit=1)
            t_sec = _parse_hhmmss_to_seconds(ts_str)
            latest_by_time[t_sec] = float(temp_str)

        times = sorted(latest_by_time.keys())
        temps = [latest_by_time[t] for t in times]
        return cls(default_temp_c=default_temp_c, _times=times, _temps=temps, _idx=0)

    def temp_at(self, t_sec: int) -> float:
        if not self._times:
            return self.default_temp_c

        while self._idx + 1 < len(self._times) and self._times[self._idx + 1] <= t_sec:
            self._idx += 1

        if self._times[self._idx] <= t_sec:
            return self._temps[self._idx]
        return self.default_temp_c


def _emit_observation(
    *,
    time_sec: int,
    room_temp_c: float,
    heat_loss_temp_c: float,
    control_signal: int,
    heater_output_c: float,
) -> None:
    rec = {
        "time_sec": int(time_sec),
        "room_temp_c": float(round(room_temp_c, 6)),
        "heat_loss_temp_c": float(round(heat_loss_temp_c, 6)),
        "control_signal": int(control_signal),
        "heater_output_c": float(round(heater_output_c, 6)),
    }
    sys.stdout.write(json.dumps(rec, separators=(",", ":")) + "\n")


def simulate(env: simpy.Environment, *, steps: int, schedule: OutdoorSchedule) -> simpy.events.Event:
    room_temp = 25.0
    prev_control_signal = 0

    for step in range(1, steps + 1):
        t_prev = step - 1

        outdoor_temp = schedule.temp_at(t_prev)
        effective_outdoor = min(outdoor_temp, room_temp)

        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor)

        heater_output = 0.5 if prev_control_signal == 1 else 0.0
        room_temp = heat_loss_temp + heater_output

        control_signal = 1 if room_temp < 24.9 else 0

        _emit_observation(
            time_sec=step,
            room_temp_c=room_temp,
            heat_loss_temp_c=heat_loss_temp,
            control_signal=control_signal,
            heater_output_c=heater_output,
        )

        prev_control_signal = control_signal
        yield env.timeout(1)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args(argv)

    steps = int(args.simulate_time)
    if steps < 0:
        raise SystemExit("--simulate_time must be non-negative")

    schedule = OutdoorSchedule.from_stdin(sys.stdin.read(), default_temp_c=25.0)

    if steps == 0:
        return 0

    env = simpy.Environment()
    env.process(simulate(env, steps=steps, schedule=schedule))
    env.run(until=steps)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
