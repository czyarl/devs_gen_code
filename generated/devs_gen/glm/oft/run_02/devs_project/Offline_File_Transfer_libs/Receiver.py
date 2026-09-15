"""Atomic DEVS model: Receiver."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Implements the Downloader logic for the second ABP loop.

    Initializes in an IDLE state. Upon receiving a data packet on input port
    `data_in` (format `{'seq': int, 'bit': int}`) while IDLE, it transitions to
    a BUSY state, stores the packet, and immediately writes a
    `processing_started` JSONL record to stdout. It schedules an internal
    transition after the `processing_delay` (10000.0 ms). Any external inputs
    received while BUSY are ignored. When the internal transition fires, it
    extracts the `bit` from the stored packet, writes an `ack_sent` JSONL record
    to stdout, and sends the bit value via the output port `ack_out`. It then
    transitions back to IDLE.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay

        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(int, "ack_out"))

        self.stored_packet: dict | None = None

    def initialize(self):
        self.stored_packet = None
        self.passivate("IDLE")

    def deltext(self, e):
        # If BUSY, ignore external inputs (stop-and-wait)
        if self.phase == "BUSY":
            self.hold_in("BUSY", max(0.0, self.ta() - e))
            return

        # If IDLE, process input
        if self.phase == "IDLE":
            for packet in self.input["data_in"].values:
                # Store the packet
                self.stored_packet = packet
                
                # Write processing_started record
                now = get_current_time()
                record = {
                    "timestamp_ms": now,
                    "model": "receiver",
                    "type": "processing_started",
                    "val": {
                        "seq": packet["seq"],
                        "duration": 10000
                    }
                }
                print(json.dumps(record), flush=True)
                
                # Transition to BUSY and schedule internal transition
                self.hold_in("BUSY", self.processing_delay)
                # Only process the first packet if multiple arrive simultaneously
                break

    def lambdaf(self):
        if self.phase == "BUSY" and self.stored_packet is not None:
            bit = self.stored_packet["bit"]
            self.output["ack_out"].add(bit)

    def deltint(self):
        if self.phase == "BUSY":
            # Write ack_sent record
            now = get_current_time()
            bit = self.stored_packet["bit"]
            record = {
                "timestamp_ms": now,
                "model": "receiver",
                "type": "ack_sent",
                "val": {
                    "bit": bit
                }
            }
            print(json.dumps(record), flush=True)

            # Clear state and return to IDLE
            self.stored_packet = None
            self.passivate("IDLE")

    def exit(self):
        pass