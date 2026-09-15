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


def read_outdoor_schedule_from_stdin() -> List[Tuple[int, float]]:
    """
    Reads lines like: 'HH:MM:SS 24.0'
    Returns sorted list of (time_sec, temp_c). If multiple entries share the same
    timestamp, the last one in input order wins.
    """
    entries: List[Tuple[int, float]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            raise ValueError(f"Invalid schedule line (need timestamp and temp): {line!r}")
        tsec = parse_hhmmss_to_seconds(parts[0])
        temp = float(parts[1])
        entries.append((tsec, temp))

    # Sort by time, and for duplicates keep the last occurrence.
    entries.sort(key=lambda x: x[0])
    dedup: List[Tuple[int, float]] = []
    i = 0
    while i < len(entries):
        t = entries[i][0]
        last_temp = entries[i][1]
        j = i + 1
        while j < len(entries) and entries[j][0] == t:
            last_temp = entries[j][1]
            j += 1
        dedup.append((t, last_temp))
        i = j
    return dedup


@dataclass
class OutdoorSchedule:
    entries: List[Tuple[int, float]]

    def temp_at(self, t: int) -> float:
        """
        For time t, return reading with greatest timestamp <= t.
        If none, return 25.0.
        """
        if not self.entries:
            return 25.0
        # Binary search for rightmost entry with time <= t
        lo, hi = 0, len(self.entries) - 1
        if self.entries[0][0] > t:
            return 25.0
        if self.entries[hi][0] <= t:
            return self.entries[hi][1]
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.entries[mid][0] <= t:
                lo = mid + 1
            else:
                hi = mid - 1
        # hi is now the index of the rightmost time <= t
        return self.entries[hi][1]


def simulate(simulate_time: float, schedule: OutdoorSchedule):
    """
    Emits JSONL observations for time_sec = 1..int(simulate_time).
    Dynamics:
      - Use outdoor temp from previous second (t-1), capped to not exceed prev room temp.
      - Apply heat loss: lose 10% of (prev_room - effective_outdoor).
      - Heater output depends on previous control signal: 0.5 if prev_control==1 else 0.0.
      - New room temp = heat_loss_temp + heater_output.
      - Next control signal = 1 if new_room < 24.9 else 0.
    Initial at t=0:
      room=25.0, control_signal[0]=0, heater_output=0.0
    """
    T = int(simulate_time)

    room_temp = 25.0
    prev_control = 0  # control_signal[0]
    # We output observations for t=1..T after applying one update from previous observation.

    out = sys.stdout
    for t in range(1, T + 1):
        outdoor_scheduled = schedule.temp_at(t - 1)
        effective_outdoor = outdoor_scheduled if outdoor_scheduled <= room_temp else room_temp

        # Heat loss: lose 10% of the gap between room and effective outdoor.
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor)

        # Delayed heater gain based on previous control.
        heater_output = 0.5 if prev_control == 1 else 0.0
        new_room_temp = heat_loss_temp + heater_output

        # Controller sets next control after seeing new temp.
        next_control = 1 if new_room_temp < 24.9 else 0

        record = {
            "time_sec": t,
            "room_temp_c": float(new_room_temp),
            "heat_loss_temp_c": float(heat_loss_temp),
            "control_signal": int(next_control),
            "heater_output_c": float(heater_output),
        }
        out.write(json.dumps(record, separators=(",", ":")) + "\n")

        # Advance state
        room_temp = new_room_temp
        prev_control = next_control


def main():
    parser = argparse.ArgumentParser(description="House heating temperature control simulation (JSONL output).")
    parser.add_argument("--simulate_time", type=float, required=True, help="Total simulation duration in seconds.")
    args = parser.parse_args()

    try:
        schedule_entries = read_outdoor_schedule_from_stdin()
    except Exception as e:
        eprint(f"Error reading outdoor temperature schedule: {e}")
        raise

    schedule = OutdoorSchedule(schedule_entries)
    simulate(args.simulate_time, schedule)


if __name__ == "__main__":
    main()