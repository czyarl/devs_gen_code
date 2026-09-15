import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """
    Atomic DEVS uploader implementing the upload-side Alternating Bit Protocol (ABP).

    Phases: IDLE, PREPARING, SEND_READY, WAIT_ACK
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        preparation_ms: float,
        timeout_ms: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.preparation_ms = float(preparation_ms)
        self.timeout_ms = float(timeout_ms)

        self.add_in_port(Port(dict, "control_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))

        # State initialized in initialize()
        self.packets_remaining: int = 0
        self.next_seq: int = 1
        self.expected_ack_bit: int = 0

        self.preparing_for_seq: tuple[int, int] | None = None
        self.waiting_for_seq: tuple[int, int] | None = None
        self.timeout_deadline: float | None = None
        self.send_is_retry: bool = False

        # Prepared output for lambdaf()
        self._pending_send_packet: dict | None = None

    def _now(self) -> float:
        return float(get_current_time())

    def _write_stdout_event(self, event_type: str, val: dict) -> None:
        record = {
            "timestamp_ms": self._now(),
            "model": "sender",
            "type": event_type,
            "val": val,
        }
        print(json.dumps(record), flush=True)

    def _warn_stderr(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _clamp_packets_remaining_after_control(self) -> None:
        # General clamp to prevent negative remaining work.
        if self.packets_remaining < 0:
            self.packets_remaining = 0

        # Edge-case rule: if a packet is already in-flight, packets_remaining must not drop below 1.
        if self.phase == "WAIT_ACK" and self.waiting_for_seq is not None and self.packets_remaining < 1:
            self.packets_remaining = 1

    def _begin_preparation(self, for_seq_bit: tuple[int, int], is_retry: bool) -> None:
        self.preparing_for_seq = for_seq_bit
        self.send_is_retry = bool(is_retry)
        self._write_stdout_event("preparation_started", {"duration": self.preparation_ms})
        self.hold_in("PREPARING", self.preparation_ms)

    def initialize(self):
        self.packets_remaining = 0
        self.next_seq = 1
        self.expected_ack_bit = 0

        self.preparing_for_seq = None
        self.waiting_for_seq = None
        self.timeout_deadline = None
        self.send_is_retry = False
        self._pending_send_packet = None

        self.passivate("IDLE")

    def deltext(self, e: float):
        # Deterministic ordering at same simulation time:
        # process all control_in first, then all ack_in.
        any_state_change = False

        # 1) control_in
        for msg in self.input["control_in"].values:
            if not isinstance(msg, dict) or "added" not in msg:
                self._warn_stderr(f"[Sender] Ignoring malformed control_in message: {msg!r}")
                continue
            try:
                added = int(msg["added"])
            except Exception:
                self._warn_stderr(f"[Sender] Ignoring non-int control_in['added']: {msg!r}")
                continue

            self.packets_remaining += added
            self._clamp_packets_remaining_after_control()

            self._write_stdout_event(
                "control_cmd",
                {"added": added, "total_remaining": int(self.packets_remaining)},
            )

            # If idle and now have work, start preparation.
            if self.phase == "IDLE" and self.packets_remaining > 0:
                seq_bit = (self.next_seq, self.expected_ack_bit)
                self._begin_preparation(seq_bit, is_retry=False)
                any_state_change = True

        # 2) ack_in
        accepted_correct_ack = False
        for ack in self.input["ack_in"].values:
            if not isinstance(ack, dict) or "bit" not in ack:
                self._warn_stderr(f"[Sender] Ignoring malformed ack_in message: {ack!r}")
                continue
            try:
                ack_bit = int(ack["bit"])
            except Exception:
                # Not parseable -> no stdout emission (schema safety)
                self._warn_stderr(f"[Sender] Ignoring non-int ack_in['bit']: {ack!r}")
                continue
            if ack_bit not in (0, 1):
                # Not 0/1 -> ignore for advancement; do not emit stdout (schema safety)
                self._warn_stderr(f"[Sender] Ignoring out-of-range ack bit (not 0/1): {ack_bit!r}")
                continue

            # Emit ack_received only for parseable int 0/1.
            self._write_stdout_event("ack_received", {"bit": ack_bit})

            if self.phase == "WAIT_ACK" and ack_bit == self.expected_ack_bit:
                accepted_correct_ack = True

        if accepted_correct_ack:
            # Correct ACK cancels timeout and advances ABP.
            self.waiting_for_seq = None
            self.timeout_deadline = None

            if self.packets_remaining > 0:
                self.packets_remaining -= 1
                if self.packets_remaining < 0:
                    self.packets_remaining = 0

            self.next_seq += 1
            self.expected_ack_bit = 1 - self.expected_ack_bit
            self.send_is_retry = False
            self._pending_send_packet = None
            self.preparing_for_seq = None

            if self.packets_remaining > 0:
                seq_bit = (self.next_seq, self.expected_ack_bit)
                self._begin_preparation(seq_bit, is_retry=False)
            else:
                self.passivate("IDLE")
            any_state_change = True

        if not any_state_change:
            # Preserve remaining time if we didn't reschedule.
            self.continuef(e)

    def lambdaf(self):
        # Only emit DEVS outputs here.
        if self.phase != "SEND_READY":
            return
        if self._pending_send_packet is None:
            return

        self.output["data_out"].add(dict(self._pending_send_packet))

        # Emit packet_sent observation at send time.
        self._write_stdout_event(
            "packet_sent",
            {
                "seq": int(self._pending_send_packet["seq"]),
                "bit": int(self._pending_send_packet["bit"]),
                "is_retry": bool(self.send_is_retry),
            },
        )

    def deltint(self):
        now = self._now()

        if self.phase == "PREPARING":
            # Preparation ended; schedule immediate send.
            if self.preparing_for_seq is None:
                # Defensive: if somehow missing, go idle.
                self.passivate("IDLE")
                return

            seq, bit = self.preparing_for_seq
            self._pending_send_packet = {"seq": int(seq), "bit": int(bit)}
            self.hold_in("SEND_READY", 0.0)

        elif self.phase == "SEND_READY":
            # After sending, start waiting for ACK with timeout.
            if self._pending_send_packet is None:
                self.passivate("IDLE")
                return

            seq = int(self._pending_send_packet["seq"])
            bit = int(self._pending_send_packet["bit"])
            self.waiting_for_seq = (seq, bit)
            self.timeout_deadline = now + self.timeout_ms

            # Clear pending output; remain in WAIT_ACK.
            self._pending_send_packet = None
            self.preparing_for_seq = None

            self.hold_in("WAIT_ACK", self.timeout_ms)

        elif self.phase == "WAIT_ACK":
            # Timeout fired (unless a correct ACK arrived simultaneously; deltcon default favors internal,
            # but requirement wants correct ACK to win. We implement that by ensuring correct ACK in deltext
            # reschedules away from WAIT_ACK; if still here, no correct ACK was accepted.)
            if self.waiting_for_seq is None:
                self.passivate("IDLE")
                return

            seq, _bit = self.waiting_for_seq
            self._write_stdout_event("timeout", {"seq": int(seq)})

            # Schedule retransmission: prepare again, then resend same seq/bit.
            self.send_is_retry = True
            self._begin_preparation((seq, _bit), is_retry=True)

        else:
            self.passivate("IDLE")

    def exit(self):
        pass