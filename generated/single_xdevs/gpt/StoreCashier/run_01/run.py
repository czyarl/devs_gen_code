#!/usr/bin/env python3
import argparse
import json
import sys
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# -----------------------------
# Time formatting / parsing
# -----------------------------
def parse_hhmmssmmm(s: str) -> float:
    # "HH:MM:SS:mmm"
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format '{s}', expected HH:MM:SS:mmm")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    sec = int(ss)
    ms = int(mmm)
    if not (0 <= m < 60 and 0 <= sec < 60 and 0 <= ms < 1000 and h >= 0):
        raise ValueError(f"Invalid time components in '{s}'")
    return float(h * 3600 + m * 60 + sec) + ms / 1000.0


def format_hhmmssmmm(t: float) -> str:
    if t < 0:
        t = 0.0
    # Round to nearest millisecond for display
    total_ms = int(round(t * 1000.0 + 1e-9))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


# -----------------------------
# JSONL Logger (Atomic)
# -----------------------------
class JsonlLogger(Atomic):
    """
    Receives event dicts and prints them to stdout as JSONL.
    Ensures time_str exists and matches time.
    """
    def __init__(self, name: str, parent: Optional[Coupled], horizon: float):
        super().__init__(name)
        self.parent = parent
        self.horizon = horizon
        self.add_in_port(Port(dict, "in_event"))
        self.add_out_port(Port(dict, "out_event"))  # unused; present for completeness
        self._pending: List[Dict[str, Any]] = []
        self.hold_in("PASSIVE", math.inf)

    def initialize(self):
        self._pending = []
        self.hold_in("PASSIVE", math.inf)

    def lambdaf(self):
        # Output not used
        pass

    def deltint(self):
        self.hold_in("PASSIVE", math.inf)

    def deltext(self, e):
        # Print all received events immediately (external transition)
        vals = list(self.input["in_event"].values)
        for ev in vals:
            if not isinstance(ev, dict):
                continue
            t = float(ev.get("time", 0.0))
            if t > self.horizon + 1e-12:
                continue
            ev["time"] = t
            ev["time_str"] = format_hhmmssmmm(t)
            print(json.dumps(ev, separators=(",", ":")), file=sys.stdout, flush=True)
        self.hold_in("PASSIVE", math.inf)

    def exit(self):
        pass


# -----------------------------
# Helper: bounded normal sampling
# -----------------------------
def bounded_normal(rng: random.Random, mean: float, std: float, lo: float, hi: float) -> float:
    if std <= 0.0:
        return float(mean)
    # Rejection sampling with a cap; then clamp as a fallback.
    for _ in range(1000):
        x = rng.gauss(mean, std)
        if lo <= x <= hi:
            return float(x)
    x = rng.gauss(mean, std)
    return float(min(hi, max(lo, x)))


# -----------------------------
# Client Generator (Atomic)
# -----------------------------
class ClientGenerator(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled],
                 client_mean: float, client_stddev: float, seed: Optional[int] = None):
        super().__init__(name)
        self.parent = parent
        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)
        self.rng = random.Random(seed if seed is not None else 0)

        self.add_out_port(Port(dict, "out_client"))   # to queue
        self.add_out_port(Port(dict, "out_event"))    # to logger

        self._next_client_id = 1
        self._emit_client_payload: Optional[Dict[str, Any]] = None
        self._emit_event_payload: Optional[Dict[str, Any]] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._next_client_id = 1
        # First client at t=0
        self._prepare_emit_client(0.0)
        self.hold_in("EMIT", 0.0)

    def _prepare_emit_client(self, now: float):
        cid = self._next_client_id
        self._next_client_id += 1
        self._emit_client_payload = {"client_id": cid, "arrival_time": float(now)}
        self._emit_event_payload = {
            "time": float(now),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {"client_id": cid, "arrival_time": float(now)},
        }

    def lambdaf(self):
        if self.phase == "EMIT":
            if self._emit_client_payload is not None:
                self.output["out_client"].add(self._emit_client_payload)
            if self._emit_event_payload is not None:
                self.output["out_event"].add(self._emit_event_payload)

    def deltint(self):
        now = float(self.time)
        if self.phase == "EMIT":
            # Schedule next generation
            lo = 0.0
            hi = self.client_mean + 5.0 * self.client_stddev
            interval = bounded_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)
            # Prepare next client payload for next internal event
            self._prepare_emit_client(now + interval)
            self.hold_in("EMIT", interval)
        else:
            self.hold_in("EMIT", 0.0)

    def deltext(self, e):
        # No inputs
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


# -----------------------------
# Queue / Dispatcher (Atomic)
# -----------------------------
@dataclass
class ClientInfo:
    client_id: int
    arrival_time: float


class QueueDispatcher(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_client"))          # from generator
        self.add_in_port(Port(dict, "in_emp_available"))   # from employees

        self.add_out_port(Port(dict, "out_to_emp1"))       # pairing to employee1
        self.add_out_port(Port(dict, "out_to_emp2"))       # pairing to employee2
        self.add_out_port(Port(dict, "out_event"))         # to logger

        self._queue: List[ClientInfo] = []
        self._available: Dict[int, bool] = {1: False, 2: False}

        self._pending_pairs: List[Tuple[int, int, float]] = []  # (client_id, emp_id, paired_time)
        self._pending_events: List[Dict[str, Any]] = []

        self.hold_in("PASSIVE", math.inf)

    def initialize(self):
        self._queue = []
        self._available = {1: False, 2: False}
        self._pending_pairs = []
        self._pending_events = []
        self.hold_in("PASSIVE", math.inf)

    def _try_pair(self, now: float):
        # Pair while possible, FIFO clients, prefer lower employee id when both available
        while self._queue and (self._available[1] or self._available[2]):
            emp_id = 1 if self._available[1] else 2
            client = self._queue.pop(0)
            self._available[emp_id] = False
            self._pending_pairs.append((client.client_id, emp_id, float(now)))
            self._pending_events.append({
                "time": float(now),
                "event": "client_paired",
                "entity_type": "queue",
                "entity": "Queue",
                "payload": {"client_id": int(client.client_id), "employee_id": int(emp_id), "paired_time": float(now)},
            })

    def lambdaf(self):
        if self.phase == "EMIT":
            # Emit pairings to employees and events to logger
            for (cid, emp_id, paired_time) in self._pending_pairs:
                msg = {"client_id": int(cid), "employee_id": int(emp_id), "paired_time": float(paired_time)}
                if emp_id == 1:
                    self.output["out_to_emp1"].add(msg)
                else:
                    self.output["out_to_emp2"].add(msg)
            for ev in self._pending_events:
                self.output["out_event"].add(ev)

    def deltint(self):
        if self.phase == "EMIT":
            self._pending_pairs = []
            self._pending_events = []
        self.hold_in("PASSIVE", math.inf)

    def deltext(self, e):
        now = float(self.time)
        # Process incoming clients
        for msg in list(self.input["in_client"].values):
            try:
                cid = int(msg["client_id"])
                at = float(msg["arrival_time"])
            except Exception:
                continue
            self._queue.append(ClientInfo(client_id=cid, arrival_time=at))

        # Process employee availability signals
        for msg in list(self.input["in_emp_available"].values):
            try:
                emp_id = int(msg["employee_id"])
            except Exception:
                continue
            if emp_id in self._available:
                self._available[emp_id] = True

        # Attempt pairings at current time
        self._pending_pairs = []
        self._pending_events = []
        self._try_pair(now)

        if self._pending_events:
            self.hold_in("EMIT", 0.0)
        else:
            self.hold_in("PASSIVE", math.inf)

    def exit(self):
        pass


# -----------------------------
# Employee (Atomic)
# -----------------------------
class Employee(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled],
                 employee_id: int, mean: float, stddev: float, seed: Optional[int] = None):
        super().__init__(name)
        self.parent = parent
        self.employee_id = int(employee_id)
        self.mean = float(mean)
        self.stddev = float(stddev)
        self.rng = random.Random(seed if seed is not None else (1000 + self.employee_id))

        self.add_in_port(Port(dict, "in_pair"))          # from queue
        self.add_out_port(Port(dict, "out_available"))   # to queue
        self.add_out_port(Port(dict, "out_event"))       # to logger

        self._busy: bool = False
        self._current_client_id: Optional[int] = None
        self._current_arrival: Optional[float] = None
        self._current_paired_time: Optional[float] = None
        self._service_duration: Optional[float] = None

        self._pending_event: Optional[Dict[str, Any]] = None
        self._pending_available_event: Optional[Dict[str, Any]] = None
        self._pending_available_msg: Optional[Dict[str, Any]] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._busy = False
        self._current_client_id = None
        self._current_arrival = None
        self._current_paired_time = None
        self._service_duration = None

        # Emit initial availability at t=0
        now = float(self.time)
        self._pending_available_msg = {"employee_id": self.employee_id}
        self._pending_available_event = {
            "time": float(now),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": f"Employee_{self.employee_id}",
            "payload": {"employee_id": self.employee_id},
        }
        self._pending_event = None
        self.hold_in("EMIT_AVAILABLE", 0.0)

    def _sample_service_duration(self) -> float:
        if self.stddev <= 0.0:
            return float(self.mean)
        lo = self.mean - 3.0 * self.stddev
        hi = self.mean + 3.0 * self.stddev
        return bounded_normal(self.rng, self.mean, self.stddev, lo, hi)

    def lambdaf(self):
        if self.phase == "EMIT_AVAILABLE":
            if self._pending_available_msg is not None:
                self.output["out_available"].add(self._pending_available_msg)
            if self._pending_available_event is not None:
                self.output["out_event"].add(self._pending_available_event)
        elif self.phase == "SERVE_DONE":
            if self._pending_event is not None:
                self.output["out_event"].add(self._pending_event)
            if self._pending_available_msg is not None:
                self.output["out_available"].add(self._pending_available_msg)
            if self._pending_available_event is not None:
                self.output["out_event"].add(self._pending_available_event)

    def deltint(self):
        now = float(self.time)
        if self.phase == "EMIT_AVAILABLE":
            # After emitting availability, wait for pairing
            self._pending_available_msg = None
            self._pending_available_event = None
            self.hold_in("IDLE", math.inf)
            return

        if self.phase == "SERVE_DONE":
            # Service completed; now idle and availability already emitted in this phase
            self._busy = False
            self._current_client_id = None
            self._current_arrival = None
            self._current_paired_time = None
            self._service_duration = None
            self._pending_event = None
            self._pending_available_msg = None
            self._pending_available_event = None
            self.hold_in("IDLE", math.inf)
            return

        # Default
        self.hold_in("IDLE", math.inf)

    def deltext(self, e):
        now = float(self.time)

        # If paired while idle, start service
        for msg in list(self.input["in_pair"].values):
            try:
                cid = int(msg["client_id"])
                emp_id = int(msg["employee_id"])
                paired_time = float(msg["paired_time"])
            except Exception:
                continue
            if emp_id != self.employee_id:
                continue
            if self._busy:
                # Should not happen; ignore
                continue

            self._busy = True
            self._current_client_id = cid
            self._current_paired_time = paired_time
            # Arrival time is not provided by pairing message; we will reconstruct via delay using paired_time?
            # Requirement: client_served must include arrived (generation time).
            # To satisfy, we require queue to preserve FIFO but doesn't pass arrival time.
            # Workaround: include arrival_time in pairing message if present; if not, set arrived=paired_time (still consistent? no).
            # Therefore, expect queue to pass arrival_time; but spec doesn't forbid extra fields.
            arrived = msg.get("arrival_time", paired_time)
            self._current_arrival = float(arrived)

            dur = self._sample_service_duration()
            self._service_duration = dur

            # Schedule completion
            self._pending_event = None
            self._pending_available_msg = None
            self._pending_available_event = None
            self.hold_in("BUSY", dur)
            return

        # If no relevant input, keep current phase/sigma
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass

    # Override deltint for BUSY completion by using phase "BUSY" -> "SERVE_DONE" with sigma 0
    def deltint(self):  # type: ignore[override]
        now = float(self.time)
        if self.phase == "EMIT_AVAILABLE":
            self._pending_available_msg = None
            self._pending_available_event = None
            self.hold_in("IDLE", math.inf)
            return

        if self.phase == "BUSY":
            # Prepare served event + availability, then emit immediately
            cid = int(self._current_client_id) if self._current_client_id is not None else -1
            arrived = float(self._current_arrival) if self._current_arrival is not None else float(now)
            dispatched = float(now)
            delay = dispatched - arrived

            self._pending_event = {
                "time": float(now),
                "event": "client_served",
                "entity_type": "employee",
                "entity": f"Employee_{self.employee_id}",
                "payload": {
                    "client_id": cid,
                    "employee_id": self.employee_id,
                    "arrived": arrived,
                    "dispatched": dispatched,
                    "delay": float(delay),
                },
            }
            self._pending_available_msg = {"employee_id": self.employee_id}
            self._pending_available_event = {
                "time": float(now),
                "event": "employee_available",
                "entity_type": "employee",
                "entity": f"Employee_{self.employee_id}",
                "payload": {"employee_id": self.employee_id},
            }
            self.hold_in("SERVE_DONE", 0.0)
            return

        if self.phase == "SERVE_DONE":
            self._busy = False
            self._current_client_id = None
            self._current_arrival = None
            self._current_paired_time = None
            self._service_duration = None
            self._pending_event = None
            self._pending_available_msg = None
            self._pending_available_event = None
            self.hold_in("IDLE", math.inf)
            return

        # IDLE/PASSIVE
        self.hold_in("IDLE", math.inf)


# -----------------------------
# System (Coupled)
# -----------------------------
class System(Coupled):
    def __init__(self, name: str, parent: Optional[Coupled],
                 horizon: float,
                 client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float,
                 employee_2_mean: float, employee_2_stddev: float,
                 seed: Optional[int] = None):
        super().__init__(name)
        self.parent = parent

        # Components
        gen_seed = None if seed is None else seed + 1
        e1_seed = None if seed is None else seed + 101
        e2_seed = None if seed is None else seed + 102

        self.gen = ClientGenerator("ClientGenerator", self, client_mean, client_stddev, seed=gen_seed)
        self.queue = QueueDispatcher("Queue", self)
        self.emp1 = Employee("Employee_1", self, 1, employee_1_mean, employee_1_stddev, seed=e1_seed)
        self.emp2 = Employee("Employee_2", self, 2, employee_2_mean, employee_2_stddev, seed=e2_seed)
        self.logger = JsonlLogger("Logger", self, horizon=horizon)

        for c in (self.gen, self.queue, self.emp1, self.emp2, self.logger):
            self.add_component(c)

        # Couplings: generator -> queue
        self.add_coupling(self.gen.output["out_client"], self.queue.input["in_client"])

        # Employees availability -> queue
        self.add_coupling(self.emp1.output["out_available"], self.queue.input["in_emp_available"])
        self.add_coupling(self.emp2.output["out_available"], self.queue.input["in_emp_available"])

        # Queue pairings -> employees
        self.add_coupling(self.queue.output["out_to_emp1"], self.emp1.input["in_pair"])
        self.add_coupling(self.queue.output["out_to_emp2"], self.emp2.input["in_pair"])

        # Event logs -> logger
        self.add_coupling(self.gen.output["out_event"], self.logger.input["in_event"])
        self.add_coupling(self.queue.output["out_event"], self.logger.input["in_event"])
        self.add_coupling(self.emp1.output["out_event"], self.logger.input["in_event"])
        self.add_coupling(self.emp2.output["out_event"], self.logger.input["in_event"])


# -----------------------------
# Patch: ensure queue passes arrival_time to employee for served payload
# (Allowed: internal structure acceptable; extra fields in messages are fine.)
# We implement by subclassing QueueDispatcher behavior via monkey-patching method.
# -----------------------------
def _queue_try_pair_with_arrival(self: QueueDispatcher, now: float):
    while self._queue and (self._available[1] or self._available[2]):
        emp_id = 1 if self._available[1] else 2
        client = self._queue.pop(0)
        self._available[emp_id] = False
        # include arrival_time in pairing message (internal message, not logged)
        self._pending_pairs.append((client.client_id, emp_id, float(now), float(client.arrival_time)))
        self._pending_events.append({
            "time": float(now),
            "event": "client_paired",
            "entity_type": "queue",
            "entity": "Queue",
            "payload": {"client_id": int(client.client_id), "employee_id": int(emp_id), "paired_time": float(now)},
        })


def _queue_lambdaf_with_arrival(self: QueueDispatcher):
    if self.phase == "EMIT":
        for item in self._pending_pairs:
            if len(item) == 4:
                cid, emp_id, paired_time, arrival_time = item
            else:
                cid, emp_id, paired_time = item
                arrival_time = paired_time
            msg = {
                "client_id": int(cid),
                "employee_id": int(emp_id),
                "paired_time": float(paired_time),
                "arrival_time": float(arrival_time),
            }
            if emp_id == 1:
                self.output["out_to_emp1"].add(msg)
            else:
                self.output["out_to_emp2"].add(msg)
        for ev in self._pending_events:
            self.output["out_event"].add(ev)


# Apply patches
QueueDispatcher._try_pair = _queue_try_pair_with_arrival  # type: ignore[attr-defined]
QueueDispatcher.lambdaf = _queue_lambdaf_with_arrival     # type: ignore[method-assign]


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000",
                        help="Total simulation horizon in HH:MM:SS:mmm format")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    horizon = parse_hhmmssmmm(args.simulation_time)

    root = System(
        name="system",
        parent=None,
        horizon=horizon,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        seed=args.seed,
    )

    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(horizon)


if __name__ == "__main__":
    main()