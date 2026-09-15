import sys
import json
import random
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ANV1(Atomic):
    """
    AccountNumberVerifier (ANV1): FIFO buffered single-server with fixed processing delay.
    On completion of each request, emits exactly one JSONL stdout record of event type
    'verification' and forwards the request to PV1 only if verification passes (50/50).
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay_s: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_s = float(processing_delay_s)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_pv"))

        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

        # Prepared at completion time (before lambdaf is called)
        self._last_result_pass: bool | None = None
        self._forward_payload: dict | None = None

    def initialize(self):
        self._queue = deque()
        self._in_flight = None
        self._last_result_pass = None
        self._forward_payload = None
        self.passivate("IDLE")

    def _start_next(self) -> None:
        self._in_flight = self._queue.popleft()
        self.hold_in("PROCESSING", self.processing_delay_s)

    def deltext(self, e: float):
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for req in self.input["request_in"].values:
            if not isinstance(req, dict):
                print(
                    f"ANV1 received non-dict payload on request_in: {type(req)}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            # Keep payload unchanged for forwarding; copy to avoid aliasing.
            self._queue.append(dict(req))

        if not was_processing and self._in_flight is None and self._queue:
            self._start_next()
        elif was_processing:
            # Preserve the already-running timer; do not subtract elapsed from a fresh timer.
            self.hold_in("PROCESSING", remaining)

    def lambdaf(self):
        # Only emit DEVS outputs here.
        if self.phase == "PROCESSING" and self._forward_payload is not None:
            self.output["to_pv"].add(dict(self._forward_payload))

    def deltint(self):
        if self.phase != "PROCESSING" or self._in_flight is None:
            # Defensive: if somehow scheduled without in-flight work, go idle.
            self._in_flight = None
            self._last_result_pass = None
            self._forward_payload = None
            if self._queue:
                self._start_next()
            else:
                self.passivate("IDLE")
            return

        # Completion time is the current simulation time at internal transition.
        t_complete = float(get_current_time())

        # Random decision at completion time; independent Bernoulli(0.5).
        passed = random.random() < 0.5
        self._last_result_pass = passed

        # Required stdout JSONL record (and nothing else on stdout).
        record = {
            "time": t_complete,
            "model": "ANV1",
            "event": "verification",
            "data": {"pass": 1 if passed else 0, "fail": 0 if passed else 1},
        }
        print(json.dumps(record), flush=True)

        # Prepare forwarding for lambdaf at the same simulation time.
        if passed:
            self._forward_payload = dict(self._in_flight)
            # Ensure an immediate output at the same simulation time.
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self._forward_payload = None
            # Move on immediately to next request (if any) at the same simulation time.
            self._in_flight = None
            self._last_result_pass = None
            if self._queue:
                self._start_next()
            else:
                self.passivate("IDLE")

    def deltcon(self):
        # Default behavior is acceptable; keep xDEVS default confluent semantics.
        super().deltcon()

    def exit(self):
        # No required shutdown actions.
        pass

    # Handle the zero-delay output phase after completion.
    def deltint(self):  # type: ignore[override]
        if self.phase == "OUTPUT_READY":
            # After lambdaf has emitted, clear and continue with next request.
            self._forward_payload = None
            self._in_flight = None
            self._last_result_pass = None
            if self._queue:
                self._start_next()
            else:
                self.passivate("IDLE")
            return

        # Otherwise, it's a PROCESSING completion.
        if self.phase != "PROCESSING" or self._in_flight is None:
            self._in_flight = None
            self._last_result_pass = None
            self._forward_payload = None
            if self._queue:
                self._start_next()
            else:
                self.passivate("IDLE")
            return

        t_complete = float(get_current_time())
        passed = random.random() < 0.5
        self._last_result_pass = passed

        record = {
            "time": t_complete,
            "model": "ANV1",
            "event": "verification",
            "data": {"pass": 1 if passed else 0, "fail": 0 if passed else 1},
        }
        print(json.dumps(record), flush=True)

        if passed:
            self._forward_payload = dict(self._in_flight)
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self._forward_payload = None
            self._in_flight = None
            self._last_result_pass = None
            if self._queue:
                self._start_next()
            else:
                self.passivate("IDLE")