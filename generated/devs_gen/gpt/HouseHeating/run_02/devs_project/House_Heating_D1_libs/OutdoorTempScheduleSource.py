import sys
from bisect import bisect_right

from xdevs.models import Atomic, Coupled, Port


class OutdoorTempScheduleSource(Atomic):
    """
    Autonomous time-driven source that:
    - Reads all schedule lines from sys.stdin at initialization (until EOF).
    - Emits exactly one message per integer observation second t=1..N where N=int(simulation_time).
    - For each t, selects outdoor temperature using lookup time q=t-1:
        greatest schedule timestamp <= q, else default_outdoor_temp_c.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
        default_outdoor_temp_c: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.simulation_time = simulation_time
        self.default_outdoor_temp_c = default_outdoor_temp_c

        self.add_out_port(Port(dict, "outdoor_temp_out"))

        # Schedule storage: sorted timestamps and aligned temperatures.
        self._times: list[int] = []
        self._temps: list[float] = []

        # Emission control
        self._N: int = 0
        self._next_t: int = 1
        self._payload_to_send: dict | None = None

    @staticmethod
    def _parse_time_to_seconds(hhmmss: str) -> int:
        parts = hhmmss.split(":")
        if len(parts) != 3:
            raise ValueError("timestamp must be HH:MM:SS")
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2])
        if hh < 0 or mm < 0 or ss < 0 or mm >= 60 or ss >= 60:
            raise ValueError("invalid time fields")
        return hh * 3600 + mm * 60 + ss

    def _read_schedule_from_stdin(self) -> None:
        # Last-wins mapping
        mapping: dict[int, float] = {}
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) != 2:
                continue
            try:
                time_sec = self._parse_time_to_seconds(fields[0])
                temp_c = float(fields[1])
            except Exception:
                # Malformed lines are ignored; optional diagnostics not required.
                continue
            mapping[time_sec] = temp_c

        if not mapping:
            self._times = []
            self._temps = []
            return

        self._times = sorted(mapping.keys())
        self._temps = [mapping[t] for t in self._times]

    def _lookup_temp(self, q: int) -> float:
        if not self._times:
            return self.default_outdoor_temp_c
        idx = bisect_right(self._times, q) - 1
        if idx < 0:
            return self.default_outdoor_temp_c
        return float(self._temps[idx])

    def _prepare_payload_for_t(self, t: int) -> None:
        q = t - 1
        temp_c = self._lookup_temp(q)
        self._payload_to_send = {"time_sec": int(t), "outdoor_temp_c": float(temp_c)}

    def initialize(self):
        # External IO: read stdin at initialization, before any DEVS outputs.
        self._read_schedule_from_stdin()

        self._N = int(self.simulation_time)
        self._next_t = 1
        self._payload_to_send = None

        if self._N <= 0:
            self.passivate("DONE")
            return

        # First output must occur at simulation time 1.
        self._prepare_payload_for_t(self._next_t)
        self.hold_in("EMIT", 1.0)

    def deltext(self, e: float):
        # No input ports; ignore external events and preserve schedule.
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT" and self._payload_to_send is not None:
            self.output["outdoor_temp_out"].add(self._payload_to_send)

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate("DONE")
            return

        # Advance to next integer observation second.
        self._next_t += 1
        self._payload_to_send = None

        if self._next_t > self._N:
            self.passivate("DONE")
            return

        # Subsequent outputs occur at each next integer second (delta=1.0).
        self._prepare_payload_for_t(self._next_t)
        self.hold_in("EMIT", 1.0)

    def exit(self):
        pass