"""Complete pattern: preparation, timeout, late feedback, and timed JSONL IO."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Send sequential jobs and log each event at its semantic occurrence time."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
    ):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "control_cmd"))
        self.add_out_port(Port(dict, "packet_out"))

        self.packets_remaining = 0
        self.preparation_delay = 10
        self.timeout = 20
        self.seq = 1
        self.bit = 0

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        for cmd in self.input["control_cmd"].values:
            added = cmd.get("added", 0)
            total_remaining = cmd.get("total_remaining", 0)
            self.packets_remaining += added
            if self.packets_remaining > 0:
                self.hold_in("WAITING_FOR_PREPARATION", self.preparation_delay)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return
        packet = {"seq": self.seq, "bit": self.bit, "is_retry": False}
        self.output["packet_out"].add(packet)
        self._write_event("packet_sent", dict(packet))

    def deltint(self):
        if self.phase == "WAITING_FOR_PREPARATION":
            # Preparation ended; schedule a distinct zero-delay output phase.
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.bit = 1 - self.bit
            self.seq += 1
            self.hold_in("WAITING_FOR_ACK", self.timeout)
        elif self.phase == "WAITING_FOR_ACK":
            self._write_event("timeout", {"seq": self.seq})
            self.bit = 1 - self.bit
            packet = {"seq": self.seq, "bit": self.bit, "is_retry": True}
            self.output["packet_out"].add(packet)
            self.hold_in("WAITING_FOR_ACK", self.timeout)
        else:
            self.passivate("IDLE")

    def exit(self):
        pass