"""Complete implementation of ClientGenerator.

This Atomic model generates clients at specified inter-arrival times and
sends them to the queue.
"""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import numpy as np

class ClientGenerator(Atomic):
    """Generate sequential clients at specified inter-arrival times and send them to the queue."""

    def __init__(self, name: str, parent: Coupled | None, mean: float, stddev: float):
        super().__init__(name)
        self.parent = parent
        self.mean = mean
        self.stddev = stddev
        self.add_out_port(Port(dict, "client_out"))
        self.next_client_id = 0

    def initialize(self):
        self.next_client_id = 0
        self.arrival_time = 0.0
        self.hold_in("WAIT_ARRIVAL", 0.0)

    def deltext(self, e):
        return None

    def lambdaf(self):
        if self.phase != "WAIT_ARRIVAL":
            return
        # Generate client
        client = {
            "client_id": self.next_client_id,
            "arrival_time": self.arrival_time,
        }
        self.output["client_out"].add(client)
        # External IO: write to stdout
        record = {
            "time": self.arrival_time,
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": client,
        }
        print(json.dumps(record), flush=True)
        # Schedule next client arrival
        self.next_client_id += 1
        interval = np.random.normal(self.mean, self.stddev)
        if interval < 0:
            interval = 0
        self.arrival_time += interval
        self.hold_in("WAIT_ARRIVAL", interval)

    def deltint(self):
        pass

    def exit(self):
        pass