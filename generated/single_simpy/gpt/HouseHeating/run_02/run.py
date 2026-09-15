#!/usr/bin/env python3
import sys
import json
import argparse
from dataclasses import dataclass
from typing import List, Tuple


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def parse_hhmmss_to_seconds(s: str) -> int:
    parts = s.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid HH:MM:SS timestamp: {s!r}")
    hh, mm, ss = parts
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


@dataclass
class OutdoorSchedule:
    # Sorted list of (time_sec, temp_c)
    readings: List[Tuple[int, float]]

    @staticmethod
    def from_stdin(stdin_text: str) -> "OutdoorSchedule":
        readings: List[Tuple[int, float]] = []
        for line_no, raw in enumerate(stdin_text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"Invalid schedule line {line_no}: {raw!r}")
            t = parse_hhmmss_to_seconds(parts[0])
            temp = float(parts[1])
            readings.append((t, temp))
        readings.sort(key=lambda x: x[0])
        return OutdoorSchedule(readings=readings)

    def temp_at(self, t_sec: int) -> float:
        """
        Greatest timestamp <= t_sec; if none, 25.0.
        """
        if not self.readings:
            return 25.0
        # Binary search for rightmost reading with time <= t_sec
        lo, hi = 0, len(self.readings) - 1
        if self.readings[0][0] > t_sec:
            return 25.0
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.readings[mid][0] <= t_sec:
                lo = mid + 1
            else:
                hi = mid - 1
        # hi is now the index of rightmost <= t_sec
        return self.readings[hi][1]


def simulate(simulate_time: float, schedule: OutdoorSchedule):
    """
    Yields observation dicts for time_sec = 1..int(simulate_time).
    Dynamics:
      - Effective outdoor temp for step t uses schedule at (t-1), capped to prev room temp.
      - Heat loss: room loses 10% of gap to effective outdoor: T_loss = T_prev - 0.1*(T_prev - T_out_eff)
      - Heater output at step t depends on previous control signal: +0.5 if u_prev==1 else +0.0
      - New room temp: T_new = T_loss + heater_output
      - New control signal u_new = 1 if T_new < 24.9 else 0
    Observed at each integer time t:
      time_sec=t, room_temp_c=T_new, heat_loss_temp_c=T_loss, control_signal=u_new, heater_output_c=heater_output
    """
    n = int(simulate_time)

    room_temp = 25.0
    control_signal_prev = 0  # control_signal[0]
    # heater output at time 0 is 0.0 by definition; applied starting from step 1 based on control_signal_prev

    for t in range(1, n + 1):
        outdoor_sched = schedule.temp_at(t - 1)
        outdoor_eff = outdoor_sched if outdoor_sched <= room_temp else room_temp

        heat_loss_temp = room_temp - 0.1 * (room_temp - outdoor_eff)

        heater_output = 0.5 if control_signal_prev == 1 else 0.0
        room_temp_new = heat_loss_temp + heater_output

        control_signal_new = 1 if room_temp_new < 24.9 else 0

        yield {
            "time_sec": t,
            "room_temp_c": float(room_temp_new),
            "heat_loss_temp_c": float(heat_loss_temp),
            "control_signal": int(control_signal_new),
            "heater_output_c": float(heater_output),
        }

        room_temp = room_temp_new
        control_signal_prev = control_signal_new


def main():
    ap = argparse.ArgumentParser(description="House heating temperature control simulation (JSONL output).")
    ap.add_argument("--simulate_time", type=float, required=True, help="Total simulation duration in seconds.")
    args = ap.parse_args()

    stdin_text = sys.stdin.read()
    try:
        schedule = OutdoorSchedule.from_stdin(stdin_text)
    except Exception as ex:
        eprint(f"Error parsing outdoor temperature schedule: {ex}")
        raise

    # Run simulation and print JSONL only to stdout
    for obs in simulate(args.simulate_time, schedule):
        sys.stdout.write(json.dumps(obs, separators=(",", ":"), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()