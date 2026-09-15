"""Complete pattern: sequential processing, one waiting slot, and timed JSONL IO."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Receive packets, process, and send ACK."""

    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent
        self.receiver_delay = receiver_delay
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.current_item = None
        self.waiting_item = None
        self.payload_to_send = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def _start_processing(self, item: dict) -> None:
        self.current_item = dict(item)
        self._write_event("delay_start", {
            "type": "processing",
            "duration": self.receiver_delay,
        })
        self.hold_in("PROCESSING", self.receiver_delay)

    def initialize(self):
        self.current_item = None
        self.waiting_item = None
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        was_processing = self.phase == "PROCESSING"
        if was_processing:
            self.continuef(e)

        for packet in self.input["packet_in"].values:
            if self.current_item is None:
                self._start_processing(packet)
                self._write_event("packet_received", {
                    "seq_num": packet["seq_num"],
                    "bit": packet["bit"],
                })
            elif self.waiting_item is None:
                self.waiting_item = dict(packet)
            # Further arrivals are dropped while both slots are occupied.

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["ack_out"].add(dict(self.payload_to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            completed_at = get_current_time()
            self.payload_to_send = {
                "bit": self.current_item["bit"],
            }
            self._write_event("ACK_sent", dict(self.payload_to_send))
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.current_item = None
            self.payload_to_send = None
            if self.waiting_item is not None:
                next_item = self.waiting_item
                self.waiting_item = None
                self._start_processing(next_item)
                self._write_event("packet_received", {
                    "seq_num": next_item["seq_num"],
                    "bit": next_item["bit"],
                })
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass