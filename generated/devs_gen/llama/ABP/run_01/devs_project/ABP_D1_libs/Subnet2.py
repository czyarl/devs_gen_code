"""Complete pattern: Subnet2 model with interference simulation."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet2(Atomic):
    """Simulate interference using a deterministic formula."""

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
        for packet in self.input["packet_in"].values:
            self.noise_level = (17 * self.noise_level + 11) % 100
            if self.noise_level < 10:
                print(json.dumps({
                    "time": get_current_time(),
                    "event": "packet_get",
                    "payload": {
                        "behavior": "drop",
                        "channel": "backward",
                        "noise_value": self.noise_level,
                    }
                }), flush=True)
            else:
                print(json.dumps({
                    "time": get_current_time(),
                    "event": "packet_get",
                    "payload": {
                        "behavior": "pass",
                        "channel": "backward",
                        "noise_value": self.noise_level,
                    }
                }), flush=True)
                self.output["packet_out"].add(packet)
                self.hold_in("WAITING", self.channel_delay)

    def lambdaf(self):
        pass

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass