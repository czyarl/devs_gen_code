"""Implementation of the Subnet2 model."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet2(Atomic):
    """Simulates the backward channel from Receiver to Sender, including latency and deterministic noise."""

    def __init__(self, name: str, parent: Coupled | None, seed: int, channel_delay: float):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.channel_delay = channel_delay
        self.noise_level = seed
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        now = get_current_time()
        for item in self.input["packet_in"].values:
            payload = dict(item)
            self.noise_level = (17 * self.noise_level + 11) % 100
            if self.noise_level >= 10:
                print(json.dumps({
                    "time": now,
                    "event": "packet_get",
                    "payload": {
                        "behavior": "pass",
                        "channel": "backward",
                        "noise_value": self.noise_level,
                    }
                }), flush=True)
                self.output["packet_out"].add(dict(payload))
                print(json.dumps({
                    "time": now + self.channel_delay,
                    "event": "packet_get",
                    "payload": {
                        "behavior": "pass",
                        "channel": "backward",
                        "noise_value": self.noise_level,
                    }
                }), flush=True)
            else:
                print(json.dumps({
                    "time": now,
                    "event": "packet_get",
                    "payload": {
                        "behavior": "drop",
                        "channel": "backward",
                        "noise_value": self.noise_level,
                    }
                }), flush=True)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def exit(self):
        pass