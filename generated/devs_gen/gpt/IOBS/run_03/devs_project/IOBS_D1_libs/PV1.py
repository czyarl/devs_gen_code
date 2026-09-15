import json
import random
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class PV1(Atomic):
    """
    Atomic DEVS model: PasswordVerifier (PV) stage.

    - Buffers incoming requests (FIFO) on request_in.
    - Processes one request at a time for a fixed delay (stage_delay_s).
    - For each request, computes pv_attempts as geometric trials until first success
      with per-trial probability success_probability; pv_success is always 1.
    - On completion, writes one JSONL stdout record and emits one message on to_bpm.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        stage_delay_s: float,
        success_probability: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.stage_delay_s = float(stage_delay_s)
        self.success_probability = float(success_probability)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_bpm"))

        # State
        self._queue: deque[dict] = deque()
        self._in_service: dict | None = None
        self._in_service_attempts: int | None = None

        # Prepared output (must exist before lambdaf)
        self._pending_stdout_record: dict | None = None
        self._pending_to_bpm: dict | None = None

    def initialize(self):
        self._queue = deque()
        self._in_service = None
        self._in_service_attempts = None
        self._pending_stdout_record = None
        self._pending_to_bpm = None
        self.passivate("IDLE")

    def _effective_success_probability(self) -> float:
        p = self.success_probability
        if p >= 1.0:
            return 1.0
        if p <= 0.0:
            # Configuration error: would never succeed. Clamp minimally to continue.
            print(
                f"PV1 configuration error: success_probability={p} must be in (0,1]; clamping to 1e-12",
                file=sys.stderr,
                flush=True,
            )
            return 1e-12
        return p

    def _draw_attempts_until_success(self) -> int:
        p = self._effective_success_probability()
        if p >= 1.0:
            return 1
        attempts = 1
        # Repeat Bernoulli trials until first success.
        while random.random() >= p:
            attempts += 1
        return attempts

    def _start_next_service(self) -> None:
        self._in_service = self._queue.popleft()
        self._in_service_attempts = self._draw_attempts_until_success()
        self.hold_in("PROCESSING", max(0.0, self.stage_delay_s))

    def deltext(self, e: float):
        # Preserve remaining time if already processing; do not subtract elapsed time
        # from a newly started timer.
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for req in self.input["request_in"].values:
            # Enqueue as received (dict). Copy to avoid external mutation.
            self._queue.append(dict(req))

        if not was_processing and self._in_service is None and self._queue:
            self._start_next_service()
        elif was_processing:
            self.hold_in("PROCESSING", remaining)

    def lambdaf(self):
        if self.phase != "PROCESSING" or self._in_service is None or self._in_service_attempts is None:
            return

        t_complete = float(get_current_time())

        # Stdout JSONL record (must be exactly one line, JSON only)
        record = {
            "time": t_complete,
            "model": "PV1",
            "event": "verification",
            "data": {"success": 1, "attempts": int(self._in_service_attempts)},
        }
        print(json.dumps(record), flush=True)

        # DEVS output to BPM
        req = self._in_service
        out_msg = {
            "request_time": float(req["request_time"]),
            "valid": int(req["valid"]),
            "invalid": int(req["invalid"]),
            "anv_pass": int(req["anv_pass"]),
            "pv_success": 1,
            "pv_attempts": int(self._in_service_attempts),
        }
        self.output["to_bpm"].add(out_msg)

    def deltint(self):
        # Completed current service
        self._in_service = None
        self._in_service_attempts = None
        self._pending_stdout_record = None
        self._pending_to_bpm = None

        if self._queue:
            self._start_next_service()
        else:
            self.passivate("IDLE")

    def exit(self):
        # No required terminal external I/O.
        pass