import json
from dataclasses import dataclass
from typing import Any

import numpy as np
from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


def _format_time_str(t: float) -> str:
    """Format simulation time seconds as HH:MM:SS:mmm."""
    if t < 0:
        t = 0.0
    total_ms = int(round(t * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def _jsonl_stdout(record: dict[str, Any]) -> None:
    print(json.dumps(record), flush=True)


@dataclass
class _PreparedEmission:
    client_msg: dict
    stdout_record: dict


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

        if client_stddev < 0.0:
            raise ValueError("client_stddev must be nonnegative.")

        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)
        self.seed = seed

        self.add_out_port(Port(dict, "clients_out"))

        self.next_client_id: int = 1
        self.next_time: float = 0.0

        self._rng: np.random.Generator | None = None
        self._prepared: _PreparedEmission | None = None

    def initialize(self):
        # RNG stream: local to this component; derive stable sub-seed if provided.
        if self.seed is None:
            self._rng = np.random.default_rng()
        else:
            # Stable sub-seed unique to ClientGenerator.
            self._rng = np.random.default_rng(int(self.seed) + 10007)

        self.next_client_id = 1
        self.next_time = 0.0
        self._prepared = None

        # First emission at t=0.0
        self.hold_in("EMIT", 0.0)

    def deltext(self, e: float):
        # No input ports.
        return None

    def _get_horizon(self) -> float:
        # Expect parent to expose simulation horizon; fall back to infinity if absent.
        if self.parent is not None and hasattr(self.parent, "horizon"):
            try:
                return float(getattr(self.parent, "horizon"))
            except Exception:
                return float("inf")
        return float("inf")

    def _within_horizon(self, t: float, horizon: float) -> bool:
        # Robust comparison: allow tiny floating error.
        return t <= horizon + 1e-12

    def _sample_interval(self) -> float:
        assert self._rng is not None
        mean = self.client_mean
        std = self.client_stddev

        if std == 0.0:
            return float(mean)

        upper = mean + 5.0 * std
        if upper < 0.0:
            # Should not happen with std>=0, but guard anyway.
            upper = 0.0

        # Prefer resampling to preserve distribution shape within bounds.
        while True:
            x = float(self._rng.normal(loc=mean, scale=std))
            if 0.0 <= x <= upper:
                return x

    def lambdaf(self):
        if self.phase != "EMIT":
            return

        horizon = self._get_horizon()
        t = float(get_current_time())

        # Do not emit after horizon.
        if not self._within_horizon(t, horizon):
            return

        payload = {"client_id": int(self.next_client_id), "arrival_time": float(t)}
        record = {
            "time": float(t),
            "time_str": _format_time_str(float(t)),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": dict(payload),
        }

        # Store prepared emission (optional), then perform both effects here.
        self._prepared = _PreparedEmission(client_msg=payload, stdout_record=record)

        self.output["clients_out"].add(payload)
        _jsonl_stdout(record)

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate()
            return

        horizon = self._get_horizon()
        now = float(get_current_time())

        # If we somehow fired beyond horizon, stop.
        if not self._within_horizon(now, horizon):
            self.passivate("passive")
            return

        # Advance client id after emitting.
        self.next_client_id += 1

        # Compute next generation time.
        if self.next_client_id == 1:
            # Not reachable; kept for completeness.
            interval = 0.0
        elif self.next_client_id == 2 and abs(now - 0.0) < 1e-12:
            # First client was at t=0.0; subsequent clients use sampling.
            interval = self._sample_interval()
        else:
            interval = self._sample_interval()

        self.next_time = now + float(interval)

        # If next would be strictly greater than horizon, stop.
        if self.next_time > horizon + 1e-12:
            self.passivate("passive")
            return

        # Schedule next internal event at next_time (relative delay).
        sigma = max(0.0, self.next_time - now)
        self.hold_in("EMIT", sigma)

    def exit(self):
        # No final external IO required.
        pass