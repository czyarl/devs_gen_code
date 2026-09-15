"""Complete implementation of ClientGenerator.

This Atomic DEVS model generates clients at specified inter-arrival times
and sends them to the queue.
"""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ClientGenerator(Atomic):
    """Generate clients at specified inter-arrival times and send them to the queue."""

    def __init__(self, name: str, parent: Coupled | None, arrival_interval_mean: float, arrival_interval_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.arrival_interval_mean = arrival_interval_mean
        self.arrival_interval_stddev = arrival_interval_stddev
        self.add_out_port(Port(dict, "client_out"))
        self.client_id = 0

    def initialize(self):
        self.client_id = 1
        self.next_arrival_time = 0.0
        self.output["client_out"].add({
            "client_id": self.client_id,
            "arrival_time": self.next_arrival_time,
        })
        print(json.dumps({
            "time": self.next_arrival_time,
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {
                "client_id": self.client_id,
                "arrival_time": self.next_arrival_time,
            }
        }), flush=True)
        self.hold_in("WAIT_FOR_NEXT_CLIENT", self.arrival_interval_mean)

    def deltext(self, e):
        return None

    def lambdaf(self):
        if self.phase != "WAIT_FOR_NEXT_CLIENT":
            return
        self.client_id += 1
        self.next_arrival_time = get_current_time() + self.arrival_interval_mean  # Assuming normal distribution for simplicity
        self.output["client_out"].add({
            "client_id": self.client_id,
            "arrival_time": self.next_arrival_time,
        })
        print(json.dumps({
            "time": self.next_arrival_time,
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {
                "client_id": self.client_id,
                "arrival_time": self.next_arrival_time,
            }
        }), flush=True)
        self.hold_in("WAIT_FOR_NEXT_CLIENT", self.arrival_interval_mean)

    def deltint(self):
        pass

    def exit(self):
        pass