import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class LoadingQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_expiration_time = pallet_expiration_time
        self.add_in_port(Port(dict, "pallet_arrived"))
        self.add_out_port(Port(dict, "pallet_queued"))
        self.add_out_port(Port(dict, "pallet_expired"))
        self.pallets = []
        self.total_expired = 0

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.pallets = []
        self.total_expired = 0
        self.passivate("IDLE")

    def deltext(self, e):
        was_idle = self.phase == "IDLE"
        if was_idle:
            self.continuef(e)

        for item in self.input["pallet_arrived"].values:
            pallet_id = item['pallet_id']
            expiration_time = item['expiration_time']
            self.pallets.append((pallet_id, expiration_time))
            self._write_event("pallet_queued", {
                "pallet_id": pallet_id,
                "queue_size": len(self.pallets),
            })

    def lambdaf(self):
        pass

    def deltint(self):
        current_time = get_current_time()
        expired_pallets = [pallet for pallet in self.pallets if pallet[1] <= current_time]
        for pallet in expired_pallets:
            self.pallets.remove(pallet)
            self._write_event("pallet_expired", {
                "pallet_id": pallet[0],
                "total_expired": self.total_expired + 1,
            })
            self.total_expired += 1
        if self.pallets:
            self.hold_in("IDLE", 0.0)
        else:
            self.passivate("IDLE")

    def exit(self):
        pass