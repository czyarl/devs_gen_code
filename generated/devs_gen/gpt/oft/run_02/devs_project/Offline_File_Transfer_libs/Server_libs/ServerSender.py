import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """
    Atomic DEVS egress endpoint for the download ABP loop (Server → Receiver).

    Maintains an internal unbounded FIFO queue of accepted packets and forwards
    at most one packet at a time, waiting for the corresponding ACK before
    forwarding the next.
    """

    MODEL_NAME_FOR_STDOUT = "server_sender"

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Input ports
        self.add_in_port(Port(dict, "request_in"))
        self.add_in_port(Port(dict, "receiver_ack_in"))
        self.add_in_port(Port(dict, "enqueue_in"))

        # Output ports
        self.add_out_port(Port(dict, "download_data_out"))

        # Retained state (initialized in initialize())
        self.download_allowed: bool = False
        self.fifo: deque[dict] = deque()
        self.waiting_for_ack: bool = False
        self.inflight_packet: dict | None = None
        self.desired_stop_after_cycle: bool = False

        # Internal output preparation
        self._pending_forward_packet: dict | None = None

    # ---------- External IO helpers ----------
    def _stdout_event(self, event_type: str, val: dict) -> None:
        record = {
            "timestamp_ms": float(get_current_time()),
            "model": self.MODEL_NAME_FOR_STDOUT,
            "type": event_type,
            "val": val,
        }
        print(json.dumps(record), flush=True)

    def _warn(self, msg: str) -> None:
        print(f"[ServerSender warning] {msg}", file=sys.stderr, flush=True)

    # ---------- Validation helpers ----------
    @staticmethod
    def _is_packet(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        if "seq" not in payload or "bit" not in payload:
            return False
        if not isinstance(payload["seq"], int):
            return False
        if payload["bit"] not in (0, 1):
            return False
        return True

    @staticmethod
    def _is_request(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        if "allowed" not in payload:
            return False
        if not isinstance(payload["allowed"], bool):
            return False
        return True

    @staticmethod
    def _is_ack(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        if "bit" not in payload:
            return False
        if payload["bit"] not in (0, 1):
            return False
        return True

    # ---------- DEVS core ----------
    def initialize(self):
        # Passive at time 0; no stdout records until input arrives.
        self.download_allowed = False
        self.fifo = deque()
        self.waiting_for_ack = False
        self.inflight_packet = None
        self.desired_stop_after_cycle = False
        self._pending_forward_packet = None
        self.passivate("WAITING")

    def deltext(self, e: float):
        # Preserve time accounting if we were active (should be rare; forwarding is zero-delay).
        if self.sigma != float("inf"):
            self.continuef(e)

        # Process all inputs at this simulation time. Order matters for edge cases:
        # - Apply request toggles before deciding whether to forward after an ACK completion.
        # - Enqueueing is just queueing.
        # - ACK handling may complete a cycle and enable forwarding.
        # This ordering matches the contract's simultaneous-event rules.
        # 1) enqueue_in
        for payload in self.input["enqueue_in"].values:
            if not self._is_packet(payload):
                self._warn(f"Ignoring malformed enqueue_in payload: {payload!r}")
                continue
            self.fifo.append({"seq": int(payload["seq"]), "bit": int(payload["bit"])})

        # 2) request_in
        for payload in self.input["request_in"].values:
            if not self._is_request(payload):
                self._warn(f"Ignoring malformed request_in payload: {payload!r}")
                continue
            prev = self.download_allowed
            new_allowed = bool(payload["allowed"])
            self.download_allowed = new_allowed
            if new_allowed != prev:
                self._stdout_event("download_valve_change", {"allowed": new_allowed})
            if (not new_allowed) and self.waiting_for_ack:
                self.desired_stop_after_cycle = True

        # 3) receiver_ack_in
        for payload in self.input["receiver_ack_in"].values:
            if not self._is_ack(payload):
                self._warn(f"Ignoring malformed receiver_ack_in payload: {payload!r}")
                continue
            ack_bit = int(payload["bit"])
            self._stdout_event("ack_received_from_receiver", {"bit": ack_bit})

            if self.waiting_for_ack and self.inflight_packet is not None:
                if ack_bit == int(self.inflight_packet.get("bit")):
                    # Complete cycle
                    self.waiting_for_ack = False
                    self.inflight_packet = None
                    if self.desired_stop_after_cycle:
                        # Stop after this cycle; do not start new forward now.
                        self.desired_stop_after_cycle = False
                    # else: forwarding decision is handled below after all inputs

        # After processing all inputs at this time, decide whether to forward immediately.
        self._maybe_schedule_forward()

    def _maybe_schedule_forward(self) -> None:
        # Only schedule one forward per decision point.
        if (
            self._pending_forward_packet is None
            and self.download_allowed
            and (not self.waiting_for_ack)
            and len(self.fifo) > 0
        ):
            pkt = self.fifo.popleft()
            self.inflight_packet = pkt
            self.waiting_for_ack = True
            self._pending_forward_packet = pkt
            # Immediate (same simulation time) output
            self.hold_in("FORWARD", 0.0)
        else:
            # No internal event needed; wait for more inputs.
            self.passivate("WAITING")

    def lambdaf(self):
        if self.phase == "FORWARD" and self._pending_forward_packet is not None:
            pkt = self._pending_forward_packet
            # DEVS output
            self.output["download_data_out"].add({"seq": int(pkt["seq"]), "bit": int(pkt["bit"])})
            # External IO (stdout JSONL)
            self._stdout_event("packet_forwarded", {"seq": int(pkt["seq"]), "bit": int(pkt["bit"])})

    def deltint(self):
        if self.phase == "FORWARD":
            # Clear pending output and then see if another immediate forward is allowed.
            # Note: ABP rule prevents forwarding another until ACK completes, so this
            # will normally passivate.
            self._pending_forward_packet = None
            self._maybe_schedule_forward()
        else:
            self.passivate("WAITING")

    def exit(self):
        # No special shutdown behavior.
        pass