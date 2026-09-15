"""Complete pattern: simulate a Subnet with deterministic noise and delay."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet1(Atomic):
    """Simulate the forward channel from Sender to Receiver, including latency and deterministic noise."""

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
            self.output["packet_get"].add({
                "behavior": "pass" if self.noise_level >= 10 else "drop",
                "channel": "forward",
                "noise_value": self.noise_level
            })
            self.noise_level = (17 * self.noise_level + 11) % 100
            if self.noise_level >= 10:
                self.output["packet_out"].add(dict(packet))
            self.hold_in("WAITING", self.channel_delay)

    def lambdaf(self):
        pass

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass