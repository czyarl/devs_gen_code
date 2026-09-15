"""Atomic DEVS model for Subnet2 (Backward Channel with Deterministic Noise)."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Subnet2(Atomic):
    """Simulates the backward communication channel (Receiver -> Sender)
    with deterministic noise and fixed transmission delay.
    """

    def __init__(self, name: str, parent: Coupled | None, seed: int, channel_delay: float):
        super().__init__(name)
        self.parent = parent
        self.seed = seed
        self.channel_delay = channel_delay

        # Internal state
        self.noise_state = seed
        # List of tuples: (delivery_time, packet_dict)
        self.pending = []

        # Ports
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))

    def initialize(self):
        self.pending = []
        self.passivate("IDLE")

    def _reschedule_from_pending(self) -> None:
        """Recalculate sigma based on the earliest pending delivery."""
        if not self.pending:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = min(delivery_time for delivery_time, _ in self.pending)
        self.hold_in("WAITING", max(0.0, next_time - now))

    def deltext(self, e: float):
        now = get_current_time()
        for packet in self.input["ack_in"].values:
            # Calculate noise
            x_old = self.noise_state
            x_new = (17 * x_old + 11) % 100
            self.noise_state = x_new

            # Determine behavior
            behavior = "drop" if x_new < 10 else "pass"

            # Emit packet_get event record to stdout
            record = {
                "time": now,
                "entity": "subnet",
                "event": "packet_get",
                "payload": {
                    "behavior": behavior,
                    "channel": "backward",
                    "noise_value": x_new
                }
            }
            print(json.dumps(record), flush=True)

            # If pass, schedule for output
            if behavior == "pass":
                delivery_time = now + self.channel_delay
                self.pending.append((delivery_time, packet))

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return
        now = get_current_time()
        for delivery_time, packet in self.pending:
            if delivery_time <= now:
                self.output["ack_out"].add(packet)

    def deltint(self):
        now = get_current_time()
        # Remove delivered packets
        self.pending = [
            (delivery_time, packet)
            for delivery_time, packet in self.pending
            if delivery_time > now
        ]
        self._reschedule_from_pending()

    def exit(self):
        pass