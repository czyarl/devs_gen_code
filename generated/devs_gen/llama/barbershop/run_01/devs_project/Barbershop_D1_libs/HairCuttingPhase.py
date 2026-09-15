"""Complete pattern: one semantic event has both DEVS and external effects."""

import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


def _format_time(value: float) -> str:
    """Format simulation seconds without depending on wall-clock datetime APIs."""
    total_milliseconds = int(round(value * 1000))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


class HairCuttingPhase(Atomic):
    """Announce availability internally and externally at the same event time."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "cut_in"))
        self.add_out_port(Port(dict, "out"))
        self.current_customer = None

    def initialize(self):
        self.current_customer = None
        # Initial availability is a real DEVS event, so schedule lambdaf at t=0.
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for customer in self.input["cut_in"].values:
            if self.current_customer is None:
                self.current_customer = dict(customer)
                self.hold_in("PROCESSING", 20.0)
                return
        self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "PROCESSING" and self.current_customer is not None:
            completion = {"message": "done"}
            self.output["out"].add(completion)
            print(json.dumps({
                "time": now,
                "type": "message",
                "model": self.name,
                "port": "out",
                "content": "done",
            }), flush=True)
            self.current_customer = None
            self.passivate("IDLE")

    def deltint(self):
        pass

    def exit(self):
        pass