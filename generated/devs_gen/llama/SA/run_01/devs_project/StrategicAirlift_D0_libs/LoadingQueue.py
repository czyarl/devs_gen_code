"""Complete model: hold pallets in queue, discard when expired, and emit events."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    """Hold pallets in queue, discard when expired, and emit events."""

    def __init__(self, name: str, parent: Coupled | None, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_expiration_time = pallet_expiration_time
        self.add_in_port(Port(dict, "pallet_arrival"))
        self.add_out_port(Port(dict, "pallet_queued"))
        self.pallet_queue = []
        self.total_expired = 0

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.pallet_queue = []
        self.total_expired = 0
        self.passivate("IDLE")

    def deltext(self, e):
        for pallet in self.input["pallet_arrival"].values:
            if self.phase == "IDLE":
                self.pallet_queue.append(pallet)
                self._write_event("pallet_queued", {
                    "pallet_id": pallet["pallet_id"],
                    "queue_size": len(self.pallet_queue),
                })
                self._check_expiration()
                self.hold_in("QUEUED", 0.0)
            else:
                self.continuef(e)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "QUEUED":
            self.passivate("IDLE")

    def _check_expiration(self):
        current_time = get_current_time()
        for pallet in self.pallet_queue[:]:
            if pallet["expiration_time"] <= current_time:
                self.pallet_queue.remove(pallet)
                self.total_expired += 1
                self._write_event("pallet_expired", {
                    "pallet_id": pallet["pallet_id"],
                    "total_expired": self.total_expired,
                })

    def exit(self):
        pass