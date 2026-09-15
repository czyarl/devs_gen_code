import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """
    Atomic DEVS Receiver.

    Consumes delivered data packets on pkt_in, applies a fixed processing delay,
    emits required JSONL KPI records to stdout, and outputs an ACK on ack_out
    upon processing completion. Maintains a one-slot waiting buffer while busy.
    """

    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent

        self.receiver_delay = float(receiver_delay)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "pkt_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # State
        self.busy: bool = False
        self.in_service: dict | None = None
        self.buffer_slot: dict | None = None

        # Output staging
        self._ack_to_send: dict | None = None

    # ---------- External IO helpers ----------
    def _write_stdout_event(self, event: str, payload: dict) -> None:
        # Keep at least 2 decimals in time formatting responsibility:
        # ensure float with >=2 decimals by rounding to 2 decimals.
        t = float(get_current_time())
        record = {
            "time": float(f"{t:.2f}"),
            "entity": "receiver",
            "event": event,
            "payload": payload,
        }
        print(json.dumps(record), flush=True)

    def _diag_stderr(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    # ---------- Validation ----------
    @staticmethod
    def _is_valid_packet(msg: object) -> bool:
        if not isinstance(msg, dict):
            return False
        if "seq_num" not in msg or "bit" not in msg:
            return False
        seq = msg.get("seq_num")
        bit = msg.get("bit")
        if not isinstance(seq, int):
            return False
        if not isinstance(bit, int) or bit not in (0, 1):
            return False
        return True

    # ---------- Core behavior helpers ----------
    def _start_processing(self, pkt: dict) -> None:
        # Start processing immediately at current simulation time.
        self.busy = True
        self.in_service = {"seq_num": int(pkt["seq_num"]), "bit": int(pkt["bit"])}

        # Emit delay_start at the moment processing begins (not deferred).
        self._write_stdout_event(
            "delay_start",
            {"type": "processing", "duration": float(self.receiver_delay)},
        )

        # Schedule completion after receiver_delay (may be 0.0).
        self.hold_in("PROCESSING", float(self.receiver_delay))

    # ---------- DEVS lifecycle ----------
    def initialize(self):
        self.busy = False
        self.in_service = None
        self.buffer_slot = None
        self._ack_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if already active in PROCESSING.
        if self.phase == "PROCESSING":
            self.continuef(e)

        for msg in self.input["pkt_in"].values:
            if not self._is_valid_packet(msg):
                # Ignore invalid messages; no stdout KPI records.
                # Optional diagnostics to stderr only.
                # self._diag_stderr(f"[Receiver] Ignored invalid pkt_in message: {msg!r}")
                continue

            pkt = {"seq_num": int(msg["seq_num"]), "bit": int(msg["bit"])}

            if not self.busy:
                # Idle: start processing immediately (do not reduce new delay by e).
                self._start_processing(pkt)
            else:
                # Busy: one-slot buffer, else drop.
                if self.buffer_slot is None:
                    self.buffer_slot = pkt
                else:
                    # Drop silently w.r.t stdout.
                    # self._diag_stderr(f"[Receiver] Dropped packet due to full buffer: {pkt!r}")
                    pass

    def lambdaf(self):
        # Only place to emit DEVS output.
        if self.phase == "OUTPUT_READY" and self._ack_to_send is not None:
            self.output["ack_out"].add(dict(self._ack_to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing completed for in_service.
            pkt = self.in_service
            if pkt is None:
                # Defensive: should not happen; go idle.
                self.busy = False
                self.passivate("IDLE")
                return

            # Ordering: for the completed packet, packet_received occurs at completion time.
            self._write_stdout_event(
                "packet_received",
                {"seq_num": int(pkt["seq_num"]), "bit": int(pkt["bit"])},
            )

            # Prepare ACK output; emitted immediately via zero-delay OUTPUT_READY.
            self._ack_to_send = {"ack_bit": int(pkt["bit"])}

            # Schedule immediate output.
            self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # ACK has been emitted; clear staged output and advance.
            self._ack_to_send = None

            # After completion, immediately start next buffered packet if any.
            if self.buffer_slot is not None:
                next_pkt = self.buffer_slot
                self.buffer_slot = None
                # Start next processing at the same simulation time.
                # Ordering guarantee: packet_received already emitted in PROCESSING phase,
                # delay_start for next packet emitted now (same time, after).
                self._start_processing(next_pkt)
            else:
                # No waiting packet: go idle.
                self.busy = False
                self.in_service = None
                self.passivate("IDLE")
        else:
            # Any other phase: remain passive.
            self.passivate("IDLE")

    def exit(self):
        pass