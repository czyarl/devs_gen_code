import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import numpy as np


class ClientGenerator(Atomic):
    """Generate clients at specified intervals according to a normal distribution of inter-arrival times."""

    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.add_out_port(Port(dict, "client_out"))
        self.client_id = 0
        self.next_arrival_time = 0.0

    def initialize(self):
        self.client_id = 0
        self.next_arrival_time = 0.0
        # Emit first client immediately at t=0.0
        self.hold_in("EMIT_CLIENT", 0.0)

    def deltext(self, e):
        # This model has no input ports
        pass

    def lambdaf(self):
        if self.phase == "EMIT_CLIENT":
            # Generate next client
            self.client_id += 1
            arrival_time = self.next_arrival_time
            payload = {
                "client_id": self.client_id,
                "arrival_time": arrival_time
            }
            self.output["client_out"].add(payload)
            
            # Emit external IO record
            current_time = get_current_time()
            time_str = f"{int(current_time)//3600:02d}:{(int(current_time)%3600)//60:02d}:{int(current_time)%60:02d}:{int((current_time%1)*1000):03d}"
            record = {
                "time": current_time,
                "time_str": time_str,
                "event": "client_generated",
                "entity_type": "client_generator",
                "entity": "ClientGenerator",
                "payload": payload
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "EMIT_CLIENT":
            # Calculate next inter-arrival time
            inter_arrival = np.random.normal(self.client_mean, self.client_stddev)
            # Clamp to [0, client_mean + 5 * client_stddev]
            max_time = self.client_mean + 5 * self.client_stddev
            inter_arrival = max(0.0, min(inter_arrival, max_time))
            self.next_arrival_time += inter_arrival
            self.hold_in("EMIT_CLIENT", inter_arrival)
        else:
            self.passivate()

    def exit(self):
        pass