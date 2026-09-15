import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet1(Atomic):
    """Simulate the forward channel (Sender to Receiver) with deterministic noise and fixed latency."""

    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, seed: int):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.seed = seed
        
        # Internal state: noise level x
        self.x = seed
        
        # Buffer for packet to be forwarded
        self.packet_buffer = None
        
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))

    def initialize(self):
        self.packet_buffer = None
        self.passivate("IDLE")

    def deltext(self, e):
        # Upon receiving a packet via packet_in
        if not self.input["packet_in"].empty():
            for packet in self.input["packet_in"].values:
                # Calculate new noise value
                x_new = (17 * self.x + 11) % 100
                
                # Determine fate
                fate = "drop" if x_new < 10 else "pass"
                
                # Update internal state
                self.x = x_new
                
                # Write JSONL record immediately
                now = get_current_time()
                record = {
                    "time": now,
                    "entity": "subnet",
                    "event": "packet_get",
                    "payload": {
                        "behavior": fate,
                        "channel": "forward",
                        "noise_value": x_new
                    }
                }
                print(json.dumps(record), flush=True)
                
                # If passed, schedule internal event to forward packet
                if fate == "pass":
                    self.packet_buffer = dict(packet)
                    self.hold_in("TRANSMITTING", self.channel_delay)
                else:
                    # If dropped, remain passive
                    self.passivate("IDLE")
        else:
            # If no input, preserve remaining time if active
            if self.phase == "TRANSMITTING":
                self.hold_in("TRANSMITTING", max(0.0, self.ta() - e))
            else:
                self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "TRANSMITTING" and self.packet_buffer is not None:
            # Forward the packet payload unchanged
            self.output["packet_out"].add(self.packet_buffer)

    def deltint(self):
        if self.phase == "TRANSMITTING":
            # After output, clear buffer and go idle
            self.packet_buffer = None
            self.passivate("IDLE")

    def exit(self):
        pass