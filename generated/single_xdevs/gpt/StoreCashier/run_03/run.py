#!/usr/bin/env python3
import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# -----------------------------
# Utilities
# -----------------------------
def hhmmssmmm_to_seconds(s: str) -> float:
    # Format: HH:MM:SS:mmm
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format '{s}'. Expected HH:MM:SS:mmm")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    sec = int(ss)
    ms = int(mmm)
    if not (0 <= m < 60 and 0 <= sec < 60 and 0 <= ms < 1000 and h >= 0):
        raise ValueError(f"Invalid time fields in '{s}'")
    return h * 3600 + m * 60 + sec + ms / 1000.0


def seconds_to_hhmmssmmm(t: float) -> str:
    if t < 0:
        t = 0.0
    # Use millisecond rounding to keep stable formatting
    total_ms = int(round(t * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sample_trunc_normal(rng: random.Random, mean: float, std: float, lo: float, hi: float) -> float:
    if std == 0.0:
        return float(mean)
    # Rejection sampling (deterministic given seed)
    for _ in range(10000):
        v = rng.gauss(mean, std)
        if lo <= v <= hi:
            return float(v)
    # Fallback to clamp if extremely unlikely
    return float(clamp(rng.gauss(mean, std), lo, hi))


def jsonl_print(event: Dict[str, Any]) -> None:
    print(json.dumps(event, separators=(",", ":")), file=sys.stdout, flush=True)


# -----------------------------
# Message types
# -----------------------------
@dataclass(frozen=True)
class ClientGeneratedMsg:
    client_id: int
    arrival_time: float


@dataclass(frozen=True)
class EmployeeAvailableMsg:
    employee_id: int


@dataclass(frozen=True)
class PairingMsg:
    client_id: int
    employee_id: int
    paired_time: float
    arrival_time: float


@dataclass(frozen=True)
class ServiceDoneMsg:
    employee_id: int
    client_id: int
    arrival_time: float
    paired_time: float
    completion_time: float


# -----------------------------
# Atomic Models
# -----------------------------
class EventLogger(Atomic):
    """
    Centralized JSONL logger to guarantee nondecreasing time order.
    Receives event dictionaries and prints them.
    """
    def __init__(self, name: str, parent: Optional[Coupled], horizon: float):
        super().__init__(name)
        self.parent = parent
        self.horizon = float(horizon)

        self.add_in_port(Port(dict, "in_event"))

        self._queue: List[Dict[str, Any]] = []
        self._to_emit: List[Dict[str, Any]] = []

        self.hold_in("PASSIVE", math.inf)

    def initialize(self):
        self._queue.clear()
        self._to_emit.clear()
        self.hold_in("PASSIVE", math.inf)

    def lambdaf(self):
        # Output is printing; no state modifications beyond emitting prepared list
        for ev in self._to_emit:
            jsonl_print(ev)

    def deltint(self):
        # After emitting, clear and go passive (or schedule next if more queued)
        self._to_emit = []
        if self._queue:
            self._to_emit = self._queue
            self._queue = []
            self.hold_in("EMIT", 0.0)
        else:
            self.hold_in("PASSIVE", math.inf)

    def deltext(self, e):
        # Collect incoming events; if idle, schedule immediate emit
        incoming = list(self.input["in_event"].values)
        if incoming:
            # Filter by horizon: do not emit events after horizon
            for ev in incoming:
                try:
                    t = float(ev.get("time", 0.0))
                except Exception:
                    t = 0.0
                if t <= self.horizon + 1e-12:
                    self._queue.append(ev)

        if self.phase == "PASSIVE" and self._queue:
            self._to_emit = self._queue
            self._queue = []
            self.hold_in("EMIT", 0.0)
        else:
            # Remain in current phase; if currently EMIT, keep sigma as is
            self.hold_in(self.phase, self.sigma)

    def exit(self):
        # Nothing to finalize
        pass


class ClientGenerator(Atomic):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        rng: random.Random,
        client_mean: float,
        client_stddev: float,
        horizon: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.rng = rng
        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)
        self.horizon = float(horizon)

        self.add_out_port(Port(ClientGeneratedMsg, "out_client"))
        self.add_out_port(Port(dict, "out_log"))

        self._next_client_id = 1
        self._pending_client: Optional[ClientGeneratedMsg] = None
        self._pending_log: Optional[Dict[str, Any]] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._next_client_id = 1
        self._pending_client = None
        self._pending_log = None
        # First client at t=0
        self.hold_in("GENERATE", 0.0)

    def _schedule_next(self):
        # Determine next inter-arrival interval within allowed range
        if self.client_stddev == 0.0:
            interval = self.client_mean
        else:
            lo = 0.0
            hi = self.client_mean + 5.0 * self.client_stddev
            interval = sample_trunc_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)
            interval = clamp(interval, lo, hi)

        # If next event would be after horizon, go passive
        now = float(self.time)
        if now + interval > self.horizon + 1e-12:
            self.hold_in("PASSIVE", math.inf)
        else:
            self.hold_in("GENERATE", float(interval))

    def lambdaf(self):
        if self._pending_client is not None:
            self.output["out_client"].add(self._pending_client)
        if self._pending_log is not None:
            self.output["out_log"].add(self._pending_log)

    def deltint(self):
        # At internal event, create client and log, then schedule next
        now = float(self.time)
        cid = self._next_client_id
        self._next_client_id += 1

        self._pending_client = ClientGeneratedMsg(client_id=cid, arrival_time=now)
        self._pending_log = {
            "time": now,
            "time_str": seconds_to_hhmmssmmm(now),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {"client_id": cid, "arrival_time": now},
        }

        # After output, clear pending and schedule next
        self._schedule_next()

    def deltext(self, e):
        # No inputs
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class QueueManager(Atomic):
    """
    FIFO queue + pairing logic.
    Inputs:
      - in_client: ClientGeneratedMsg
      - in_emp_avail: EmployeeAvailableMsg
    Outputs:
      - out_pair: PairingMsg (to employee)
      - out_log: dict event for logger
    """
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(ClientGeneratedMsg, "in_client"))
        self.add_in_port(Port(EmployeeAvailableMsg, "in_emp_avail"))

        self.add_out_port(Port(PairingMsg, "out_pair"))
        self.add_out_port(Port(dict, "out_log"))

        self._waiting: List[ClientGeneratedMsg] = []
        self._available_emps: List[int] = []  # employee ids available
        self._out_pairs: List[PairingMsg] = []
        self._out_logs: List[Dict[str, Any]] = []

        self.hold_in("PASSIVE", math.inf)

    def initialize(self):
        self._waiting = []
        self._available_emps = []
        self._out_pairs = []
        self._out_logs = []
        self.hold_in("PASSIVE", math.inf)

    def _try_pair(self, now: float):
        # Deterministic employee selection: smallest id first
        self._available_emps.sort()
        while self._waiting and self._available_emps:
            client = self._waiting.pop(0)
            emp_id = self._available_emps.pop(0)
            pair = PairingMsg(
                client_id=client.client_id,
                employee_id=emp_id,
                paired_time=now,
                arrival_time=client.arrival_time,
            )
            self._out_pairs.append(pair)
            self._out_logs.append(
                {
                    "time": now,
                    "time_str": seconds_to_hhmmssmmm(now),
                    "event": "client_paired",
                    "entity_type": "queue",
                    "entity": "Queue",
                    "payload": {
                        "client_id": client.client_id,
                        "employee_id": emp_id,
                        "paired_time": now,
                    },
                }
            )

    def lambdaf(self):
        for p in self._out_pairs:
            self.output["out_pair"].add(p)
        for ev in self._out_logs:
            self.output["out_log"].add(ev)

    def deltint(self):
        # After emitting, clear outputs and go passive
        self._out_pairs = []
        self._out_logs = []
        self.hold_in("PASSIVE", math.inf)

    def deltext(self, e):
        now = float(self.time)

        # Consume inputs
        for c in self.input["in_client"].values:
            self._waiting.append(c)
        for a in self.input["in_emp_avail"].values:
            self._available_emps.append(a.employee_id)

        # Try to pair immediately
        self._try_pair(now)

        if self._out_pairs or self._out_logs:
            self.hold_in("EMIT", 0.0)
        else:
            self.hold_in("PASSIVE", math.inf)

    def exit(self):
        pass


class Employee(Atomic):
    """
    Employee server.
    Inputs:
      - in_pair: PairingMsg (may include pairings for either employee; employee filters)
    Outputs:
      - out_emp_avail: EmployeeAvailableMsg
      - out_log: dict event for logger
    """
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        employee_id: int,
        rng: random.Random,
        service_mean: float,
        service_stddev: float,
        horizon: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.employee_id = int(employee_id)
        self.rng = rng
        self.service_mean = float(service_mean)
        self.service_stddev = float(service_stddev)
        self.horizon = float(horizon)

        self.add_in_port(Port(PairingMsg, "in_pair"))
        self.add_out_port(Port(EmployeeAvailableMsg, "out_emp_avail"))
        self.add_out_port(Port(dict, "out_log"))

        self._busy: bool = False
        self._current: Optional[PairingMsg] = None
        self._pending_avail: bool = False
        self._pending_served_log: Optional[Dict[str, Any]] = None
        self._pending_avail_log: Optional[Dict[str, Any]] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._busy = False
        self._current = None
        self._pending_avail = True  # initial availability at t=0
        now = float(self.time)
        self._pending_avail_log = {
            "time": now,
            "time_str": seconds_to_hhmmssmmm(now),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": f"Employee_{self.employee_id}",
            "payload": {"employee_id": self.employee_id},
        }
        self._pending_served_log = None
        self.hold_in("EMIT_AVAIL", 0.0)

    def _sample_service_time(self) -> float:
        if self.service_stddev == 0.0:
            return float(self.service_mean)
        lo = self.service_mean - 3.0 * self.service_stddev
        hi = self.service_mean + 3.0 * self.service_stddev
        dur = sample_trunc_normal(self.rng, self.service_mean, self.service_stddev, lo, hi)
        return float(clamp(dur, lo, hi))

    def lambdaf(self):
        if self._pending_avail:
            self.output["out_emp_avail"].add(EmployeeAvailableMsg(employee_id=self.employee_id))
        if self._pending_avail_log is not None:
            self.output["out_log"].add(self._pending_avail_log)
        if self._pending_served_log is not None:
            self.output["out_log"].add(self._pending_served_log)

    def deltint(self):
        now = float(self.time)

        if self.phase == "EMIT_AVAIL":
            # Clear pending availability outputs; wait for pairing
            self._pending_avail = False
            self._pending_avail_log = None
            self._pending_served_log = None
            self.hold_in("IDLE", math.inf)
            return

        if self.phase == "SERVING":
            # Service completes now; emit client_served and employee_available at same time
            assert self._current is not None
            completion = now
            arrived = float(self._current.arrival_time)
            cid = int(self._current.client_id)
            delay = completion - arrived

            self._pending_served_log = {
                "time": completion,
                "time_str": seconds_to_hhmmssmmm(completion),
                "event": "client_served",
                "entity_type": "employee",
                "entity": f"Employee_{self.employee_id}",
                "payload": {
                    "client_id": cid,
                    "employee_id": self.employee_id,
                    "arrived": arrived,
                    "dispatched": completion,
                    "delay": delay,
                },
            }
            self._pending_avail = True
            self._pending_avail_log = {
                "time": completion,
                "time_str": seconds_to_hhmmssmmm(completion),
                "event": "employee_available",
                "entity_type": "employee",
                "entity": f"Employee_{self.employee_id}",
                "payload": {"employee_id": self.employee_id},
            }

            self._busy = False
            self._current = None

            # Emit both logs and availability immediately
            self.hold_in("EMIT_AFTER_SERVICE", 0.0)
            return

        if self.phase == "EMIT_AFTER_SERVICE":
            # After emitting, clear and go idle
            self._pending_served_log = None
            self._pending_avail_log = None
            self._pending_avail = False
            self.hold_in("IDLE", math.inf)
            return

        # Default
        self.hold_in("IDLE", math.inf)

    def deltext(self, e):
        now = float(self.time)

        # If currently idle, accept pairing for this employee
        for p in self.input["in_pair"].values:
            if p.employee_id != self.employee_id:
                continue
            if self._busy:
                # Should not happen; ignore to keep robustness
                continue
            # Start service
            self._busy = True
            self._current = p
            dur = self._sample_service_time()

            # If completion would be after horizon, do not schedule completion (and thus no served/available events after horizon)
            if now + dur > self.horizon + 1e-12:
                # Stay busy but no further events; effectively stops producing outputs
                self.hold_in("SERVING", math.inf)
            else:
                self.hold_in("SERVING", float(dur))
            return

        # Otherwise keep current phase
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


# -----------------------------
# Coupled System
# -----------------------------
class StoreSystem(Coupled):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        horizon: float,
        seed: Optional[int],
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
    ):
        super().__init__(name)
        self.parent = parent

        # RNGs (separate streams for determinism)
        base_seed = 12345 if seed is None else int(seed)
        rng_client = random.Random(base_seed + 1)
        rng_e1 = random.Random(base_seed + 2)
        rng_e2 = random.Random(base_seed + 3)

        # Components
        logger = EventLogger("Logger", parent=self, horizon=horizon)
        gen = ClientGenerator(
            "ClientGenerator",
            parent=self,
            rng=rng_client,
            client_mean=client_mean,
            client_stddev=client_stddev,
            horizon=horizon,
        )
        queue = QueueManager("Queue", parent=self)
        emp1 = Employee(
            "Employee_1",
            parent=self,
            employee_id=1,
            rng=rng_e1,
            service_mean=employee_1_mean,
            service_stddev=employee_1_stddev,
            horizon=horizon,
        )
        emp2 = Employee(
            "Employee_2",
            parent=self,
            employee_id=2,
            rng=rng_e2,
            service_mean=employee_2_mean,
            service_stddev=employee_2_stddev,
            horizon=horizon,
        )

        self.add_component(logger)
        self.add_component(gen)
        self.add_component(queue)
        self.add_component(emp1)
        self.add_component(emp2)

        # Couplings: generator -> queue
        self.add_coupling(gen.output["out_client"], queue.input["in_client"])

        # Employees availability -> queue
        self.add_coupling(emp1.output["out_emp_avail"], queue.input["in_emp_avail"])
        self.add_coupling(emp2.output["out_emp_avail"], queue.input["in_emp_avail"])

        # Queue pairing -> employees (broadcast; employees filter by id)
        self.add_coupling(queue.output["out_pair"], emp1.input["in_pair"])
        self.add_coupling(queue.output["out_pair"], emp2.input["in_pair"])

        # Logs -> logger
        self.add_coupling(gen.output["out_log"], logger.input["in_event"])
        self.add_coupling(queue.output["out_log"], logger.input["in_event"])
        self.add_coupling(emp1.output["out_log"], logger.input["in_event"])
        self.add_coupling(emp2.output["out_log"], logger.input["in_event"])


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier simulation (xdevs.py)")
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000", help="HH:MM:SS:mmm")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    horizon = hhmmssmmm_to_seconds(args.simulation_time)

    root = StoreSystem(
        name="StoreSystem",
        parent=None,
        horizon=horizon,
        seed=args.seed,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
    )

    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(horizon)


if __name__ == "__main__":
    main()