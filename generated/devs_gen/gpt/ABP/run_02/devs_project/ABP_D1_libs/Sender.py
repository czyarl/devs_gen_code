import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """
    Atomic DEVS Sender implementing stop-and-wait ABP with preparation delay,
    timeout-based retransmission, late-ACK cancellation, and JSONL event logging.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        timeout: float,
        sender_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.total_packets = int(total_packets)
        self.timeout = float(timeout)
        self.sender_delay = float(sender_delay)

        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))

        # State variables (initialized in initialize)
        self.current_seq_num: int = 1
        self.current_bit: int = 0

        # Phase/state flags
        self.is_retry_next_send: bool = False
        self.pending_retry_preparation: bool = False  # scheduled due to timeout but not yet sent
        self.timeout_active: bool = False  # conceptual; true only during WAITING_FOR_ACK

    # -----------------------
    # External IO (stdout/stderr)
    # -----------------------
    @staticmethod
    def _fmt_time(t: float) -> float:
        # Ensure float with at least 2 decimals in JSON output.
        return float(f"{float(t):.2f}")

    def _write_stdout_event(self, event: str, payload: dict) -> None:
        record = {
            "time": self._fmt_time(get_current_time()),
            "entity": "sender",
            "event": event,
            "payload": payload,
        }
        print(json.dumps(record), flush=True)

    def _write_stderr(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    # -----------------------
    # Internal helpers
    # -----------------------
    def _begin_preparation(self) -> None:
        # Emit delay_start at the instant preparation begins.
        self._write_stdout_event(
            "delay_start",
            {"type": "preparation", "duration": float(self.sender_delay)},
        )
        self.hold_in("preparing_to_send", float(self.sender_delay))

    def _advance_after_valid_ack(self) -> None:
        # Cancel any pending retry preparation for current packet.
        self.pending_retry_preparation = False
        self.is_retry_next_send = False
        self.timeout_active = False

        # Advance to next packet
        self.current_seq_num += 1
        self.current_bit = 1 - int(self.current_bit)

        if self.current_seq_num > self.total_packets:
            self.passivate("done")
        else:
            # Immediately start preparation for next packet at same simulation time.
            self._begin_preparation()

    # -----------------------
    # DEVS lifecycle
    # -----------------------
    def initialize(self):
        self.current_seq_num = 1
        self.current_bit = 0
        self.is_retry_next_send = False
        self.pending_retry_preparation = False
        self.timeout_active = False

        if self.total_packets > 0:
            # At time 0.0 begin preparation for first packet.
            self._begin_preparation()
        else:
            self.passivate("done")

    def deltext(self, e: float):
        # Same-time ordering edge case: if internal timeout expiry and ACK arrive at same time,
        # timeout must be processed first. Default xDEVS confluent calls deltcon() which by
        # default runs deltint then deltext, satisfying the required ordering.
        accepted = False

        for ack in self.input["ack_in"].values:
            ack_bit = ack.get("bit")
            try:
                ack_bit_int = int(ack_bit)
            except Exception:
                ack_bit_int = ack_bit  # will fail validity check

            is_valid = (ack_bit_int == self.current_bit)
            self._write_stdout_event(
                "ack_received",
                {"ack_bit": ack_bit_int, "is_valid": bool(is_valid)},
            )

            if is_valid:
                accepted = True

        if accepted:
            self._advance_after_valid_ack()
        else:
            # No valid ACK: keep current phase and remaining time.
            self.continuef(e)

    def lambdaf(self):
        # Only send packet when preparation completes (OUTPUT_READY).
        if self.phase != "OUTPUT_READY":
            return

        # If this OUTPUT_READY corresponds to a retry that was canceled by a late valid ACK,
        # suppress packet_sent and DEVS output.
        if self.is_retry_next_send and not self.pending_retry_preparation:
            return

        packet = {
            "seq_num": int(self.current_seq_num),
            "bit": int(self.current_bit),
            "is_retry": bool(self.is_retry_next_send),
        }
        self.output["data_out"].add(packet)
        self._write_stdout_event("packet_sent", dict(packet))

    def deltint(self):
        if self.phase == "preparing_to_send":
            # Preparation ended; schedule immediate output at same time.
            self.hold_in("OUTPUT_READY", 0.0)
            return

        if self.phase == "OUTPUT_READY":
            # If this was a canceled retry output, just proceed as if nothing was sent.
            if self.is_retry_next_send and not self.pending_retry_preparation:
                # Return to waiting_for_ack with remaining timeout? The timeout would have been
                # canceled if a valid ACK arrived; otherwise this cancellation cannot happen.
                # So safest is to passivate done only if already done; else keep waiting if active.
                # However, cancellation only occurs on valid ACK, which would have moved phase away
                # from OUTPUT_READY via deltext at same time. This is a defensive fallback.
                self.passivate("waiting_for_ack")
                return

            # After sending (original or retry), start/restart timeout.
            if self.is_retry_next_send:
                # Retry has now been actually sent; clear pending flag.
                self.pending_retry_preparation = False

            self.timeout_active = True
            self.hold_in("waiting_for_ack", float(self.timeout))
            return

        if self.phase == "waiting_for_ack":
            # Timeout expired: schedule retransmission preparation.
            self.is_retry_next_send = True
            self.pending_retry_preparation = True
            self.timeout_active = False
            self._begin_preparation()
            return

        # done or any other phase
        self.passivate("done")

    def exit(self):
        pass