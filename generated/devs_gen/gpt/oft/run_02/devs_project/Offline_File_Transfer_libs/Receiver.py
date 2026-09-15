import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_ms: float):
        super().__init__(name)
        self.parent = parent
        self.processing_ms = float(processing_ms)

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # State required by contract
        self.busy: bool = False
        self.inflight: dict | None = None
        self.remaining_processing_ms: float = float("inf")

    def initialize(self):
        self.busy = False
        self.inflight = None
        self.remaining_processing_ms = float("inf")
        self.passivate("IDLE")

    @staticmethod
    def _is_valid_packet(packet) -> bool:
        if not isinstance(packet, dict):
            return False
        if "seq" not in packet or "bit" not in packet:
            return False
        if not isinstance(packet["seq"], int):
            return False
        bit = packet["bit"]
        if not isinstance(bit, int):
            return False
        if bit not in (0, 1):
            return False
        return True

    @staticmethod
    def _stderr(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    @staticmethod
    def _stdout_event(event_type: str, val: dict) -> None:
        record = {
            "timestamp_ms": float(get_current_time()),
            "model": "receiver",
            "type": event_type,
            "val": val,
        }
        print(json.dumps(record), flush=True)

    def deltext(self, e: float):
        # If already busy, preserve remaining time and drop any arrivals.
        if self.busy:
            self.continuef(e)
            for pkt in self.input["data_in"].values:
                if not self._is_valid_packet(pkt):
                    self._stderr(f"Receiver: dropped malformed packet while busy: {pkt!r}")
                else:
                    self._stderr(f"Receiver: dropped packet while busy: {pkt!r}")
            self.remaining_processing_ms = max(0.0, self.ta())
            return

        # Idle: accept at most one valid packet; drop others.
        accepted = False
        for pkt in self.input["data_in"].values:
            if not accepted:
                if not self._is_valid_packet(pkt):
                    self._stderr(f"Receiver: ignored malformed packet: {pkt!r}")
                    continue

                self.inflight = {"seq": int(pkt["seq"]), "bit": int(pkt["bit"])}
                self.busy = True

                # Log processing start immediately at acceptance time.
                self._stdout_event(
                    "processing_started",
                    {"seq": self.inflight["seq"], "duration": 10000},
                )

                self.hold_in("PROCESSING", self.processing_ms)
                self.remaining_processing_ms = max(0.0, self.ta())
                accepted = True
            else:
                if not self._is_valid_packet(pkt):
                    self._stderr(f"Receiver: dropped malformed packet while busy (same bag): {pkt!r}")
                else:
                    self._stderr(f"Receiver: dropped packet while busy (same bag): {pkt!r}")

        if not accepted:
            self.passivate("IDLE")
            self.remaining_processing_ms = float("inf")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.busy and self.inflight is not None:
            # Emit ACK at completion time.
            ack = {"bit": int(self.inflight["bit"])}
            self.output["ack_out"].add(ack)

            # Log ack_sent at the same simulation time as ACK emission.
            self._stdout_event("ack_sent", {"bit": ack["bit"]})

    def deltint(self):
        # Processing completed; go idle.
        self.busy = False
        self.inflight = None
        self.remaining_processing_ms = float("inf")
        self.passivate("IDLE")

    def exit(self):
        pass