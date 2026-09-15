"""Complete pattern: sequential processing, one waiting slot, and timed JSONL IO."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Implement the Receiver's behavior, including processing delay, packet reception, and ACK sending."""

    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent
        self.receiver_delay = receiver_delay
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "ack_sent"))
        self.current_packet = None
        self.waiting_packet = None
        self.payload_to_send = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def _start_processing(self, packet: dict) -> None:
        self.current_packet = dict(packet)
        self._write_event("delay_start", {
            "type": "processing",
            "duration": self.receiver_delay,
        })
        self.hold_in("PROCESSING", self.receiver_delay)

    def initialize(self):
        self.current_packet = None
        self.waiting_packet = None
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        was_processing = self.phase == "PROCESSING"
        if was_processing:
            self.continuef(e)

        for packet in self.input["packet_in"].values:
            if self.current_packet is None:
                self._start_processing(packet)
            elif self.waiting_packet is None:
                self.waiting_packet = dict(packet)
            # Further arrivals are dropped while both slots are occupied.

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["ack_sent"].add(dict(self.payload_to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            completed_at = get_current_time()
            self.payload_to_send = {
                "seq_num": self.current_packet["seq_num"],
                "bit": self.current_packet["bit"],
            }
            self._write_event("packet_received", dict(self.payload_to_send))
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.current_packet = None
            self.payload_to_send = None
            if self.waiting_packet is not None:
                next_packet = self.waiting_packet
                self.waiting_packet = None
                self._start_processing(next_packet)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass