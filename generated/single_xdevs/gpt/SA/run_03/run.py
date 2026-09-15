#!/usr/bin/env python3
# run.py - Airfreight Logistics Operations simulation using xdevs.py (Formal DEVS)

import argparse
import sys
import json
import logging
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# ----------------------------
# JSONL event emission (stdout)
# ----------------------------
def emit(time_value: float, entity: str, event: str, payload: dict):
    obj = {
        "time": float(time_value),
        "entity": str(entity),
        "event": str(event),
        "payload": payload if isinstance(payload, dict) else {},
    }
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


INF = float("inf")
EPS = 1e-9


# ----------------------------
# Atomic Models
# ----------------------------
class Facility(Atomic):
    """
    Generates pallets every pallet_interval starting at t=0.
    Outputs pallet dict to queue.
    Logs pallet_generated (facility).
    """

    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "out_pallet"))

        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)

        self.now = 0.0
        self.next_pallet_id = 1
        self._next_pallet = None  # prepared for next lambdaf output

    def _prepare_pallet_for_time(self, gen_time: float):
        pid = self.next_pallet_id
        exp_time = gen_time + self.pallet_expiration_time
        self._next_pallet = {
            "pallet_id": pid,
            "gen_time": float(gen_time),
            "expiration_time": float(exp_time),
        }

    def initialize(self):
        self.now = 0.0
        self.next_pallet_id = 1
        self._prepare_pallet_for_time(0.0)
        self.hold_in("GENERATE", 0.0)

    def lambdaf(self):
        if self.phase == "GENERATE" and self._next_pallet is not None:
            self.output["out_pallet"].add(self._next_pallet)

    def deltint(self):
        # Advance local time to current event time
        self.now = self.now + float(self.sigma)

        if self.phase == "GENERATE" and self._next_pallet is not None:
            # Log generation at the actual generation time (= self.now)
            emit(
                self.now,
                "facility",
                "pallet_generated",
                {
                    "pallet_id": int(self._next_pallet["pallet_id"]),
                    "expiration_time": float(self._next_pallet["expiration_time"]),
                },
            )

            # Prepare next pallet for next scheduled generation
            self.next_pallet_id += 1
            next_gen_time = self.now + self.pallet_interval
            self._prepare_pallet_for_time(next_gen_time)
            self.hold_in("GENERATE", self.pallet_interval)
        else:
            self.hold_in("GENERATE", self.pallet_interval)

    def deltext(self, e):
        # Facility has no inputs; just advance time
        self.now += float(e)
        # Keep current scheduling
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class LoadingQueue(Atomic):
    """
    Holds pallets awaiting assignment. Pallets expire while in queue.
    FIFO, expiration order matches FIFO because expiration_time = gen_time + constant.
    Responds to dequeue requests from coordinator and emits:
      - out_dequeued: {"aircraft_id": int, "pallet": dict|None, "queue_size": int}
      - out_queue_state: {"queue_size": int}
    Logs:
      - pallet_queued (queue)
      - pallet_expired (queue)
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_pallet"))
        self.add_in_port(Port(dict, "in_dequeue"))

        self.add_out_port(Port(dict, "out_dequeued"))
        self.add_out_port(Port(dict, "out_queue_state"))

        self.now = 0.0
        self.q = deque()  # each element: {"pallet_id", "gen_time", "expiration_time"}
        self.total_expired = 0

        # Pending outputs (emitted on phase OUTPUT)
        self._pending_dequeued = []
        self._pending_emit_state = False

    def _schedule_next(self):
        # Decide next internal event after outputs have been sent / no immediate outputs.
        if len(self.q) == 0:
            self.hold_in("WAIT", INF)
            return
        head_exp = float(self.q[0]["expiration_time"])
        dt = head_exp - self.now
        if dt < 0.0:
            dt = 0.0
        self.hold_in("EXPIRE", dt)

    def initialize(self):
        self.now = 0.0
        self.q.clear()
        self.total_expired = 0
        self._pending_dequeued = []
        self._pending_emit_state = False
        self.hold_in("WAIT", INF)

    def lambdaf(self):
        if self.phase != "OUTPUT":
            return

        # Emit dequeue responses (possibly multiple in same time)
        for msg in self._pending_dequeued:
            self.output["out_dequeued"].add(msg)

        # Emit queue state if requested
        if self._pending_emit_state:
            self.output["out_queue_state"].add({"queue_size": int(len(self.q))})

    def deltint(self):
        # Advance local time to current event time
        self.now = self.now + float(self.sigma)

        if self.phase == "OUTPUT":
            # Clear pending outputs and schedule next expiration
            self._pending_dequeued = []
            self._pending_emit_state = False
            self._schedule_next()
            return

        if self.phase == "EXPIRE":
            # Expire all pallets whose deadline is now (or in the past due to numeric issues)
            expired_any = False
            while self.q and float(self.q[0]["expiration_time"]) <= self.now + EPS:
                p = self.q.popleft()
                self.total_expired += 1
                expired_any = True
                emit(
                    self.now,
                    "queue",
                    "pallet_expired",
                    {"pallet_id": int(p["pallet_id"]), "total_expired": int(self.total_expired)},
                )

            if expired_any:
                self._pending_emit_state = True
                self.hold_in("OUTPUT", 0.0)
            else:
                # Shouldn't happen, but keep consistent
                self._schedule_next()
            return

        # WAIT or any other: just re-schedule
        self._schedule_next()

    def deltext(self, e):
        self.now += float(e)

        state_changed = False

        # Handle incoming pallets
        for pallet in list(self.input["in_pallet"].values):
            # pallet: {"pallet_id","gen_time","expiration_time"}
            self.q.append(pallet)
            state_changed = True
            emit(
                self.now,
                "queue",
                "pallet_queued",
                {"pallet_id": int(pallet["pallet_id"]), "queue_size": int(len(self.q))},
            )

        # Handle dequeue requests
        for req in list(self.input["in_dequeue"].values):
            # req: {"aircraft_id": int}
            aid = int(req.get("aircraft_id"))
            if self.q:
                pallet = self.q.popleft()
                state_changed = True
                self._pending_dequeued.append(
                    {"aircraft_id": aid, "pallet": pallet, "queue_size": int(len(self.q))}
                )
            else:
                # Respond even if empty, so coordinator can clear "requesting"
                self._pending_dequeued.append({"aircraft_id": aid, "pallet": None, "queue_size": 0})

        if state_changed:
            self._pending_emit_state = True

        # If we have any immediate outputs to emit, do it now at the same simulation time
        if self._pending_dequeued or self._pending_emit_state:
            self.hold_in("OUTPUT", 0.0)
        else:
            # No output needed; reschedule next expiration considering updated time
            self._schedule_next()

    def exit(self):
        pass


class FleetCoordinator(Atomic):
    """
    Matches idle aircraft with queue pallets by requesting dequeues and then assigning.
    Logs assignment_created (coordinator).
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_queue_state"))
        self.add_in_port(Port(dict, "in_dequeued"))
        self.add_in_port(Port(dict, "in_aircraft_status"))

        self.add_out_port(Port(dict, "out_dequeue"))
        self.add_out_port(Port(dict, "out_assign"))

        self.now = 0.0

        self.queue_size = 0
        self.idle_aircraft = set()
        self.requesting = set()

        self._pending_dequeue = []  # list of {"aircraft_id": int}
        self._pending_assign = []   # list of {"aircraft_id": int, "pallet": dict}
        self._pending_assign_logs = []  # list of (aircraft_id, pallet_id)

    def initialize(self):
        self.now = 0.0
        self.queue_size = 0
        self.idle_aircraft = set()
        self.requesting = set()
        self._pending_dequeue = []
        self._pending_assign = []
        self._pending_assign_logs = []
        self.hold_in("IDLE", INF)

    def _plan(self):
        # Plan dequeues for idle aircraft if queue has pallets available beyond outstanding requests
        available_aircraft = sorted(self.idle_aircraft - self.requesting)
        available_pallets = max(int(self.queue_size) - len(self.requesting), 0)
        if available_pallets <= 0 or not available_aircraft:
            return

        n = min(len(available_aircraft), available_pallets)
        for i in range(n):
            aid = int(available_aircraft[i])
            self.requesting.add(aid)
            self._pending_dequeue.append({"aircraft_id": aid})

    def lambdaf(self):
        if self.phase != "ACTION":
            return
        for msg in self._pending_dequeue:
            self.output["out_dequeue"].add(msg)
        for msg in self._pending_assign:
            self.output["out_assign"].add(msg)

    def deltint(self):
        self.now = self.now + float(self.sigma)

        if self.phase == "ACTION":
            # Log assignment_created at the exact assignment (send) time
            for aid, pid in self._pending_assign_logs:
                emit(self.now, "coordinator", "assignment_created", {"aircraft_id": int(aid), "pallet_id": int(pid)})

            # Clear pending actions
            self._pending_dequeue = []
            self._pending_assign = []
            self._pending_assign_logs = []

            # Passivate until new information arrives
            self.hold_in("IDLE", INF)
            return

        self.hold_in("IDLE", INF)

    def deltext(self, e):
        self.now += float(e)

        changed = False

        # Queue size updates
        for msg in list(self.input["in_queue_state"].values):
            qs = int(msg.get("queue_size", 0))
            if qs != self.queue_size:
                self.queue_size = qs
                changed = True

        # Aircraft status updates
        for msg in list(self.input["in_aircraft_status"].values):
            aid = int(msg.get("aircraft_id"))
            status = msg.get("status")
            if status == "idle":
                if aid not in self.idle_aircraft:
                    self.idle_aircraft.add(aid)
                    changed = True

        # Dequeued responses
        for msg in list(self.input["in_dequeued"].values):
            aid = int(msg.get("aircraft_id"))
            # clear requesting for this aircraft
            if aid in self.requesting:
                self.requesting.remove(aid)
                changed = True

            # update queue size using authoritative value if provided
            if "queue_size" in msg:
                qs = int(msg.get("queue_size", 0))
                if qs != self.queue_size:
                    self.queue_size = qs
                    changed = True

            pallet = msg.get("pallet")
            if pallet is not None:
                # schedule assignment to this aircraft
                pid = int(pallet["pallet_id"])
                if aid in self.idle_aircraft:
                    self.idle_aircraft.remove(aid)  # will be busy
                self._pending_assign.append({"aircraft_id": aid, "pallet": pallet})
                self._pending_assign_logs.append((aid, pid))
                changed = True
            else:
                # no pallet available; aircraft remains idle and can be planned again
                self.idle_aircraft.add(aid)

        # Plan any dequeue requests if possible
        self._plan()

        if self._pending_dequeue or self._pending_assign:
            self.hold_in("ACTION", 0.0)
        else:
            # remain idle
            self.hold_in("IDLE", INF)

    def exit(self):
        pass


class Aircraft(Atomic):
    """
    Aircraft lifecycle:
      INIT (emit idle) -> IDLE
      On assignment: DEPART(0) -> FLY(flight_time) -> UNLOAD(unload_time) -> RETURN(return_time) -> MAINT(maintenance_time) -> IDLE
    Logs:
      - depart
      - return
      - maintenance_start
      - maintenance_end
    Sends:
      - out_status: {"aircraft_id": int, "status":"idle"} on INIT and at maintenance end
      - out_delivery: {"pallet_id", "aircraft_id", "gen_time", "delivery_time"} at unload completion (lambdaf)
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_assign"))
        self.add_out_port(Port(dict, "out_status"))
        self.add_out_port(Port(dict, "out_delivery"))

        self.aircraft_id = int(aircraft_id)

        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.now = 0.0
        self.pallet = None  # current pallet dict when assigned

    def initialize(self):
        self.now = 0.0
        self.pallet = None
        self.hold_in("INIT", 0.0)

    def lambdaf(self):
        t_event = self.now + float(self.sigma)

        if self.phase == "INIT":
            self.output["out_status"].add({"aircraft_id": self.aircraft_id, "status": "idle"})

        elif self.phase == "UNLOAD" and self.pallet is not None:
            # Unload completes at t_event; delivery is recorded then
            self.output["out_delivery"].add(
                {
                    "pallet_id": int(self.pallet["pallet_id"]),
                    "aircraft_id": int(self.aircraft_id),
                    "gen_time": float(self.pallet["gen_time"]),
                    "delivery_time": float(t_event),
                }
            )

        elif self.phase == "MAINTENANCE":
            # Maintenance ends at t_event; aircraft becomes idle
            self.output["out_status"].add({"aircraft_id": self.aircraft_id, "status": "idle"})

    def deltint(self):
        # Advance local time to current event time
        self.now = self.now + float(self.sigma)

        if self.phase == "INIT":
            self.hold_in("IDLE", INF)
            return

        if self.phase == "DEPART":
            # Depart with assigned pallet (loading is instantaneous)
            pid = int(self.pallet["pallet_id"]) if self.pallet is not None else None
            emit(self.now, "aircraft", "depart", {"aircraft_id": int(self.aircraft_id), "pallet_id": int(pid)})
            self.hold_in("FLY", self.flight_time)
            return

        if self.phase == "FLY":
            self.hold_in("UNLOAD", self.unload_time)
            return

        if self.phase == "UNLOAD":
            # delivery already emitted in lambdaf at this same time
            self.hold_in("RETURN", self.return_time)
            return

        if self.phase == "RETURN":
            emit(self.now, "aircraft", "return", {"aircraft_id": int(self.aircraft_id)})
            emit(self.now, "aircraft", "maintenance_start", {"aircraft_id": int(self.aircraft_id)})
            self.hold_in("MAINTENANCE", self.maintenance_time)
            return

        if self.phase == "MAINTENANCE":
            emit(self.now, "aircraft", "maintenance_end", {"aircraft_id": int(self.aircraft_id)})
            # trip complete, clear pallet, go idle
            self.pallet = None
            self.hold_in("IDLE", INF)
            return

        # IDLE or unknown
        self.hold_in("IDLE", INF)

    def deltext(self, e):
        self.now += float(e)

        if self.phase == "IDLE":
            for msg in list(self.input["in_assign"].values):
                if int(msg.get("aircraft_id", -1)) != self.aircraft_id:
                    continue
                pallet = msg.get("pallet")
                if pallet is None:
                    continue
                # accept assignment
                self.pallet = pallet
                self.hold_in("DEPART", 0.0)
                return

        else:
            # If busy, ignore assignments (should not happen)
            pass

        # Keep current schedule
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class Destination(Atomic):
    """
    Receives delivery notifications and logs pallet_delivered (destination).
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_delivery"))

        self.now = 0.0

    def initialize(self):
        self.now = 0.0
        self.hold_in("PASSIVE", INF)

    def lambdaf(self):
        # No DEVS outputs needed
        return

    def deltint(self):
        self.now = self.now + float(self.sigma)
        self.hold_in("PASSIVE", INF)

    def deltext(self, e):
        self.now += float(e)

        for msg in list(self.input["in_delivery"].values):
            pid = int(msg["pallet_id"])
            aid = int(msg["aircraft_id"])
            gen_time = float(msg["gen_time"])
            # delivery_time in msg should match self.now, but use self.now as authoritative local time
            latency = self.now - gen_time
            emit(
                self.now,
                "destination",
                "pallet_delivered",
                {"pallet_id": pid, "aircraft_id": aid, "latency": float(latency)},
            )

        self.hold_in("PASSIVE", INF)

    def exit(self):
        pass


# ----------------------------
# Coupled System
# ----------------------------
class AirfreightSystem(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        num_aircraft: int,
        pallet_interval: float,
        pallet_expiration_time: float,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        facility = Facility(
            name="facility",
            parent=self,
            pallet_interval=pallet_interval,
            pallet_expiration_time=pallet_expiration_time,
        )
        queue = LoadingQueue(name="queue", parent=self)
        coordinator = FleetCoordinator(name="coordinator", parent=self)
        destination = Destination(name="destination", parent=self)

        self.add_component(facility)
        self.add_component(queue)
        self.add_component(coordinator)
        self.add_component(destination)

        aircraft_models = []
        for i in range(1, int(num_aircraft) + 1):
            a = Aircraft(
                name=f"aircraft_{i}",
                parent=self,
                aircraft_id=i,
                flight_time=flight_time,
                unload_time=unload_time,
                return_time=return_time,
                maintenance_time=maintenance_time,
            )
            aircraft_models.append(a)
            self.add_component(a)

        # Couplings
        self.add_coupling(facility.output["out_pallet"], queue.input["in_pallet"])

        self.add_coupling(queue.output["out_queue_state"], coordinator.input["in_queue_state"])
        self.add_coupling(coordinator.output["out_dequeue"], queue.input["in_dequeue"])
        self.add_coupling(queue.output["out_dequeued"], coordinator.input["in_dequeued"])

        for a in aircraft_models:
            self.add_coupling(coordinator.output["out_assign"], a.input["in_assign"])
            self.add_coupling(a.output["out_status"], coordinator.input["in_aircraft_status"])
            self.add_coupling(a.output["out_delivery"], destination.input["in_delivery"])


# ----------------------------
# Entry point
# ----------------------------
def main():
    parser = argparse.ArgumentParser(description="Airfreight logistics simulation (xdevs.py)")

    parser.add_argument("--duration", type=float, default=10000.0)
    parser.add_argument("--num_aircraft", type=int, default=2)
    parser.add_argument("--pallet_interval", type=float, default=25.0)
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0)
    parser.add_argument("--flight_time", type=float, default=30.0)
    parser.add_argument("--unload_time", type=float, default=2.0)
    parser.add_argument("--return_time", type=float, default=30.0)
    parser.add_argument("--maintenance_time", type=float, default=10.0)

    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")

    if args.num_aircraft < 1:
        logging.error("--num_aircraft must be >= 1")
        sys.exit(2)
    if args.duration < 0:
        logging.error("--duration must be >= 0")
        sys.exit(2)

    root = AirfreightSystem(
        name="system",
        parent=None,
        num_aircraft=args.num_aircraft,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        flight_time=args.flight_time,
        unload_time=args.unload_time,
        return_time=args.return_time,
        maintenance_time=args.maintenance_time,
    )

    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.duration))


if __name__ == "__main__":
    main()