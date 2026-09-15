import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """
    Atomic DEVS model implementing the Sender side of an Alternating Bit Protocol (ABP)
    stop-and-wait session.

    Time unit: 1.0 simulation time unit = 1 ms.
    """

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

        # Parameters
        self.total_packets = int(total_packets)
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "pkt_out"))

        # State (initialized in initialize)
        self.seq_num: int = 1
        self.bit: int = 0
        self.is_retry: bool = False

        self.done: bool = False

        # Whether a preparation delay is pending for the current packet
        self.prep_pending: bool = False
        self.prep_kind: str | None = None  # "original" | "retransmission" | None

        # Timeout tracking
        self.timeout_active: bool = False

    def _now(self) -> float:
        return float(get_current_time())

    def _write_stdout_event(self, event: str, payload: dict) -> None:
        t = self._now()
        # Ensure float with at least 2 decimals in textual representation
        record = {
            "time": float(f"{t:.2f}"),
            "entity": "sender",
            "event": event,
            "payload": payload,
        }
        print(json.dumps(record), flush=True)

    def _begin_preparation(self, kind: str) -> None:
        # kind: "original" or "retransmission"
        self.prep_pending = True
        self.prep_kind = kind
        self._write_stdout_event("delay_start", {"type": "preparation", "duration": self.sender_delay})
        self.hold_in("PREPARING", self.sender_delay)

    def initialize(self):
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False

        self.done = False
        self.prep_pending = False
        self.prep_kind = None
        self.timeout_active = False

        if self.total_packets > 0:
            # Autonomous start at t=0.0: begin preparation and emit delay_start now.
            self._begin_preparation("original")
        else:
            self.done = True
            self.passivate("DONE")

    def deltext(self, e: float):
        # Process all ACKs arriving at this time.
        accepted_valid_ack = False

        for ack in self.input["ack_in"].values:
            ack_bit = ack.get("ack_bit")
            is_valid = (int(ack_bit) == int(self.bit))
            self._write_stdout_event("ack_received", {"ack_bit": int(ack_bit), "is_valid": bool(is_valid)})

            if is_valid:
                accepted_valid_ack = True

        if accepted_valid_ack:
            # Accept ACK for current packet.
            # Cancel any active timeout and any pending retransmission preparation.
            self.timeout_active = False

            # Late-ACK rule: cancel pending retransmission preparation for same packet.
            if self.prep_pending and self.prep_kind == "retransmission":
                self.prep_pending = False
                self.prep_kind = None

            # Advance to next packet.
            self.seq_num += 1
            self.bit = 1 - int(self.bit)
            self.is_retry = False

            if self.seq_num > self.total_packets:
                self.done = True
                self.prep_pending = False
                self.prep_kind = None
                self.passivate("DONE")
            else:
                # Immediately begin preparation for next packet at same time.
                self._begin_preparation("original")
        else:
            # No valid ACK accepted; keep current schedule.
            self.continuef(e)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        packet = {"seq_num": int(self.seq_num), "bit": int(self.bit), "is_retry": bool(self.is_retry)}
        self.output["pkt_out"].add(packet)
        self._write_stdout_event(
            "packet_sent",
            {"seq_num": int(self.seq_num), "bit": int(self.bit), "is_retry": bool(self.is_retry)},
        )

    def deltint(self):
        if self.done:
            self.passivate("DONE")
            return

        if self.phase == "PREPARING":
            # Preparation completed; immediately send packet.
            # If preparation was canceled by a late valid ACK, do nothing and remain passive.
            if not self.prep_pending:
                self.passivate("PASSIVE")
                return
            self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # Output has just been produced in lambdaf(); now (re)start timeout.
            self.prep_pending = False
            self.prep_kind = None
            self.timeout_active = True
            self.hold_in("WAITING_FOR_ACK", self.timeout)

        elif self.phase == "WAITING_FOR_ACK":
            # Timeout expired before valid ACK: begin retransmission preparation.
            # Same-time ordering with ACK is handled by default DEVS confluent:
            # internal transition first, then external (deltint then deltext).
            self.is_retry = True
            self.timeout_active = False  # will be restarted only after packet is resent
            self._begin_preparation("retransmission")

        else:
            self.passivate("PASSIVE")

    def exit(self):
        pass