from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json


class Subnet2(Atomic):
    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, noise_seed: int):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.noise_seed = noise_seed
        self.x = noise_seed
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "packet_get"))
        self.add_out_port(Port(dict, "ack_out"))
        self.ack_to_forward = None

    def initialize(self):
        self.x = self.noise_seed
        self.ack_to_forward = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for ack in self.input["ack_in"].values:
            # Calculate new noise level: x_new = (17 * x_old + 11) mod 100
            x_new = (17 * self.x + 11) % 100
            self.x = x_new

            # Determine if packet should be dropped (x_new < 10) or passed
            behavior = "drop" if x_new < 10 else "pass"

            # Emit packet_get event with behavior, channel, and noise_value
            packet_get_event = {
                "behavior": behavior,
                "channel": "backward",
                "noise_value": x_new
            }

            # Write to stdout as per external_io specification
            record = {
                "time": get_current_time(),
                "entity": "subnet",
                "event": "packet_get",
                "payload": packet_get_event
            }
            print(json.dumps(record), flush=True)

            # Store ack for forwarding if passed
            if behavior == "pass":
                self.ack_to_forward = dict(ack)
                self.hold_in("DELAYING", self.channel_delay)
            else:
                self.passivate("IDLE")
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.ack_to_forward is not None:
            self.output["ack_out"].add(self.ack_to_forward)

    def deltint(self):
        self.ack_to_forward = None
        self.passivate("IDLE")

    def exit(self):
        pass