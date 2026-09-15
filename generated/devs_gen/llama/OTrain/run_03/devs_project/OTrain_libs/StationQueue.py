"""Complete pattern: external JSONL output owned by an atomic model."""

import json
from xdevs.models import Atomic, Coupled, Port


class StationQueue(Atomic):
    """Manages passengers waiting at a station to board the train."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "passenger_boarding"))

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        # Process external inputs here
        self.passivate("WAITING")

    def lambdaf(self):
        # Emit DEVS output port here
        # Example: self.output["passenger_boarding"].add({"passenger_id": 1, "passenger_num": 1, "origin": 1, "destination": 2})
        pass

    def deltint(self):
        # Process internal events here
        self.passivate("WAITING")

    def exit(self):
        # Perform external IO here
        pass