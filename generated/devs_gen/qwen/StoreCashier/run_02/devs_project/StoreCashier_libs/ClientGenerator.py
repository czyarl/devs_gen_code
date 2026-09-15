import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import numpy as np


class ClientGenerator(Atomic):
    """Generate clients at specified intervals, beginning at t=0.0."""

    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.add_out_port(Port(dict, "client_out"))
        self.client_id = 0
        self.next_arrival = 0.0

    def initialize(self):
        self.client_id = 1
        self.next_arrival = 0.0
        # Emit the first client at t=0.0
        self.hold_in("EMIT", 0.0)

    def deltext(self, e):
        # This source has no input ports. The method remains a valid no-op.
        return None

    def lambdaf(self):
        if self.phase != "EMIT":
            return
        # Get the actual time when this event is emitted
        emitted_at = get_current_time()
        payload = {
            "client_id": self.client_id,
            "arrival_time": emitted_at
        }
        self.output["client_out"].add(payload)
        
        # Write to stdout
        record = {
            "time": emitted_at,
            "time_str": self._format_time(emitted_at),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": payload
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate()
            return
        # lambdaf() emitted the current client immediately before this transition.
        self.client_id += 1
        # Sample next inter-arrival time
        interval = np.random.normal(self.client_mean, self.client_stddev)
        # Clip to [0, client_mean + 5 * client_stddev]
        max_interval = self.client_mean + 5 * self.client_stddev
        interval = max(0.0, min(interval, max_interval))
        self.next_arrival += interval
        self.hold_in("EMIT", interval)

    def exit(self):
        pass

    def _format_time(self, time_val: float) -> str:
        """Format time as HH:MM:SS:mmm"""
        hours = int(time_val // 3600)
        minutes = int((time_val % 3600) // 60)
        seconds = int(time_val % 60)
        milliseconds = int((time_val % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"