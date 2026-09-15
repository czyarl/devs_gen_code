import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class AAM1(Atomic):
    """
    Atomic DEVS model: AccountAccessManager (AAM1)

    - Receives login requests on request_in (dict with keys: request_time, valid, invalid)
    - Processes one at a time with fixed delay stage_delay_s (FIFO, unbounded)
    - On completion:
        * Always prints exactly one JSONL record to stdout:
            - invalid==0 => account_generated
            - invalid==1 => logout
        * Conditionally forwards the request to ANV via to_anv only when invalid==0
    """

    def __init__(self, name: str, parent: Coupled | None, stage_delay_s: float):
        super().__init__(name)
        self.parent = parent
        self.stage_delay_s = float(stage_delay_s)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_anv"))

        # State
        self._queue: deque[dict] = deque()
        self._in_service: dict | None = None

        # Prepared outputs for the next internal event
        self._stdout_record: dict | None = None
        self._forward_payload: dict | None = None

    def initialize(self):
        self._queue.clear()
        self._in_service = None
        self._stdout_record = None
        self._forward_payload = None
        self.passivate("IDLE")

    def _is_request_well_formed(self, req: object) -> bool:
        if not isinstance(req, dict):
            return False
        if "request_time" not in req or "valid" not in req or "invalid" not in req:
            return False
        try:
            float(req["request_time"])
            int(req["valid"])
            int(req["invalid"])
        except Exception:
            return False
        return True

    def _coerce_or_invalidate(self, req: object) -> dict:
        """
        Return a request dict. If malformed, return a safe dict treated as invalid.
        Must not emit stdout beyond the required completion record; diagnostics go to stderr only.
        """
        if not self._is_request_well_formed(req):
            print(f"{self.name}: malformed request received; treating as invalid: {req!r}",
                  file=sys.stderr, flush=True)
            return {"request_time": float(get_current_time()), "valid": 1, "invalid": 1}

        # Copy and coerce types
        out = dict(req)
        try:
            out["request_time"] = float(out["request_time"])
        except Exception:
            out["request_time"] = float(get_current_time())
        try:
            out["valid"] = int(out["valid"])
        except Exception:
            out["valid"] = 1
        try:
            out["invalid"] = int(out["invalid"])
        except Exception:
            out["invalid"] = 1

        # Validate expected ranges; if unexpected, treat as invalid
        if out.get("valid") != 1 or out.get("invalid") not in (0, 1):
            print(f"{self.name}: unexpected valid/invalid values; treating as invalid: {out!r}",
                  file=sys.stderr, flush=True)
            out["valid"] = 1
            out["invalid"] = 1

        return out

    def _start_next_if_idle(self) -> None:
        if self._in_service is None and self._queue:
            self._in_service = self._queue.popleft()
            self.hold_in("PROCESSING", self.stage_delay_s)

    def deltext(self, e: float):
        # Preserve remaining time if already processing
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for req in self.input["request_in"].values:
            self._queue.append(self._coerce_or_invalidate(req))

        if was_processing:
            # Continue current service; new arrivals only queue
            self.hold_in("PROCESSING", remaining)
        else:
            # If idle, start service immediately if something is available
            self._start_next_if_idle()

    def lambdaf(self):
        if self.phase != "PROCESSING" or self._in_service is None:
            return

        t_complete = float(get_current_time())
        invalid = int(self._in_service.get("invalid", 1))

        if invalid == 0:
            event = "account_generated"
        else:
            event = "logout"

        record = {"time": t_complete, "model": "AAM1", "event": event, "data": {}}
        print(json.dumps(record), flush=True)

        if invalid == 0:
            # Forward unchanged (at minimum preserve required keys)
            self.output["to_anv"].add(dict(self._in_service))

    def deltint(self):
        # Completed current service
        self._in_service = None

        # Start next if queued, else become passive
        if self._queue:
            self._start_next_if_idle()
        else:
            self.passivate("IDLE")

    def exit(self):
        # No required finalization IO
        pass