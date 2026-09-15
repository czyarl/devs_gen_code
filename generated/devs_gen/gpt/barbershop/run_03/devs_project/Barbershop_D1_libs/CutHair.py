import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CutHair(Atomic):
    """
    Atomic DEVS model: barbershop Hair Cutting Phase (cuthair).

    - Input: 'newcust' on port to_cut_in
    - Processing: deterministic cut_time_s seconds per customer, single-server
    - Output: 'done' on port out upon completion
    - External IO: JSONL records to stdout on each completion (message + state)
    """

    def __init__(self, name: str, parent: Coupled | None, cut_time_s: float):
        super().__init__(name)
        self.parent = parent

        if cut_time_s < 0.0:
            raise ValueError(f"cut_time_s must be nonnegative, got {cut_time_s}")
        self.cut_time_s = float(cut_time_s)

        self.add_in_port(Port(str, "to_cut_in"))
        self.add_out_port(Port(str, "out"))

        # State
        self.busy: bool = False
        self.waiting: deque[str] = deque()
        self.in_flight: str | None = None
        self.total_customer_done: int = 0

        # Prepared output flag for lambdaf()
        self._emit_done_now: bool = False

    def initialize(self):
        self.busy = False
        self.waiting = deque()
        self.in_flight = None
        self.total_customer_done = 0
        self._emit_done_now = False
        self.passivate("IDLE")

    def _start_next(self) -> None:
        self.in_flight = self.waiting.popleft()
        self.busy = True
        self._emit_done_now = False
        self.hold_in("PROCESSING", self.cut_time_s)

    def deltext(self, e: float):
        # Preserve remaining time if already processing; do not subtract elapsed
        # time from a timer that is newly started during this deltext.
        was_processing = self.phase == "PROCESSING"
        remaining = max(0.0, self.ta() - e) if was_processing else None

        for msg in self.input["to_cut_in"].values:
            if msg == "newcust":
                self.waiting.append("newcust")
            else:
                print(
                    f"CutHair ignoring unexpected input on to_cut_in: {msg!r}",
                    file=sys.stderr,
                    flush=True,
                )

        if not was_processing and not self._emit_done_now and not self.busy and self.waiting:
            self._start_next()
        elif was_processing:
            self.hold_in("PROCESSING", remaining)

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight is not None:
            now = float(get_current_time())

            # DEVS output
            self.output["out"].add("done")

            # External IO (stdout JSONL only): deterministic order at same timestamp
            print(
                json.dumps(
                    {
                        "time": now,
                        "type": "message",
                        "model": "cuthair",
                        "port": "out",
                        "content": "done",
                    }
                ),
                flush=True,
            )

            # Increment counter at completion time and emit state-change record
            self.total_customer_done += 1
            print(
                json.dumps(
                    {
                        "time": now,
                        "type": "state",
                        "model": "cuthair",
                        "field": "total customer done",
                        "value": int(self.total_customer_done),
                    }
                ),
                flush=True,
            )

    def deltint(self):
        if self.phase == "PROCESSING":
            self.in_flight = None
            self.busy = False
            self._emit_done_now = False

            if self.waiting:
                self._start_next()
            else:
                self.passivate("IDLE")
        else:
            # Any other phase is not used; remain passive deterministically.
            self.passivate("IDLE")

    def exit(self):
        pass