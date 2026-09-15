import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_ms: float):
        super().__init__(name)
        self.parent = parent

        # Fixed configuration
        self.processing_ms = float(processing_ms)

        # Ports
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # State (must be remembered)
        self.busy: bool = False
        self.inflight_packet: dict | None = None
        self.pending_ack: dict | None = None

    def initialize(self):
        # Startup behavior: idle, no inflight, no internal events, no stdout.
        self.busy = False
        self.inflight_packet = None
        self.pending_ack = None
        self.passivate("IDLE")

    @staticmethod
    def _is_valid_packet(packet) -> bool:
        if not isinstance(packet, dict):
            return False
        if "seq" not in packet or "bit" not in packet:
            return False
        if not isinstance(packet["seq"], int):
            return False
        if not isinstance(packet["bit"], int):
            return False
        if packet["bit"] not in (0, 1):
            return False
        return True

    @staticmethod
    def _stderr(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    @staticmethod
    def _stdout_jsonl(record: dict) -> None:
        # Must never write non-JSONL text to stdout.
        print(json.dumps(record), flush=True)

    def deltext(self, e: float):
        # If already busy, ignore/drop all arriving packets.
        if self.busy:
            # Preserve remaining time to completion (no rescheduling).
            self.continuef(e)
            return

        # Idle: select exactly one packet to start processing, in bag iteration order.
        for packet in self.input["data_in"].values:
            if not self._is_valid_packet(packet):
                # Ignore malformed payloads; optional stderr warning.
                self._stderr(f"[receiver] Ignoring malformed packet on data_in: {packet!r}")
                continue

            t = float(get_current_time())
            self.inflight_packet = {"seq": int(packet["seq"]), "bit": int(packet["bit"])}

            # Immediately log processing start to stdout at time t.
            self._stdout_jsonl(
                {
                    "timestamp_ms": t,
                    "model": "receiver",
                    "type": "processing_started",
                    "val": {"seq": self.inflight_packet["seq"], "duration": self.processing_ms},
                }
            )

            # Prepare ACK to emit at completion.
            self.pending_ack = {"bit": self.inflight_packet["bit"]}
            self.busy = True

            # Schedule completion after processing_ms.
            self.hold_in("PROCESSING", max(0.0, self.processing_ms))
            return

        # No valid packet found; remain idle.
        self.passivate("IDLE")

    def lambdaf(self):
        # When completion event fires, emit ACK and log ack_sent at same simulation time.
        if self.phase == "PROCESSING" and self.busy and self.pending_ack is not None:
            self.output["ack_out"].add(dict(self.pending_ack))

            t_done = float(get_current_time())
            self._stdout_jsonl(
                {
                    "timestamp_ms": t_done,
                    "model": "receiver",
                    "type": "ack_sent",
                    "val": {"bit": int(self.pending_ack["bit"])},
                }
            )

    def deltint(self):
        # Completion: clear state and become idle.
        if self.phase == "PROCESSING":
            self.inflight_packet = None
            self.pending_ack = None
            self.busy = False
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        # No special end-of-simulation action.
        pass