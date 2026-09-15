import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ReceptionDesk(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "cust"))
        self.add_out_port(Port(dict, "queue_status"))
        self.queue = []
        self.processing_customer = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.queue = []
        self.processing_customer = None
        self.passivate("IDLE")

    def deltext(self, e):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def exit(self):
        pass