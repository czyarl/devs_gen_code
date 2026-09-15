import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet1(Atomic):
    """
    Atomic DEVS model simulating the forward channel (Sender to Receiver)
    with deterministic noise-based packet loss.
    """

    def __init__(self, name: str, parent: Coupled | None, seed: int, delay: float):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.delay = delay
        
        # Initialize internal noise level x to the provided seed
        self.x = self.seed
        
        # Store packets scheduled for transmission: list of (delivery_time, payload)
        self.pending = []
        
        # Define ports
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))

    def initialize(self):
        """Initialize the model state."""
        self.pending = []
        self.passivate("IDLE")

    def _reschedule_from_pending(self) -> None:
        """Recalculate the next internal event time based on pending packets."""
        if not self.pending:
            self.passivate("IDLE")
            return
        
        now = get_current_time()
        next_time = min(delivery_time for delivery_time, _ in self.pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e: float):
        """
        Handle external input (packet arrival).
        Calculates noise, determines fate, logs to stdout, and schedules transmission if passed.
        """
        now = get_current_time()
        
        for packet in self.input["in"].values:
            # Calculate new noise x_new = (17 * x + 11) % 100
            x_new = (17 * self.x + 11) % 100
            
            # Update internal state x
            self.x = x_new
            
            # Determine packet fate
            if x_new < 10:
                behavior = "drop"
            else:
                behavior = "pass"
                # Schedule the packet to be forwarded after channel_delay
                # The payload is a dict, ensure we copy it to avoid reference issues if needed
                payload = dict(packet)
                self.pending.append((now + self.delay, payload))
            
            # Write 'packet_get' JSONL record to stdout immediately
            record = {
                "time": now,
                "entity": "subnet",
                "event": "packet_get",
                "payload": {
                    "behavior": behavior,
                    "channel": "forward",
                    "noise_value": x_new
                }
            }
            print(json.dumps(record), flush=True)
            
        # Update scheduling based on new pending packets
        self._reschedule_from_pending()

    def lambdaf(self):
        """Emit packets whose transmission delay has expired."""
        if self.phase != "WAITING":
            return
        
        now = get_current_time()
        for delivery_time, payload in self.pending:
            if delivery_time <= now:
                self.output["out"].add(payload)

    def deltint(self):
        """Remove transmitted packets and reschedule next event."""
        now = get_current_time()
        
        # Filter out packets that have been delivered (time <= now)
        self.pending = [
            (delivery_time, payload)
            for delivery_time, payload in self.pending
            if delivery_time > now
        ]
        
        self._reschedule_from_pending()

    def exit(self):
        """Cleanup on simulation exit."""
        pass