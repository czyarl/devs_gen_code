import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class Facility(Atomic):
    """Generates cargo pallets autonomously starting at t=0."""

    def __init__(self, name: str, parent: Coupled | None, duration: float, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.duration = duration
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        
        # Internal state
        self.pallet_id_counter = 0
        
        # Ports
        self.add_out_port(Port(dict, "pallet_out"))

    def initialize(self):
        self.pallet_id_counter = 0
        # Schedule first generation at t=0
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e: float):
        # No input ports, so this is a no-op, but required by interface.
        pass

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        current_time = get_current_time()
        
        # Calculate absolute expiration time
        # Note: The contract says "absolute expiration_time as generation_time + pallet_expiration_time"
        expiration_time = current_time + self.pallet_expiration_time
        
        # Prepare DEVS port payload
        # Structure: {'pallet_id': int, 'generation_time': float, 'expiration_time': float}
        port_payload = {
            "pallet_id": self.pallet_id_counter,
            "generation_time": current_time,
            "expiration_time": expiration_time
        }
        self.output["pallet_out"].add(port_payload)

        # Prepare External IO (stdout) payload
        # Schema: {'time': float, 'entity': 'facility', 'event': 'pallet_generated', 'payload': {'pallet_id': int, 'expiration_time': float}}
        external_record = {
            "time": current_time,
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": self.pallet_id_counter,
                "expiration_time": expiration_time
            }
        }
        
        # Write to stdout
        print(json.dumps(external_record), flush=True)

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate()
            return

        # Increment ID for next generation
        self.pallet_id_counter += 1
        
        current_time = get_current_time()
        next_generation_time = current_time + self.pallet_interval

        # Check if next generation is within duration
        # Contract: "If the next scheduled generation time is greater than or equal to duration, the model passivates"
        if next_generation_time >= self.duration:
            self.passivate()
        else:
            self.hold_in("GENERATE", self.pallet_interval)

    def exit(self):
        pass