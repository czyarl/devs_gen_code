"""Complete pattern: Subnet1 model with delay and noise."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet1(Atomic):
    """Simulate forward channel from Sender to Receiver with delay and noise."""

    def __init__(self, name: str, parent: Coupled | None, seed: int, channel_delay: float):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.noise_level = seed
        self.channel_delay = channel_delay
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        now = get_current_time()
        for item in self.input["packet_in"].values:
            payload = dict(item)
            self.noise_level = (17 * self.noise_level + 11) % 100
            print(json.dumps({
                "time": now,
                "entity": "subnet",
                "event": "packet_get",
                "payload": {
                    "behavior": "drop" if self.noise_level < 10 else "pass",
                    "channel": "forward",
                    "noise_value": self.noise_level,
                }
            }), flush=True)
            if self.noise_level >= 10:
                self.output["packet_out"].add(dict(payload))
                self.hold_in("WAITING", self.channel_delay)
            else:
                self.hold_in("WAITING", 0.0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass