import json
import random
import sys
import time
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class BPM1(Atomic):
    """
    BillPaymentManager (BPM1): single-server FIFO buffered timed processor.

    - Input: request_in: {'request_time': float}
    - Output: bill_out: {'amount': int}
    - On each completion after fixed delay, generate a random bill amount in
      [bill_amount_min, bill_amount_max] constrained by local remaining balance,
      print one JSONL record to stdout, and emit one DEVS message on bill_out.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        processing_delay_s: float,
        bill_amount_min: int,
        bill_amount_max: int,
        initial_balance: int,
    ):
        super().__init__(name)
        self.parent = parent

        self.processing_delay_s = float(processing_delay_s)
        self.bill_amount_min = int(bill_amount_min)
        self.bill_amount_max = int(bill_amount_max)
        self.initial_balance = int(initial_balance)

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "bill_out"))

        self._queue: deque[dict] = deque()
        self._in_service: dict | None = None

        self._remaining_local: int = self.initial_balance

        # Prepared at completion time, emitted in lambdaf()
        self._amount_to_emit: int | None = None

    def initialize(self):
        random.seed(time.time_ns())
        self._queue = deque()
        self._in_service = None
        self._remaining_local = self.initial_balance
        self._amount_to_emit = None
        self.passivate("IDLE")

    def _start_next(self) -> None:
        self._in_service = self._queue.popleft()
        self.hold_in("PROCESSING", self.processing_delay_s)

    def deltext(self, e: float):
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for req in self.input["request_in"].values:
            # Preserve payload shape; only request_time is expected.
            self._queue.append(dict(req))

        if not was_processing and self._in_service is None and self._queue:
            self._start_next()
        elif was_processing:
            self.hold_in("PROCESSING", remaining)

    def _compute_amount_and_update_balance(self) -> int:
        remaining_local = int(self._remaining_local)
        cap = min(self.bill_amount_max, remaining_local)

        if cap < self.bill_amount_min:
            amount = int(cap)
        else:
            amount = int(random.randint(self.bill_amount_min, cap))

        if amount > remaining_local:
            amount = remaining_local
        if amount < 0:
            amount = 0

        self._remaining_local = remaining_local - amount
        if self._remaining_local < 0:
            self._remaining_local = 0

        return amount

    def lambdaf(self):
        if self.phase != "PROCESSING" or self._in_service is None:
            return

        # Completion occurs at current simulation time.
        t_complete = float(get_current_time())

        amount = self._compute_amount_and_update_balance()
        self._amount_to_emit = amount

        record = {
            "time": t_complete,
            "model": "BPM1",
            "event": "bill",
            "data": {"amount": amount},
        }
        print(json.dumps(record), flush=True)

        self.output["bill_out"].add({"amount": amount})

    def deltint(self):
        # One request completed.
        self._in_service = None
        self._amount_to_emit = None

        if self._queue:
            self._start_next()
        else:
            self.passivate("IDLE")

    def exit(self):
        pass