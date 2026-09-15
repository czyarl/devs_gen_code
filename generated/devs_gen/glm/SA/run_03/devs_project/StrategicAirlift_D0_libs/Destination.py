import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class Destination(Atomic):
    """
    Receives delivery confirmation from Aircraft.
    Computes latency and writes 'pallet_delivered' record to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Input port: delivery_in
        # Structure: {'aircraft_id': int, 'pallet_id': int, 'generation_time': float}
        self.add_in_port(Port(dict, "delivery_in"))

    def initialize(self):
        # Start in a passive state waiting for input
        self.passivate("IDLE")

    def deltext(self, e: float):
        """
        Handle external events (delivery info from Aircraft).
        """
        # Iterate over all incoming messages on delivery_in
        for payload in self.input["delivery_in"].values:
            # Extract required fields
            aircraft_id = payload["aircraft_id"]
            pallet_id = payload["pallet_id"]
            generation_time = payload["generation_time"]
            
            # Get current simulation time (delivery time)
            delivery_time = get_current_time()
            
            # Calculate latency
            latency = delivery_time - generation_time
            
            # Construct the JSONL record
            record = {
                "time": delivery_time,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": pallet_id,
                    "aircraft_id": aircraft_id,
                    "latency": latency
                }
            }
            
            # Write to stdout immediately upon receipt
            print(json.dumps(record), flush=True)
        
        # Return to passive state
        self.passivate("IDLE")

    def lambdaf(self):
        # This model has no output ports, so nothing to do here.
        pass

    def deltint(self):
        # This model is purely reactive and does not schedule internal events.
        # If deltint is called, it implies a logic error or unsupported transition,
        # but we must define it. We passivate to be safe.
        self.passivate("IDLE")

    def exit(self):
        # No final state output required for this model.
        pass