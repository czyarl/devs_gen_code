import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """
    ABP Receiver atomic model:
    - Fixed processing delay per delivered data packet.
    - One-slot waiting buffer while busy; overflow arrivals are dropped.
    - Logs JSONL KPI events to stdout (delay_start, packet_received).
    - Generates ACKs on completion (ack_out).
    """

    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent

        self.receiver_delay: float = float(receiver_delay)

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # State
        self.in_service: dict | None = None
        self.buffer_slot: dict | None = None

        # Output staging
        self._ack_to_send: dict | None = None

    def _now(self) -> float:
        return float(get_current_time())

    def _fmt_time(self, t: float) -> float:
        # Ensure float with at least 2 decimals when serialized.
        return float(f"{float(t):.2f}")

    def _write_stdout_event(self, event: str, payload: dict) -> None:
        record = {
            "time": self._fmt_time(self._now()),
            "entity": "receiver",
            "event": event,
            "payload": payload,
        }
        print(json.dumps(record), flush=True)

    def _diag(self, msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def _start_processing(self, pkt: dict) -> None:
        # Start processing immediately at current simulation time.
        self.in_service = dict(pkt)
        self._write_stdout_event(
            "delay_start",
            {"type": "processing", "duration": float(self.receiver_delay)},
        )
        self.hold_in("PROCESSING", float(self.receiver_delay))

    def initialize(self):
        self.in_service = None
        self.buffer_slot = None
        self._ack_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if already processing.
        if self.phase == "PROCESSING":
            self.continuef(e)

        for pkt in self.input["data_in"].values:
            # Port contract says dict with keys; invalid inputs are unspecified.
            if not isinstance(pkt, dict):
                self._diag("Receiver: ignoring non-dict packet on data_in")
                continue

            if self.in_service is None:
                # If idle, start processing immediately; do not reduce new delay by e.
                self._start_processing(pkt)
            elif self.buffer_slot is None:
                self.buffer_slot = dict(pkt)
            else:
                # Drop overflow silently (no stdout KPI, no ACK).
                pass

    def lambdaf(self):
        # ACK is produced only at processing completion instants.
        if self.phase == "OUTPUT_READY" and self._ack_to_send is not None:
            self.output["ack_out"].add(dict(self._ack_to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing completes now: log packet_received and prepare ACK.
            if self.in_service is not None:
                seq_num = self.in_service.get("seq_num")
                bit = self.in_service.get("bit")

                # KPI log (must not be corrupted by diagnostics)
                try:
                    self._write_stdout_event(
                        "packet_received",
                        {"seq_num": int(seq_num), "bit": int(bit)},
                    )
                except Exception:
                    # Outside contract; do not emit malformed KPI. Optional stderr diag.
                    self._diag("Receiver: invalid packet fields at completion; suppressing KPI/ACK")
                    self._ack_to_send = None
                    self.in_service = None
                    if self.buffer_slot is not None:
                        next_pkt = self.buffer_slot
                        self.buffer_slot = None
                        self._start_processing(next_pkt)
                    else:
                        self.passivate("IDLE")
                    return

                # Prepare ACK for lambdaf at same simulation time.
                try:
                    self._ack_to_send = {"bit": int(bit)}
                except Exception:
                    self._ack_to_send = None

                # Ensure ACK is emitted at the same time instant via zero-delay phase.
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # Should not happen; become idle.
                self.passivate("IDLE")

        elif self.phase == "OUTPUT_READY":
            # ACK has been emitted (or there was none). Advance service/buffer.
            self._ack_to_send = None
            self.in_service = None

            if self.buffer_slot is not None:
                next_pkt = self.buffer_slot
                self.buffer_slot = None
                # Start next processing immediately at the same time.
                self._start_processing(next_pkt)
            else:
                self.passivate("IDLE")

        else:
            self.passivate("IDLE")

    def exit(self):
        pass