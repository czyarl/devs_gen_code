import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# ----------------------------
# Time formatting utilities
# ----------------------------
def parse_hhmmssmmm(s: str) -> float:
    # "HH:MM:SS:mmm"
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError("simulation_time must be in HH:MM:SS:mmm format")
    hh, mm, ss, mmm = map(int, parts)
    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise ValueError("simulation_time parts must be non-negative")
    return hh * 3600.0 + mm * 60.0 + ss * 1.0 + (mmm / 1000.0)


def format_hhmmssmmm(t: float) -> str:
    if t < 0:
        t = 0.0
    # Round to nearest millisecond for stable formatting
    ms_total = int(round(t * 1000.0))
    hh = ms_total // (3600 * 1000)
    ms_total -= hh * 3600 * 1000
    mm = ms_total // (60 * 1000)
    ms_total -= mm * 60 * 1000
    ss = ms_total // 1000
    ms_total -= ss * 1000
    mmm = ms_total
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{mmm:03d}"


# ----------------------------
# Random sampling utilities
# ----------------------------
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sample_trunc_normal(rng: random.Random, mean: float, std: float, lo: float, hi: float) -> float:
    if std == 0.0:
        return float(mean)
    # Rejection sampling; bounded ranges are small enough for typical params.
    for _ in range(10000):
        x = rng.gauss(mean, std)
        if lo <= x <= hi:
            return float(x)
    # Fallback: clamp a final draw
    return float(clamp(rng.gauss(mean, std), lo, hi))


# ----------------------------
# Event logger atomic
# ----------------------------
class EventLogger(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled], horizon: float):
        super().__init__(name)
        self.parent = parent
        self.horizon = horizon

        self.add_in_port(Port(dict, "in_event"))
        self.add_out_port(Port(dict, "noop"))  # unused

        self._queue: List[Dict[str, Any]] = []
        self._next_event: Optional[Dict[str, Any]] = None

        self.hold_in("PASSIVE", math.inf)

    def initialize(self):
        self._queue.clear()
        self._next_event = None
        self.hold_in("PASSIVE", math.inf)

    def lambdaf(self):
        if self._next_event is None:
            return
        ev = self._next_event
        t = float(ev["time"])
        if t <= self.horizon + 1e-12:
            # Ensure required fields exist
            out = {
                "time": t,
                "time_str": format_hhmmssmmm(t),
                "event": ev["event"],
                "entity_type": ev["entity_type"],
                "entity": ev["entity"],
                "payload": ev.get("payload", {}),
            }
            print(json.dumps(out, separators=(",", ":")), file=sys.stdout, flush=True)

    def deltint(self):
        # Remove the event we just emitted
        if self._queue:
            self._queue.pop(0)
        self._next_event = self._queue[0] if self._queue else None
        if self._next_event is None:
            self.hold_in("PASSIVE", math.inf)
        else:
            # Emit remaining queued events at same simulation time (sigma=0)
            self.hold_in("EMIT", 0.0)

    def deltext(self, e):
        # Collect incoming events; they all occur at current simulation time
        incoming = list(self.input["in_event"].values)
        if not incoming:
            # No change
            self.hold_in(self.phase, self.sigma)
            return

        # Append in arrival order; all should have time equal to current time
        for ev in incoming:
            if not isinstance(ev, dict):
                continue
            self._queue.append(ev)

        if self._next_event is None and self._queue:
            self._next_event = self._queue[0]
            self.hold_in("EMIT", 0.0)
        else:
            # If already emitting, keep immediate emission; otherwise keep passive
            if self.phase == "PASSIVE":
                self._next_event = self._queue[0] if self._queue else None
                if self._next_event is not None:
                    self.hold_in("EMIT", 0.0)
                else:
                    self.hold_in("PASSIVE", math.inf)
            else:
                self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


# ----------------------------
# Client generator atomic
# ----------------------------
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

        self.add_out_port(Port(dict, "out_client"))
        self.add_out_port(Port(dict, "out_log"))

        self._next_client_id = 1
        self._pending_client: Optional[Dict[str, Any]] = None
        self._pending_log: Optional[Dict[str, Any]] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._next_client_id = 1
        self._pending_client = None
        self._pending_log = None
        # First client at t=0.0
        self.hold_in("GENERATE", 0.0)

    def _next_interval(self) -> float:
        lo = 0.0
        hi = self.client_mean + 5.0 * self.client_stddev
        if hi < lo:
            hi = lo
        if self.client_stddev == 0.0:
            return float(clamp(self.client_mean, lo, hi))
        return sample_trunc_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)

    def lambdaf(self):
        if self._pending_client is not None:
            self.output["out_client"].add(self._pending_client)
        if self._pending_log is not None:
            self.output["out_log"].add(self._pending_log)

    def deltint(self):
        # After generating, schedule next generation
        self._pending_client = None
        self._pending_log = None

        # If next event would be beyond horizon, go passive
        interval = self._next_interval()
        # The coordinator will stop at horizon anyway, but we avoid emitting after horizon
        # by not scheduling if it would exceed horizon.
        # Current time is implicitly advanced; we don't have direct access here, so we schedule anyway;
        # logger filters by horizon, but generator would still send to queue after horizon.
        # To avoid that, we rely on coordinator stopping at horizon; still safe.
        self.hold_in("GENERATE", interval)

    def deltext(self, e):
        # No inputs
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass

    def _prepare_generation(self, t: float):
        cid = self._next_client_id
        self._next_client_id += 1
        self._pending_client = {"client_id": cid, "arrival_time": t}
        self._pending_log = {
            "time": t,
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {"client_id": cid, "arrival_time": t},
        }

    # xdevs calls lambdaf before deltint; we need to prepare payload before lambdaf.
    # We do so by using deltext? Not available. Instead, we prepare in initialize and deltint?
    # But time changes. We can prepare in lambdaf by reading clock? Not allowed to modify state.
    # Workaround: use phase "GENERATE" and prepare in deltext with elapsed=0? Not.
    # Alternative: prepare in deltint of previous state. For first event, prepare in initialize.
    # For subsequent events, prepare in deltint right after scheduling? Not.
    # So we implement as: in deltint, we first prepare for *current* time before clearing? Not possible.
    # Therefore: use two-step phases: "SCHEDULE" then "GENERATE".
    # We'll override initialize/deltint accordingly below.


class ClientGenerator2(ClientGenerator):
    def initialize(self):
        self._next_client_id = 1
        self._pending_client = None
        self._pending_log = None
        # Prepare first generation at t=0, emit immediately
        self._prepare_generation(0.0)
        self.hold_in("EMIT", 0.0)

    def lambdaf(self):
        super().lambdaf()

    def deltint(self):
        # After emitting, decide next time and prepare next payload at that future time
        if self.phase == "EMIT":
            self._pending_client = None
            self._pending_log = None
            interval = self._next_interval()
            self.hold_in("WAIT", interval)
            return

        if self.phase == "WAIT":
            # Now at generation time; prepare and emit instantly
            # We don't have direct access to absolute time; reconstruct by accumulating internally.
            # Maintain internal clock offset.
            pass

    def deltext(self, e):
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


# We need absolute time in generator; xdevs Atomic has self.time? Not guaranteed.
# We'll instead have generator receive a "tick" from a TimeKeeper that provides current time at each internal event.
# Simpler: avoid needing absolute time by having queue/employee compute arrived time from generator's own accumulated time.
# We'll keep generator's internal current_time accumulator updated deterministically.

class ClientGeneratorAtomic(Atomic):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        rng: random.Random,
        client_mean: float,
        client_stddev: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.rng = rng
        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)

        self.add_out_port(Port(dict, "out_client"))
        self.add_out_port(Port(dict, "out_log"))

        self._next_client_id = 1
        self._t = 0.0
        self._pending_client: Optional[Dict[str, Any]] = None
        self._pending_log: Optional[Dict[str, Any]] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._next_client_id = 1
        self._t = 0.0
        self._pending_client = {"client_id": 1, "arrival_time": 0.0}
        self._pending_log = {
            "time": 0.0,
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {"client_id": 1, "arrival_time": 0.0},
        }
        self._next_client_id = 2
        self.hold_in("EMIT", 0.0)

    def _next_interval(self) -> float:
        lo = 0.0
        hi = self.client_mean + 5.0 * self.client_stddev
        if hi < lo:
            hi = lo
        if self.client_stddev == 0.0:
            return float(clamp(self.client_mean, lo, hi))
        return sample_trunc_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)

    def lambdaf(self):
        if self._pending_client is not None:
            self.output["out_client"].add(self._pending_client)
        if self._pending_log is not None:
            self.output["out_log"].add(self._pending_log)

    def deltint(self):
        if self.phase == "EMIT":
            # Clear pending and schedule next arrival
            self._pending_client = None
            self._pending_log = None
            interval = self._next_interval()
            self.hold_in("WAIT", interval)
            return

        if self.phase == "WAIT":
            # Time advanced by sigma; update internal time and prepare next client
            interval = self.sigma  # elapsed since last state set
            self._t += float(interval)
            cid = self._next_client_id
            self._next_client_id += 1
            self._pending_client = {"client_id": cid, "arrival_time": self._t}
            self._pending_log = {
                "time": self._t,
                "event": "client_generated",
                "entity_type": "client_generator",
                "entity": "ClientGenerator",
                "payload": {"client_id": cid, "arrival_time": self._t},
            }
            self.hold_in("EMIT", 0.0)
            return

        # Default
        self.hold_in("WAIT", self._next_interval())

    def deltext(self, e):
        # No inputs
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


# ----------------------------
# Queue / dispatcher atomic
# ----------------------------
@dataclass
class ClientInfo:
    client_id: int
    arrival_time: float


class QueueDispatcher(Atomic):
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_client"))
        self.add_in_port(Port(dict, "in_employee_available"))
        self.add_out_port(Port(dict, "out_assign"))
        self.add_out_port(Port(dict, "out_log"))

        self._queue: List[ClientInfo] = []
        self._available_employees: List[int] = []  # maintain sorted for determinism

        self._pending_assignments: List[Dict[str, Any]] = []
        self._pending_logs: List[Dict[str, Any]] = []
        self._t = 0.0

        self.hold_in("PASSIVE", math.inf)

    def initialize(self):
        self._queue.clear()
        self._available_employees.clear()
        self._pending_assignments.clear()
        self._pending_logs.clear()
        self._t = 0.0
        self.hold_in("PASSIVE", math.inf)

    def _pair_as_much_as_possible(self, t: float):
        self._pending_assignments.clear()
        self._pending_logs.clear()
        # Deterministic: always pick smallest employee id first, FIFO client
        self._available_employees.sort()
        while self._queue and self._available_employees:
            emp_id = self._available_employees.pop(0)
            client = self._queue.pop(0)
            assign = {
                "employee_id": emp_id,
                "client_id": client.client_id,
                "arrival_time": client.arrival_time,
                "paired_time": t,
            }
            self._pending_assignments.append(assign)
            self._pending_logs.append(
                {
                    "time": t,
                    "event": "client_paired",
                    "entity_type": "queue",
                    "entity": "Queue",
                    "payload": {
                        "client_id": client.client_id,
                        "employee_id": emp_id,
                        "paired_time": t,
                    },
                }
            )

    def lambdaf(self):
        for a in self._pending_assignments:
            self.output["out_assign"].add(a)
        for ev in self._pending_logs:
            self.output["out_log"].add(ev)

    def deltint(self):
        # After emitting assignments, go passive
        self._pending_assignments.clear()
        self._pending_logs.clear()
        self.hold_in("PASSIVE", math.inf)

    def deltext(self, e):
        # Update internal time accumulator
        self._t += float(e)

        # Process employee availability first, then clients; pairing after all inputs
        for msg in list(self.input["in_employee_available"].values):
            if isinstance(msg, dict) and "employee_id" in msg:
                emp_id = int(msg["employee_id"])
                if emp_id not in self._available_employees:
                    self._available_employees.append(emp_id)

        for msg in list(self.input["in_client"].values):
            if isinstance(msg, dict) and "client_id" in msg and "arrival_time" in msg:
                self._queue.append(ClientInfo(int(msg["client_id"]), float(msg["arrival_time"])))

        self._pair_as_much_as_possible(self._t)
        if self._pending_assignments or self._pending_logs:
            self.hold_in("EMIT", 0.0)
        else:
            self.hold_in("PASSIVE", math.inf)

    def exit(self):
        pass


# ----------------------------
# Employee atomic
# ----------------------------
class Employee(Atomic):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        employee_id: int,
        rng: random.Random,
        service_mean: float,
        service_stddev: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.employee_id = int(employee_id)
        self.rng = rng
        self.service_mean = float(service_mean)
        self.service_stddev = float(service_stddev)

        self.add_in_port(Port(dict, "in_assign"))
        self.add_out_port(Port(dict, "out_available"))
        self.add_out_port(Port(dict, "out_log"))

        self._t = 0.0

        self._current_client_id: Optional[int] = None
        self._current_arrival_time: Optional[float] = None
        self._paired_time: Optional[float] = None

        self._pending_available_log: Optional[Dict[str, Any]] = None
        self._pending_served_log: Optional[Dict[str, Any]] = None
        self._pending_available_msg: Optional[Dict[str, Any]] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._t = 0.0
        self._current_client_id = None
        self._current_arrival_time = None
        self._paired_time = None

        # Emit initial availability at t=0
        self._pending_available_msg = {"employee_id": self.employee_id}
        self._pending_available_log = {
            "time": 0.0,
            "event": "employee_available",
            "entity_type": "employee",
            "entity": f"Employee_{self.employee_id}",
            "payload": {"employee_id": self.employee_id},
        }
        self._pending_served_log = None
        self.hold_in("EMIT_AVAILABLE", 0.0)

    def _sample_service_duration(self) -> float:
        if self.service_stddev == 0.0:
            return float(self.service_mean)
        lo = self.service_mean - 3.0 * self.service_stddev
        hi = self.service_mean + 3.0 * self.service_stddev
        if hi < lo:
            lo, hi = hi, lo
        return sample_trunc_normal(self.rng, self.service_mean, self.service_stddev, lo, hi)

    def lambdaf(self):
        if self._pending_available_msg is not None:
            self.output["out_available"].add(self._pending_available_msg)
        if self._pending_available_log is not None:
            self.output["out_log"].add(self._pending_available_log)
        if self._pending_served_log is not None:
            self.output["out_log"].add(self._pending_served_log)

    def deltint(self):
        if self.phase == "EMIT_AVAILABLE":
            self._pending_available_msg = None
            self._pending_available_log = None
            self.hold_in("IDLE", math.inf)
            return

        if self.phase == "BUSY":
            # Service completes now
            dispatched = self._t + float(self.sigma)
            self._t = dispatched

            cid = int(self._current_client_id) if self._current_client_id is not None else -1
            arrived = float(self._current_arrival_time) if self._current_arrival_time is not None else float("nan")
            delay = dispatched - arrived

            self._pending_served_log = {
                "time": dispatched,
                "event": "client_served",
                "entity_type": "employee",
                "entity": f"Employee_{self.employee_id}",
                "payload": {
                    "client_id": cid,
                    "employee_id": self.employee_id,
                    "arrived": arrived,
                    "dispatched": dispatched,
                    "delay": delay,
                },
            }

            # Become available immediately after completion
            self._current_client_id = None
            self._current_arrival_time = None
            self._paired_time = None

            self._pending_available_msg = {"employee_id": self.employee_id}
            self._pending_available_log = {
                "time": dispatched,
                "event": "employee_available",
                "entity_type": "employee",
                "entity": f"Employee_{self.employee_id}",
                "payload": {"employee_id": self.employee_id},
            }
            self.hold_in("EMIT_SERVED_AND_AVAILABLE", 0.0)
            return

        if self.phase == "EMIT_SERVED_AND_AVAILABLE":
            self._pending_served_log = None
            self._pending_available_msg = None
            self._pending_available_log = None
            self.hold_in("IDLE", math.inf)
            return

        self.hold_in("IDLE", math.inf)

    def deltext(self, e):
        self._t += float(e)

        # Accept assignment only if idle
        assigns = list(self.input["in_assign"].values)
        chosen: Optional[Dict[str, Any]] = None
        for a in assigns:
            if isinstance(a, dict) and int(a.get("employee_id", -1)) == self.employee_id:
                chosen = a
                break

        if chosen is None:
            self.hold_in(self.phase, self.sigma)
            return

        if self.phase in ("IDLE", "INIT", "EMIT_AVAILABLE", "EMIT_SERVED_AND_AVAILABLE"):
            self._current_client_id = int(chosen["client_id"])
            self._current_arrival_time = float(chosen["arrival_time"])
            self._paired_time = float(chosen["paired_time"])
            # Start service immediately; schedule completion
            dur = self._sample_service_duration()
            self._pending_available_msg = None
            self._pending_available_log = None
            self._pending_served_log = None
            self.hold_in("BUSY", dur)
        else:
            # If busy, ignore (should not happen)
            self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


# ----------------------------
# Coupled system
# ----------------------------
class StoreSystem(Coupled):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        horizon: float,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
        seed: Optional[int],
    ):
        super().__init__(name)
        self.parent = parent

        # RNGs for determinism and independence
        base_seed = 12345 if seed is None else int(seed)
        rng_gen = random.Random(base_seed + 1)
        rng_e1 = random.Random(base_seed + 2)
        rng_e2 = random.Random(base_seed + 3)

        gen = ClientGeneratorAtomic("ClientGenerator", parent=self, rng=rng_gen,
                                    client_mean=client_mean, client_stddev=client_stddev)
        queue = QueueDispatcher("Queue", parent=self)
        e1 = Employee("Employee_1", parent=self, employee_id=1, rng=rng_e1,
                      service_mean=employee_1_mean, service_stddev=employee_1_stddev)
        e2 = Employee("Employee_2", parent=self, employee_id=2, rng=rng_e2,
                      service_mean=employee_2_mean, service_stddev=employee_2_stddev)
        logger = EventLogger("Logger", parent=self, horizon=horizon)

        self.add_component(gen)
        self.add_component(queue)
        self.add_component(e1)
        self.add_component(e2)
        self.add_component(logger)

        # Couplings: generator -> queue
        self.add_coupling(gen.output["out_client"], queue.input["in_client"])
        # generator logs -> logger
        self.add_coupling(gen.output["out_log"], logger.input["in_event"])

        # employees availability -> queue
        self.add_coupling(e1.output["out_available"], queue.input["in_employee_available"])
        self.add_coupling(e2.output["out_available"], queue.input["in_employee_available"])

        # queue assignments -> employees
        self.add_coupling(queue.output["out_assign"], e1.input["in_assign"])
        self.add_coupling(queue.output["out_assign"], e2.input["in_assign"])

        # queue logs -> logger
        self.add_coupling(queue.output["out_log"], logger.input["in_event"])

        # employee logs -> logger
        self.add_coupling(e1.output["out_log"], logger.input["in_event"])
        self.add_coupling(e2.output["out_log"], logger.input["in_event"])


# ----------------------------
# Main
# ----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    horizon = parse_hhmmssmmm(args.simulation_time)

    root = StoreSystem(
        name="StoreSystem",
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

    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(horizon)


if __name__ == "__main__":
    main()