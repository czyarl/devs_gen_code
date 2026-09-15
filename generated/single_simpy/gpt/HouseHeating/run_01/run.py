#!/usr/bin/env python3
import sys
import json
import argparse
from dataclasses import dataclass
from typing import List, Tuple, Optional


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def parse_hhmmss_to_seconds(s: str) -> int:
    s = s.strip()
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    hh, mm, ss = parts
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


@dataclass
class OutdoorSchedule:
    # Sorted list of (time_sec, temp_c)
    readings: List[Tuple[int, float]]

    @staticmethod
    def from_stdin(stdin) -> "OutdoorSchedule":
        readings: List[Tuple[int, float]] = []
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"Invalid schedule line (expected 'HH:MM:SS temp'): {line!r}")
            t = parse_hhmmss_to_seconds(parts[0])
            temp = float(parts[1])
            readings.append((t, temp))
        readings.sort(key=lambda x: x[0])
        return OutdoorSchedule(readings=readings)

    def get_temp_at(self, t_sec: int) -> float:
        # greatest timestamp <= t_sec; default 25.0 if none
        if not self.readings:
            return 25.0
        # binary search
        lo, hi = 0, len(self.readings) - 1
        if self.readings[0][0] > t_sec:
            return 25.0
        # find rightmost <= t_sec
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.readings[mid][0] <= t_sec:
                lo = mid + 1
            else:
                hi = mid - 1
        return self.readings[hi][1]


def simulate(simulate_time: float, schedule: OutdoorSchedule):
    n_steps = int(simulate_time)

    # Initial state at time 0
    room_temp = 25.0
    control_signal = 0  # control_signal[0] = 0

    for t in range(1, n_steps + 1):
        prev_room_temp = room_temp
        prev_control = control_signal

        # Effective outdoor temperature from previous second (t-1)
        outdoor = schedule.get_temp_at(t - 1)
        effective_outdoor = outdoor if outdoor <= prev_room_temp else prev_room_temp

        # Apply heat loss: lose 10% of the gap between room and effective outdoor
        heat_loss_temp = prev_room_temp - 0.1 * (prev_room_temp - effective_outdoor)

        # Heater gain delayed by one step: depends on previous control signal
        heater_output = 0.5 if prev_control == 1 else 0.0

        # New room temperature
        room_temp = heat_loss_temp + heater_output

        # Controller sets next control signal based on new room temperature
        control_signal = 1 if room_temp < 24.9 else 0

        # Output observable state at time t
        record = {
            "time_sec": t,
            "room_temp_c": float(room_temp),
            "heat_loss_temp_c": float(heat_loss_temp),
            "control_signal": int(control_signal),
            "heater_output_c": float(heater_output),
        }
        sys.stdout.write(json.dumps(record, separators=(",", ":")) + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="House heating bang-bang controller simulation (JSONL output).")
    parser.add_argument("--simulate_time", type=float, required=True, help="Total simulation duration in seconds.")
    args = parser.parse_args(argv)

    try:
        schedule = OutdoorSchedule.from_stdin(sys.stdin)
    except Exception as ex:
        eprint(f"Error parsing outdoor temperature schedule from stdin: {ex}")
        return 2

    try:
        simulate(args.simulate_time, schedule)
    except BrokenPipeError:
        # Allow piping to head, etc.
        return 0
    except Exception as ex:
        eprint(f"Simulation error: {ex}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())