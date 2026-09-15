import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet2(Atomic):
    """Simulate the backward channel (Receiver to Sender) with deterministic noise and fixed latency."""

    def __init__(self, name: str, parent: Coupled | None, channel_delay: float, seed: int):
        super().__init__(name)
        self.parent = parent
        self.channel_delay = channel_delay
        self.seed = seed
        
        # Internal state
        self.noise_level = seed
        self.pending_packet = None
        
        # Ports
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        # Upon receiving an ACK packet on 'ack_in'
        if not self.input["ack_in"].empty():
            # Get the packet (assuming one per event cycle based on typical ABP flow, but iterating to be safe)
            for packet in self.input["ack_in"].values:
                # Calculate new noise value
                x_new = (17 * self.noise_level + 11) % 100
                
                # Determine fate
                if x_new < 10:
                    fate = "drop"
                else:
                    fate = "pass"
                
                # Write 'packet_get' JSONL record to stdout immediately
                now = get_current_time()
                print(json.dumps({
                    "time": now,
                    "entity": "subnet",
                    "event": "packet_get",
                    "payload": {
                        "behavior": fate,
                        "channel": "backward",
                        "noise_value": x_new
                    }
                }), flush=True)
                
                # Update internal noise state
                self.noise_level = x_new
                
                if fate == "pass":
                    # Retain packet and schedule for output
                    self.pending_packet = packet
                    self.hold_in("TRANSMITTING", self.channel_delay)
                else:
                    # Drop packet, no output scheduled
                    self.passivate("IDLE")
        else:
            # If no input, maintain current phase (usually IDLE)
            self.continuef(e)

    def lambdaf(self):
        # If the phase is TRANSMITTING, emit the packet
        if self.phase == "TRANSMITTING" and self.pending_packet is not None:
            self.output["ack_out"].add(self.pending_packet)

    def deltint(self):
        if self.phase == "TRANSMITTING":
            # After output, clear pending packet and go to IDLE
            self.pending_packet = None
            self.passivate("IDLE")

    def exit(self):
        pass