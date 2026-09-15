from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Iterable, TextIO


_TIME_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")


def _hhmmss_to_seconds(s: str) -> int:
    m = _TIME_RE.match(s)
    if not m:
        raise ValueError(f"Invalid timestamp '{s}', expected HH:MM:SS")
    hh, mm, ss = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if not (0 <= mm < 60 and 0 <= ss < 60 and 0 <= hh):
        raise ValueError(f"Invalid timestamp '{s}', expected HH:MM:SS")
    return hh * 3600 + mm * 60 + ss


@dataclass(frozen=True)
class OutdoorTempSchedule:
    """Piecewise-constant outdoor temperature schedule keyed by seconds."""

    times_sec: list[int]
    temps_c: list[float]

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> "OutdoorTempSchedule":
        last_by_time: dict[int, float] = {}
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"Invalid schedule line: {raw!r}")
            ts_s, temp_s = parts
            t = _hhmmss_to_seconds(ts_s)
            last_by_time[t] = float(temp_s)

        times = sorted(last_by_time.keys())
        temps = [last_by_time[t] for t in times]
        return cls(times_sec=times, temps_c=temps)

    @classmethod
    def from_stream(cls, stream: TextIO) -> "OutdoorTempSchedule":
        return cls.from_lines(stream.readlines())

    def get_outdoor_temp(self, t_sec: int) -> float:
        """Return scheduled outdoor temp at time t_sec, or 25.0 if absent."""
        if not self.times_sec:
            return 25.0
        idx = bisect_right(self.times_sec, t_sec) - 1
        if idx < 0:
            return 25.0
        return self.temps_c[idx]
