"""Complete implementation of the TrainQueue model using xdevs.py."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TrainQueue(Atomic):
    """Manages passengers currently on the train and handles their exit at specific destinations."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "passenger_exiting"))

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "entity_type": "train_queue",
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.passengers = []
        self.passenger_num = 0
        self.train_arrival_time = None
        self.passenger_exiting_time = None
        self.passenger_exiting_num = 0
        self.passivate("IDLE")

    def deltext(self, e):
        pass

    def lambdaf(self):
        if self.phase == "PROCESSING":
            self._write_event("passenger_exiting", {
                "passenger_id": self.passenger_id,
                "passenger_num": self.passenger_num,
                "origin": self.origin,
                "destination": self.destination,
            })
            self.passenger_exiting_num += 1
            if self.passenger_exiting_num == len(self.passengers):
                self.passenger_exiting_num = 0
                self.passengers = []
                self.passivate("IDLE")
            else:
                self.hold_in("PROCESSING", 0.025)

    def deltint(self):
        pass

    def exit(self):
        pass