"""Atomic model: ServerReceiver (ingress ABP checker for upload direction)."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_ms = float(processing_delay_ms)

        self.add_in_port(Port(dict, "upload_data_in"))
        self.add_out_port(Port(dict, "sender_ack_out"))
        self.add_out_port(Port(dict, "storage_push_out"))

        # State (initialized in initialize)
        self.expected_bit: int = 0
        self.pending: list[dict] = []
        self.last_stdout_timestamp_ms: float = 0.0

        # Prepared outputs for next lambdaf()
        self._due_to_process: list[dict] = []
        self._acks_to_send: list[dict] = []
        self._storage_to_push: list[dict] = []

    def initialize(self):
        self.expected_bit = 0
        self.pending = []
        self.last_stdout_timestamp_ms = 0.0

        self._due_to_process = []
        self._acks_to_send = []
        self._storage_to_push = []

        self.passivate("IDLE")

    def _emit_stdout(self, timestamp_ms: float, event_type: str, val: dict) -> None:
        # Enforce nondecreasing timestamps on stdout.
        ts = float(timestamp_ms)
        if ts < self.last_stdout_timestamp_ms:
            ts = self.last_stdout_timestamp_ms
        record = {
            "timestamp_ms": ts,
            "model": "server_receiver",
            "type": event_type,
            "val": dict(val),
        }
        print(json.dumps(record), flush=True)
        self.last_stdout_timestamp_ms = ts

    @staticmethod
    def _is_well_formed_packet(msg: object) -> bool:
        if not isinstance(msg, dict):
            return False
        if "seq" not in msg or "bit" not in msg:
            return False
        seq = msg.get("seq")
        bit = msg.get("bit")
        if not isinstance(seq, int):
            return False
        if not isinstance(bit, int):
            return False
        if bit not in (0, 1):
            return False
        return True

    def _reschedule_from_pending(self) -> None:
        if not self.pending:
            self.passivate("IDLE")
            return
        now = float(get_current_time())
        next_completion = min(item["completion_time_ms"] for item in self.pending)
        self.hold_in("WAITING", max(0.0, next_completion - now))

    def deltext(self, e: float):
        now = float(get_current_time())

        for msg in self.input["upload_data_in"].values:
            if not self._is_well_formed_packet(msg):
                # Ignore malformed input (no ACK, no storage push, no stdout record required).
                continue

            pkt = {"seq": int(msg["seq"]), "bit": int(msg["bit"])}
            # Immediate stdout record at arrival time.
            self._emit_stdout(
                timestamp_ms=now,
                event_type="packet_received",
                val={"seq": pkt["seq"], "bit": pkt["bit"]},
            )

            self.pending.append(
                {
                    "arrival_time_ms": now,
                    "completion_time_ms": now + self.processing_delay_ms,
                    "seq": pkt["seq"],
                    "bit": pkt["bit"],
                }
            )

        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = float(get_current_time())

        # Determine due packets in completion-time order, then arrival order.
        due = [item for item in self.pending if item["completion_time_ms"] <= now]
        if not due:
            return

        # Stable ordering: completion_time then arrival_time; list order preserves arrival order for ties.
        due.sort(key=lambda x: (x["completion_time_ms"], x["arrival_time_ms"]))

        self._due_to_process = due
        self._acks_to_send = []
        self._storage_to_push = []

        for item in self._due_to_process:
            pkt_bit = int(item["bit"])
            if pkt_bit == self.expected_bit:
                decided_bit = pkt_bit
                self._acks_to_send.append({"bit": decided_bit})
                self._storage_to_push.append({"seq": int(item["seq"]), "bit": pkt_bit})
                # Flip expected bit only when accepted packet completes processing (now).
                self.expected_bit = 1 - self.expected_bit
            else:
                decided_bit = 1 - self.expected_bit
                self._acks_to_send.append({"bit": decided_bit})

            # Emit stdout record at the same simulation time as ACK emission.
            self._emit_stdout(
                timestamp_ms=now,
                event_type="ack_sent_to_sender",
                val={"bit": int(decided_bit)},
            )

        # Emit DEVS outputs (ACKs and storage pushes).
        for ack in self._acks_to_send:
            self.output["sender_ack_out"].add(dict(ack))
        for pkt in self._storage_to_push:
            self.output["storage_push_out"].add(dict(pkt))

    def deltint(self):
        if self.phase != "WAITING":
            self.passivate("IDLE")
            return

        now = float(get_current_time())

        # Remove processed items (those whose completion time has been reached).
        self.pending = [item for item in self.pending if item["completion_time_ms"] > now]

        # Clear prepared output batches.
        self._due_to_process = []
        self._acks_to_send = []
        self._storage_to_push = []

        self._reschedule_from_pending()

    def exit(self):
        pass