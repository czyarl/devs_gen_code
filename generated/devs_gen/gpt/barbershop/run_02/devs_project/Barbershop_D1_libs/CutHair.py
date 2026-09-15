import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class CutHair(Atomic):
    def __init__(self, name: str, parent: Coupled | None, cut_time_s: float):
        super().__init__(name)
        self.parent = parent

        if cut_time_s < 0.0:
            raise ValueError("cut_time_s must be nonnegative")
        self.cut_time_s = float(cut_time_s)

        self.add_in_port(Port(dict, "in_cust"))
        self.add_out_port(Port(dict, "out"))

        # State
        self.busy: bool = False
        self.in_flight: bool = False
        self.total_done: int = 0

        # Output staging for lambdaf()
        self._emit_done: bool = False
        self._done_payload: dict | None = None

    def initialize(self):
        self.busy = False
        self.in_flight = False
        self.total_done = 0

        self._emit_done = False
        self._done_payload = None

        # No startup stdout records and no startup DEVS messages.
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If busy, preserve remaining time and ignore any new arrivals.
        if self.phase == "PROCESSING":
            self.continuef(e)
            ignored = 0
            for payload in self.input["in_cust"].values:
                ignored += 1
            if ignored:
                print(
                    f"[cuthair] WARNING: received {ignored} in_cust message(s) while busy; ignoring.",
                    file=sys.stderr,
                    flush=True,
                )
            return

        # If idle, accept at most one valid newcust message.
        accepted = False
        ignored = 0
        malformed = 0

        for payload in self.input["in_cust"].values:
            if accepted:
                ignored += 1
                continue

            if not isinstance(payload, dict):
                malformed += 1
                continue
            evt = payload.get("event", None)
            if not isinstance(evt, str) or evt != "newcust":
                malformed += 1
                continue

            # Accept exactly one customer.
            accepted = True
            self.busy = True
            self.in_flight = True
            self.hold_in("PROCESSING", self.cut_time_s)

        if ignored:
            print(
                f"[cuthair] WARNING: received multiple in_cust messages while idle; accepted 1 and ignored {ignored}.",
                file=sys.stderr,
                flush=True,
            )
        if malformed:
            print(
                f"[cuthair] WARNING: ignored {malformed} malformed in_cust payload(s).",
                file=sys.stderr,
                flush=True,
            )

        if not accepted:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self._emit_done and self._done_payload is not None:
            # DEVS output message
            self.output["out"].add(dict(self._done_payload))

            # External IO Type B message record (stdout)
            t = float(get_current_time())
            msg_rec = {
                "time": t,
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done",
            }
            print(json.dumps(msg_rec), flush=True)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Completion moment: update counter and write Type A state record first,
            # then schedule immediate output for the DEVS message + Type B record.
            self.total_done += 1
            t = float(get_current_time())
            state_rec = {
                "time": t,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": int(self.total_done),
            }
            print(json.dumps(state_rec), flush=True)

            self._done_payload = {"event": "done"}
            self._emit_done = True
            self.hold_in("OUTPUT_READY", 0.0)
            return

        if self.phase == "OUTPUT_READY":
            # Clear in-flight and return to idle.
            self._emit_done = False
            self._done_payload = None
            self.busy = False
            self.in_flight = False
            self.passivate("IDLE")
            return

        # Fallback safety
        self.passivate("IDLE")

    def exit(self):
        # No final output required.
        pass