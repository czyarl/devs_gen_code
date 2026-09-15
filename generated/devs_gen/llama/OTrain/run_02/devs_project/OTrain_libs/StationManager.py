"""StationManager Atomic DEVS model implementation."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class StationManager(Atomic):
    """Manages passengers waiting at each station and handles boarding and exiting."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "train_arrival"))
        self.add_in_port(Port(dict, "passenger_generated"))
        self.add_out_port(Port(dict, "passenger_boarding"))
        self.add_out_port(Port(dict, "passenger_exiting"))

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.passengers_waiting = {}
        self.passengers_on_train = {}
        self.passenger_num = 0
        self.passivate("IDLE")

    def deltext(self, e):
        for item in self.input["train_arrival"].values:
            # Process train arrival
            station = item['station']
            direction = item['direction']
            # ...

        for item in self.input["passenger_generated"].values:
            # Process passenger generated
            passenger_id = item['passenger_id']
            passenger_num = item['passenger_num']
            origin = item['origin']
            destination = item['destination']
            # ...

    def lambdaf(self):
        # Emit passenger boarding event
        self.output["passenger_boarding"].add({
            'passenger_id': 1,
            'passenger_num': 1,
            'origin': 1,
            'destination': 2,
        })

        # Emit passenger exiting event
        self.output["passenger_exiting"].add({
            'passenger_id': 1,
            'passenger_num': 1,
            'origin': 1,
            'destination': 2,
        })

    def deltint(self):
        # Update internal state
        pass

    def exit(self):
        pass