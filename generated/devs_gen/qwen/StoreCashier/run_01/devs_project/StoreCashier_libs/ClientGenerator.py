"""ClientGenerator model for the store cashier system."""

import json
import numpy as np
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ClientGenerator(Atomic):
    """Generate clients at inter-arrival times drawn from a normal distribution."""

    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.add_out_port(Port(dict, "client_out"))
        self.client_id = 0
        self.next_arrival = 0.0

    def initialize(self):
        self.client_id = 0
        self.next_arrival = 0.0
        # Emit the first client at t=0
        self.hold_in("EMIT", 0.0)

    def deltext(self, e):
        # This model has no input ports
        return None

    def lambdaf(self):
        if self.phase != "EMIT":
            return
        # Generate the next client
        self.client_id += 1
        arrival_time = self.next_arrival
        client_payload = {
            "client_id": self.client_id,
            "arrival_time": arrival_time
        }
        
        # Emit client through output port
        self.output["client_out"].add(client_payload)
        
        # Write to stdout
        current_time = get_current_time()
        time_str = f"{int(current_time // 3600):02d}:{int((current_time % 3600) // 60):02d}:{int(current_time % 60):02d}:{int((current_time % 1) * 1000):03d}"
        record = {
            "time": current_time,
            "time_str": time_str,
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": client_payload
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate()
            return
        # Generate next inter-arrival time
        inter_arrival = np.random.normal(self.client_mean, self.client_stddev)
        # Clamp to [0, client_mean + 5 * client_stddev]
        max_time = self.client_mean + 5 * self.client_stddev
        inter_arrival = max(0.0, min(inter_arrival, max_time))
        self.next_arrival += inter_arrival
        self.hold_in("EMIT", inter_arrival)

    def exit(self):
        pass