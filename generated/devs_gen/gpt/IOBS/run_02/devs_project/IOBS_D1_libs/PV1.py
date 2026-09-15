import json
import random
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class PV1(Atomic):
    """
    Atomic DEVS model: PasswordVerifier (PV1)

    - Single-server FIFO buffered timed service with fixed processing delay.
    - For each request, compute attempts as number of Bernoulli(0.5) trials until first success.
    - On completion: emit required JSONL to stdout and forward {'request_time': float} to BPM1.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay_s: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_s = float(processing_delay_s)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_bpm"))

        # Internal state
        self._queue: deque[dict] = deque()
        self._in_service: dict | None = None
        self._in_service_attempts: int | None = None
        self._completion_time: float | None = None

    def initialize(self):
        self._queue = deque()
        self._in_service = None
        self._in_service_attempts = None
        self._completion_time = None
        self.passivate("IDLE")

    @staticmethod
    def _safe_request_time(payload: dict) -> float | None:
        try:
            rt = payload.get("request_time", None)
            if rt is None:
                return None
            return float(rt)
        except Exception:
            return None

    @staticmethod
    def _compute_attempts_until_success() -> int:
        attempts = 0
        # Bernoulli trials with p=0.5 until success
        while True:
            attempts += 1
            if random.random() < 0.5:
                return attempts

    def _start_next_if_idle(self, now: float) -> None:
        if self._in_service is not None:
            return
        if not self._queue:
            return

        self._in_service = self._queue.popleft()
        self._in_service_attempts = self._compute_attempts_until_success()
        self._completion_time = now + self.processing_delay_s
        self.hold_in("PROCESSING", self.processing_delay_s)

    def deltext(self, e: float):
        # Preserve remaining time if already processing; do not subtract elapsed time from a newly started timer.
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        # Enqueue all arrivals in delivery order
        for msg in self.input["request_in"].values:
            if not isinstance(msg, dict):
                print(
                    f"PV1 diagnostic: expected dict on request_in, got {type(msg)}; attempting to coerce",
                    file=sys.stderr,
                    flush=True,
                )
                try:
                    msg = dict(msg)
                except Exception:
                    msg = {"request_time": None, "valid": None, "invalid": None}

            rt = self._safe_request_time(msg)
            if rt is None:
                print(
                    f"PV1 diagnostic: missing/invalid request_time in payload {msg}; forwarding request_time as None",
                    file=sys.stderr,
                    flush=True,
                )
            # PV1 ignores valid/invalid for branching; carry request_time for traceability
            self._queue.append({"request_time": rt})

        now = get_current_time()

        if was_processing:
            # Continue current processing with preserved remaining time
            self.hold_in("PROCESSING", remaining if remaining is not None else 0.0)
        else:
            # If idle, start service immediately if queue has items
            self._start_next_if_idle(now)

    def lambdaf(self):
        if self.phase != "PROCESSING" or self._in_service is None:
            return

        t_complete = get_current_time()
        attempts = int(self._in_service_attempts) if self._in_service_attempts is not None else 1

        # External IO: stdout JSONL record on completion
        record = {
            "time": t_complete,
            "model": "PV1",
            "event": "verification",
            "data": {"success": 1, "attempts": attempts},
        }
        print(json.dumps(record), flush=True)

        # DEVS output to BPM1
        self.output["to_bpm"].add({"request_time": self._in_service.get("request_time", None)})

    def deltint(self):
        # Completion of current service
        self._in_service = None
        self._in_service_attempts = None
        self._completion_time = None

        now = get_current_time()
        if self._queue:
            self._start_next_if_idle(now)
        else:
            self.passivate("IDLE")

    def exit(self):
        # No special termination action required
        pass