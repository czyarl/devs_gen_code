"""Complete pattern: external JSONL output owned by an atomic sink."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Destination(Atomic):
    """Receive completed deliveries from Aircraft and compute delivery latency; independently write each delivery record to stdout."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "delivery_in"))

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for delivery in self.input["delivery_in"].values:
            # Compute latency as the difference between current simulation time and generation_time
            current_time = get_current_time()
            generation_time = delivery["generation_time"]
            latency = current_time - generation_time

            # Prepare the JSONL record as specified
            record = {
                "time": current_time,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": delivery["pallet_id"],
                    "aircraft_id": delivery["aircraft_id"],
                    "latency": latency
                }
            }

            # Write to stdout as per external_io specification
            print(json.dumps(record), flush=True)

        self.passivate("WAITING")

    def lambdaf(self):
        # A pure sink has no DEVS output ports.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # Never print lifecycle or diagnostic records to stdout.
        pass