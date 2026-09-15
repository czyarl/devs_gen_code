from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json


class Subnet2(Atomic):
    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, noise_seed: int):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.noise_seed = noise_seed
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(dict, "packet_get"))
        self.noise_level = 0
        self.current_packet = None
        self.phase = ""
        self.sigma = 0.0

    def initialize(self):
        self.noise_level = self.noise_seed
        self.current_packet = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for ack in self.input["ack_in"].values:
            # Process the incoming ACK packet
            self.noise_level = (17 * self.noise_level + 11) % 100
            behavior = "drop" if self.noise_level < 10 else "pass"
            noise_value = self.noise_level
            channel = "backward"
            packet_get_payload = {
                "behavior": behavior,
                "channel": channel,
                "noise_value": noise_value
            }
            self.output["packet_get"].add(packet_get_payload)
            if behavior == "pass":
                self.current_packet = dict(ack)
                self.hold_in("DELAYING", self.channel_delay)
            else:
                self.passivate("IDLE")
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.current_packet is not None:
            self.output["ack_out"].add(dict(self.current_packet))

    def deltint(self):
        if self.phase == "DELAYING":
            self.current_packet = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass