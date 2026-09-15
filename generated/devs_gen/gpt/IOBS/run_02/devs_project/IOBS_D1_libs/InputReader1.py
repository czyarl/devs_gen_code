import json
import sys
import heapq

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputReader1(Atomic):
    """
    Atomic DEVS source model: reads stdin once, schedules timestamped requests,
    emits JSONL observations on stdout, and emits DEVS messages on request_out.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "request_out"))

        # Required retained state
        self.start_emitted: bool = False
        self._agenda: list[tuple[float, int, int]] = []  # (t_req, seq, invalid)
        self._seq: int = 0

        # Internal scheduling helpers
        self._sim_time: float = 0.0
        self._pending_emit: tuple[float, int, int] | None = None  # (t_req, seq, invalid)

        # For out-of-order detection
        self._last_read_time: float | None = None

    @staticmethod
    def _parse_timestamp_to_seconds(text: str) -> float:
        parts = text.split(":")
        if len(parts) != 4:
            raise ValueError("timestamp must have exactly four colon-separated integer components")
        hh_s, mm_s, ss_s, mmm_s = parts
        hh = int(hh_s)
        mm = int(mm_s)
        ss = int(ss_s)
        mmm = int(mmm_s)
        return hh * 3600.0 + mm * 60.0 + ss + (mmm / 1000.0)

    def _stderr(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _stdout_jsonl(self, record: dict) -> None:
        # Stdout reserved exclusively for required JSONL records
        print(json.dumps(record), flush=True)

    def _read_stdin_to_agenda(self) -> None:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            fields = line.split()
            if len(fields) != 5:
                self._stderr(f"Malformed line (expected 5 fields): {raw_line.rstrip()}")
                continue

            ts_text, valid_text, invalid_text = fields[0], fields[3], fields[4]
            try:
                t_req = self._parse_timestamp_to_seconds(ts_text)
                valid_in = int(valid_text)
                invalid = int(invalid_text)
            except Exception as exc:
                self._stderr(f"Malformed line (parse error: {exc}): {raw_line.rstrip()}")
                continue

            if t_req < 0.0:
                self._stderr(f"Malformed line (negative time): {raw_line.rstrip()}")
                continue

            if invalid not in (0, 1):
                self._stderr(f"Malformed line (invalid not in {{0,1}}): {raw_line.rstrip()}")
                continue

            if valid_in != 1:
                self._stderr(f"Warning: valid field expected 1 but got {valid_in}; echoing 1: {raw_line.rstrip()}")

            if self._last_read_time is not None and t_req < self._last_read_time:
                self._stderr(
                    f"Warning: out-of-order timestamp {t_req} earlier than previously read {self._last_read_time}: "
                    f"{raw_line.rstrip()}"
                )
            self._last_read_time = t_req

            heapq.heappush(self._agenda, (t_req, self._seq, invalid))
            self._seq += 1

    def initialize(self):
        self.start_emitted = False
        self._agenda.clear()
        self._seq = 0
        self._sim_time = 0.0
        self._pending_emit = None
        self._last_read_time = None

        # Read stdin exactly once at startup (until EOF)
        self._read_stdin_to_agenda()

        # Emit required start record at t=0.0 first (stdout only)
        self.hold_in("START", 0.0)

    def deltext(self, e: float):
        # No input ports; just advance time if needed
        self.continuef(e)

    def lambdaf(self):
        # External IO and DEVS output happen at the scheduled internal event time
        if self.phase == "START":
            self._stdout_jsonl({"time": 0.0, "model": "input_reader1", "event": "start", "data": {}})
            return

        if self.phase == "EMIT" and self._pending_emit is not None:
            t_req, _seq, invalid = self._pending_emit

            # Stdout JSONL record for input
            self._stdout_jsonl(
                {
                    "time": t_req,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {"valid": 1, "invalid": invalid},
                }
            )

            # DEVS output message
            self.output["request_out"].add({"request_time": t_req, "valid": 1, "invalid": invalid})

    def deltint(self):
        # Advance simulated time by elapsed sigma
        self._sim_time += self.sigma

        if self.phase == "START":
            self.start_emitted = True
            # Schedule first request emission if any
            if not self._agenda:
                self.passivate("DONE")
                return
            t_req, seq, invalid = heapq.heappop(self._agenda)
            self._pending_emit = (t_req, seq, invalid)
            self.hold_in("EMIT", max(0.0, t_req - self._sim_time))
            return

        if self.phase == "EMIT":
            # Clear emitted item and schedule next
            self._pending_emit = None
            if not self._agenda:
                self.passivate("DONE")
                return
            next_t, next_seq, next_invalid = heapq.heappop(self._agenda)
            self._pending_emit = (next_t, next_seq, next_invalid)
            self.hold_in("EMIT", max(0.0, next_t - self._sim_time))
            return

        # Fallback
        self.passivate("DONE")

    def exit(self):
        # No final stdout output required
        pass