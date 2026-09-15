import sys
from xdevs.models import Atomic, Coupled, Port


class ScheduleSource(Atomic):
    """
    Autonomous atomic DEVS source that preloads an arrival schedule from stdin
    before simulation starts and emits 'newcust' at the scheduled absolute times.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(str, "newcust_out"))

        # Required remembered state
        self.schedule_times: list[float] = []
        self.next_index: int = 0

        # Internal helpers
        self._next_time: float | None = None
        self._batch_count: int = 0
        self._last_event_time: float = 0.0

    @staticmethod
    def _warn(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    @staticmethod
    def _parse_line_to_time_s(raw_line: str) -> float | None:
        line = raw_line.strip()
        if not line:
            return None  # ignore blank lines silently

        fields = line.split()
        if len(fields) != 2:
            ScheduleSource._warn(f"Warning: malformed schedule line (expected 2 tokens): {raw_line.rstrip()}")
            return None

        time_token, event_name = fields
        if event_name != "newcust":
            ScheduleSource._warn(f"Warning: unsupported event name (expected 'newcust'): {raw_line.rstrip()}")
            return None

        parts = time_token.split(":")
        if len(parts) != 4:
            ScheduleSource._warn(f"Warning: malformed time token (expected HH:MM:SS:mm): {raw_line.rstrip()}")
            return None

        try:
            hh = int(parts[0])
            mm = int(parts[1])
            ss = int(parts[2])
            cc = int(parts[3])  # hundredths
        except ValueError:
            ScheduleSource._warn(f"Warning: non-integer time component: {raw_line.rstrip()}")
            return None

        if hh < 0 or mm < 0 or ss < 0 or cc < 0 or mm >= 60 or ss >= 60 or cc >= 100:
            ScheduleSource._warn(f"Warning: out-of-range time component: {raw_line.rstrip()}")
            return None

        return hh * 3600.0 + mm * 60.0 + ss * 1.0 + (cc / 100.0)

    def _recompute_next(self) -> None:
        if self.next_index >= len(self.schedule_times):
            self._next_time = None
            self._batch_count = 0
            return

        t_next = self.schedule_times[self.next_index]
        j = self.next_index
        n = len(self.schedule_times)
        while j < n and self.schedule_times[j] == t_next:
            j += 1

        self._next_time = t_next
        self._batch_count = j - self.next_index

    def initialize(self):
        # Pre-simulation input consumption: read all stdin once
        self.schedule_times = []
        self.next_index = 0
        self._next_time = None
        self._batch_count = 0
        self._last_event_time = 0.0

        for raw_line in sys.stdin:
            t_s = self._parse_line_to_time_s(raw_line)
            if t_s is None:
                continue
            self.schedule_times.append(float(t_s))

        self.schedule_times.sort()

        if not self.schedule_times:
            self.passivate("PASSIVE")
            return

        self._recompute_next()
        assert self._next_time is not None

        sigma = max(0.0, self._next_time - self._last_event_time)
        self.hold_in("EMIT", sigma)

    def deltext(self, e: float):
        # No input ports; just preserve timing if any (or remain passive)
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT":
            return
        # Emit one 'newcust' per scheduled entry at this timestamp
        for _ in range(self._batch_count):
            self.output["newcust_out"].add("newcust")

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate("PASSIVE")
            return

        # Advance past all duplicates we just emitted
        emitted_time = self._next_time if self._next_time is not None else self._last_event_time
        self._last_event_time = float(emitted_time)

        self.next_index += self._batch_count
        self._recompute_next()

        if self._next_time is None:
            self.passivate("PASSIVE")
            return

        sigma = max(0.0, self._next_time - self._last_event_time)
        self.hold_in("EMIT", sigma)

    def exit(self):
        pass