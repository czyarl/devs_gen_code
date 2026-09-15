"""Facility DEVS model."""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class Facility(Atomic):
    """Facility model."""

    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.add_out_port(Port(dict, "pallet_generated"))
        self.next_pallet_id = 0

    def initialize(self):
        self.next_pallet_id = 0
        self.hold_in("GENERATE", self.pallet_interval)

    def deltext(self, e):
        return None

    def lambdaf(self):
        if self.phase != "GENERATE":
            return
        pallet_id = self.next_pallet_id
        expiration_time = get_current_time() + self.pallet_expiration_time
        self.output["pallet_generated"].add({"pallet_id": pallet_id, "expiration_time": expiration_time})
        print(json.dumps({"time": get_current_time(), "entity": "facility", "event": "pallet_generated", "payload": {"pallet_id": pallet_id, "expiration_time": expiration_time}}, flush=True))
        self.next_pallet_id += 1

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate()
            return
        self.hold_in("GENERATE", self.pallet_interval)

    def exit(self):
        pass