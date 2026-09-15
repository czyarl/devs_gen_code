import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputReader1(Atomic):
    """
    Atomic DEVS source model:
    - Sole consumer of sys.stdin for the simulation.
    - Emits required JSONL records on stdout.
    - Sends timestamped request payloads on request_out at absolute times.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "request_out"))

        # State
        self._start_emitted: bool = False
        self._pending: list[tuple[float, int, dict]] = []  # (t_abs, seq, payload)
        self._next_index: int = 0
        self._sim_time: float = 0.0

        # Output preparation for current internal event
        self._payload_to_send: dict | None = None
        self._stdout_record_to_emit: dict | None = None

    @staticmethod
    def _parse_timestamp_to_seconds(token: str) -> float:
        parts = token.split(":")
        if len(parts) != 4:
            raise ValueError("timestamp must have exactly four colon-separated integer components")
        hh, mm, ss, mmm = (int(p) for p in parts)
        return hh * 3600.0 + mm * 60.0 + ss + (mmm / 1000.0)

    def _stderr_diag(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    def _read_and_prepare_schedule(self) -> None:
        parsed: list[tuple[float, int, dict]] = []
        seq = 0
        for raw_line in sys.stdin:
            if raw_line.strip() == "":
                continue
            try:
                fields = raw_line.split()
                if len(fields) != 3:
                    raise ValueError(f"expected exactly 3 space-separated fields, got {len(fields)}")
                t_token, valid_token, invalid_token = fields
                t_abs = self._parse_timestamp_to_seconds(t_token)
                valid = int(valid_token)
                invalid = int(invalid_token)
                payload = {"request_time": float(t_abs), "valid": int(valid), "invalid": int(invalid)}
                parsed.append((float(t_abs), seq, payload))
                seq += 1
            except Exception as exc:
                self._stderr_diag(f"InputReader1: malformed line skipped: {raw_line.rstrip()} ({exc})")
                continue

        # Order by absolute time, then by read order for ties
        parsed.sort(key=lambda item: (item[0], item[1]))
        self._pending = parsed
        self._next_index = 0

    def _emit_stdout_jsonl(self, record: dict) -> None:
        print(json.dumps(record), flush=True)

    def initialize(self):
        self._start_emitted = False
        self._payload_to_send = None
        self._stdout_record_to_emit = None
        self._sim_time = 0.0

        # Read stdin once at startup (until EOF)
        self._read_and_prepare_schedule()

        # Schedule start record at t=0.0
        self.hold_in("START", 0.0)

    def deltext(self, e: float):
        # No input ports; just preserve timing if any (should not matter here).
        self.continuef(e)

    def lambdaf(self):
        # DEVS output only here.
        if self.phase == "EMIT_REQUEST":
            if self._payload_to_send is not None:
                self.output["request_out"].add(self._payload_to_send)

        # Stdout JSONL emission at semantic event times.
        if self.phase in ("START", "EMIT_REQUEST"):
            if self._stdout_record_to_emit is not None:
                self._emit_stdout_jsonl(self._stdout_record_to_emit)

    def deltint(self):
        # Advance simulated time by elapsed sigma
        self._sim_time += float(self.sigma)

        if self.phase == "START":
            # Emit exactly one start record at t=0.0
            if not self._start_emitted:
                # Note: record is emitted in lambdaf() before deltint()
                pass
            self._start_emitted = True
            self._stdout_record_to_emit = None
            self._payload_to_send = None

            # Schedule first request if any
            if self._next_index >= len(self._pending):
                self.passivate("DONE")
                return

            next_t_abs = self._pending[self._next_index][0]
            sigma = max(0.0, next_t_abs - self._sim_time)
            self.hold_in("EMIT_REQUEST", sigma)
            # Prepare outputs for that internal event (at its time)
            # (Preparation can be done now; values are deterministic.)
            t_abs, _seq, payload = self._pending[self._next_index]
            self._payload_to_send = payload
            self._stdout_record_to_emit = {
                "time": float(t_abs),
                "model": "input_reader1",
                "event": "input",
                "data": {"valid": int(payload["valid"]), "invalid": int(payload["invalid"])},
            }
            return

        if self.phase == "EMIT_REQUEST":
            # Current request has just been emitted/sent
            self._stdout_record_to_emit = None
            self._payload_to_send = None
            self._next_index += 1

            if self._next_index >= len(self._pending):
                self.passivate("DONE")
                return

            next_t_abs, _seq, payload = self._pending[self._next_index]
            sigma = max(0.0, next_t_abs - self._sim_time)
            self.hold_in("EMIT_REQUEST", sigma)

            # Prepare the next outputs
            self._payload_to_send = payload
            self._stdout_record_to_emit = {
                "time": float(next_t_abs),
                "model": "input_reader1",
                "event": "input",
                "data": {"valid": int(payload["valid"]), "invalid": int(payload["invalid"])},
            }
            return

        # Fallback
        self.passivate("DONE")

    def exit(self):
        # No additional required output.
        pass