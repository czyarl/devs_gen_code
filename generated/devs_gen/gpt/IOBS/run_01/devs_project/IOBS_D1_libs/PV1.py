import json
import random
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PV1(Atomic):
    """
    PV1 (PasswordVerifier): accepts requests from ANV1, waits a fixed delay per
    request, then deterministically succeeds after a geometric number of
    Bernoulli(0.5) attempts, emitting both stdout JSONL and a DEVS message.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay_s: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_s = float(processing_delay_s)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "to_bpm_out"))

        # pending items: list of (deadline_time: float, payload: dict)
        self._pending: list[tuple[float, dict]] = []
        # prepared outputs for the next lambdaf: list of dict payloads
        self._due_outputs: list[dict] = []

    def initialize(self):
        self._pending = []
        self._due_outputs = []
        self.passivate("IDLE")

    def _reschedule_from_pending(self) -> None:
        if not self._pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_deadline = min(deadline for deadline, _ in self._pending)
        self.hold_in("WAITING", max(0.0, next_deadline - now))

    @staticmethod
    def _compute_attempts_until_success() -> int:
        attempts = 1
        while True:
            if random.random() < 0.5:
                return attempts
            attempts += 1

    def deltext(self, e: float):
        now = get_current_time()

        for item in self.input["request_in"].values:
            # Treat as opaque context; store a copy, but only specified fields are forwarded later.
            payload = dict(item)
            deadline = now + self.processing_delay_s
            self._pending.append((deadline, payload))

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()

        # Prepare and emit all outputs due at 'now' (deadline == now; tolerate float jitter with <=).
        self._due_outputs = []
        for deadline, payload in self._pending:
            if deadline <= now:
                attempts = self._compute_attempts_until_success()

                # Required stdout JSONL record (and nothing else to stdout).
                print(json.dumps({
                    "time": float(now),
                    "model": "PV1",
                    "event": "verification",
                    "data": {
                        "success": 1,
                        "attempts": int(attempts),
                    }
                }), flush=True)

                out_msg = {
                    "request_time": float(payload["request_time"]),
                    "valid": int(payload["valid"]),
                    "invalid": int(payload["invalid"]),
                    "attempts": int(attempts),
                }
                self._due_outputs.append(out_msg)

        for out_msg in self._due_outputs:
            self.output["to_bpm_out"].add(out_msg)

    def deltint(self):
        now = get_current_time()

        # Remove all items that were due at this firing time.
        self._pending = [
            (deadline, payload)
            for deadline, payload in self._pending
            if deadline > now
        ]
        self._due_outputs = []
        self._reschedule_from_pending()

    def exit(self):
        # No required finalization IO.
        pass