import json
import sys
from collections import deque

from devs_project.devs_utils.devs_context import get_current_time
from xdevs.models import Atomic, Coupled, Port


class TPM1(Atomic):
    """
    Atomic TransactionProcessManager (TPM1)

    Fixed-delay, sequential transaction processing with balance tracking.
    """

    def __init__(self, name: str, parent: Coupled | None, stage_delay_s: float, initial_balance: int):
        super().__init__(name)
        self.parent = parent

        self.stage_delay_s = float(stage_delay_s)
        self.initial_balance = int(initial_balance)

        self.add_in_port(Port(dict, "bill_in"))
        self.add_out_port(Port(dict, "balance_update_out"))

        # Persistent state
        self.balance: int = self.initial_balance
        self.transaction_count: int = 0

        # Service control
        self._waiting: deque[dict] = deque()
        self._in_service: dict | None = None

        # Prepared output for the next internal event
        self._pending_balance_update: dict | None = None
        self._pending_stdout_record: dict | None = None

    def initialize(self):
        self.balance = self.initial_balance
        self.transaction_count = 0

        self._waiting = deque()
        self._in_service = None

        self._pending_balance_update = None
        self._pending_stdout_record = None

        self.passivate("IDLE")

    def _validate_bill(self, bill: object) -> dict | None:
        if not isinstance(bill, dict):
            return None
        if "amount" not in bill:
            return None
        amount = bill["amount"]
        if not isinstance(amount, int):
            return None
        return {"amount": amount}

    def _start_next(self) -> None:
        self._in_service = self._waiting.popleft()
        self.hold_in("PROCESSING", self.stage_delay_s)

    def deltext(self, e: float):
        # Preserve the old timer if we were already processing.
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        # Enqueue all arrivals in arrival order.
        for msg in self.input["bill_in"].values:
            bill = self._validate_bill(msg)
            if bill is None:
                # Optional diagnostics only
                print(f"{self.name}: ignoring invalid bill message: {msg!r}", file=sys.stderr, flush=True)
                continue
            self._waiting.append(bill)

        # If idle, start service immediately after enqueuing.
        if not was_processing and self._in_service is None and self._waiting:
            self._start_next()
        elif was_processing:
            # Continue processing with preserved remaining time.
            self.hold_in("PROCESSING", remaining)

    def lambdaf(self):
        # At completion, emit both stdout JSONL and DEVS output at the same sim time.
        if self.phase == "PROCESSING" and self._pending_balance_update is not None:
            self.output["balance_update_out"].add(dict(self._pending_balance_update))

            if self._pending_stdout_record is not None:
                print(json.dumps(self._pending_stdout_record), flush=True)

    def deltint(self):
        if self.phase != "PROCESSING" or self._in_service is None:
            # Defensive: no scheduled processing should exist without an in-service bill.
            self._pending_balance_update = None
            self._pending_stdout_record = None
            if self._waiting:
                self._start_next()
            else:
                self.passivate("IDLE")
            return

        # Service completion at current simulation time.
        t_complete = float(get_current_time())
        amount = int(self._in_service["amount"])

        # Apply transaction
        self.balance = int(self.balance - amount)
        self.transaction_count = int(self.transaction_count + 1)

        # Prepare outputs for lambdaf() at this same internal event time.
        self._pending_balance_update = {"remaining": self.balance, "count": self.transaction_count}
        self._pending_stdout_record = {
            "time": t_complete,
            "model": "TPM1",
            "event": "transaction",
            "data": {"remaining": self.balance, "count": self.transaction_count},
        }

        # Clear in-service and advance to next item (starts immediately at t_complete).
        self._in_service = None

        if self._waiting:
            # Start next service immediately; next completion is t_complete + stage_delay_s.
            self._start_next()
        else:
            self.passivate("IDLE")

        # Clear pending outputs AFTER scheduling next state? No: keep them until lambdaf() emits.
        # In xDEVS order, lambdaf() runs before deltint(); thus we must clear now for next cycle.
        # However, since we're in deltint() now, lambdaf() already ran for this event.
        self._pending_balance_update = None
        self._pending_stdout_record = None

    def exit(self):
        # No required finalization output.
        pass