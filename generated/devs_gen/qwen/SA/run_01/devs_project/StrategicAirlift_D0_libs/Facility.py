from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json


class Facility(Atomic):
    """Generate pallets at regular intervals starting at t=0."""

    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, pallet_expiration_time: float, duration: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.duration = duration
        self.add_out_port(Port(dict, "pallet_out"))
        self.pallet_id_counter = 0
        self.next_pallet_time = 0.0

    def initialize(self):
        # Schedule the first pallet generation at t=0
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e):
        # This model has no input ports
        pass

    def lambdaf(self):
        if self.phase == "GENERATE":
            # Generate a pallet
            generation_time = get_current_time()
            expiration_time = generation_time + self.pallet_expiration_time
            pallet_id = self.pallet_id_counter
            self.pallet_id_counter += 1

            # Emit the pallet through the output port
            pallet_payload = {
                "pallet_id": pallet_id,
                "expiration_time": expiration_time
            }
            self.output["pallet_out"].add(pallet_payload)

            # Write to stdout as per external_io requirement
            record = {
                "time": generation_time,
                "entity": "facility",
                "event": "pallet_generated",
                "payload": {
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        current_time = get_current_time()
        if self.phase == "GENERATE":
            # Check if we should generate the next pallet
            next_generation_time = self.next_pallet_time + self.pallet_interval
            if next_generation_time < self.duration:
                self.next_pallet_time = next_generation_time
                self.hold_in("GENERATE", self.pallet_interval)
            else:
                # No more pallets to generate
                self.passivate()
        else:
            self.passivate()

    def exit(self):
        pass