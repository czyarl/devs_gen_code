import sys
import json

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

        # State (initialized in initialize())
        self.next_pallet_id: int = 1
        self.next_generation_time: float = 0.0

    def initialize(self):
        self.next_pallet_id = 1
        self.next_generation_time = 0.0

        # Schedule first generation at absolute t=0.0
        # Generation occurs only when generation_time < duration.
        if self.duration <= 0.0:
            self.passivate("passive")
            return

        self.hold_in("GENERATE", 0.0)

    def deltext(self, e: float):
        # No input ports; ignore all external stimuli.
        return None

    def _build_pallet_payload(self, t_gen: float) -> dict:
        return {
            "pallet_id": int(self.next_pallet_id),
            "generation_time": float(t_gen),
            "expiration_time": float(t_gen + self.pallet_expiration_time),
        }

    def _emit_stdout_event(self, t_gen: float, pallet_id: int, expiration_time: float) -> None:
        record = {
            "time": float(t_gen),
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": int(pallet_id),
                "expiration_time": float(expiration_time),
            },
        }
        print(json.dumps(record), flush=True)

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        # Use the actual current absolute simulation time for emission/logging.
        t_now = float(get_current_time())

        # Guard: never generate at or beyond duration (including exactly duration).
        if not (t_now < self.duration):
            return

        pallet = self._build_pallet_payload(t_now)

        # 1) Emit internal pallet payload to LoadingQueue via DEVS port.
        self.output["pallet_out"].add(pallet)

        # 2) Emit exactly one JSONL stdout record.
        self._emit_stdout_event(
            t_gen=t_now,
            pallet_id=pallet["pallet_id"],
            expiration_time=pallet["expiration_time"],
        )

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate("passive")
            return

        # The pallet (if any) was emitted in lambdaf() immediately before this.
        t_gen = float(get_current_time())

        # If we were scheduled but at/after duration, stop.
        if not (t_gen < self.duration):
            self.passivate("passive")
            return

        # Advance ID for the next potential generation.
        self.next_pallet_id += 1

        # Compute next scheduled generation time.
        t_next = t_gen + self.pallet_interval
        self.next_generation_time = float(t_next)

        # Edge case: ill-defined interval -> emit at most one pallet at t=0.0 then passive.
        if self.pallet_interval <= 0.0:
            if self.duration > 0.0:
                print(
                    "Warning: pallet_interval <= 0.0; emitted at most one pallet at t=0.0 then passivating.",
                    file=sys.stderr,
                    flush=True,
                )
            self.passivate("passive")
            return

        # Termination: do not schedule if next time would be >= duration (including equal).
        if not (t_next < self.duration):
            self.passivate("passive")
            return

        # Schedule next generation with a delay relative to now.
        sigma = max(0.0, float(t_next - t_gen))
        self.hold_in("GENERATE", sigma)

    def exit(self):
        pass