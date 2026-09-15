"""Destination atomic DEVS model: terminal sink for completed deliveries.

Receives delivery completion dicts from Aircraft and writes one JSONL event per
delivered pallet to stdout with computed end-to-end latency.

Stdout: JSONL only (no diagnostics).
Stderr: optional warnings only.
"""

import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Destination(Atomic):
    """Terminal sink that logs pallet delivery events as JSONL to stdout."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "delivery_in"))

        # Optional counters (no business state required).
        self.total_received: int = 0
        self.total_logged: int = 0
        self.total_malformed: int = 0
        self.total_negative_latency: int = 0

    def initialize(self):
        # Passive waiting state; no internal events scheduled.
        self.passivate("WAITING")

    @staticmethod
    def _is_number(x) -> bool:
        # Accept int/float; reject bool (since bool is a subclass of int).
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    def _validate_message(self, msg) -> tuple[int, int, float] | None:
        if not isinstance(msg, dict):
            print(
                f"[Destination] Warning: ignoring non-dict delivery message: {type(msg).__name__}",
                file=sys.stderr,
                flush=True,
            )
            return None

        missing = [k for k in ("aircraft_id", "pallet_id", "generation_time") if k not in msg]
        if missing:
            print(
                f"[Destination] Warning: ignoring malformed delivery message (missing keys {missing}): {msg}",
                file=sys.stderr,
                flush=True,
            )
            return None

        aircraft_id = msg.get("aircraft_id")
        pallet_id = msg.get("pallet_id")
        generation_time = msg.get("generation_time")

        if not isinstance(aircraft_id, int) or isinstance(aircraft_id, bool):
            print(
                f"[Destination] Warning: ignoring malformed delivery message (aircraft_id not int): {msg}",
                file=sys.stderr,
                flush=True,
            )
            return None
        if not isinstance(pallet_id, int) or isinstance(pallet_id, bool):
            print(
                f"[Destination] Warning: ignoring malformed delivery message (pallet_id not int): {msg}",
                file=sys.stderr,
                flush=True,
            )
            return None
        if not self._is_number(generation_time):
            print(
                f"[Destination] Warning: ignoring malformed delivery message (generation_time not numeric): {msg}",
                file=sys.stderr,
                flush=True,
            )
            return None

        return aircraft_id, pallet_id, float(generation_time)

    def deltext(self, e: float):
        # No internal events are scheduled; remain passive.
        _ = e

        t_now = float(get_current_time())

        for msg in self.input["delivery_in"].values:
            self.total_received += 1

            validated = self._validate_message(msg)
            if validated is None:
                self.total_malformed += 1
                continue

            aircraft_id, pallet_id, generation_time = validated
            latency = t_now - generation_time

            if latency < 0.0:
                self.total_negative_latency += 1
                print(
                    f"[Destination] Warning: negative latency computed (t_now={t_now}, generation_time={generation_time}, latency={latency}) "
                    f"for aircraft_id={aircraft_id}, pallet_id={pallet_id}",
                    file=sys.stderr,
                    flush=True,
                )

            record = {
                "time": t_now,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": pallet_id,
                    "aircraft_id": aircraft_id,
                    "latency": latency,
                },
            }

            # External IO: stdout JSONL event record (and nothing else).
            print(json.dumps(record), flush=True)
            self.total_logged += 1

        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports.
        pass

    def deltint(self):
        # No internal events; remain passive.
        self.passivate("WAITING")

    def exit(self):
        # No end-of-simulation flush needed beyond per-event printing.
        pass