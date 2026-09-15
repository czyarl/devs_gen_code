from xdevs.models import Atomic, Coupled, Port
import json
import sys
from devs_project.devs_utils.devs_context import get_current_time


class Facility(Atomic):
    """Generates pallets at fixed intervals starting at t=0."""

    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, duration: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.duration = duration
        self.add_out_port(Port(dict, "pallet_out"))
        self.pallet_id_counter = 0
        self.next_generation_time = 0.0

    def initialize(self):
        self.pallet_id_counter = 0
        self.next_generation_time = 0.0
        # Schedule the first pallet generation at t=0
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e):
        # This model has no input ports
        pass

    def lambdaf(self):
        if self.phase == "GENERATE":
            # Generate a pallet
            generation_time = get_current_time()
            expiration_time = generation_time + self.pallet_interval  # Using pallet_interval as expiration time for now
            pallet_id = self.pallet_id_counter
            self.pallet_id_counter += 1

            # Send pallet to LoadingQueue
            pallet_data = {
                "pallet_id": pallet_id,
                "expiration_time": expiration_time
            }
            self.output["pallet_out"].add(pallet_data)

            # Write event to stdout
            event_record = {
                "time": generation_time,
                "entity": "facility",
                "event": "pallet_generated",
                "payload": {
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            }
            print(json.dumps(event_record), flush=True)

    def deltint(self):
        current_time = get_current_time()
        if self.phase == "GENERATE":
            # Check if we should continue generating pallets
            if current_time + self.pallet_interval < self.duration:
                self.next_generation_time += self.pallet_interval
                self.hold_in("GENERATE", self.pallet_interval)
            else:
                self.passivate()
        else:
            self.passivate()

    def exit(self):
        pass