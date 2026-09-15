import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        preparation_delay_ms: float,
        ack_timeout_ms: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Fixed scenario parameters (passed by root)
        self.preparation_delay_ms = float(preparation_delay_ms)
        self.ack_timeout_ms = float(ack_timeout_ms)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "control_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))

        # State (initialized in initialize)
        self.packets_remaining: int = 0
        self.seq: int = 1
        self.bit: int = 0
        self.phase: str = "IDLE"

        self.inflight_seq: int = 1
        self.inflight_bit: int = 0
        self.next_send_is_retry: bool = False

        self.deadline_kind: str | None = None
        self.last_emitted_timestamp_ms: float = float("-inf")

        # Output staging for lambdaf()
        self._pending_data_out: dict | None = None

    def _now_ms(self) -> float:
        return float(get_current_time())

    def _emit(self, event_type: str, val: dict) -> None:
        now = self._now_ms()
        # Ensure nondecreasing timestamps (ordering guard for same-time multi-events)
        if now < self.last_emitted_timestamp_ms:
            now = self.last_emitted_timestamp_ms
        self.last_emitted_timestamp_ms = now
        print(
            json.dumps(
                {
                    "timestamp_ms": now,
                    "model": "sender",
                    "type": event_type,
                    "val": val,
                }
            ),
            flush=True,
        )

    def _begin_preparation(self) -> None:
        # Enter PREPARING immediately and schedule preparation completion.
        self.phase = "PREPARING"
        self.deadline_kind = "prep_done"
        self._emit("preparation_started", {"duration": 10000})
        self.hold_in("PREPARING", self.preparation_delay_ms)

    def initialize(self):
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.phase = "IDLE"

        self.inflight_seq = self.seq
        self.inflight_bit = self.bit
        self.next_send_is_retry = False

        self.deadline_kind = None
        self.last_emitted_timestamp_ms = float("-inf")

        self._pending_data_out = None

        self.passivate("IDLE")

    def deltext(self, e: float):
        # Process control commands (additive)
        for msg in self.input["control_in"].values:
            added = int(msg.get("added", 0))
            if added > 0:
                self.packets_remaining += added
            self._emit(
                "control_cmd",
                {"added": added, "total_remaining": int(self.packets_remaining)},
            )

            if self.phase == "IDLE" and self.packets_remaining > 0:
                # Start preparing immediately at the same simulation time.
                self._begin_preparation()

        # Process ACKs (per-message)
        for msg in self.input["ack_in"].values:
            ack_bit = int(msg.get("bit", 0))
            self._emit("ack_received", {"bit": ack_bit})

            if self.phase != "WAIT_ACK":
                continue

            if ack_bit == int(self.inflight_bit):
                # Accept correct ACK: advance protocol and cancel timeout by rescheduling.
                self.packets_remaining -= 1
                self.seq += 1
                self.bit = 1 - int(self.bit)

                self.deadline_kind = None
                self._pending_data_out = None

                if self.packets_remaining > 0:
                    self._begin_preparation()
                else:
                    self.phase = "IDLE"
                    self.passivate("IDLE")
            else:
                # Incorrect/duplicate ACK: ignore for progress; do not reset timeout.
                pass

        # If still active and not rescheduled above, preserve remaining time.
        if self.phase in ("PREPARING", "WAIT_ACK", "SEND"):
            if self.phase == "SEND":
                # SEND is a zero-time output phase; keep it at 0.
                self.hold_in("SEND", 0.0)
            else:
                self.hold_in(self.phase, max(0.0, self.ta() - e))
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase != "SEND":
            return
        if self._pending_data_out is None:
            return
        self.output["data_out"].add(dict(self._pending_data_out))

    def deltint(self):
        if self.phase == "PREPARING":
            # Preparation completed: move to WAIT_ACK and send first transmission immediately.
            self.phase = "WAIT_ACK"
            self.inflight_seq = int(self.seq)
            self.inflight_bit = int(self.bit)
            self.next_send_is_retry = False

            self._pending_data_out = {"seq": int(self.inflight_seq), "bit": int(self.inflight_bit)}
            self._emit(
                "packet_sent",
                {
                    "seq": int(self.inflight_seq),
                    "bit": int(self.inflight_bit),
                    "is_retry": False,
                },
            )

            self.deadline_kind = "ack_timeout"
            self.hold_in("SEND", 0.0)

        elif self.phase == "SEND":
            # After sending, start/restart the ACK timeout.
            self._pending_data_out = None
            self.phase = "WAIT_ACK"
            self.deadline_kind = "ack_timeout"
            self.hold_in("WAIT_ACK", self.ack_timeout_ms)

        elif self.phase == "WAIT_ACK":
            # Timeout expired: retransmit immediately and restart timeout.
            self._emit("timeout", {"seq": int(self.inflight_seq)})

            self.next_send_is_retry = True
            self._pending_data_out = {"seq": int(self.inflight_seq), "bit": int(self.inflight_bit)}
            self._emit(
                "packet_sent",
                {
                    "seq": int(self.inflight_seq),
                    "bit": int(self.inflight_bit),
                    "is_retry": True,
                },
            )

            self.deadline_kind = "ack_timeout"
            self.hold_in("SEND", 0.0)

        else:
            self.phase = "IDLE"
            self.deadline_kind = None
            self._pending_data_out = None
            self.passivate("IDLE")

    def exit(self):
        pass