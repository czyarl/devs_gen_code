from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys

class Facility(Atomic):
    """Generates cargo pallets at regular intervals and emits them to the Loading Queue."""

    def __init__(self, name: str, parent: Coupled | None, duration: float, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.duration = duration
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        
        # Initialize state variables
        self.pallet_id_counter = 0
        self.current_pallet_payload = None
        
        # Define ports
        self.add_out_port(Port(dict, "pallet_out"))

    def initialize(self):
        """Initialize the model and schedule the first generation at t=0."""
        self.pallet_id_counter = 0
        self.current_pallet_payload = None
        # Schedule the first event immediately at t=0
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e: float):
        """This model has no input ports, so this method does nothing."""
        # No external inputs to process
        pass

    def lambdaf(self):
        """Emit the generated pallet to the output port and write to stdout."""
        if self.phase != "GENERATE":
            return

        current_time = get_current_time()

        # Prepare the internal payload for the DEVS port
        # Structure: {"pallet_id": int, "generation_time": float, "expiration_time": float}
        self.current_pallet_payload = {
            "pallet_id": self.pallet_id_counter,
            "generation_time": current_time,
            "expiration_time": current_time + self.pallet_expiration_time
        }
        
        # Emit to DEVS port
        self.output["pallet_out"].add(self.current_pallet_payload)

        # Write external IO (JSONL to stdout)
        # Schema: {"time": <float>, "entity": "facility", "event": "pallet_generated", "payload": {...}}
        record = {
            "time": current_time,
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": self.pallet_id_counter,
                "expiration_time": current_time + self.pallet_expiration_time
            }
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        """Transition to the next generation state or passivate if duration is reached."""
        if self.phase != "GENERATE":
            self.passivate()
            return

        # Increment ID for the next pallet
        self.pallet_id_counter += 1
        
        # Check if we should continue generating
        # The contract says "Stop generating when time >= duration"
        # We calculate the time of the *next* generation to decide.
        # Since deltint happens after lambdaf, get_current_time() here is the time of the current event.
        current_time = get_current_time()
        next_generation_time = current_time + self.pallet_interval

        if next_generation_time < self.duration:
            # Schedule the next generation
            self.hold_in("GENERATE", self.pallet_interval)
        else:
            # Stop generating
            self.passivate()

    def exit(self):
        """Clean up resources."""
        pass