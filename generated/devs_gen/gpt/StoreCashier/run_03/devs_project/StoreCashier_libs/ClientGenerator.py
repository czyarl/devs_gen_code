import json
import random
from dataclasses import dataclass

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


def _format_time_hhmmss_mmm(t_seconds: float) -> str:
    # Format as HH:MM:SS:mmm, with milliseconds derived from the same float.
    if t_seconds < 0:
        t_seconds = 0.0
    total_ms = int(round(t_seconds * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_min = total_s // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def _derive_model_seed(seed: int | None, model_name: str) -> int | None:
    if seed is None:
        return None
    # Deterministic, model-local derivation so this RNG stream is independent
    # from other models that may also use the same base seed.
    mixed = (seed ^ 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
    for ch in model_name.encode("utf-8"):
        mixed = (mixed ^ ch) * 1099511628211 & ((1 << 64) - 1)
    return mixed


def _clamp_interval(candidate: float, client_mean: float, client_stddev: float) -> float:
    upper = client_mean + 5.0 * client_stddev
    if upper < 0.0:
        upper = 0.0
    if candidate < 0.0:
        return 0.0
    if candidate > upper:
        return upper
    return candidate


@dataclass
class _PreparedEmission:
    client_id: int
    arrival_time: float


class ClientGenerator(Atomic):
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

        self.next_client_id: int = 1
        self.next_generation_time: float = 0.0
        self.rng: random.Random = random.Random()
        self._prepared: _PreparedEmission | None = None

    def initialize(self):
        self.next_client_id = 1
        self.next_generation_time = 0.0

        derived_seed = _derive_model_seed(self.seed, self.name)
        self.rng = random.Random(derived_seed)

        # Schedule first generation at t=0.0 (output occurs in lambdaf()).
        self._prepared = None
        self.hold_in("GENERATE", 0.0)

    def deltext(self, e: float):
        # No input ports by contract.
        return None

    def lambdaf(self):
        if self.phase != "GENERATE":
            return

        now = float(get_current_time())

        payload = {"client_id": int(self.next_client_id), "arrival_time": float(now)}
        self._prepared = _PreparedEmission(client_id=self.next_client_id, arrival_time=now)

        # External IO: JSONL to stdout (exactly one line per generated client).
        record = {
            "time": float(now),
            "time_str": _format_time_hhmmss_mmm(now),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": dict(payload),
        }
        print(json.dumps(record), flush=True)

        # DEVS output.
        self.output["client_out"].add(payload)

    def deltint(self):
        if self.phase != "GENERATE":
            self.passivate()
            return

        # Advance client id after emitting.
        self.next_client_id += 1

        # Sample next inter-arrival interval and clamp to required bounds.
        if self.client_stddev == 0.0:
            candidate = self.client_mean
        else:
            candidate = self.rng.gauss(self.client_mean, self.client_stddev)
        dt = _clamp_interval(float(candidate), self.client_mean, self.client_stddev)

        # Schedule next generation.
        self.next_generation_time = float(get_current_time()) + dt
        self._prepared = None
        self.hold_in("GENERATE", dt)

    def exit(self):
        pass