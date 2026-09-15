import json
import sys
from typing import Any

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ServerReceiver(Atomic):
    """
    Atomic DEVS ingress endpoint that terminates the upload-side ABP at the server
    and feeds accepted packets into the server’s internal storage path.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_ms: float):
        super().__init__(name)
        self.parent = parent
        self.processing_ms = float(processing_ms)

        self.add_in_port(Port(dict, "upload_data_in"))
        self.add_out_port(Port(dict, "sender_ack_out"))
        self.add_out_port(Port(dict, "enqueue_out"))

        # Remembered state (initialized in initialize())
        self.expected_bit: int = 0
        self.busy: bool = False
        self.inflight_pkt: dict[str, Any] | None = None

        # Prepared outputs for lambdaf()
        self._ack_to_send: dict[str, int] | None = None
        self._enqueue_to_send: dict[str, Any] | None = None

    # --------- helpers ---------
    def _now_ms(self) -> float:
        return float(get_current_time())

    def _stdout_event(self, event_type: str, val: dict) -> None:
        record = {
            "timestamp_ms": self._now_ms(),
            "model": "server_receiver",
            "type": event_type,
            "val": val,
        }
        print(json.dumps(record), flush=True)

    def _warn(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _validate_packet(self, pkt: Any) -> dict[str, Any] | None:
        if not isinstance(pkt, dict):
            self._warn(f"ServerReceiver warning: ignoring non-dict packet: {pkt!r}")
            return None
        if "seq" not in pkt or "bit" not in pkt:
            self._warn(f"ServerReceiver warning: ignoring packet missing keys: {pkt!r}")
            return None
        seq = pkt.get("seq")
        bit = pkt.get("bit")
        if not isinstance(seq, int):
            self._warn(f"ServerReceiver warning: ignoring packet with non-int seq: {pkt!r}")
            return None
        if bit not in (0, 1):
            self._warn(f"ServerReceiver warning: ignoring packet with invalid bit: {pkt!r}")
            return None
        return {"seq": seq, "bit": int(bit)}

    # --------- DEVS methods ---------
    def initialize(self):
        self.expected_bit = 0
        self.busy = False
        self.inflight_pkt = None
        self._ack_to_send = None
        self._enqueue_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if already processing; do not alter inflight or schedule.
        if self.phase == "PROCESSING":
            self.continuef(e)
        else:
            # If idle, remain idle unless we accept a first valid packet.
            self.passivate("IDLE")

        accepted_started = False

        for raw_pkt in self.input["upload_data_in"].values:
            pkt = self._validate_packet(raw_pkt)
            if pkt is None:
                continue

            # Log every valid packet arrival immediately.
            self._stdout_event("packet_received", {"seq": pkt["seq"], "bit": pkt["bit"]})

            # If idle and not busy, accept the first iterated packet as inflight.
            if (not self.busy) and (not accepted_started) and (self.phase != "PROCESSING"):
                self.inflight_pkt = pkt
                self.busy = True
                accepted_started = True
                self.hold_in("PROCESSING", max(0.0, self.processing_ms))

        # If we were idle and no valid packet accepted, ensure passivated.
        if (not self.busy) and (self.phase != "PROCESSING"):
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            if self._ack_to_send is not None:
                self.output["sender_ack_out"].add(dict(self._ack_to_send))
            if self._enqueue_to_send is not None:
                self.output["enqueue_out"].add(dict(self._enqueue_to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing completes now; decide ACK/enqueue and schedule immediate output.
            if self.inflight_pkt is None:
                # Defensive: nothing to do.
                self.busy = False
                self.passivate("IDLE")
                return

            bit = self.inflight_pkt["bit"]
            seq = self.inflight_pkt["seq"]

            self._ack_to_send = None
            self._enqueue_to_send = None

            if bit == self.expected_bit:
                ack_bit = self.expected_bit
                self._stdout_event("ack_sent_to_sender", {"bit": ack_bit})
                self._ack_to_send = {"bit": ack_bit}
                self._enqueue_to_send = {"seq": seq, "bit": bit}
                self.expected_bit = 1 - self.expected_bit
            else:
                ack_bit = 1 - self.expected_bit
                self._stdout_event("ack_sent_to_sender", {"bit": ack_bit})
                self._ack_to_send = {"bit": ack_bit}
                self._enqueue_to_send = None

            self.hold_in("OUTPUT_READY", 0.0)
            return

        if self.phase == "OUTPUT_READY":
            # Clear inflight and become idle; do not auto-start another cycle.
            self._ack_to_send = None
            self._enqueue_to_send = None
            self.inflight_pkt = None
            self.busy = False
            self.passivate("IDLE")
            return

        # Fallback: passivate
        self.passivate("IDLE")

    def exit(self):
        pass