import sys

from xdevs.models import Atomic, Coupled, Port


class ScheduleSource(Atomic):
    """
    Atomic DEVS source model that reads a pre-simulation schedule from stdin and
    emits 'newcust' on newcust_out at the scheduled absolute simulation times.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(str, "newcust_out"))

        # State required by contract
        self.schedule_times: list[float] = []  # sorted, includes duplicates
        self.next_index: int = 0

        # Internal bookkeeping for absolute-time scheduling
        self._sim_time: float = 0.0

        # Prepared batch for current emission time (emitted in lambdaf)
        self._pending_count: int = 0
        self._pending_time: float | None = None

    @staticmethod
    def _log_stderr(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    @staticmethod
    def _parse_line_to_time(raw_line: str, line_no: int) -> float | None:
        stripped = raw_line.strip()
        if not stripped:
            # Blank/whitespace-only lines: ignored; may log a brief notice.
            ScheduleSource._log_stderr(f"ScheduleSource: ignoring blank line {line_no}")
            return None

        fields = stripped.split()
        if len(fields) != 2:
            ScheduleSource._log_stderr(
                f"ScheduleSource: malformed line {line_no}: expected 2 tokens "
                f"'HH:MM:SS:mm newcust', got {len(fields)} token(s): {stripped!r}"
            )
            return None

        ts_token, event_name = fields
        if event_name != "newcust":
            ScheduleSource._log_stderr(
                f"ScheduleSource: ignoring line {line_no}: unsupported EventName {event_name!r} "
                f"(expected 'newcust')"
            )
            return None

        parts = ts_token.split(":")
        if len(parts) != 4:
            ScheduleSource._log_stderr(
                f"ScheduleSource: malformed timestamp on line {line_no}: expected 4 fields "
                f"'HH:MM:SS:mm', got {len(parts)}: {ts_token!r}"
            )
            return None

        try:
            hh = int(parts[0])
            mm = int(parts[1])
            ss = int(parts[2])
            ms = int(parts[3])
        except ValueError as exc:
            ScheduleSource._log_stderr(
                f"ScheduleSource: malformed integers on line {line_no}: {ts_token!r} ({exc})"
            )
            return None

        # Strictness: treat out-of-range fields as invalid.
        if hh < 0 or not (0 <= mm < 60) or not (0 <= ss < 60) or not (0 <= ms < 1000):
            ScheduleSource._log_stderr(
                f"ScheduleSource: ignoring line {line_no}: out-of-range time fields "
                f"HH={hh}, MM={mm}, SS={ss}, mm={ms} in {ts_token!r}"
            )
            return None

        t = hh * 3600.0 + mm * 60.0 + ss + (ms / 1000.0)
        if t < 0.0:
            ScheduleSource._log_stderr(
                f"ScheduleSource: ignoring line {line_no}: negative time computed {t} from {ts_token!r}"
            )
            return None
        return t

    def _read_schedule_from_stdin(self) -> None:
        # Sole stdin reader (pre-simulation): consume ALL lines until EOF.
        parsed_times: list[float] = []
        for i, raw_line in enumerate(sys.stdin, start=1):
            t = self._parse_line_to_time(raw_line, i)
            if t is None:
                continue
            parsed_times.append(t)

        parsed_times.sort()
        self.schedule_times = parsed_times

    def _prepare_pending_batch(self) -> None:
        """
        Prepare the batch of 'newcust' emissions for the next scheduled time.
        Must be called only when next_index < len(schedule_times).
        """
        t = self.schedule_times[self.next_index]
        j = self.next_index
        n = len(self.schedule_times)
        while j < n and self.schedule_times[j] == t:
            j += 1
        self._pending_time = t
        self._pending_count = j - self.next_index

    def initialize(self):
        # Pre-simulation stdin consumption and schedule build.
        self._read_schedule_from_stdin()

        self.next_index = 0
        self._sim_time = 0.0
        self._pending_count = 0
        self._pending_time = None

        if not self.schedule_times:
            self.passivate("PASSIVE")
            return

        # Schedule first emission at absolute time schedule_times[0].
        self._prepare_pending_batch()
        first_time = self.schedule_times[0]
        self.hold_in("EMIT", max(0.0, first_time - self._sim_time))

    def deltext(self, e: float):
        # No input ports; just preserve remaining time if any.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT":
            return
        # Emit one 'newcust' per scheduled line at this timestamp (batch).
        if self._pending_count > 0:
            # Use extend to add multiple messages in the same output function call.
            self.output["newcust_out"].extend(["newcust"] * self._pending_count)

    def deltint(self):
        # Advance absolute simulated time by elapsed sigma.
        self._sim_time += self.sigma

        if self.phase == "EMIT":
            # Consume the batch we just emitted.
            self.next_index += self._pending_count
            self._pending_count = 0
            self._pending_time = None

            if self.next_index >= len(self.schedule_times):
                self.passivate("PASSIVE")
                return

            # Prepare next batch and schedule it at its absolute time.
            self._prepare_pending_batch()
            next_time = self.schedule_times[self.next_index]
            self.hold_in("EMIT", max(0.0, next_time - self._sim_time))
            return

        # Fallback: if somehow in another phase, remain passive.
        self.passivate("PASSIVE")

    def exit(self):
        # No required end-of-simulation external IO.
        pass