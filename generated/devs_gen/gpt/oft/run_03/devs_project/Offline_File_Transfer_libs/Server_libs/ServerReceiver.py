import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ServerReceiver(Atomic):
    """
    Atomic DEVS model: ingress (upload) half of Server ABP termination.

    - Accepts at most one in-flight packet at a time; drops arrivals while busy
      (but still logs packet_received for every arrival).
    - Applies fixed processing delay per accepted packet.
    - After processing, sends ACK per ABP and forwards only in-order packets to storage.
    - Emits ONLY the required stdout JSONL observations for this model.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_ms: float):
        super().__init__(name)
        self.parent = parent
        self.processing_ms = float(processing_ms)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "upload_data_in"))
        self.add_out_port(Port(dict, "sender_ack_out"))
        self.add_out_port(Port(dict, "storage_push_out"))

        # State (locked contract)
        self.expected_bit: int = 0
        self.last_accepted_bit: int = 1
        self.busy: bool = False
        self.inflight_pkt: dict | None = None

        # Prepared outputs for lambdaf()
        self._ack_to_send: dict | None = None
        self._storage_to_push: dict | None = None
        self._ack_log_record: dict | None = None

    def initialize(self):
        self.expected_bit = 0
        self.last_accepted_bit = 1
        self.busy = False
        self.inflight_pkt = None

        self._ack_to_send = None
        self._storage_to_push = None
        self._ack_log_record = None

        self.passivate("IDLE")

    @staticmethod
    def _stdout_jsonl(record: dict) -> None:
        print(json.dumps(record), flush=True)

    @staticmethod
    def _is_valid_bit(bit_val) -> bool:
        return bit_val in (0, 1)

    def deltext(self, e: float):
        # Preserve remaining time if already processing.
        if self.phase == "PROCESSING":
            self.continuef(e)
        else:
            # Ensure we're in a passive/idle phase if not processing.
            # (No internal event should be scheduled here.)
            self.passivate("IDLE")

        # Handle all arrivals: always log packet_received immediately at arrival time.
        now = float(get_current_time())

        for pkt in self.input["upload_data_in"].values:
            # Log arrival observation (always)
            try:
                seq_val = pkt.get("seq")
                bit_val = pkt.get("bit")
            except AttributeError:
                # Non-dict payload; still log received value as-is where possible.
                seq_val = None
                bit_val = None

            self._stdout_jsonl(
                {
                    "timestamp_ms": now,
                    "model": "server_receiver",
                    "type": "packet_received",
                    "val": {"seq": seq_val, "bit": bit_val},
                }
            )

            # Accept into processing only if idle and not already busy.
            if not self.busy and self.phase != "PROCESSING":
                # Store packet as-is (dict expected by contract); best-effort copy.
                self.inflight_pkt = dict(pkt) if isinstance(pkt, dict) else {"seq": seq_val, "bit": bit_val}
                self.busy = True
                self.hold_in("PROCESSING", max(0.0, self.processing_ms))
            else:
                # Busy: drop packet (no ACK, no storage push).
                pass

    def lambdaf(self):
        # Only emit DEVS outputs here.
        if self.phase == "PROCESSING":
            if self._ack_to_send is not None:
                self.output["sender_ack_out"].add(dict(self._ack_to_send))
            if self._storage_to_push is not None:
                self.output["storage_push_out"].add(dict(self._storage_to_push))

    def deltint(self):
        # Internal event: processing completion. Prepare outputs and logs first, then
        # schedule a zero-time OUTPUT phase to emit them via lambdaf().
        if self.phase == "PROCESSING" and self.inflight_pkt is not None:
            now = float(get_current_time())

            pkt_bit = None
            if isinstance(self.inflight_pkt, dict):
                pkt_bit = self.inflight_pkt.get("bit")

            in_order = self._is_valid_bit(pkt_bit) and int(pkt_bit) == int(self.expected_bit)

            if in_order:
                ack_bit = int(pkt_bit)
                self._ack_to_send = {"bit": ack_bit}
                self._storage_to_push = dict(self.inflight_pkt)
                self.expected_bit = 1 - int(self.expected_bit)
                self.last_accepted_bit = 1 - int(self.expected_bit)
            else:
                ack_bit = 1 - int(self.expected_bit)
                self._ack_to_send = {"bit": ack_bit}
                self._storage_to_push = None
                # expected_bit unchanged; last_accepted_bit remains consistent
                self.last_accepted_bit = 1 - int(self.expected_bit)

            # Log ACK observation at completion time (same time as port emission)
            self._ack_log_record = {
                "timestamp_ms": now,
                "model": "server_receiver",
                "type": "ack_sent_to_sender",
                "val": {"bit": int(self._ack_to_send["bit"])},
            }

            # Clear processing state now (as required), but keep prepared outputs/logs
            # for the immediate OUTPUT phase.
            self.busy = False
            self.inflight_pkt = None

            self.hold_in("OUTPUT", 0.0)
            return

        if self.phase == "OUTPUT":
            # External IO side-effect aligned with the output event time.
            if self._ack_log_record is not None:
                self._stdout_jsonl(self._ack_log_record)

            # Clear prepared outputs/logs after emitting.
            self._ack_to_send = None
            self._storage_to_push = None
            self._ack_log_record = None

            self.passivate("IDLE")
            return

        # Fallback: passivate
        self.passivate("IDLE")

    def exit(self):
        # No required termination IO.
        pass