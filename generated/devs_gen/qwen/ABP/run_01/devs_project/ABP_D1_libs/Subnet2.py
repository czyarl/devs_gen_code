"""Subnet2: Atomic DEVS model implementing the backward subnet with deterministic noise."""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class Subnet2(Atomic):
    def __init__(self, name: str, parent: Coupled | None, link_delay: float, noise_seed: int):
        super().__init__(name)
        self.parent = parent
        self.link_delay = link_delay
        self.noise_seed = noise_seed
        self.noise_level = noise_seed
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.packet = None
        self.behavior = None
        self.channel = "backward"
        self.noise_value = 0

    def initialize(self):
        self.noise_level = self.noise_seed
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for packet in self.input["ack_in"].values:
            # Update noise level: x_new = (17 * x_old + 11) mod 100
            self.noise_value = (17 * self.noise_level + 11) % 100
            self.noise_level = self.noise_value

            # Determine behavior
            if self.noise_value < 10:
                self.behavior = "drop"
            else:
                self.behavior = "pass"
                self.packet = dict(packet)

            # Emit packet_get event
            time = get_current_time()
            payload = {
                "behavior": self.behavior,
                "channel": self.channel,
                "noise_value": self.noise_value
            }
            record = {
                "time": time,
                "entity": "subnet",
                "event": "packet_get",
                "payload": payload
            }
            print(json.dumps(record), flush=True)

            # Handle forwarding or dropping
            if self.behavior == "pass":
                self.hold_in("DELAYING", self.link_delay)
            else:
                self.passivate("IDLE")
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.packet is not None:
            # Forward the packet with is_valid flag
            self.packet["is_valid"] = True
            self.output["ack_out"].add(dict(self.packet))

    def deltint(self):
        self.packet = None
        self.passivate("IDLE")

    def exit(self):
        pass