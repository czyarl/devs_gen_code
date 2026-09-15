"""Atomic DEVS model: Destination (terminal sink for delivery-completion messages).

Writes one JSONL stdout record per valid delivered pallet message received.
"""

import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Destination(Atomic):
    """
    Purpose: act as a terminal sink for delivery-completion messages from Aircraft
    and emit one final JSONL event per delivered pallet.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Input ports
        self.add_in_port(Port(dict, "delivery_in"))

        # Optional debug counters (must not affect stdout schema)
        self.total_delivered: int = 0
        self.total_malformed: int = 0

    def initialize(self):
        # Passive on startup; no autonomous internal events.
        self.passivate("WAITING")

    def deltext(self, e: float):
        t_now = float(get_current_time())

        for msg in self.input["delivery_in"].values:
            parsed = self._parse_delivery_message(msg)
            if parsed is None:
                continue

            aircraft_id, pallet_id, generation_time = parsed
            latency = t_now - generation_time

            if generation_time > t_now:
                print(
                    (
                        "WARNING Destination: generation_time > current_time "
                        f"(generation_time={generation_time}, t_now={t_now}); "
                        f"latency will be negative ({latency})."
                    ),
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
            print(json.dumps(record), flush=True)
            self.total_delivered += 1

        # Remain passive between external inputs.
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output messages (no downstream consumers).
        pass

    def deltint(self):
        # No internal events are scheduled; keep passive.
        self.passivate("WAITING")

    def exit(self):
        # No end-of-run action required.
        pass

    def _parse_delivery_message(self, msg: object) -> tuple[int, int, float] | None:
        if not isinstance(msg, dict):
            self.total_malformed += 1
            print(
                f"WARNING Destination: malformed delivery message (not a dict): {msg!r}",
                file=sys.stderr,
                flush=True,
            )
            return None

        missing = [k for k in ("aircraft_id", "pallet_id", "generation_time") if k not in msg]
        if missing:
            self.total_malformed += 1
            print(
                f"WARNING Destination: malformed delivery message (missing keys {missing}): {msg!r}",
                file=sys.stderr,
                flush=True,
            )
            return None

        try:
            aircraft_id = int(msg["aircraft_id"])
            pallet_id = int(msg["pallet_id"])
            generation_time = float(msg["generation_time"])
        except (TypeError, ValueError) as exc:
            self.total_malformed += 1
            print(
                f"WARNING Destination: malformed delivery message (bad types): {msg!r}; error={exc}",
                file=sys.stderr,
                flush=True,
            )
            return None

        return aircraft_id, pallet_id, generation_time