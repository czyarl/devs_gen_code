from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class Subnet1(Atomic):
    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, noise_seed: int):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.noise_seed = noise_seed
        self.noise_level = noise_seed
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))
        self.add_out_port(Port(dict, "packet_get"))

    def initialize(self):
        self.noise_level = self.noise_seed
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for packet in self.input["packet_in"].values:
            # Calculate new noise level
            x_new = (17 * self.noise_level + 11) % 100
            self.noise_level = x_new

            # Determine behavior
            if x_new < 10:
                behavior = "drop"
            else:
                behavior = "pass"

            # Emit packet_get event
            packet_get_payload = {
                "behavior": behavior,
                "channel": "forward",
                "noise_value": x_new
            }
            self.output["packet_get"].add(packet_get_payload)

            # Handle packet fate
            if behavior == "drop":
                # Passivate without scheduling output
                self.passivate("IDLE")
            else:
                # Store packet and schedule output after delay
                self.packet = dict(packet)
                self.hold_in("DELAYING", self.channel_delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and hasattr(self, 'packet'):
            self.output["packet_out"].add(dict(self.packet))

    def deltint(self):
        if self.phase == "DELAYING":
            self.packet = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass