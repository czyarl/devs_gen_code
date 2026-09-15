import json
import math
import random
from datetime import timedelta

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ClientGenerator(Atomic):
    """
    Autonomous DEVS source that generates an unbounded sequence of clients.

    - First client at t=0.0 with client_id=1.
    - Subsequent inter-arrival intervals follow bounded-normal selection.
    - Emits one DEVS message on client_out and writes one JSONL stdout record
      per generated client, both at the same simulation time.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        client_mean: float,
        client_stddev: float,
        seed: int,
    ):
        super().__init__(name)
        self.parent = parent

        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)
        self.seed = seed

        self.add_out_port(Port(dict, "client_out"))

        # State
        self.next_client_id: int = 1
        self.next_t: float = 0.0
        self.rng: random.Random = random.Random()

    def initialize(self):
        self.next_client_id = 1
        self.next_t = 0.0
        self.rng = random.Random(self.seed) if self.seed is not None else random.Random()
        # Schedule first generation at t=0.0
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e: float):
        # No input ports; no external messages affect behavior.
        return None

    @staticmethod
    def _format_time_str(t: float) -> str:
        if not math.isfinite(t):
            t = 0.0
        if t < 0:
            t = 0.0
        total_ms = int(round(t * 1000.0))
        td = timedelta(milliseconds=total_ms)
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        millis = total_ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{millis:03d}"

    def _sample_interval(self) -> float:
        upper = self.client_mean + 5.0 * self.client_stddev
        if upper <= 0.0:
            return 0.0

        if self.client_stddev <= 0.0:
            interval = max(0.0, self.client_mean)
            return min(interval, upper)

        draw = self.rng.normalvariate(self.client_mean, self.client_stddev)
        if draw < 0.0:
            return 0.0
        if draw > upper:
            return upper
        return float(draw)

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        t = float(get_current_time())
        payload = {"client_id": int(self.next_client_id), "arrival_time": t}

        # DEVS output
        self.output["client_out"].add(dict(payload))

        # Stdout JSONL record (exact schema)
        record = {
            "time": t,
            "time_str": self._format_time_str(t),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": dict(payload),
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate()
            return

        t = float(get_current_time())

        # Advance client id
        self.next_client_id += 1

        # Schedule next generation time (nondecreasing)
        interval = self._sample_interval()
        self.next_t = t + float(interval)

        sigma = max(0.0, self.next_t - t)
        self.hold_in("GENERATE", sigma)

    def exit(self):
        # No final external IO required.
        pass