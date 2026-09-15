import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class TPM1(Atomic):
    """
    TransactionProcessManager (TPM1)

    Timed, stateful atomic DEVS processor that applies bill-payment transactions
    to an internal account balance and reports each completed transaction both
    externally (stdout JSONL) and internally (a DEVS balance update to BPM1).
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay_s: float, initial_balance: int):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_s = float(processing_delay_s)
        self.initial_balance = int(initial_balance)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "bill_in"))
        self.add_out_port(Port(dict, "balance_update_out"))

        # State
        self.balance: int = self.initial_balance
        self.count: int = 0
        self._pending: deque[dict] = deque()
        self._in_service: dict | None = None

        # Prepared output for lambdaf()
        self._to_send: dict | None = None

    def initialize(self):
        self.balance = self.initial_balance
        self.count = 0
        self._pending = deque()
        self._in_service = None
        self._to_send = None
        self.passivate("IDLE")

    def _is_valid_bill(self, msg: object) -> bool:
        if not isinstance(msg, dict):
            return False
        if "amount" not in msg:
            return False
        amt = msg.get("amount")
        if not isinstance(amt, int):
            return False
        if amt < 0:
            return False
        return True

    def _start_next_if_idle(self) -> None:
        if self._in_service is None and self._pending:
            self._in_service = dict(self._pending.popleft())
            # Fixed, positive processing delay per scenario/contract.
            self.hold_in("PROCESSING", self.processing_delay_s)

    def deltext(self, e: float):
        # Preserve remaining time if already processing; do not subtract elapsed
        # time from a timer started due to arrivals handled in this deltext.
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for msg in self.input["bill_in"].values:
            if not self._is_valid_bill(msg):
                print(f"{self.name}: invalid bill_in message ignored: {msg!r}", file=sys.stderr, flush=True)
                continue
            self._pending.append({"amount": int(msg["amount"])})

        if was_processing:
            self.hold_in("PROCESSING", remaining)
        else:
            self._start_next_if_idle()
            if self._in_service is None:
                self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self._to_send is not None:
            self.output["balance_update_out"].add(dict(self._to_send))

    def deltint(self):
        if self.phase != "PROCESSING" or self._in_service is None:
            # Defensive: if somehow scheduled, just become idle or continue.
            if self._pending:
                self._start_next_if_idle()
            else:
                self.passivate("IDLE")
            return

        # Completion of current in-service transaction at current simulation time.
        amount = int(self._in_service["amount"])
        remaining = int(self.balance - amount)
        self.balance = remaining
        self.count += 1

        payload = {"remaining": int(remaining), "count": int(self.count)}
        self._to_send = payload

        # External IO: stdout JSONL emission at completion time.
        t_complete = float(get_current_time())
        record = {
            "time": t_complete,
            "model": "TPM1",
            "event": "transaction",
            "data": {"remaining": int(remaining), "count": int(self.count)},
        }
        print(json.dumps(record), flush=True)

        # Finish this item and immediately start next if queued.
        self._in_service = None

        if self._pending:
            # Start next at the same simulation time; next completion at t + delay.
            self._start_next_if_idle()
            # Keep _to_send until lambdaf() of this internal event has run.
            # Note: lambdaf() is called before deltint() in xDEVS, so _to_send
            # must be prepared before the internal event fires. However, we are
            # preparing it here, so we need a zero-time OUTPUT phase to emit it.
            # To comply with xDEVS ordering, schedule an immediate output phase.
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self.hold_in("OUTPUT_READY", 0.0)

    def deltcon(self):
        # Deterministic handling at same simulation time:
        # internal completion outputs at time t, then external arrivals at time t
        # are enqueued and may start service after completion is accounted for.
        self.deltint()
        self.deltext(0.0)

    def exit(self):
        pass

    def ta(self) -> float:
        # Use base class ta behavior (sigma). Kept for clarity; not overriding.
        return super().ta()

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self._to_send is not None:
            self.output["balance_update_out"].add(dict(self._to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            if self._in_service is None:
                if self._pending:
                    self._start_next_if_idle()
                else:
                    self.passivate("IDLE")
                return

            amount = int(self._in_service["amount"])
            remaining = int(self.balance - amount)
            self.balance = remaining
            self.count += 1

            self._to_send = {"remaining": int(remaining), "count": int(self.count)}

            t_complete = float(get_current_time())
            record = {
                "time": t_complete,
                "model": "TPM1",
                "event": "transaction",
                "data": {"remaining": int(remaining), "count": int(self.count)},
            }
            print(json.dumps(record), flush=True)

            self._in_service = None

            # After completion, next service (if any) begins at same time.
            if self._pending:
                self._start_next_if_idle()
                # But must emit output now; use OUTPUT_READY immediately.
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # Clear output payload after emission and proceed with processing/idle.
            self._to_send = None
            if self._in_service is not None and self.phase != "PROCESSING":
                # If a next item was started in previous PROCESSING completion,
                # ensure we're in PROCESSING with remaining sigma already set.
                # _start_next_if_idle() already scheduled PROCESSING, but it may
                # have been overwritten by OUTPUT_READY; restore PROCESSING.
                self.hold_in("PROCESSING", self.processing_delay_s)
            else:
                # If there is queued work and idle, start it; else idle.
                if self._in_service is None and self._pending:
                    self._start_next_if_idle()
                if self._in_service is None:
                    self.passivate("IDLE")
        else:
            if self._pending and self._in_service is None:
                self._start_next_if_idle()
            if self._in_service is None:
                self.passivate("IDLE")