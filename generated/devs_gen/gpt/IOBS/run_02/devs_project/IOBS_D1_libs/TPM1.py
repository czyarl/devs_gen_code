"""TPM1: Atomic TransactionProcessManager (TPM) for IOBS.

Consumes bill messages on input port `bill_in` and, after a fixed processing
delay, applies each bill amount to an internal balance and logs a JSONL
transaction event to stdout.

Stdout MUST contain only required JSONL records.
"""

import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class TPM1(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        processing_delay_s: float,
        initial_balance: int,
    ):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_s = float(processing_delay_s)
        self.initial_balance = int(initial_balance)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "bill_in"))

        # Persistent state
        self.balance: int = self.initial_balance
        self.count: int = 0
        self._queue: deque[dict] = deque()

        # Service state
        self._in_service: dict | None = None

        # Prepared stdout record to emit at the next internal event
        self._pending_stdout_record: dict | None = None

    def initialize(self):
        self.balance = self.initial_balance
        self.count = 0
        self._queue = deque()
        self._in_service = None
        self._pending_stdout_record = None
        self.passivate("IDLE")

    def _is_well_formed_bill(self, payload) -> bool:
        if not isinstance(payload, dict):
            return False
        if "amount" not in payload:
            return False
        if not isinstance(payload["amount"], int):
            return False
        return True

    def _start_next_if_idle(self) -> None:
        if self._in_service is None and self._queue:
            self._in_service = self._queue.popleft()
            self.hold_in("PROCESSING", self.processing_delay_s)

    def deltext(self, e: float):
        # Preserve remaining time if already processing; do not alter completion time.
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for bill in self.input["bill_in"].values:
            if not self._is_well_formed_bill(bill):
                print(
                    f"{self.name}: ignoring malformed bill payload: {bill!r}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            # Enqueue as-is (dict), preserving arrival order
            self._queue.append(dict(bill))

        if was_processing:
            # Keep existing schedule unchanged (except for elapsed time subtraction)
            self.hold_in("PROCESSING", remaining)
        else:
            self._start_next_if_idle()
            if self.phase != "PROCESSING":
                self.passivate("IDLE")

    def lambdaf(self):
        # No DEVS output ports. Only external IO (stdout) is required.
        if self.phase == "PROCESSING" and self._pending_stdout_record is not None:
            print(json.dumps(self._pending_stdout_record), flush=True)

    def deltint(self):
        if self.phase != "PROCESSING":
            self.passivate("IDLE")
            return

        # Complete exactly one transaction for the in-service bill
        if self._in_service is None:
            # Defensive: nothing to process; go idle.
            self._pending_stdout_record = None
            self.passivate("IDLE")
            return

        amount = int(self._in_service["amount"])
        self.balance = self.balance - amount
        self.count += 1

        t_complete = float(get_current_time())
        self._pending_stdout_record = {
            "time": t_complete,
            "model": "TPM1",
            "event": "transaction",
            "data": {"remaining": int(self.balance), "count": int(self.count)},
        }

        # Clear in-service and schedule next item if any
        self._in_service = None

        if self._queue:
            # Start next immediately; next completion is now + processing_delay_s
            self._in_service = self._queue.popleft()
            self.hold_in("PROCESSING", self.processing_delay_s)
        else:
            # Become idle with no scheduled internal event
            self.passivate("IDLE")

    def exit(self):
        # No final summary record required.
        pass