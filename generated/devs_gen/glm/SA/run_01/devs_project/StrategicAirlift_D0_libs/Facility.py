from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class Facility(Atomic):
    """Generates new cargo pallets at regular intervals until duration is reached."""

    def __init__(self, name: str, parent: Coupled | None, duration: float, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.duration = duration
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        
        self.add_out_port(Port(dict, "pallet_out"))
        
        self.pallet_id_counter = 1

    def initialize(self):
        self.pallet_id_counter = 1
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e: float):
        # No input ports defined for this model.
        pass

    def lambdaf(self):
        if self.phase != "GENERATE":
            return
        
        current_time = get_current_time()
        
        # Only generate if strictly less than duration
        if current_time < self.duration:
            generation_time = current_time
            deadline = generation_time + self.pallet_expiration_time
            
            # Prepare DEVS port payload
            payload = {
                'pallet_id': self.pallet_id_counter,
                'generation_time': generation_time,
                'deadline': deadline
            }
            self.output["pallet_out"].add(payload)
            
            # Prepare external IO (stdout) record
            record = {
                "time": current_time,
                "entity": "facility",
                "event": "pallet_generated",
                "payload": {
                    "pallet_id": self.pallet_id_counter,
                    "expiration_time": deadline
                }
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate()
            return
            
        current_time = get_current_time()
        
        if current_time < self.duration:
            self.pallet_id_counter += 1
            self.hold_in("GENERATE", self.pallet_interval)
        else:
            self.passivate("DONE")

    def exit(self):
        pass