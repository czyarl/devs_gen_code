import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet1(Atomic):
    """Simulates the forward channel (Sender -> Receiver) with deterministic noise and fixed transmission delay."""

    def __init__(self, name: str, parent: Coupled | None, seed: int, channel_delay: float):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.channel_delay = channel_delay
        
        # Initialize internal noise state x
        self.x = self.seed
        
        # State variables for packet processing
        self.current_packet = None
        self.noise_value = None
        self.fate = None # 'drop' or 'pass'
        
        # Ports
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        # The model is atomic and processes one packet at a time based on the description.
        # "Upon receiving a packet via 'packet_in', it immediately calculates..."
        # We assume standard atomic behavior where we process the input.
        
        for packet in self.input["packet_in"].values:
            # Calculate noise
            x_new = (17 * self.x + 11) % 100
            self.noise_value = x_new
            
            # Determine fate
            if x_new < 10:
                self.fate = "drop"
            else:
                self.fate = "pass"
                self.current_packet = packet
            
            # Update internal noise state
            self.x = x_new
            
            # Emit external IO event 'packet_get'
            # Requirement: "Emits JSONL records for 'packet_get' events with channel='forward'."
            # Schema: {"time": <float>, "entity": "subnet", "event": "packet_get", "payload": {"behavior": ..., "channel": ..., "noise_value": ...}}
            now = get_current_time()
            print(json.dumps({
                "time": now,
                "entity": "subnet",
                "event": "packet_get",
                "payload": {
                    "behavior": self.fate,
                    "channel": "forward",
                    "noise_value": self.noise_value
                }
            }), flush=True)

        # Schedule next event
        if self.fate == "pass":
            # If passed, schedule internal event to forward after channel_delay
            self.hold_in("TRANSMITTING", self.channel_delay)
        else:
            # If dropped, go back to idle
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "TRANSMITTING" and self.current_packet is not None:
            # Forward the packet to output port
            # Structure: {'seq_num': int, 'bit': int (0 or 1)}
            self.output["packet_out"].add(self.current_packet)

    def deltint(self):
        if self.phase == "TRANSMITTING":
            # After transmission, clear the packet and go idle
            self.current_packet = None
            self.passivate("IDLE")

    def exit(self):
        pass