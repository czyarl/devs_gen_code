import bisect
import sys
from typing import Final

from xdevs.models import Atomic, Coupled, Port


class StdinOutdoorScheduleSource(Atomic):
    """
    Atomic DEVS model that preloads an outdoor temperature schedule from stdin
    during initialization and then emits exactly one selected scheduled outdoor
    temperature per integer simulation second t=1..int(simulate_time).

    Output message format on port scheduled_outdoor_temp_out:
      {'time_sec': t, 'scheduled_outdoor_temp_c': float}
    """

    PHASE_EMIT: Final[str] = "EMIT"
    PHASE_DONE: Final[str] = "DONE"

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: float,
        default_outdoor_temp_c: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Ports
        self.add_out_port(Port(dict, "scheduled_outdoor_temp_out"))

        # Remembered state
        self.simulate_time: float = float(simulate_time)
        self.horizon_T: int = int(self.simulate_time)
        self.default_outdoor_temp_c: float = float(default_outdoor_temp_c)

        # Preloaded schedule representation (sorted unique timestamps + aligned values)
        self._times: list[int] = []
        self._temps: list[float] = []

        # Emission counter
        self.next_t: int = 1

        # Prepared payload for lambdaf()
        self._payload_to_send: dict | None = None

    @staticmethod
    def _parse_hhmmss_to_sec(token: str) -> int:
        parts = token.split(":")
        if len(parts) != 3:
            raise ValueError("timestamp must be HH:MM:SS")
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2])
        if hh < 0 or mm < 0 or ss < 0:
            raise ValueError("negative time fields not allowed")
        if mm > 59 or ss > 59:
            raise ValueError("MM and SS must be in 0..59")
        return hh * 3600 + mm * 60 + ss

    def _read_schedule_from_stdin(self) -> None:
        """
        Read sys.stdin to EOF exactly once, parse lines of the form:
          "<HH:MM:SS> <numeric_temp>"
        Ignore empty lines; skip malformed lines; last-wins for duplicate timestamps.
        """
        last_wins: dict[int, float] = {}
        for line_no, raw_line in enumerate(sys.stdin, start=1):
            line = raw_line.strip()
            if not line:
                continue

            fields = line.split()
            if len(fields) != 2:
                print(
                    f"[StdinOutdoorScheduleSource] Skipping malformed line {line_no}: "
                    f"expected 2 tokens, got {len(fields)}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            ts_token, temp_token = fields
            try:
                time_sec = self._parse_hhmmss_to_sec(ts_token)
                if time_sec < 0:
                    raise ValueError("negative timestamp not allowed")
                temp_c = float(temp_token)
            except Exception as ex:
                print(
                    f"[StdinOutdoorScheduleSource] Skipping malformed line {line_no}: {ex}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            last_wins[time_sec] = temp_c

        if not last_wins:
            self._times = []
            self._temps = []
            return

        items = sorted(last_wins.items(), key=lambda kv: kv[0])
        self._times = [t for t, _ in items]
        self._temps = [v for _, v in items]

    def _lookup(self, query_time_sec: int) -> float:
        """
        Return the reading whose timestamp is the greatest time_sec <= query_time_sec,
        else default_outdoor_temp_c.
        """
        if not self._times:
            return self.default_outdoor_temp_c
        idx = bisect.bisect_right(self._times, query_time_sec) - 1
        if idx < 0:
            return self.default_outdoor_temp_c
        return float(self._temps[idx])

    def _prepare_next_payload(self) -> None:
        t = self.next_t
        lookup_time = t - 1
        selected = self._lookup(lookup_time)
        self._payload_to_send = {"time_sec": int(t), "scheduled_outdoor_temp_c": float(selected)}

    def initialize(self):
        # One-time preload from stdin
        self._read_schedule_from_stdin()

        # Reset counters
        self.horizon_T = int(self.simulate_time)
        self.next_t = 1
        self._payload_to_send = None

        # If no horizon, remain passive from the start
        if self.horizon_T <= 0:
            self.passivate(self.PHASE_DONE)
            return

        # First emission at simulation time t=1
        self._prepare_next_payload()
        self.hold_in(self.PHASE_EMIT, 1.0)

    def deltext(self, e: float):
        # No input ports; remain on schedule.
        self.continuef(e)

    def lambdaf(self):
        if self.phase == self.PHASE_EMIT and self._payload_to_send is not None:
            self.output["scheduled_outdoor_temp_out"].add(self._payload_to_send)

    def deltint(self):
        if self.phase != self.PHASE_EMIT:
            self.passivate(self.PHASE_DONE)
            return

        # Advance to next second
        self.next_t += 1

        if self.next_t > self.horizon_T:
            self._payload_to_send = None
            self.passivate(self.PHASE_DONE)
            return

        self._prepare_next_payload()
        self.hold_in(self.PHASE_EMIT, 1.0)

    def exit(self):
        pass