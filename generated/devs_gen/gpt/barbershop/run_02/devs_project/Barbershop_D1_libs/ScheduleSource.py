import math
import sys

from xdevs.models import Atomic, Coupled, Port


class ScheduleSource(Atomic):
    """
    Atomic DEVS source that preloads a plaintext schedule from stdin once (before the
    simulation loop starts) and emits one arrival message at each absolute time.

    Input line format (whitespace-delimited into exactly two tokens):
        HH:MM:SS:mm newcust

    Where mm is centiseconds (00-99) and absolute time is:
        t = HH*3600 + MM*60 + SS + (mm/100.0)
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "arrival_out"))

        # Remembered state (per contract)
        self.schedule: list[tuple[float, int]] = []  # (event_time_s, seq)
        self.next_index: int = 0
        self.next_time_s: float = math.inf

        # Internal helpers
        self._sim_time_s: float = 0.0
        self._emit_count: int = 0  # number of events to emit at current internal firing

    @staticmethod
    def _warn(line: str, reason: str) -> None:
        print(f"ScheduleSource warning: ignoring line {line!r}: {reason}", file=sys.stderr, flush=True)

    @staticmethod
    def _parse_timestamp_to_seconds(ts: str) -> float:
        parts = ts.split(":")
        if len(parts) != 4:
            raise ValueError("timestamp must be HH:MM:SS:mm")
        hh_s, mm_s, ss_s, cs_s = parts
        hh = int(hh_s)
        mm = int(mm_s)
        ss = int(ss_s)
        cs = int(cs_s)

        if hh < 0:
            raise ValueError("HH must be >= 0")
        if not (0 <= mm < 60):
            raise ValueError("MM must be in [0, 59]")
        if not (0 <= ss < 60):
            raise ValueError("SS must be in [0, 59]")
        if not (0 <= cs < 100):
            raise ValueError("mm (centiseconds) must be in [0, 99]")

        return hh * 3600.0 + mm * 60.0 + ss + (cs / 100.0)

    def _read_schedule_from_stdin(self) -> None:
        parsed: list[tuple[float, int]] = []
        seq = 0
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            fields = line.split()
            if len(fields) != 2:
                self._warn(raw_line.rstrip("\n"), "expected exactly two tokens: 'HH:MM:SS:mm newcust'")
                continue

            ts_text, event_name = fields
            if event_name != "newcust":
                self._warn(raw_line.rstrip("\n"), "EventName must be exactly 'newcust'")
                continue

            try:
                t_s = self._parse_timestamp_to_seconds(ts_text)
            except Exception as exc:
                self._warn(raw_line.rstrip("\n"), f"timestamp parse/validation failed ({exc})")
                continue

            if t_s < 0.0:
                self._warn(raw_line.rstrip("\n"), "event time < 0 is invalid")
                continue

            parsed.append((t_s, seq))
            seq += 1

        # Stable sort by (time, seq) to preserve stdin order for ties
        parsed.sort(key=lambda item: (item[0], item[1]))
        self.schedule = parsed

    def _refresh_next_time_cache(self) -> None:
        if self.next_index >= len(self.schedule):
            self.next_time_s = math.inf
        else:
            self.next_time_s = self.schedule[self.next_index][0]

    def initialize(self):
        # One-time stdin preload (must complete before simulation loop starts)
        self._read_schedule_from_stdin()

        self._sim_time_s = 0.0
        self.next_index = 0
        self._emit_count = 0
        self._refresh_next_time_cache()

        if not self.schedule:
            self.passivate("PASSIVE")
            return

        # Schedule first emission at absolute time next_time_s
        sigma = max(0.0, self.next_time_s - self._sim_time_s)
        self.hold_in("EMIT", sigma)

    def deltext(self, e: float):
        # No input ports; just preserve timing if ever called.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT":
            return

        # Emit all events scheduled exactly at current simulation time.
        # Current time is self._sim_time_s + self.sigma (time of this internal firing).
        t_now = self._sim_time_s + self.sigma

        # Determine how many to emit at this timestamp.
        idx = self.next_index
        count = 0
        while idx < len(self.schedule) and self.schedule[idx][0] == t_now:
            count += 1
            idx += 1

        # Cache for deltint()
        self._emit_count = count

        for _ in range(count):
            self.output["arrival_out"].add({"event": "newcust"})

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate("PASSIVE")
            return

        # Advance simulated time to the time of this firing
        self._sim_time_s += self.sigma

        # Consume emitted events
        if self._emit_count > 0:
            self.next_index += self._emit_count
        self._emit_count = 0

        self._refresh_next_time_cache()

        if self.next_index >= len(self.schedule):
            self.passivate("PASSIVE")
            return

        # Schedule next emission at absolute time next_time_s
        sigma = max(0.0, self.next_time_s - self._sim_time_s)
        self.hold_in("EMIT", sigma)

    def exit(self):
        # No required final IO.
        pass