import json
import random
import sys
import time
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class BPM1(Atomic):
    """
    BillPaymentManager (BPM1)

    - For each pv_success_in received at time t_recv, schedule one bill completion at
      t_complete = t_recv + processing_delay_s.
    - At each completion time, generate one bill amount, emit one stdout JSONL record,
      and send one DEVS message on bill_out.
    - Track last_known_remaining from balance_update_in messages to constrain bills.
    - Support multiple overlapping PV successes via an internal pending queue.
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

        self.add_in_port(Port(dict, "pv_success_in"))
        self.add_in_port(Port(dict, "balance_update_in"))
        self.add_out_port(Port(dict, "bill_out"))

        self.last_known_remaining: int = self.initial_balance
        self._pending: list[tuple[float, dict]] = []
        self._due_outputs: list[dict] = []

        random.seed(time.time_ns())

    def initialize(self):
        self.last_known_remaining = self.initial_balance
        self._pending = []
        self._due_outputs = []

        if self.bill_amount_min > self.bill_amount_max:
            print(
                f"{self.name}: misconfiguration bill_amount_min({self.bill_amount_min}) "
                f"> bill_amount_max({self.bill_amount_max})",
                file=sys.stderr,
                flush=True,
            )
        self.passivate("IDLE")

    def _reschedule_from_pending(self) -> None:
        if not self._pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = min(t_complete for t_complete, _ctx in self._pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e: float):
        now = get_current_time()

        # Deterministic tie-break: apply external updates first, then allow internal
        # completion(s) at the same simulation time to use the updated balance.
        for msg in self.input["balance_update_in"].values:
            try:
                self.last_known_remaining = int(msg["remaining"])
            except Exception as ex:
                print(
                    f"{self.name}: malformed balance_update_in {msg!r}: {ex}",
                    file=sys.stderr,
                    flush=True,
                )

        for msg in self.input["pv_success_in"].values:
            # Schedule completion; payload retained only for traceability.
            t_complete = now + self.processing_delay_s
            self._pending.append((t_complete, dict(msg)))

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()

        # Prepare and emit all completions due at 'now'.
        # Ensure stdout is nondecreasing in time by only emitting at current time.
        self._due_outputs = []
        for t_complete, _ctx in self._pending:
            if t_complete <= now:
                try:
                    candidate = random.randint(self.bill_amount_min, self.bill_amount_max)
                except ValueError as ex:
                    # Misconfiguration; report to stderr and skip output.
                    print(
                        f"{self.name}: cannot sample bill amount from "
                        f"[{self.bill_amount_min}, {self.bill_amount_max}]: {ex}",
                        file=sys.stderr,
                        flush=True,
                    )
                    continue

                amount = int(min(candidate, self.last_known_remaining))
                payload = {"amount": amount}
                self._due_outputs.append(payload)

        for payload in self._due_outputs:
            # DEVS output
            self.output["bill_out"].add(dict(payload))

            # Required stdout JSONL event
            print(
                json.dumps(
                    {
                        "time": float(now),
                        "model": "BPM1",
                        "event": "bill",
                        "data": {"amount": int(payload["amount"])},
                    }
                ),
                flush=True,
            )

    def deltint(self):
        if self.phase != "WAITING":
            self.passivate("IDLE")
            return

        now = get_current_time()
        # Remove delivered items
        self._pending = [
            (t_complete, ctx) for (t_complete, ctx) in self._pending if t_complete > now
        ]
        self._due_outputs = []
        self._reschedule_from_pending()

    def exit(self):
        pass