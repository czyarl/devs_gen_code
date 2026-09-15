from xdevs.models import Atomic, Coupled, Port
import json
from devs_project.devs_utils.devs_context import get_current_time


class Facility(Atomic):
    """Generates cargo pallets at regular intervals defined by pallet_interval."""

    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.add_out_port(Port(dict, "pallet_out"))
        self.pallet_id_counter = 0
        self.next_pallet_time = 0.0

    def initialize(self):
        self.pallet_id_counter = 0
        self.next_pallet_time = 0.0
        # Schedule the first pallet generation at t=0
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e):
        # This model has no input ports
        pass

    def lambdaf(self):
        if self.phase == "GENERATE":
            # Generate a new pallet
            generation_time = get_current_time()
            expiration_time = generation_time + self.pallet_expiration_time
            pallet_id = self.pallet_id_counter
            self.pallet_id_counter += 1
            
            # Send pallet to LoadingQueue
            pallet = {
                "pallet_id": pallet_id,
                "generation_time": generation_time,
                "expiration_time": expiration_time
            }
            self.output["pallet_out"].add(pallet)
            
            # Emit pallet_generated event to stdout
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
        if self.phase == "GENERATE":
            # Schedule next pallet generation
            self.next_pallet_time += self.pallet_interval
            self.hold_in("GENERATE", self.pallet_interval)
        else:
            self.passivate()

    def exit(self):
        pass