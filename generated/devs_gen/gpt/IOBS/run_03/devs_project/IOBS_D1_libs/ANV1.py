import json
import random
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ANV1(Atomic):
    """
    Atomic DEVS model: AccountNumberVerifier stage.

    - Buffers requests FIFO.
    - Processes exactly one at a time with fixed delay stage_delay_s.
    - At completion: writes one stdout JSONL verification record.
    - On pass: emits one DEVS message on to_pv at the same completion time.
    - On fail: emits no DEVS output.
    """

    def __init__(self, name: str, parent: Coupled | None, stage_delay_s: float, pass_probability: float):
        super().__init__(name)
        self.parent = parent
        self.stage_delay_s = float(stage_delay_s)
        self.pass_probability = float(pass_probability)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_pv"))

        # State
        self._queue: deque[dict] = deque()
        self._in_service: dict | None = None

        # Prepared for the next internal event's lambdaf()
        self._prepared_stdout_record: dict | None = None
        self._prepared_to_pv_payload: dict | None = None

    def initialize(self):
        self._queue = deque()
        self._in_service = None
        self._prepared_stdout_record = None
        self._prepared_to_pv_payload = None
        self.passivate("IDLE")

    def _stderr_diag(self, msg: str) -> None:
        # Optional diagnostics only; never write non-JSONL to stdout.
        print(msg, file=sys.stderr, flush=True)

    def _start_next_if_possible(self) -> None:
        if self._in_service is None and self._queue:
            self._in_service = self._queue.popleft()
            self.hold_in("PROCESSING", max(0.0, self.stage_delay_s))

    def _coerce_request_or_mark_failed(self, req: object) -> tuple[dict, bool]:
        """
        Returns (request_dict, ok_flag). If ok_flag is False, treat as failed verification
        but still process with delay and emit required stdout record.
        """
        if not isinstance(req, dict):
            self._stderr_diag(f"ANV1 received non-dict request: {type(req)}; treating as fail.")
            return ({"request_time": 0.0, "valid": 0, "invalid": 1}, False)

        ok = True
        for k in ("request_time", "valid", "invalid"):
            if k not in req:
                ok = False
        if not ok:
            self._stderr_diag(f"ANV1 received malformed request (missing keys): {req}; treating as fail.")
            # best-effort fill
            filled = {
                "request_time": float(req.get("request_time", 0.0)) if isinstance(req.get("request_time", 0.0), (int, float)) else 0.0,
                "valid": int(req.get("valid", 0)) if isinstance(req.get("valid", 0), (int, float, bool)) else 0,
                "invalid": 1,
            }
            return (filled, False)

        # Coerce types best-effort
        try:
            rt = float(req["request_time"])
        except Exception:
            rt = 0.0
            ok = False
        try:
            v = int(req["valid"])
        except Exception:
            v = 0
            ok = False
        try:
            inv = int(req["invalid"])
        except Exception:
            inv = 1
            ok = False

        if inv != 0:
            ok = False

        if not ok:
            self._stderr_diag(f"ANV1 received unexpected request (invalid!=0 or bad types): {req}; treating as fail.")

        return ({"request_time": rt, "valid": v, "invalid": inv}, ok)

    def deltext(self, e: float):
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for req in self.input["request_in"].values:
            coerced, ok = self._coerce_request_or_mark_failed(req)
            # Preserve original fields (coerced) and tag internal flag for forced fail if needed
            coerced["_force_fail"] = 0 if ok else 1
            self._queue.append(coerced)

        if not was_processing:
            self._start_next_if_possible()
        else:
            # Keep current processing timer; do not let new arrivals affect it.
            self.hold_in("PROCESSING", remaining)

    def lambdaf(self):
        if self.phase != "PROCESSING":
            return

        # Prepare outputs exactly at completion time.
        t_complete = float(get_current_time())

        req = self._in_service if isinstance(self._in_service, dict) else None
        force_fail = bool(req.get("_force_fail", 0)) if req else True

        if force_fail:
            passed = False
        else:
            # Bernoulli draw at completion time; independent per request.
            passed = random.random() < self.pass_probability

        pass_i = 1 if passed else 0
        fail_i = 0 if passed else 1

        record = {
            "time": t_complete,
            "model": "ANV1",
            "event": "verification",
            "data": {"pass": pass_i, "fail": fail_i},
        }
        print(json.dumps(record), flush=True)

        if passed and req is not None:
            out_payload = {
                "request_time": float(req.get("request_time", 0.0)),
                "valid": int(req.get("valid", 0)),
                "invalid": int(req.get("invalid", 0)),
                "anv_pass": 1,
            }
            self.output["to_pv"].add(out_payload)

    def deltint(self):
        # Completed current service
        self._in_service = None

        # Start next immediately if queued, else become idle.
        if self._queue:
            self._start_next_if_possible()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass