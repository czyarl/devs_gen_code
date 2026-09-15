import json
import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Facility(Atomic):
    """
    Autonomous periodic source that generates cargo pallets over a finite horizon.

    Outputs:
      - pallet_out (dict): {'pallet_id': int, 'generation_time': float, 'expiration_time': float}

    External IO:
      - stdout JSONL per pallet generation:
        {"time": float, "entity": "facility", "event": "pallet_generated",
         "payload": {"pallet_id": int, "expiration_time": float}}
    """

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

        # Configuration
        self.duration = float(duration)
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)

        # Ports
        self.add_out_port(Port(dict, "pallet_out"))

        # State
        self.next_pallet_id: int = 1
        self.next_generation_time: float = 0.0

    def initialize(self):
        self.next_pallet_id = 1
        self.next_generation_time = 0.0

        if self.duration <= 0.0:
            self.passivate("PASSIVE")
            return

        # Schedule first generation at t=0
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e: float):
        # No input ports; ignore external transitions.
        return None

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        t_gen = float(get_current_time())

        # Guard: never generate at or after duration
        if t_gen >= self.duration:
            return

        pallet_id = int(self.next_pallet_id)
        expiration_time = t_gen + self.pallet_expiration_time

        pallet_payload = {
            "pallet_id": pallet_id,
            "generation_time": t_gen,
            "expiration_time": expiration_time,
        }
        self.output["pallet_out"].add(pallet_payload)

        record = {
            "time": t_gen,
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
            self.passivate("PASSIVE")
            return

        t_gen = float(get_current_time())

        # If we reached/overran duration, terminate.
        if t_gen >= self.duration:
            self.passivate("PASSIVE")
            return

        # Advance ID after emitting at this internal event.
        self.next_pallet_id += 1

        # Compute next generation time.
        t_next = t_gen + self.pallet_interval
        self.next_generation_time = t_next

        # Ill-defined interval: prevent infinite zero-time loop.
        if self.pallet_interval <= 0.0:
            print(
                f"Warning: Facility pallet_interval={self.pallet_interval} is non-positive; "
                f"emitted at most one pallet at t=0 and now passivating.",
                file=sys.stderr,
                flush=True,
            )
            self.passivate("PASSIVE")
            return

        if t_next < self.duration:
            # Schedule next internal event after the interval.
            self.hold_in("GENERATE", self.pallet_interval)
        else:
            self.passivate("PASSIVE")

    def exit(self):
        # No end-of-simulation output required.
        pass