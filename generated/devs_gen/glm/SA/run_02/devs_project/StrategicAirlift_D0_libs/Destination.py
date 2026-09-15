import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Destination(Atomic):
    """Act as a passive sink for delivery confirmations."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        # Input port for delivery info
        self.add_in_port(Port(dict, "delivery_in"))
        # No output ports defined in the contract

    def initialize(self):
        # The model retains no internal state and performs no autonomous transitions.
        # It waits passively for input.
        self.passivate("WAITING")

    def deltext(self, e):
        # Process all incoming delivery events
        for packet in self.input["delivery_in"].values:
            # packet structure: {"aircraft_id": int, "pallet_id": int, "generation_time": float}
            aircraft_id = packet["aircraft_id"]
            pallet_id = packet["pallet_id"]
            generation_time = packet["generation_time"]

            # Compute latency
            current_time = get_current_time()
            latency = current_time - generation_time

            # Construct the JSONL record
            record = {
                "time": current_time,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": pallet_id,
                    "aircraft_id": aircraft_id,
                    "latency": latency
                }
            }

            # Write to stdout immediately
            print(json.dumps(record), flush=True)

        # Return to passive state
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports are defined for this model
        pass

    def deltint(self):
        # No autonomous internal transitions
        self.passivate("WAITING")

    def exit(self):
        # No final external IO required
        pass