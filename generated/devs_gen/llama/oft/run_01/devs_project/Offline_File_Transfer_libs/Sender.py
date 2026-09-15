"""Complete pattern: preparation, timeout, late feedback, and timed JSONL IO."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Send sequential jobs and log each event at its semantic occurrence time."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "control_cmd"))
        self.add_out_port(Port(dict, "data_out"))
        self.packets_remaining = 0
        self.total_packets_to_send = 0
        self.preparation_delay = 10.0
        self.timeout = 20.0
        self.seq = 1
        self.bit = 0
        self.is_ack_received = False
        self.outstanding = False

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def _begin_preparation(self) -> None:
        # This record belongs to the start of preparation, not its completion.
        self._write_event("preparation_started", {
            "duration": self.preparation_delay,
        })
        self.hold_in("PREPARING", self.preparation_delay)

    def initialize(self):
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.is_ack_received = False
        self.outstanding = False
        self.passivate("DONE")

    def deltext(self, e):
        for cmd in self.input["control_cmd"].values:
            added = cmd.get("added", 0)
            total_remaining = cmd.get("total_remaining", 0)
            self.packets_remaining += added
            if self.packets_remaining > 0 and not self.outstanding:
                self._begin_preparation()

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            packet = {"seq": self.seq, "bit": self.bit, "is_retry": self.outstanding}
            self.output["data_out"].add(packet)
            self._write_event("packet_sent", packet)
            self.hold_in("WAITING_FOR_ACK", self.timeout)

        elif self.phase == "WAITING_FOR_ACK":
            self.outstanding = False
            self._write_event("timeout", {"seq": self.seq})

        elif self.phase == "PREPARING":
            # Preparation ended; schedule a distinct zero-delay output phase.
            self.hold_in("OUTPUT_READY", 0.0)

    def deltint(self):
        if self.phase == "WAITING_FOR_ACK":
            for ack in self.input["control_cmd"].values:
                if ack.get("bit") == self.bit:
                    self._write_event("ack_received", {"bit": self.bit})
                    self.bit = 1 - self.bit
                    self.seq += 1
                    self.packets_remaining -= 1
                    self.outstanding = False
                    if self.packets_remaining > 0:
                        self._begin_preparation()
                    else:
                        self.passivate("DONE")
                    return
            self.is_retry = True
            self._begin_preparation()

    def exit(self):
        pass