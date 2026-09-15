"""Complete implementation of the ServerSender model."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """ServerSender model implementation."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
    ):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(bool, "download_valve"))
        self.add_in_port(Port(list, "storage_queue"))
        self.add_out_port(Port(dict, "packet_out"))
        self.add_in_port(Port(dict, "ack_in"))
        self.download_allowed = False
        self.storage_queue = []
        self.waiting_for_ack = False
        self.current_packet = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.download_allowed = False
        self.storage_queue = []
        self.waiting_for_ack = False
        self.current_packet = None
        self.passivate("IDLE")

    def deltext(self, e):
        for download_valve in self.input["download_valve"].values:
            self.download_allowed = download_valve
            self._write_event("download_valve_change", {
                "allowed": self.download_allowed,
            })

        for storage_queue in self.input["storage_queue"].values:
            self.storage_queue.extend(storage_queue)
            self._write_event("storage_queue_update", {
                "queue": self.storage_queue,
            })

        for ack in self.input["ack_in"].values:
            self._write_event("ack_received_from_receiver", {
                "bit": ack["bit"],
            })
            if self.waiting_for_ack and ack["bit"] == self.current_packet["bit"]:
                self.waiting_for_ack = False
                self.current_packet = None
                if not self.storage_queue:
                    self._try_send_packet()

        self.continuef(e)

    def lambdaf(self):
        if self.phase != "SEND_PACKET":
            return

        self.output["packet_out"].add(self.current_packet)
        self._write_event("packet_forwarded", self.current_packet)
        self.waiting_for_ack = True
        self.hold_in("WAITING_FOR_ACK", 3.0)

    def deltint(self):
        if self.phase == "WAITING_FOR_ACK":
            self._write_event("timeout", {
                "packet": self.current_packet,
            })
            self.output["packet_out"].add(self.current_packet)
            self._write_event("packet_forwarded", self.current_packet)
            self.waiting_for_ack = True
            self.hold_in("WAITING_FOR_ACK", 3.0)
        elif self.phase == "IDLE":
            self._try_send_packet()

    def _try_send_packet(self):
        if self.download_allowed and self.storage_queue and not self.waiting_for_ack:
            self.current_packet = self.storage_queue.pop(0)
            self.hold_in("SEND_PACKET", 0.0)

    def exit(self):
        pass