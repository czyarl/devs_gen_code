"""Atomic DEVS model for Receiver component with 10s processing delay and ACK emission."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Processes data packets received from Server with a 10-second delay, then sends an ACK back to Server."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.current_item = None
        self.waiting_item = None
        self.payload_to_send = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "timestamp_ms": get_current_time(),
            "model": "receiver",
            "type": event,
            "val": payload,
        }), flush=True)

    def _start_processing(self, item: dict) -> None:
        self.current_item = dict(item)
        self._write_event("processing_started", {
            "seq": self.current_item["seq"],
            "duration": self.processing_delay,
        })
        self.hold_in("PROCESSING", self.processing_delay)

    def initialize(self):
        self.current_item = None
        self.waiting_item = None
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        was_processing = self.phase == "PROCESSING"
        if was_processing:
            self.continuef(e)

        for item in self.input["data_in"].values:
            if self.current_item is None:
                # A newly created delay must not be reduced by e.
                self._start_processing(item)
            elif self.waiting_item is None:
                self.waiting_item = dict(item)
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
            self._write_event("ack_sent", dict(self.payload_to_send))
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.current_item = None
            self.payload_to_send = None
            if self.waiting_item is not None:
                next_item = self.waiting_item
                self.waiting_item = None
                self._start_processing(next_item)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass