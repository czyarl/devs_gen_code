"""Atomic DEVS model for LoadingQueue."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """Monitors pallet deadlines and discards pallets when deadlines are exceeded."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "pallet_arrival"))
        self.add_out_port(Port(dict, "pallet_queued"))
        self.add_out_port(Port(dict, "pallet_expired"))
        self.pallets = {}
        self.total_expired = 0

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.pallets = {}
        self.total_expired = 0
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["pallet_arrival"].values:
            pallet_id = packet["pallet_id"]
            expiration_time = packet["expiration_time"]
            if pallet_id in self.pallets:
                # Ignore duplicate arrivals
                continue
            self.pallets[pallet_id] = expiration_time
            self._write_event("pallet_queued", {
                "pallet_id": pallet_id,
                "queue_size": len(self.pallets),
            })
            self.check_deadlines()

    def lambdaf(self):
        pass

    def deltint(self):
        self.check_deadlines()
        self.passivate("IDLE")

    def exit(self):
        pass

    def check_deadlines(self):
        current_time = get_current_time()
        expired_pallets = [pallet_id for pallet_id, expiration_time in self.pallets.items() if current_time >= expiration_time]
        for pallet_id in expired_pallets:
            self._write_event("pallet_expired", {
                "pallet_id": pallet_id,
                "total_expired": self.total_expired + 1,
            })
            self.total_expired += 1
            del self.pallets[pallet_id]