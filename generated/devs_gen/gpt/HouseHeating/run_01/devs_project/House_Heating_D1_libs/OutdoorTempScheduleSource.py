import bisect
import sys
from typing import Any

from xdevs.models import Atomic, Coupled, Port


class OutdoorTempScheduleSource(Atomic):
    """
    Atomic DEVS model:
    - Reads a timestamped outdoor temperature schedule from stdin once at initialization.
    - Emits exactly one message per integer second t=1..int(simulation_time) on outdoor_temp_c_out.
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

        self.simulation_time = float(simulation_time)
        self.default_outdoor_temp_c = float(default_outdoor_temp_c)

        self.add_out_port(Port(dict, "outdoor_temp_c_out"))

        # State
        self.schedule: dict[int, float] = {}
        self.sorted_timestamps: list[int] = []
        self.next_emit_time_sec: int = 1
        self.T: int = 0

        # Prepared output payload for lambdaf()
        self._payload_to_send: dict[str, Any] | None = None

    @staticmethod
    def _parse_hhmmss_to_seconds(token: str) -> int:
        parts = token.split(":")
        if len(parts) != 3:
            raise ValueError("time token must have format HH:MM:SS")
        hh_s, mm_s, ss_s = parts
        hh = int(hh_s)
        mm = int(mm_s)
        ss = int(ss_s)
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59):
            raise ValueError("time components out of range")
        return 3600 * hh + 60 * mm + ss

    def _read_stdin_schedule_once(self) -> None:
        schedule: dict[int, float] = {}
        for line_num, raw_line in enumerate(sys.stdin, start=1):
            line = raw_line.strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) < 2:
                # Ignore malformed lines
                # Optional diagnostic to stderr
                print(
                    f"[OutdoorTempScheduleSource] Ignored malformed line {line_num}: expected '<HH:MM:SS> <temp>'",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            time_token = fields[0]
            temp_token = fields[1]
            try:
                ts_sec = self._parse_hhmmss_to_seconds(time_token)
                temp_c = float(temp_token)
            except Exception as exc:
                print(
                    f"[OutdoorTempScheduleSource] Ignored malformed line {line_num}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            # Last one wins for same timestamp
            schedule[int(ts_sec)] = float(temp_c)

        self.schedule = schedule
        self.sorted_timestamps = sorted(self.schedule.keys())

    def _lookup_temp_for_time(self, t_sec: int) -> float:
        # Greatest timestamp <= t_sec
        idx = bisect.bisect_right(self.sorted_timestamps, t_sec) - 1
        if idx >= 0:
            ts = self.sorted_timestamps[idx]
            return float(self.schedule[ts])
        return float(self.default_outdoor_temp_c)

    def _prepare_payload_for_next_emit(self) -> None:
        t = self.next_emit_time_sec
        selected = self._lookup_temp_for_time(t)
        self._payload_to_send = {"time_sec": int(t), "outdoor_temp_c": float(selected)}

    def initialize(self):
        # Read stdin exactly once and fully consume it during initialization.
        self._read_stdin_schedule_once()

        self.T = int(self.simulation_time)
        self.next_emit_time_sec = 1
        self._payload_to_send = None

        if self.T <= 0:
            self.passivate("DONE")
            return

        # First emission at simulation time t=1
        self._prepare_payload_for_next_emit()
        self.hold_in("EMIT", 1.0)

    def deltext(self, e: float):
        # No input ports; just preserve timing if any external events occur (shouldn't).
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT" and self._payload_to_send is not None:
            self.output["outdoor_temp_c_out"].add(self._payload_to_send)

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate("DONE")
            return

        # Advance to next integer second
        self.next_emit_time_sec += 1

        if self.next_emit_time_sec > self.T:
            self._payload_to_send = None
            self.passivate("DONE")
            return

        self._prepare_payload_for_next_emit()
        self.hold_in("EMIT", 1.0)

    def exit(self):
        # No required final external I/O.
        pass