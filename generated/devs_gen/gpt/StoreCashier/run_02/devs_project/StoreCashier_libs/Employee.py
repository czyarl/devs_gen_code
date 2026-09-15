import json
import math
import random

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


def _format_time(value: float) -> str:
    """Format simulation seconds as HH:MM:SS:mmm."""
    total_milliseconds = int(round(value * 1000))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


def _get_simulation_horizon(parent: Coupled | None) -> float | None:
    """
    Best-effort horizon lookup. The runtime is authoritative; if we cannot
    discover it, we do not suppress output.
    """
    if parent is None:
        return None

    # Common attribute names in runners/framework wrappers.
    for attr in ("simulation_horizon", "horizon", "until", "end_time", "stop_time", "sim_time"):
        try:
            value = getattr(parent, attr)
        except Exception:
            continue
        if isinstance(value, (int, float)):
            return float(value)

    # Some runtimes store config in a dict-like field.
    for attr in ("config", "params", "settings"):
        try:
            cfg = getattr(parent, attr)
        except Exception:
            continue
        if isinstance(cfg, dict):
            for key in ("simulation_horizon", "horizon", "until", "end_time", "stop_time", "simulation_time"):
                v = cfg.get(key)
                if isinstance(v, (int, float)):
                    return float(v)

    return None


class Employee(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        employee_id: int,
        service_mean: float,
        service_stddev: float,
        seed: int,
    ):
        super().__init__(name)
        self.parent = parent

        self.employee_id = int(employee_id)
        self.service_mean = float(service_mean)
        self.service_stddev = float(service_stddev)
        self.seed = seed

        self.add_in_port(Port(dict, "pairing_in"))
        self.add_out_port(Port(dict, "available_out"))

        # State
        self.busy: bool = False
        self.current_client: dict | None = None
        self.service_deadline: float | None = None

        # Output flags for the next lambdaf()
        self._emit_available: bool = False
        self._emit_served: bool = False

        # RNG stream (stable per employee)
        if self.seed is None:
            # Deterministic fallback within a run: derive from employee_id only.
            sub_seed = 1000003 + 1009 * self.employee_id
        else:
            sub_seed = int(self.seed) + int(self.employee_id)
        self._rng = random.Random(sub_seed)

    def initialize(self):
        self.busy = False
        self.current_client = None
        self.service_deadline = None

        # Initial availability must be emitted at t=0.0 (DEVS + JSONL).
        self._emit_available = True
        self._emit_served = False
        self.hold_in("OUTPUT_AVAILABLE", 0.0)

    def _within_horizon(self, t: float) -> bool:
        horizon = _get_simulation_horizon(self.parent)
        if horizon is None:
            return True
        return t <= horizon

    def _log_employee_available(self, now: float) -> None:
        if not self._within_horizon(now):
            return
        print(
            json.dumps(
                {
                    "time": now,
                    "time_str": _format_time(now),
                    "event": "employee_available",
                    "entity_type": "employee",
                    "entity": self.name,
                    "payload": {"employee_id": self.employee_id},
                }
            ),
            flush=True,
        )

    def _log_client_served(self, now: float) -> None:
        if not self._within_horizon(now):
            return
        if self.current_client is None:
            return
        arrived = float(self.current_client["arrived"])
        print(
            json.dumps(
                {
                    "time": now,
                    "time_str": _format_time(now),
                    "event": "client_served",
                    "entity_type": "employee",
                    "entity": self.name,
                    "payload": {
                        "client_id": int(self.current_client["client_id"]),
                        "employee_id": self.employee_id,
                        "arrived": arrived,
                        "dispatched": now,
                        "delay": now - arrived,
                    },
                }
            ),
            flush=True,
        )

    def _validate_pairing(self, m) -> dict | None:
        if not isinstance(m, dict):
            return None
        required = ("client_id", "arrival_time", "employee_id", "paired_time")
        for k in required:
            if k not in m:
                return None
        return m

    def _sample_service_duration(self) -> float:
        mean = self.service_mean
        std = self.service_stddev

        if math.isclose(std, 0.0, abs_tol=0.0):
            d = mean
        else:
            lo = mean - 3.0 * std
            hi = mean + 3.0 * std
            # Clamp a normal sample into [lo, hi]
            candidate = self._rng.normalvariate(mean, std)
            d = min(hi, max(lo, candidate))

        # Ensure causal DEVS time: no negative durations.
        if d < 0.0:
            d = 0.0
        return float(d)

    def deltext(self, e: float):
        # Preserve remaining time if currently busy.
        if self.phase == "SERVING":
            self.continuef(e)
        elif self.phase in ("OUTPUT_AVAILABLE", "OUTPUT_COMPLETE"):
            # We keep the scheduled immediate output; do not cancel it.
            self.continuef(e)

        now = get_current_time()

        accepted = False
        for msg in self.input["pairing_in"].values:
            m = self._validate_pairing(msg)
            if m is None:
                continue
            if int(m["employee_id"]) != self.employee_id:
                continue

            if accepted:
                continue

            if not self.busy:
                accepted = True
                # Start service
                self.busy = True
                self.current_client = {
                    "client_id": int(m["client_id"]),
                    "arrived": float(m["arrival_time"]),
                    "paired_time": float(m["paired_time"]),
                }
                d = self._sample_service_duration()
                self.service_deadline = now + d
                self._emit_available = False
                self._emit_served = False
                self.hold_in("SERVING", d)
            else:
                # Busy: ignore addressed pairing safely.
                continue

        # If idle and no pending output and no accepted work, remain/passivate.
        if not self.busy and self.phase not in ("OUTPUT_AVAILABLE", "OUTPUT_COMPLETE"):
            self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()

        if self.phase == "OUTPUT_AVAILABLE":
            # DEVS output
            self.output["available_out"].add({"employee_id": self.employee_id})
            # External IO
            self._log_employee_available(now)

        elif self.phase == "OUTPUT_COMPLETE":
            # External IO: served first, then availability (same simulation time)
            self._log_client_served(now)

            # DEVS output: availability
            self.output["available_out"].add({"employee_id": self.employee_id})
            # External IO: availability
            self._log_employee_available(now)

        # SERVING has no direct DEVS output; completion is handled via OUTPUT_COMPLETE.

    def deltint(self):
        now = get_current_time()

        if self.phase == "OUTPUT_AVAILABLE":
            self._emit_available = False
            self.passivate("IDLE")
            return

        if self.phase == "SERVING":
            # Service completion moment: schedule zero-time output phase.
            self._emit_served = True
            self._emit_available = True
            self.hold_in("OUTPUT_COMPLETE", 0.0)
            return

        if self.phase == "OUTPUT_COMPLETE":
            # After emitting completion+availability, become idle.
            self.busy = False
            self.current_client = None
            self.service_deadline = None
            self._emit_served = False
            self._emit_available = False
            self.passivate("IDLE")
            return

        self.passivate("IDLE")

    def exit(self):
        pass