"""Atomic DEVS model for the Destination entity."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Destination(Atomic):
    """Receives delivered pallets from aircraft and computes latency."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "delivery_in"))

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for delivery in self.input["delivery_in"].values:
            # Compute latency as delivery_time - generation_time
            delivery_time = get_current_time()
            generation_time = delivery['generation_time']
            latency = delivery_time - generation_time

            # Prepare the output record as specified in the locked contract
            record = {
                "time": delivery_time,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": delivery['pallet_id'],
                    "aircraft_id": delivery['aircraft_id'],
                    "latency": latency
                }
            }

            # Write to stdout as JSONL
            print(json.dumps(record), flush=True)

        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports defined
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # No final external IO required
        pass