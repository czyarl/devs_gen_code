import sys
import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """
    Alternating Bit Protocol (ABP) Sender: stop-and-wait with preparation delay,
    ACK timeout, and retransmission. Emits JSONL KPI records to stdout.
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

        self.total_packets = total_packets
        self.sender_delay = float(sender_delay)
        self.timeout = float(timeout)

        # Ports
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "pkt_out"))

        # Protocol state
        self.current_seq_num: int = 1
        self.current_bit: int = 0

        # Logging-only flag: whether the next send is a retry
        self.is_retry_next_send: bool = False

        # Timeout generation to ignore stale timeout expiries
        self.timeout_gen: int = 0
        self.armed_timeout_gen: int | None = None  # gen id currently armed, or None if no timeout armed

        # Preparation tracking/cancellation
        self.prep_active: bool = False
        self.prep_gen: int = 0
        self.active_prep_gen: int | None = None
        self.prep_is_retry: bool = False
        self.prep_cancelled_gens: set[int] = set()

        # Output staging
        self._pending_pkt_out: dict | None = None
        self._pending_send_is_retry: bool = False

    def _time_ms(self) -> float:
        return float(get_current_time())

    def _fmt_time(self, t: float) -> float:
        # Ensure at least 2 decimals by rounding to 2; stays float.
        return float(f"{t:.2f}")

    def _write_stdout_event(self, event: str, payload: dict) -> None:
        record = {
            "time": self._fmt_time(self._time_ms()),
            "entity": "sender",
            "event": event,
            "payload": payload,
        }
        print(json.dumps(record), flush=True)

    def _write_stderr(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _begin_preparation(self, is_retry: bool) -> None:
        """
        Start a preparation phase for the current packet.
        Emits delay_start immediately and schedules internal event after sender_delay.
        """
        self.prep_active = True
        self.prep_gen += 1
        self.active_prep_gen = self.prep_gen
        self.prep_is_retry = bool(is_retry)

        self._write_stdout_event(
            "delay_start",
            {"type": "preparation", "duration": float(self.sender_delay)},
        )
        self.hold_in("PREPARING", float(self.sender_delay))

    def _cancel_active_preparation(self) -> None:
        if self.prep_active and self.active_prep_gen is not None:
            self.prep_cancelled_gens.add(self.active_prep_gen)
        self.prep_active = False
        self.active_prep_gen = None

    def _arm_timeout(self) -> None:
        """
        Arm/re-arm the timeout for the current packet.
        """
        self.timeout_gen += 1
        self.armed_timeout_gen = self.timeout_gen
        self.hold_in("WAITING_ACK", float(self.timeout))

    def _disarm_timeout(self) -> None:
        self.armed_timeout_gen = None

    def initialize(self):
        self.current_seq_num = 1
        self.current_bit = 0

        self.is_retry_next_send = False

        self.timeout_gen = 0
        self.armed_timeout_gen = None

        self.prep_active = False
        self.prep_gen = 0
        self.active_prep_gen = None
        self.prep_is_retry = False
        self.prep_cancelled_gens = set()

        self._pending_pkt_out = None
        self._pending_send_is_retry = False

        if self.total_packets > 0:
            # Autonomous startup: begin preparing first packet at t=0.0
            self._begin_preparation(is_retry=False)
        else:
            self.passivate("PASSIVE")

    def deltext(self, e: float):
        accepted_valid_ack = False

        # Process all ACKs in the bag
        for ack in self.input["ack_in"].values:
            ack_bit = ack.get("ack_bit")
            is_valid = int(ack_bit) == int(self.current_bit)
            self._write_stdout_event(
                "ack_received",
                {"ack_bit": int(ack_bit), "is_valid": bool(is_valid)},
            )

            if is_valid:
                accepted_valid_ack = True

        if accepted_valid_ack:
            # Accept ACK for current packet
            self._disarm_timeout()
            self.is_retry_next_send = False

            # Cancel any pending preparation for retry/original of the just-acked packet
            self._cancel_active_preparation()

            # Advance to next packet
            self.current_seq_num += 1
            self.current_bit = 1 - int(self.current_bit)

            if self.current_seq_num > self.total_packets:
                self.passivate("PASSIVE")
            else:
                # Immediately begin preparation for next packet at same time
                self._begin_preparation(is_retry=False)
        else:
            # No state change; preserve remaining time in current phase
            self.continuef(e)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return
        if self._pending_pkt_out is None:
            return

        self.output["pkt_out"].add(dict(self._pending_pkt_out))
        self._write_stdout_event(
            "packet_sent",
            {
                "seq_num": int(self._pending_pkt_out["seq_num"]),
                "bit": int(self._pending_pkt_out["bit"]),
                "is_retry": bool(self._pending_send_is_retry),
            },
        )

    def deltint(self):
        if self.phase == "PREPARING":
            # Preparation completed; if cancelled, do nothing further.
            prep_gen = self.active_prep_gen
            was_cancelled = (prep_gen is not None and prep_gen in self.prep_cancelled_gens)

            # Clear preparation active marker now (we are leaving PREPARING)
            self.prep_active = False
            self.active_prep_gen = None

            if was_cancelled:
                # Remove cancellation marker and go passive; next actions (if any) come from ACK handling.
                self.prep_cancelled_gens.discard(prep_gen)
                self.passivate("PASSIVE")
            else:
                # Schedule output at same time instant
                self._pending_pkt_out = {"seq_num": int(self.current_seq_num), "bit": int(self.current_bit)}
                self._pending_send_is_retry = bool(self.prep_is_retry)
                self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # Output just occurred; clear staged output and arm timeout
            self._pending_pkt_out = None
            self._pending_send_is_retry = False

            # After each send, start/restart ACK timeout
            self._arm_timeout()

        elif self.phase == "WAITING_ACK":
            # Timeout expired. Apply generation check to ignore stale expiries.
            # Note: default xDEVS confluent transition processes external first; we rely on generation
            # and cancellation to satisfy same-time ordering requirements.
            if self.armed_timeout_gen is None:
                # No timeout currently armed; ignore
                self.passivate("PASSIVE")
                return

            # Timeout is for the current packet; start retry preparation
            self.is_retry_next_send = True
            self._begin_preparation(is_retry=True)

        else:
            self.passivate("PASSIVE")

    def exit(self):
        pass