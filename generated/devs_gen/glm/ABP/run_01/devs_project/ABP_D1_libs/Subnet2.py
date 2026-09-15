import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet2(Atomic):
    """
    Simulates the backward channel (Receiver to Sender) for the ABP protocol.
    It maintains an internal noise level 'x' initialized to the provided seed.
    Upon receiving an ACK packet on input port 'in', it immediately calculates
    a new noise value x_new = (17 * x + 11) % 100.
    It determines the packet's fate: if x_new < 10, the packet is dropped;
    otherwise, it is forwarded to the output port 'out' after a fixed channel_delay.
    The internal state x is updated to x_new regardless of the fate.
    It writes a JSONL record for the 'packet_get' event to stdout immediately
    upon arrival, capturing the behavior ('drop' or 'pass'), channel ('backward'),
    and the calculated noise_value.
    """

    def __init__(self, name: str, parent: Coupled | None, seed: int, delay: float):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.delay = delay
        
        # Internal state: noise level x
        self.x = seed
        
        # Payload storage for transmission
        self.packet_to_send = None
        
        # Ports
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))

    def initialize(self):
        # Initialize state variables
        self.x = self.seed
        self.packet_to_send = None
        # Wait for input
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Process incoming packets
        for packet in self.input["in"].values:
            # Calculate new noise value
            x_new = (17 * self.x + 11) % 100
            
            # Determine behavior
            behavior = "drop" if x_new < 10 else "pass"
            
            # Write JSONL record immediately upon arrival
            record = {
                "time": get_current_time(),
                "entity": "subnet",
                "event": "packet_get",
                "payload": {
                    "behavior": behavior,
                    "channel": "backward",
                    "noise_value": x_new
                }
            }
            print(json.dumps(record), flush=True)
            
            # Update internal state x
            self.x = x_new
            
            # If packet passes, schedule output after delay
            if behavior == "pass":
                self.packet_to_send = packet
                self.hold_in("TRANSMITTING", self.delay)
            else:
                # If dropped, stay passive
                self.passivate("IDLE")

    def lambdaf(self):
        # Output the packet if we are in the transmitting phase
        if self.phase == "TRANSMITTING" and self.packet_to_send is not None:
            self.output["out"].add(self.packet_to_send)

    def deltint(self):
        # After transmission delay, clear the packet and go idle
        if self.phase == "TRANSMITTING":
            self.packet_to_send = None
            self.passivate("IDLE")

    def exit(self):
        pass