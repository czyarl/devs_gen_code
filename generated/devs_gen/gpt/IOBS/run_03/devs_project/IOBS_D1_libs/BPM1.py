import json
import random
import sys
from collections import deque

from devs_project.devs_utils.devs_context import get_current_time
from xdevs.models import Atomic, Coupled, Port


class BPM1(Atomic):
    """
    Atomic BillPaymentManager (BPM1)

    - Receives PV-success requests on request_in (dict), buffers FIFO, single-server.
    - Receives balance updates on balance_update_in (dict) and stores latest remaining balance.
    - After fixed delay stage_delay_s per request, generates a bill amount constrained by
      bill_min/bill_max and current remaining balance, logs JSONL to stdout, and emits bill_out.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        stage_delay_s: float,
        bill_min: int,
        bill_max: int,
        initial_remaining_balance: int,
    ):
        super().__init__(name)
        self.parent = parent

        self.stage_delay_s = float(stage_delay_s)
        self.bill_min = int(bill_min)
        self.bill_max = int(bill_max)
        self.initial_remaining_balance = int(initial_remaining_balance)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "request_in"))
        self.add_in_port(Port(dict, "balance_update_in"))
        self.add_out_port(Port(dict, "bill_out"))

        # State
        self.remaining_balance: int = self.initial_remaining_balance
        self._queue: deque[dict] = deque()
        self._in_flight: dict | None = None

        # Prepared output for lambdaf()
        self._pending_bill_payload: dict | None = None
        self._pending_bill_log_record: dict | None = None

    def initialize(self):
        self.remaining_balance = self.initial_remaining_balance
        self._queue = deque()
        self._in_flight = None
        self._pending_bill_payload = None
        self._pending_bill_log_record = None
        self.passivate("IDLE")

    def _start_next(self) -> None:
        self._in_flight = self._queue.popleft()
        self.hold_in("PROCESSING", self.stage_delay_s)

    def _choose_amount(self) -> int:
        # Constrain by remaining balance at completion time.
        cap = min(self.bill_max, self.remaining_balance)
        if cap < self.bill_min:
            # Clamp to feasible nonnegative payment, also <= bill_max.
            return int(max(0, min(self.bill_max, self.remaining_balance)))
        return int(random.randint(self.bill_min, cap))

    def deltext(self, e: float):
        # Preserve remaining time only if we were already processing before this external transition.
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        # Consume balance updates first (order within same time doesn't matter; only latest at completion matters).
        for msg in self.input["balance_update_in"].values:
            try:
                self.remaining_balance = int(msg["remaining"])
            except Exception as ex:
                print(f"{self.name}: malformed balance_update_in {msg!r}: {ex}", file=sys.stderr, flush=True)

        # Enqueue all incoming requests
        for req in self.input["request_in"].values:
            self._queue.append(dict(req))

        if not was_processing and self.phase != "OUTPUT_READY" and self._in_flight is None and self._queue:
            self._start_next()
        elif was_processing:
            self.hold_in("PROCESSING", remaining)
        # If OUTPUT_READY, keep it; do not reschedule here.

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self._pending_bill_payload is not None:
            # External IO: required JSONL record to stdout at the same simulation time as DEVS output.
            if self._pending_bill_log_record is not None:
                print(json.dumps(self._pending_bill_log_record), flush=True)
            self.output["bill_out"].add(dict(self._pending_bill_payload))

    def deltint(self):
        if self.phase == "PROCESSING":
            # Prepare output for immediate emission at the same simulation time.
            t_complete = float(get_current_time())
            amount = self._choose_amount()

            self._pending_bill_payload = {"amount": int(amount)}
            self._pending_bill_log_record = {
                "time": t_complete,
                "model": "BPM1",
                "event": "bill",
                "data": {"amount": int(amount)},
            }
            self.hold_in("OUTPUT_READY", 0.0)
            return

        if self.phase == "OUTPUT_READY":
            # Clear emitted payload and advance.
            self._pending_bill_payload = None
            self._pending_bill_log_record = None
            self._in_flight = None

            if self._queue:
                self._start_next()
            else:
                self.passivate("IDLE")
            return

        # Fallback: if somehow called in another phase, passivate safely.
        self.passivate("IDLE")

    def exit(self):
        # No required finalization output.
        pass