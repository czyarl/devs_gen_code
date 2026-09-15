import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Facility(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        duration: float,
        pallet_interval: float,
        pallet_expiration_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.duration = float(duration)
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)

        self.add_out_port(Port(dict, "pallet_out"))

        self._warned_bad_interval: bool = False
        self._next_pallet_id: int = 1
        self._payload_to_send: dict | None = None

    def initialize(self):
        self._next_pallet_id = 1
        self._payload_to_send = None

        # Edge cases: invalid interval must not cause infinite/negative-time events.
        if self.pallet_interval <= 0:
            if not self._warned_bad_interval:
                print(
                    f"WARNING: Facility pallet_interval <= 0 ({self.pallet_interval}); generating no pallets.",
                    file=sys.stderr,
                    flush=True,
                )
                self._warned_bad_interval = True
            self.passivate("passive")
            return

        # If duration <= 0, generate nothing.
        if self.duration <= 0:
            self.passivate("passive")
            return

        # Schedule first generation at absolute simulation time t=0.
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e: float):
        # No input ports; never reacts to external DEVS messages.
        return None

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        t = float(get_current_time())

        pallet_id = int(self._next_pallet_id)
        expiration_time = float(t + self.pallet_expiration_time)

        pallet_payload = {
            "pallet_id": pallet_id,
            "generation_time": float(t),
            "expiration_time": expiration_time,
        }
        self._payload_to_send = pallet_payload

        # DEVS output to LoadingQueue.
        self.output["pallet_out"].add(pallet_payload)

        # External IO: stdout JSONL event record (and nothing else).
        record = {
            "time": float(t),
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": pallet_id,
                "expiration_time": expiration_time,
            },
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate("passive")
            return

        # Advance ID after emitting.
        self._next_pallet_id += 1
        self._payload_to_send = None

        # Determine next generation time based on the current absolute time.
        t = float(get_current_time())
        t_next = t + self.pallet_interval

        if t_next < self.duration:
            self.hold_in("GENERATE", self.pallet_interval)
        else:
            self.passivate("passive")

    def exit(self):
        pass