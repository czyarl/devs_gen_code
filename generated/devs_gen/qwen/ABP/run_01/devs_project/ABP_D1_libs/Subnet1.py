"""Subnet1: Atomic DEVS model implementing deterministic noise and packet forwarding."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet1(Atomic):
    def __init__(self, name: str, parent: Coupled | None, link_delay: float, noise_seed: int):
        super().__init__(name)
        self.parent = parent
        self.link_delay = link_delay
        self.noise_seed = noise_seed
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))
        self.noise_level = noise_seed
        self.packet = None

    def initialize(self):
        self.noise_level = self.noise_seed
        self.packet = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for packet in self.input["packet_in"].values:
            # Calculate new noise level
            x_new = (17 * self.noise_level + 11) % 100
            self.noise_level = x_new

            # Determine packet fate
            if x_new < 10:
                behavior = "drop"
            else:
                behavior = "pass"
                self.packet = dict(packet)

            # Emit packet_get event
            record = {
                "time": get_current_time(),
                "entity": "subnet",
                "event": "packet_get",
                "payload": {
                    "behavior": behavior,
                    "channel": "forward",
                    "noise_value": x_new
                }
            }
            print(json.dumps(record), flush=True)

            # If packet is to be passed, schedule output
            if behavior == "pass":
                self.hold_in("DELAYING", self.link_delay)
            else:
                self.passivate("IDLE")
            return

        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.packet is not None:
            # Forward the packet after delay
            self.output["packet_out"].add({
                "seq_num": self.packet["seq_num"],
                "bit": self.packet["bit"]
            })

    def deltint(self):
        self.packet = None
        self.passivate("IDLE")

    def exit(self):
        pass