import json
import sys
from dataclasses import dataclass

from xdevs.models import Atomic, Coupled, Port


@dataclass(frozen=True)
class _ScheduledRequest:
    request_time: float
    invalid: int
    order: int  # stable ordering for identical timestamps


class InputReader1(Atomic):
    """
    Atomic DEVS source model that reads sys.stdin once, parses timestamped login
    requests, and emits each request at its absolute simulation time.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Output ports (locked contract)
        self.add_out_port(Port(dict, "request_out"))

        # Internal state
        self._start_emitted: bool = False
        self._schedule: list[_ScheduledRequest] = []
        self._next_index: int = 0
        self._sim_time: float = 0.0

        # Prepared output for current internal event (may be a batch at same time)
        self._to_emit: list[_ScheduledRequest] = []

    @staticmethod
    def _warn(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    @staticmethod
    def _parse_timestamp_to_seconds(token: str) -> float:
        # Expected: HH:MM:SS:mmm (exactly 4 fields)
        parts = token.split(":")
        if len(parts) != 4:
            raise ValueError("timestamp must have format HH:MM:SS:mmm")
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2])
        mmm = int(parts[3])
        if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
            raise ValueError("timestamp fields must be nonnegative")
        if mm >= 60 or ss >= 60 or mmm >= 1000:
            raise ValueError("timestamp fields out of range")
        return hh * 3600.0 + mm * 60.0 + ss + (mmm / 1000.0)

    def _stdout_jsonl(self, time_value: float, event: str, data: dict) -> None:
        record = {
            "time": float(time_value),
            "model": "input_reader1",
            "event": event,
            "data": data,
        }
        print(json.dumps(record), flush=True)

    def _read_and_build_schedule(self) -> None:
        parsed: list[_ScheduledRequest] = []
        order = 0
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            fields = line.split()
            if len(fields) != 3:
                self._warn(f"InputReader1: malformed line (expected 3 tokens): {raw_line.rstrip()}")
                continue

            ts_token, valid_token, invalid_token = fields
            try:
                request_time = self._parse_timestamp_to_seconds(ts_token)
                valid = int(valid_token)
                invalid = int(invalid_token)
            except Exception as exc:
                self._warn(f"InputReader1: malformed line (parse error): {raw_line.rstrip()} ({exc})")
                continue

            if request_time < 0.0:
                self._warn(f"InputReader1: malformed line (negative time): {raw_line.rstrip()}")
                continue
            if valid != 1:
                self._warn(f"InputReader1: malformed line (valid must be 1): {raw_line.rstrip()}")
                continue
            if invalid not in (0, 1):
                self._warn(f"InputReader1: malformed line (invalid must be 0 or 1): {raw_line.rstrip()}")
                continue

            parsed.append(_ScheduledRequest(request_time=request_time, invalid=invalid, order=order))
            order += 1

        # Sort by time, then stdin order for stability; ensures stdout nondecreasing time order.
        self._schedule = sorted(parsed, key=lambda r: (r.request_time, r.order))

    def _prepare_emit_batch_at_current_time(self) -> None:
        """Prepare all requests whose absolute time equals the next scheduled time."""
        self._to_emit = []
        if self._next_index >= len(self._schedule):
            return
        t = self._schedule[self._next_index].request_time
        i = self._next_index
        while i < len(self._schedule) and self._schedule[i].request_time == t:
            self._to_emit.append(self._schedule[i])
            i += 1

    def initialize(self):
        # Emit required start record at absolute t=0.0
        self._stdout_jsonl(0.0, "start", {})
        self._start_emitted = True

        # Read stdin fully and build schedule (may be empty)
        self._read_and_build_schedule()

        self._next_index = 0
        self._sim_time = 0.0
        self._to_emit = []

        if not self._schedule:
            self.passivate("DONE")
            return

        first_time = self._schedule[0].request_time
        sigma = max(0.0, first_time - self._sim_time)
        self.hold_in("EMIT", sigma)

    def deltext(self, e: float):
        # No input ports; just preserve timing if any.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT":
            return

        # Prepare batch for the time being emitted (absolute time == current internal event time)
        self._prepare_emit_batch_at_current_time()

        # Emit one DEVS message and one stdout JSONL record per request, all at same simulation time.
        for req in self._to_emit:
            payload = {"request_time": req.request_time, "valid": 1, "invalid": req.invalid}
            self.output["request_out"].add(payload)
            self._stdout_jsonl(req.request_time, "input", {"valid": 1, "invalid": req.invalid})

    def deltint(self):
        # Advance simulated time by elapsed sigma
        self._sim_time += self.sigma

        # Consume the batch we emitted
        if self._to_emit:
            self._next_index += len(self._to_emit)
        else:
            # Should not happen, but avoid infinite loop
            self._next_index += 1

        self._to_emit = []

        if self._next_index >= len(self._schedule):
            self.passivate("DONE")
            return

        next_time = self._schedule[self._next_index].request_time
        sigma = max(0.0, next_time - self._sim_time)
        self.hold_in("EMIT", sigma)

    def exit(self):
        # No required finalization output.
        pass