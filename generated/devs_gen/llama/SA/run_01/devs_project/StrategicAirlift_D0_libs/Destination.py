"""Complete pattern: external JSONL output owned by an atomic sink."""

import json
from xdevs.models import Atomic, Coupled, Port
from datetime import datetime


class Destination(Atomic):
    """Write only received business records to stdout as JSONL."""

    def __init__(self, name: str, parent: Coupled | None, unload_time: float = 2.0):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "pallet_delivered"))
        self.unload_time = unload_time

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for event in self.input["pallet_delivered"].values:
            self.output["event_out"].add(event)
            print(json.dumps({
                "time": datetime.now().timestamp(),
                "event": "pallet_delivered",
                "payload": event
            }), flush=True)
        self.passivate("WAITING")

    def lambdaf(self):
        # A pure sink has no DEVS output ports.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # Never print lifecycle or diagnostic records to stdout.
        pass