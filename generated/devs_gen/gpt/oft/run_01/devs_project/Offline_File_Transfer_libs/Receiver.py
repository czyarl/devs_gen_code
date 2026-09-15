import json
from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_delay_ms: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay_ms = float(processing_delay_ms)

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # State
        self.busy: bool = False
        self.inflight_packet: dict | None = None
        self.remaining_ms: float = 0.0

        # Prepared output
        self._ack_payload: dict | None = None

    def initialize(self):
        self.busy = False
        self.inflight_packet = None
        self.remaining_ms = 0.0
        self._ack_payload = None
        self.passivate("IDLE")

    def _emit_stdout_event(self, event_type: str, val: dict):
        record = {
            "timestamp_ms": float(get_current_time()),
            "model": "receiver",
            "type": event_type,
            "val": val,
        }
        print(json.dumps(record), flush=True)

    @staticmethod
    def _is_valid_packet(packet) -> bool:
        if not isinstance(packet, dict):
            return False
        if "seq" not in packet or "bit" not in packet:
            return False
        if not isinstance(packet["seq"], int):
            return False
        bit = packet["bit"]
        if isinstance(bit, bool):
            return False
        if not isinstance(bit, int):
            return False
        return True

    def deltext(self, e: float):
        # If already busy, preserve remaining time and drop all arrivals silently.
        if self.phase == "PROCESSING":
            self.continuef(e)
            self.remaining_ms = max(0.0, float(self.ta()))
            return

        # Idle: accept at most one valid packet (first in bag order), drop the rest.
        accepted = False
        for packet in self.input["data_in"].values:
            if accepted:
                continue
            if not self._is_valid_packet(packet):
                continue

            # Accept
            self.inflight_packet = {"seq": int(packet["seq"]), "bit": int(packet["bit"])}
            self.busy = True

            # Emit processing_started at acceptance time
            self._emit_stdout_event(
                "processing_started",
                {"seq": self.inflight_packet["seq"], "duration": 10000},
            )

            delay = max(0.0, float(self.processing_delay_ms))
            self.remaining_ms = delay
            self.hold_in("PROCESSING", delay)
            accepted = True

        if not accepted:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.inflight_packet is not None:
            bit = self.inflight_packet["bit"]
            self._ack_payload = {"bit": bit}
            self.output["ack_out"].add(dict(self._ack_payload))
            self._emit_stdout_event("ack_sent", {"bit": bit})

    def deltint(self):
        if self.phase == "PROCESSING":
            self.busy = False
            self.inflight_packet = None
            self.remaining_ms = 0.0
            self._ack_payload = None
            self.passivate("IDLE")
            return

        self.passivate("IDLE")

    def exit(self):
        pass