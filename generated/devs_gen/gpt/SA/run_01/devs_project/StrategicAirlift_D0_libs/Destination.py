"""Destination atomic model: passive sink that records successful pallet deliveries.

Responsibilities:
- Receive delivery completion messages on delivered_in.
- Compute latency = current_time - generation_time.
- Emit one compact JSONL event to stdout per valid delivery message.
- Never emit non-JSON content to stdout; warnings go to stderr.
"""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Destination(Atomic):
    """Passive atomic sink that logs pallet deliveries as JSONL to stdout."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "delivered_in"))

    def initialize(self):
        self.passivate("WAITING")

    @staticmethod
    def _is_valid_message(msg: object) -> bool:
        if not isinstance(msg, dict):
            return False
        if "aircraft_id" not in msg or "pallet_id" not in msg or "generation_time" not in msg:
            return False
        if not isinstance(msg["aircraft_id"], int):
            return False
        if not isinstance(msg["pallet_id"], int):
            return False
        if not isinstance(msg["generation_time"], (int, float)):
            return False
        return True

    def deltext(self, e: float):
        t_now = float(get_current_time())

        for msg in self.input["delivered_in"].values:
            if not self._is_valid_message(msg):
                print(
                    f"[Destination] Ignoring malformed delivery message: {msg!r}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            aircraft_id = int(msg["aircraft_id"])
            pallet_id = int(msg["pallet_id"])
            t_gen = float(msg["generation_time"])
            latency = t_now - t_gen

            if t_gen > t_now:
                print(
                    f"[Destination] Warning: generation_time ({t_gen}) > delivery_time ({t_now}); "
                    f"negative latency will be emitted for pallet_id={pallet_id}, aircraft_id={aircraft_id}.",
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

        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # No end-of-run output.
        pass