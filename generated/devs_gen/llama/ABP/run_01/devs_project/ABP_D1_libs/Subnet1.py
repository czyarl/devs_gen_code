"""Complete pattern: Subnet1 model."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet1(Atomic):
    """Simulate interference using a deterministic formula."""

    def __init__(self, name: str, parent: Coupled | None, seed: int, channel_delay: float):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.noise = seed
        self.channel_delay = channel_delay
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        now = get_current_time()
        for packet in self.input["packet_in"].values:
            self.noise = (17 * self.noise + 11) % 100
            if self.noise >= 10:
                print(json.dumps({
                    "time": now,
                    "entity": "subnet",
                    "event": "packet_get",
                    "payload": {
                        "behavior": "pass",
                        "channel": "forward",
                        "noise_value": self.noise,
                    }
                }), flush=True)
                self.output["packet_out"].add(dict(packet))
            else:
                print(json.dumps({
                    "time": now,
                    "entity": "subnet",
                    "event": "packet_get",
                    "payload": {
                        "behavior": "drop",
                        "channel": "forward",
                        "noise_value": self.noise,
                    }
                }), flush=True)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def exit(self):
        pass