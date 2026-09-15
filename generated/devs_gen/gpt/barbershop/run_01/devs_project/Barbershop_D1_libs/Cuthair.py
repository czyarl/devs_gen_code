import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Cuthair(Atomic):
    """
    Atomic DEVS model: single hair-cutting chair.

    - Accepts 'newcust' on input port 'to_cut_in' only when idle.
    - After exactly cut_time_s seconds, emits:
        * Type A state JSONL to stdout for 'total customer done' increment
        * DEVS output 'done' on port 'out' and Type B message JSONL to stdout
    - Ignores unexpected inputs with warnings to stderr.
    """

    def __init__(self, name: str, parent: Coupled | None, cut_time_s: float):
        super().__init__(name)
        self.parent = parent
        self.cut_time_s = float(cut_time_s)

        self.add_in_port(Port(str, "to_cut_in"))
        self.add_out_port(Port(str, "out"))

        self.busy: bool = False
        self.service_deadline: float | None = None
        self.total_customer_done: int = 0

        # Prepared output for the next lambdaf (only valid in OUTPUT_READY phase)
        self._pending_done: str | None = None
        self._pending_time: float | None = None

    def initialize(self):
        self.busy = False
        self.service_deadline = None
        self.total_customer_done = 0
        self._pending_done = None
        self._pending_time = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if already active.
        if self.phase != "IDLE":
            self.continuef(e)

        for msg in self.input["to_cut_in"].values:
            if msg != "newcust":
                print(
                    f"[cuthair] Warning: unexpected payload on to_cut_in: {msg!r}; ignoring.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            if self.busy:
                print(
                    "[cuthair] Warning: received 'newcust' while busy; ignoring.",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            # Accept customer only when idle.
            now = float(get_current_time())
            self.busy = True
            self.service_deadline = now + self.cut_time_s
            self.hold_in("CUTTING", self.cut_time_s)
            return

        # If idle and nothing accepted, remain idle.
        if not self.busy and self.phase == "IDLE":
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self._pending_done is not None and self._pending_time is not None:
            t = float(self._pending_time)

            # External IO: Type A state record (increment already applied before scheduling OUTPUT_READY).
            print(
                json.dumps(
                    {
                        "time": t,
                        "type": "state",
                        "model": "cuthair",
                        "field": "total customer done",
                        "value": int(self.total_customer_done),
                    }
                ),
                flush=True,
            )

            # DEVS output + External IO: Type B message record.
            self.output["out"].add(self._pending_done)
            print(
                json.dumps(
                    {
                        "time": t,
                        "type": "message",
                        "model": "cuthair",
                        "port": "out",
                        "content": self._pending_done,
                    }
                ),
                flush=True,
            )

    def deltint(self):
        if self.phase == "CUTTING":
            # Cutting completes at current simulation time.
            t_complete = float(get_current_time())

            self.total_customer_done += 1
            self._pending_done = "done"
            self._pending_time = t_complete

            # Ensure the completion time matches the scheduled deadline (within float tolerance).
            self.service_deadline = t_complete

            # Emit outputs at the same absolute simulation time via a zero-delay output phase.
            self.hold_in("OUTPUT_READY", 0.0)
            return

        if self.phase == "OUTPUT_READY":
            # Clear in-flight state and become idle again.
            self._pending_done = None
            self._pending_time = None
            self.busy = False
            self.service_deadline = None
            self.passivate("IDLE")
            return

        # Fallback: if any other phase, go idle.
        self.passivate("IDLE")

    def exit(self):
        pass