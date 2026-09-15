from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json


class Subnet1(Atomic):
    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, noise_seed: int):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.noise_seed = noise_seed
        self.x_old = noise_seed
        self.packet = None
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_get"))
        self.add_out_port(Port(dict, "packet_out"))

    def initialize(self):
        self.x_old = self.noise_seed
        self.packet = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for packet in self.input["packet_in"].values:
            # Compute new noise level
            x_new = (17 * self.x_old + 11) % 100
            
            # Determine fate
            if x_new < 10:
                behavior = "drop"
            else:
                behavior = "pass"
            
            # Emit packet_get event immediately
            packet_get_payload = {
                "behavior": behavior,
                "channel": "forward",
                "noise_value": x_new
            }
            self.output["packet_get"].add(packet_get_payload)
            
            # Write to stdout as per external_io
            record = {
                "time": get_current_time(),
                "entity": "subnet",
                "event": "packet_get",
                "payload": packet_get_payload
            }
            print(json.dumps(record), flush=True)
            
            # Update state
            self.x_old = x_new
            
            # If passed, retain packet and schedule delay
            if behavior == "pass":
                self.packet = dict(packet)
                self.hold_in("DELAYING", self.channel_delay)
            else:
                self.passivate("IDLE")
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.packet is not None:
            self.output["packet_out"].add(dict(self.packet))

    def deltint(self):
        self.packet = None
        self.passivate("IDLE")

    def exit(self):
        pass