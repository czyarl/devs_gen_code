import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Destination(Atomic):
    """Atomic model representing the destination point for cargo.
    
    Receives delivery confirmation messages on the `delivery_in` port.
    Calculates latency and writes a JSONL record to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Input port for delivery confirmation
        self.add_in_port(Port(dict, "delivery_in"))

    def initialize(self):
        # The model passively waits for input.
        self.passivate("WAITING")

    def deltext(self, e):
        """Handle external input on `delivery_in`."""
        # Iterate over all incoming events on the delivery_in port
        for payload in self.input["delivery_in"].values:
            # Extract required fields from the payload
            # Structure: {'aircraft_id': int, 'pallet_id': int, 'generation_time': float}
            aircraft_id = payload["aircraft_id"]
            pallet_id = payload["pallet_id"]
            generation_time = payload["generation_time"]
            
            # Get current simulation time
            current_time = get_current_time()
            
            # Calculate latency
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
            
            # Write to stdout (Stream 1)
            print(json.dumps(record), flush=True)
        
        # Remain passive after processing the input
        self.passivate("WAITING")

    def lambdaf(self):
        """Internal transition output function.
        
        This model has no output ports, so this is empty.
        """
        pass

    def deltint(self):
        """Internal transition function.
        
        Since we passivate in deltext and initialize, this is only reached
        if we scheduled an internal event, which we do not.
        """
        self.passivate("WAITING")

    def exit(self):
        """Cleanup function.
        
        No specific cleanup required for this model.
        """
        pass