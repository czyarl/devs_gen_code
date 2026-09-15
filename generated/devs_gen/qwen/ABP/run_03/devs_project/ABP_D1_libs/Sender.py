"""Complete implementation of the Sender atomic model as per the locked contract."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Sender atomic model implementing the ABP with preparation delays, timeouts, and retransmissions."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        sender_delay: float,
        timeout: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.sender_delay = sender_delay
        self.timeout = timeout
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "delay_start"))
        self.add_out_port(Port(dict, "packet_out"))
        self.add_out_port(Port(dict, "ack_received"))

        # Internal state
        self.seq_num = 1
        self.bit = 0
        self.current_packet = None
        self.outstanding = False
        self.retry_pending = False

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "entity": "sender",
            "event": event,
            "payload": payload,
        }), flush=True)

    def _begin_preparation(self) -> None:
        # Emit delay_start event
        self._write_event("delay_start", {
            "type": "preparation",
            "duration": self.sender_delay,
        })
        self.hold_in("PREPARING", self.sender_delay)

    def initialize(self):
        self.seq_num = 1
        self.bit = 0
        self.current_packet = None
        self.outstanding = False
        self.retry_pending = False
        if self.total_packets > 0:
            self._begin_preparation()
        else:
            self.passivate("DONE")

    def deltext(self, e):
        accepted = False
        for ack in self.input["ack_in"].values:
            ack_bit = ack.get("ack_bit")
            is_valid = self.outstanding and ack_bit == self.bit
            self._write_event("ack_received", {
                "ack_bit": ack_bit,
                "is_valid": is_valid,
            })
            if is_valid:
                accepted = True
                # Cancel pending retry if any
                if self.retry_pending:
                    self.retry_pending = False
                # Advance to next packet
                self.outstanding = False
                self.seq_num += 1
                self.bit = 1 - self.bit  # alternate
                if self.seq_num > self.total_packets:
                    self.passivate("DONE")
                else:
                    self._begin_preparation()

        if accepted:
            self.continuef(e)
        else:
            self.continuef(e)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            assert self.current_packet is not None
            self.output["packet_out"].add(self.current_packet)
            self._write_event("packet_sent", dict(self.current_packet))

    def deltint(self):
        if self.phase == "PREPARING":
            # Preparation ended; prepare the packet and schedule output
            self.current_packet = {
                "seq_num": self.seq_num,
                "bit": self.bit,
                "is_retry": self.retry_pending,
            }
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            # Packet sent; start waiting for ACK
            self.outstanding = True
            self.hold_in("WAITING_FOR_ACK", self.timeout)
        elif self.phase == "WAITING_FOR_ACK":
            # Timeout occurred; retry
            self.retry_pending = True
            self._begin_preparation()
        else:
            self.passivate("DONE")

    def exit(self):
        pass