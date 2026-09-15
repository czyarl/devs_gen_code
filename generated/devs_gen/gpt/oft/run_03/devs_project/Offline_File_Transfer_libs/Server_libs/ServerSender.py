import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """
    Atomic DEVS model implementing the egress side of the Server for the download ABP loop.

    Buffers accepted packets from ServerReceiver in an internal unbounded FIFO queue,
    applies a request-controlled download valve, forwards at most one packet at a time
    toward the Receiver, and waits for an ACK before forwarding the next packet.
    """

    MODEL_NAME_FOR_STDOUT = "server_sender"

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports (locked contract)
        self.add_in_port(Port(dict, "download_request_in"))
        self.add_in_port(Port(dict, "receiver_ack_in"))
        self.add_in_port(Port(dict, "storage_push_in"))
        self.add_out_port(Port(dict, "download_data_out"))

        # State (initialized in initialize)
        self.download_allowed: bool = False
        self.queue: deque[dict] = deque()
        self.waiting_for_ack: bool = False
        self.inflight_packet: dict | None = None
        self.inflight_bit: int | None = None

        # Output staging for zero-delay emissions
        self._pending_forward_packet: dict | None = None

    # -----------------------
    # Helpers: validation + IO
    # -----------------------
    @staticmethod
    def _is_valid_bit(bit) -> bool:
        return isinstance(bit, int) and bit in (0, 1)

    def _warn(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _emit_stdout_event(self, type_name: str, val: dict) -> None:
        now = float(get_current_time())
        record = {
            "timestamp_ms": now,
            "model": self.MODEL_NAME_FOR_STDOUT,
            "type": type_name,
            "val": dict(val),
        }
        print(json.dumps(record), flush=True)

    def _maybe_prepare_forward(self) -> None:
        """
        Prepare at most one forwarding action if allowed and possible.
        This does not emit DEVS output; it only stages it and schedules OUTPUT_READY.
        """
        if self._pending_forward_packet is not None:
            return
        if not self.download_allowed:
            return
        if self.waiting_for_ack:
            return
        if not self.queue:
            return

        pkt = self.queue.popleft()
        # pkt is expected to be {'seq': int, 'bit': int}
        self.inflight_packet = pkt
        self.inflight_bit = pkt.get("bit")
        self.waiting_for_ack = True

        self._pending_forward_packet = pkt
        self.hold_in("OUTPUT_READY", 0.0)

    # -------------
    # DEVS callbacks
    # -------------
    def initialize(self):
        self.download_allowed = False
        self.queue = deque()
        self.waiting_for_ack = False
        self.inflight_packet = None
        self.inflight_bit = None
        self._pending_forward_packet = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if already active; otherwise remain/passivate unless we schedule OUTPUT_READY.
        if self.phase != "IDLE":
            self.continuef(e)

        # Apply all state updates for inputs at this same simulation time.
        # 1) download_request_in
        for req in self.input["download_request_in"].values:
            if not isinstance(req, dict) or "allowed" not in req or not isinstance(req.get("allowed"), bool):
                self._warn(f"[ServerSender] Ignoring malformed download_request_in: {req!r}")
                continue
            self.download_allowed = req["allowed"]
            self._emit_stdout_event("download_valve_change", {"allowed": self.download_allowed})
            # Graceful stop is implicit: if set False while waiting_for_ack, do nothing else.

        # 2) storage_push_in
        for pkt in self.input["storage_push_in"].values:
            if not isinstance(pkt, dict) or "seq" not in pkt or "bit" not in pkt:
                self._warn(f"[ServerSender] Ignoring malformed storage_push_in: {pkt!r}")
                continue
            bit = pkt.get("bit")
            if not self._is_valid_bit(bit):
                self._warn(f"[ServerSender] Ignoring storage_push_in with invalid bit: {pkt!r}")
                continue
            seq = pkt.get("seq")
            if not isinstance(seq, int):
                self._warn(f"[ServerSender] Ignoring storage_push_in with invalid seq: {pkt!r}")
                continue
            self.queue.append({"seq": seq, "bit": bit})

        # 3) receiver_ack_in
        for ack in self.input["receiver_ack_in"].values:
            if not isinstance(ack, dict) or "bit" not in ack:
                self._warn(f"[ServerSender] Ignoring malformed receiver_ack_in: {ack!r}")
                continue
            bit = ack.get("bit")
            if not self._is_valid_bit(bit):
                self._warn(f"[ServerSender] Ignoring receiver_ack_in with invalid bit: {ack!r}")
                continue

            self._emit_stdout_event("ack_received_from_receiver", {"bit": bit})

            if not self.waiting_for_ack:
                # Unexpected/stale ACK: log only, no state change.
                continue

            # waiting_for_ack == True
            if self.inflight_bit is not None and bit == self.inflight_bit:
                # Complete cycle
                self.waiting_for_ack = False
                self.inflight_packet = None
                self.inflight_bit = None
            else:
                # Out-of-sync/duplicate ACK: keep waiting, do not retransmit here.
                pass

        # After applying all updates, attempt at most one forward if possible.
        # Confluence requirement: apply all updates first, then forward decision.
        if self.phase == "IDLE":
            self._maybe_prepare_forward()
            if self.phase == "IDLE":
                self.passivate("IDLE")

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return
        if self._pending_forward_packet is None:
            return

        pkt = self._pending_forward_packet
        # DEVS output
        self.output["download_data_out"].add(dict(pkt))
        # External IO stdout
        self._emit_stdout_event(
            "packet_forwarded",
            {"seq": int(pkt["seq"]), "bit": int(pkt["bit"])},
        )

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            # Clear staged output and decide whether to remain active.
            self._pending_forward_packet = None
            # Must not send again until ACK arrives (waiting_for_ack True), so typically idle.
            self.passivate("IDLE")
            return

        self.passivate("IDLE")

    def exit(self):
        pass