import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """
    Atomic DEVS Receiver.

    Consumes data packets from the forward subnet, applies a fixed processing delay,
    and upon completion emits:
      - one ACK on ack_out: {'ack_bit': bit}
      - stdout JSONL event records (delay_start, packet_received)
    """

    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent

        # Parameters
        self.receiver_delay = float(receiver_delay)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "pkt_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # State
        self.processing_pkt: dict | None = None
        self.buffered_pkt: dict | None = None

        # Output staging
        self._ack_to_send: dict | None = None

    def _now(self) -> float:
        return float(get_current_time())

    def _fmt_time(self, t: float) -> float:
        # Ensure at least 2 decimal places when serialized by json.dumps.
        # Using round(., 2) guarantees representation with >=2 decimals in typical dumps,
        # but JSON may still omit trailing zeros. To strictly enforce "at least 2 decimal places",
        # we keep the float value and rely on consumer tolerance; requirements specify float.
        return float(f"{t:.2f}")

    def _write_stdout_event(self, event: str, payload: dict) -> None:
        record = {
            "time": self._fmt_time(self._now()),
            "entity": "receiver",
            "event": event,
            "payload": payload,
        }
        print(json.dumps(record), flush=True)

    def _start_processing_now(self, pkt: dict) -> None:
        # Start processing immediately at current simulation time.
        self.processing_pkt = dict(pkt)
        self._write_stdout_event("delay_start", {
            "type": "processing",
            "duration": float(self.receiver_delay),
        })
        self.hold_in("PROCESSING", float(self.receiver_delay))

    def initialize(self):
        # Start idle at time 0.0; no outputs and no stdout records.
        self.processing_pkt = None
        self.buffered_pkt = None
        self._ack_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if already active.
        if self.phase in ("PROCESSING", "OUTPUT_ACK"):
            self.continuef(e)

        # Process arrivals in bag order without advancing time.
        for pkt in self.input["pkt_in"].values:
            if self.processing_pkt is None:
                # Idle: take first arriving packet and begin processing immediately.
                self._start_processing_now(pkt)
            else:
                # Busy: buffer one, drop rest silently.
                if self.buffered_pkt is None:
                    self.buffered_pkt = dict(pkt)
                else:
                    # Drop silently.
                    pass

    def lambdaf(self):
        # Only place to emit DEVS outputs.
        if self.phase == "OUTPUT_ACK" and self._ack_to_send is not None:
            self.output["ack_out"].add(dict(self._ack_to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing completion at current time: emit packet_received stdout and stage ACK.
            if self.processing_pkt is None:
                # Defensive: should not happen; go idle.
                self.passivate("IDLE")
                return

            self._write_stdout_event("packet_received", {
                "seq_num": int(self.processing_pkt["seq_num"]),
                "bit": int(self.processing_pkt["bit"]),
            })
            self._ack_to_send = {"ack_bit": int(self.processing_pkt["bit"])}

            # Output ACK at the same simulation time via zero-delay phase.
            self.hold_in("OUTPUT_ACK", 0.0)

        elif self.phase == "OUTPUT_ACK":
            # ACK has been emitted; clear and move to next work item.
            self._ack_to_send = None

            if self.buffered_pkt is not None:
                next_pkt = self.buffered_pkt
                self.buffered_pkt = None
                # Start processing immediately at the same time.
                self._start_processing_now(next_pkt)
            else:
                self.processing_pkt = None
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def deltcon(self):
        # Confluence rule required by contract:
        # behave as if internal completion happens first, then handle arrivals at same time.
        self.deltint()
        self.deltext(0.0)

    def exit(self):
        pass