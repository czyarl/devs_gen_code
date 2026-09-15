from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.add_out_port(Port(dict, "pallet_generated"))

    def initialize(self):
        self.hold_in("EMIT", 0.0)

    def deltext(self, e):
        return None

    def lambdaf(self):
        if self.phase != "EMIT":
            return
        emitted_at = get_current_time()
        pallet_id = id(self)
        expiration_time = emitted_at + self.pallet_expiration_time
        pallet = {
            "pallet_id": pallet_id,
            "expiration_time": expiration_time
        }
        self.output["pallet_generated"].add(pallet)
        print(json.dumps({
            "time": emitted_at,
            "entity": "facility",
            "event": "pallet_generated",
            "payload": pallet
        }), flush=True)
        self.hold_in("EMIT", self.pallet_interval)

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate()
            return

    def exit(self):
        pass