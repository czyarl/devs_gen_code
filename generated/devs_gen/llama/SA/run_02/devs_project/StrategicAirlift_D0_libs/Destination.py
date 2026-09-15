"""Complete pattern: external JSONL output owned by an atomic sink."""

import json
from xdevs.models import Atomic, Coupled, Port
import argparse
import sys


class Destination(Atomic):
    """Write only received business records to stdout as JSONL."""

    def __init__(self, name: str, parent: Coupled | None, unload_time: float):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "pallet_delivered"))
        self.unload_time = unload_time

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for event in self.input["pallet_delivered"].values:
            # This is OS-level external IO, not a DEVS port write. The target
            # specification determines the exact schema used in real code.
            current_time = get_current_time()
            event['latency'] = current_time - event['generation_time']
            print(json.dumps({"time": current_time, "entity": "destination", "event": "pallet_delivered", "payload": event}), flush=True)
        self.passivate("WAITING")

    def lambdaf(self):
        # A pure sink has no DEVS output ports.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # Never print lifecycle or diagnostic records to stdout.
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--unload_time", type=float, default=2.0)
    args = parser.parse_args()
    model = Destination("Destination", None, args.unload_time)
    # Run the model