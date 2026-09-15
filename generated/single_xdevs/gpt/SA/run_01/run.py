#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

INF = float("inf")


def _get_time_last(model) -> float:
    return float(getattr(model, "time_last", getattr(model, "t_last", 0.0)))


def _get_time_next(model) -> float:
    tn = getattr(model, "time_next", getattr(model, "t_next", None))
    if tn is None:
        # Fallback: last + sigma if available
        tl = _get_time_last(model)
        sigma = float(getattr(model, "sigma", INF))
        return tl + sigma
    return float(tn)


def _now_external(model, e: float) -> float:
    return _get_time_last(model) + float(e)


class JsonlPrinter(Atomic):
    """
    Receives log dicts and prints to stdout as JSONL.
    Must be the ONLY component that prints to stdout.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "log_in"))
        self._buffer = []
        self.hold_in("PASSIVE", INF)

    def initialize(self):
        self._buffer.clear()
        self.hold_in("PASSIVE", INF)

    def lambdaf(self):
        # No DEVS outputs; printing is done in deltext.
        pass

    def deltint(self):
        self.hold_in("PASSIVE", INF)

    def deltext(self, e):
        for item in list(self.input["log_in"].values):
            # Enforce JSONL-only output
            try:
                sys.stdout.write(json.dumps(item) + "\n")
            except Exception:
                # If serialization fails, do not print partial non-JSON lines to stdout.
                # Emit a minimal JSON error line instead.
                fallback = {
                    "time": float(item.get("time", 0.0)) if isinstance(item, dict) else 0.0,
                    "entity": "logger",
                    "event": "serialization_error",
                    "payload": {"type": str(type(item))}
                }
                sys.stdout.write(json.dumps(fallback) + "\n")
        sys.stdout.flush()
        self.hold_in("PASSIVE", INF)

    def exit(self):
        return


class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)

        self.add_out_port(Port(dict, "pallet_out"))
        self.add_out_port(Port(dict, "log_out"))

        self._next_pallet_id = 1
        self._pending_pallet = None
        self._pending_logs = []

        self.hold_in("GEN", 0.0)

    def initialize(self):
        self._next_pallet_id = 1
        self._pending_pallet = None
        self._pending_logs.clear()
        self.hold_in("GEN", 0.0)

    def lambdaf(self):
        if self._pending_pallet is not None:
            self.output["pallet_out"].add(self._pending_pallet)
        for ev in self._pending_logs:
            self.output["log_out"].add(ev)

    def deltint(self):
        t = _get_time_next(self)

        # Clear pending outputs
        self._pending_pallet = None
        self._pending_logs.clear()

        # Generate pallet
        pid = self._next_pallet_id
        self._next_pallet_id += 1
        expiration_time = t + self.pallet_expiration_time

        pallet = {
            "pallet_id": pid,
            "gen_time": t,
            "expiration_time": expiration_time
        }

        self._pending_pallet = pallet
        self._pending_logs.append({
            "time": t,
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": pid,
                "expiration_time": expiration_time
            }
        })

        # Schedule next generation
        self.hold_in("GEN", self.pallet_interval)

    def deltext(self, e):
        # Facility has no inputs; keep schedule unchanged.
        # Reduce remaining time by elapsed (xdevs typically manages, but we re-hold for safety).
        tl = _get_time_last(self)
        tn = _get_time_next(self)
        now = _now_external(self, e)
        remaining = max(0.0, tn - now)
        self.hold_in(self.phase, remaining)

    def exit(self):
        return


class LoadingQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "pallet_in"))
        self.add_in_port(Port(dict, "request_in"))  # {"aircraft_id": int}

        self.add_out_port(Port(dict, "pallet_out"))  # {"aircraft_id": int, "pallet": dict|None}
        self.add_out_port(Port(dict, "status_out"))  # {"queue_size": int}
        self.add_out_port(Port(dict, "log_out"))

        self._q = deque()
        self._total_expired = 0

        self._emit_logs = []
        self._emit_status = []
        self._emit_pallet_msgs = []

        # For scheduled expiration event:
        self._scheduled_expiring_pallet_id = None
        self._scheduled_expiring_total = None

        self.hold_in("WAIT", INF)

    def initialize(self):
        self._q.clear()
        self._total_expired = 0
        self._emit_logs.clear()
        self._emit_status.clear()
        self._emit_pallet_msgs.clear()
        self._scheduled_expiring_pallet_id = None
        self._scheduled_expiring_total = None
        self.hold_in("WAIT", INF)

    def _schedule_next(self, now: float):
        if len(self._q) == 0:
            self._scheduled_expiring_pallet_id = None
            self._scheduled_expiring_total = None
            self.hold_in("WAIT", INF)
            return

        head = self._q[0]
        exp_t = float(head["expiration_time"])
        sigma = exp_t - now
        if sigma < 0.0:
            sigma = 0.0

        self._scheduled_expiring_pallet_id = int(head["pallet_id"])
        self._scheduled_expiring_total = int(self._total_expired + 1)

        # Use explicit EXPIRE phase to indicate expiration output at time now+sigma
        self.hold_in("EXPIRE", sigma)

    def lambdaf(self):
        # Emit pending outputs
        for msg in self._emit_pallet_msgs:
            self.output["pallet_out"].add(msg)
        for st in self._emit_status:
            self.output["status_out"].add(st)
        for ev in self._emit_logs:
            self.output["log_out"].add(ev)

        # If this is the scheduled expiration moment, output pallet_expired event.
        if self.phase == "EXPIRE":
            # Only output if still consistent (queue not empty and head matches)
            if len(self._q) > 0 and int(self._q[0]["pallet_id"]) == int(self._scheduled_expiring_pallet_id):
                t = _get_time_next(self)
                self.output["log_out"].add({
                    "time": t,
                    "entity": "queue",
                    "event": "pallet_expired",
                    "payload": {
                        "pallet_id": int(self._scheduled_expiring_pallet_id),
                        "total_expired": int(self._scheduled_expiring_total)
                    }
                })

    def deltint(self):
        t = _get_time_next(self)

        if self.phase == "EMIT":
            # Clear emitted buffers and schedule next expiration
            self._emit_logs.clear()
            self._emit_status.clear()
            self._emit_pallet_msgs.clear()
            self._schedule_next(t)
            return

        if self.phase == "EXPIRE":
            # Expire head (state change) then schedule next
            if len(self._q) > 0 and int(self._q[0]["pallet_id"]) == int(self._scheduled_expiring_pallet_id):
                self._q.popleft()
                self._total_expired += 1
                # Status update after expiration
                self._emit_status.append({"queue_size": len(self._q)})
                # Emit status via immediate internal
                self.hold_in("EMIT", 0.0)
                return

            # If mismatch, just reschedule safely
            self._schedule_next(t)
            return

        # WAIT should not internally fire (INF). Keep passive.
        self.hold_in("WAIT", INF)

    def deltext(self, e):
        now = _now_external(self, e)

        # Reset buffers for this external transition
        self._emit_logs.clear()
        self._emit_status.clear()
        self._emit_pallet_msgs.clear()

        # Active expiration guard for confluent/simultaneous events:
        # If head already expired at 'now' (<= now), expire immediately.
        while len(self._q) > 0 and float(self._q[0]["expiration_time"]) <= now:
            expired = self._q.popleft()
            self._total_expired += 1
            self._emit_logs.append({
                "time": now,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": int(expired["pallet_id"]),
                    "total_expired": int(self._total_expired)
                }
            })

        # Process new pallets
        for pallet in list(self.input["pallet_in"].values):
            self._q.append(pallet)
            self._emit_logs.append({
                "time": now,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": int(pallet["pallet_id"]),
                    "queue_size": int(len(self._q))
                }
            })

        # Process coordinator requests
        for req in list(self.input["request_in"].values):
            aid = int(req.get("aircraft_id"))
            if len(self._q) > 0:
                pallet = self._q.popleft()
                self._emit_pallet_msgs.append({"aircraft_id": aid, "pallet": pallet})
            else:
                self._emit_pallet_msgs.append({"aircraft_id": aid, "pallet": None})

        # If queue size changed (enqueue/dequeue/expire), emit status
        if len(self.input["pallet_in"].values) > 0 or len(self.input["request_in"].values) > 0 or len(self._emit_logs) > 0:
            self._emit_status.append({"queue_size": len(self._q)})

        # Emit any outputs at current time
        if self._emit_logs or self._emit_status or self._emit_pallet_msgs:
            self.hold_in("EMIT", 0.0)
        else:
            # No outputs; just reschedule next expiration relative to now
            self._schedule_next(now)

    def exit(self):
        return


class FleetCoordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = int(num_aircraft)

        self.add_in_port(Port(dict, "queue_status_in"))     # {"queue_size": int}
        self.add_in_port(Port(dict, "pallet_in"))           # {"aircraft_id": int, "pallet": dict|None}
        self.add_in_port(Port(dict, "aircraft_status_in"))  # {"aircraft_id": int, "state": str}

        self.add_out_port(Port(dict, "queue_request_out"))  # {"aircraft_id": int}
        self.add_out_port(Port(dict, "assignment_out"))     # {"aircraft_id": int, "pallet": dict, "assign_time": float}
        self.add_out_port(Port(dict, "log_out"))

        self._queue_size = 0
        self._idle_aircraft = set()
        self._outstanding_requests = set()

        self._emit_requests = []
        self._emit_assignments = []
        self._emit_logs = []

        self.hold_in("PASSIVE", INF)

    def initialize(self):
        self._queue_size = 0
        self._idle_aircraft = set(range(1, self.num_aircraft + 1))
        self._outstanding_requests.clear()
        self._emit_requests.clear()
        self._emit_assignments.clear()
        self._emit_logs.clear()
        self.hold_in("PASSIVE", INF)

    def _plan(self, now: float):
        # Create as many requests as possible given queue size and idle aircraft
        # but do not exceed queue size.
        available_idle = sorted(a for a in self._idle_aircraft if a not in self._outstanding_requests)
        can_request = min(int(self._queue_size), len(available_idle))
        for i in range(can_request):
            aid = available_idle[i]
            self._outstanding_requests.add(aid)
            self._emit_requests.append({"aircraft_id": aid})

    def lambdaf(self):
        for req in self._emit_requests:
            self.output["queue_request_out"].add(req)
        for asg in self._emit_assignments:
            self.output["assignment_out"].add(asg)
        for ev in self._emit_logs:
            self.output["log_out"].add(ev)

    def deltint(self):
        if self.phase == "EMIT":
            self._emit_requests.clear()
            self._emit_assignments.clear()
            self._emit_logs.clear()
        self.hold_in("PASSIVE", INF)

    def deltext(self, e):
        now = _now_external(self, e)

        self._emit_requests.clear()
        self._emit_assignments.clear()
        self._emit_logs.clear()

        # Queue status updates
        for st in list(self.input["queue_status_in"].values):
            if "queue_size" in st:
                self._queue_size = int(st["queue_size"])

        # Aircraft status updates (we mainly care about becoming idle)
        for st in list(self.input["aircraft_status_in"].values):
            aid = int(st.get("aircraft_id"))
            state = st.get("state")
            if state == "idle":
                self._idle_aircraft.add(aid)
            else:
                # Not idle => remove from idle set
                if aid in self._idle_aircraft:
                    self._idle_aircraft.remove(aid)

        # Pallet responses (from queue) to outstanding requests
        for msg in list(self.input["pallet_in"].values):
            aid = int(msg.get("aircraft_id"))
            pallet = msg.get("pallet")

            # Request resolved
            if aid in self._outstanding_requests:
                self._outstanding_requests.remove(aid)

            if pallet is None:
                # Queue empty, aircraft remains idle
                self._idle_aircraft.add(aid)
                continue

            # Assign pallet to aircraft
            if aid in self._idle_aircraft:
                self._idle_aircraft.remove(aid)

            pid = int(pallet["pallet_id"])
            self._emit_logs.append({
                "time": now,
                "entity": "coordinator",
                "event": "assignment_created",
                "payload": {"aircraft_id": aid, "pallet_id": pid}
            })
            self._emit_assignments.append({
                "aircraft_id": aid,
                "pallet": pallet,
                "assign_time": now
            })

        # Plan requests if possible
        self._plan(now)

        if self._emit_requests or self._emit_assignments or self._emit_logs:
            self.hold_in("EMIT", 0.0)
        else:
            self.hold_in("PASSIVE", INF)

    def exit(self):
        return


class Aircraft(Atomic):
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
        self.aircraft_id = int(aircraft_id)

        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.add_in_port(Port(dict, "assign_in"))   # {"aircraft_id": int, "pallet": dict, "assign_time": float}

        self.add_out_port(Port(dict, "status_out"))   # {"aircraft_id": int, "state": str}
        self.add_out_port(Port(dict, "log_out"))      # JSON event dict
        self.add_out_port(Port(dict, "delivery_out")) # {"aircraft_id": int, "pallet": dict, "delivery_time": float}

        self._pallet = None

        self._emit_logs = []
        self._emit_status = []
        self._emit_delivery = []

        self.hold_in("IDLE", INF)

    def initialize(self):
        self._pallet = None
        self._emit_logs.clear()
        self._emit_status.clear()
        self._emit_delivery.clear()
        # Consider idle at t=0 (coordinator also assumes so; harmless)
        self.hold_in("EMIT_IDLE", 0.0)

    def lambdaf(self):
        for ev in self._emit_logs:
            self.output["log_out"].add(ev)
        for st in self._emit_status:
            self.output["status_out"].add(st)
        for d in self._emit_delivery:
            self.output["delivery_out"].add(d)

        # Phase-specific outputs
        t = _get_time_next(self)

        if self.phase == "DEPART":
            if self._pallet is not None:
                self.output["log_out"].add({
                    "time": t,
                    "entity": "aircraft",
                    "event": "depart",
                    "payload": {
                        "aircraft_id": self.aircraft_id,
                        "pallet_id": int(self._pallet["pallet_id"])
                    }
                })

        elif self.phase == "UNLOAD":
            # Delivery occurs when unload completes (i.e., at UNLOAD's internal event time)
            if self._pallet is not None:
                self.output["delivery_out"].add({
                    "aircraft_id": self.aircraft_id,
                    "pallet": self._pallet,
                    "delivery_time": t
                })

        elif self.phase == "RETURN":
            self.output["log_out"].add({
                "time": t,
                "entity": "aircraft",
                "event": "return",
                "payload": {"aircraft_id": self.aircraft_id}
            })

        elif self.phase == "MAINT_START":
            self.output["log_out"].add({
                "time": t,
                "entity": "aircraft",
                "event": "maintenance_start",
                "payload": {"aircraft_id": self.aircraft_id}
            })

        elif self.phase == "MAINT":
            self.output["log_out"].add({
                "time": t,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {"aircraft_id": self.aircraft_id}
            })
            self.output["status_out"].add({"aircraft_id": self.aircraft_id, "state": "idle"})

        elif self.phase == "EMIT_IDLE":
            self.output["status_out"].add({"aircraft_id": self.aircraft_id, "state": "idle"})

    def deltint(self):
        t = _get_time_next(self)
        # Clear buffered emissions
        self._emit_logs.clear()
        self._emit_status.clear()
        self._emit_delivery.clear()

        if self.phase == "EMIT_IDLE":
            self.hold_in("IDLE", INF)
            return

        if self.phase == "DEPART":
            self.hold_in("FLY", self.flight_time)
            return

        if self.phase == "FLY":
            self.hold_in("UNLOAD", self.unload_time)
            return

        if self.phase == "UNLOAD":
            self.hold_in("RETURN", self.return_time)
            return

        if self.phase == "RETURN":
            self.hold_in("MAINT_START", 0.0)
            return

        if self.phase == "MAINT_START":
            self.hold_in("MAINT", self.maintenance_time)
            return

        if self.phase == "MAINT":
            # Cycle complete, clear pallet and become idle
            self._pallet = None
            self.hold_in("IDLE", INF)
            return

        # IDLE with INF shouldn't internal fire
        self.hold_in("IDLE", INF)

    def deltext(self, e):
        now = _now_external(self, e)

        # If assignment arrives, accept if idle
        for asg in list(self.input["assign_in"].values):
            if int(asg.get("aircraft_id", -1)) != self.aircraft_id:
                continue
            if self.phase != "IDLE":
                continue
            pallet = asg.get("pallet")
            if pallet is None:
                continue
            self._pallet = pallet
            # Immediate depart (loading time 0)
            self.hold_in("DEPART", 0.0)
            return

        # Otherwise keep current schedule (reduce remaining time)
        tn = _get_time_next(self)
        remaining = max(0.0, tn - now)
        self.hold_in(self.phase, remaining)

    def exit(self):
        return


class Destination(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "delivery_in"))  # {"aircraft_id": int, "pallet": dict, "delivery_time": float}
        self.add_out_port(Port(dict, "log_out"))

        self._emit_logs = []
        self.hold_in("PASSIVE", INF)

    def initialize(self):
        self._emit_logs.clear()
        self.hold_in("PASSIVE", INF)

    def lambdaf(self):
        for ev in self._emit_logs:
            self.output["log_out"].add(ev)

    def deltint(self):
        self._emit_logs.clear()
        self.hold_in("PASSIVE", INF)

    def deltext(self, e):
        now = _now_external(self, e)
        self._emit_logs.clear()

        for d in list(self.input["delivery_in"].values):
            aid = int(d.get("aircraft_id"))
            pallet = d.get("pallet")
            delivery_time = float(d.get("delivery_time", now))
            if pallet is None:
                continue
            pid = int(pallet["pallet_id"])
            gen_time = float(pallet["gen_time"])
            latency = float(delivery_time - gen_time)
            self._emit_logs.append({
                "time": delivery_time,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {"pallet_id": pid, "aircraft_id": aid, "latency": latency}
            })

        if self._emit_logs:
            self.hold_in("EMIT", 0.0)
        else:
            self.hold_in("PASSIVE", INF)

    def exit(self):
        return


class AirfreightSystem(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        *,
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
        coordinator = FleetCoordinator(name="coordinator", parent=self, num_aircraft=num_aircraft)
        destination = Destination(name="destination", parent=self)
        printer = JsonlPrinter(name="printer", parent=self)

        self.add_component(facility)
        self.add_component(queue)
        self.add_component(coordinator)
        self.add_component(destination)
        self.add_component(printer)

        aircraft_list = []
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
            aircraft_list.append(a)
            self.add_component(a)

        # Couplings: Facility -> Queue + Printer
        self.add_coupling(facility.output["pallet_out"], queue.input["pallet_in"])
        self.add_coupling(facility.output["log_out"], printer.input["log_in"])

        # Queue -> Coordinator + Printer
        self.add_coupling(queue.output["status_out"], coordinator.input["queue_status_in"])
        self.add_coupling(queue.output["pallet_out"], coordinator.input["pallet_in"])
        self.add_coupling(queue.output["log_out"], printer.input["log_in"])

        # Coordinator -> Queue + Aircraft + Printer
        self.add_coupling(coordinator.output["queue_request_out"], queue.input["request_in"])
        self.add_coupling(coordinator.output["log_out"], printer.input["log_in"])
        for a in aircraft_list:
            self.add_coupling(coordinator.output["assignment_out"], a.input["assign_in"])

        # Aircraft -> Destination + Coordinator + Printer
        for a in aircraft_list:
            self.add_coupling(a.output["delivery_out"], destination.input["delivery_in"])
            self.add_coupling(a.output["status_out"], coordinator.input["aircraft_status_in"])
            self.add_coupling(a.output["log_out"], printer.input["log_in"])

        # Destination -> Printer
        self.add_coupling(destination.output["log_out"], printer.input["log_in"])


def _validate_args(args) -> None:
    if args.duration <= 0:
        raise ValueError("--duration must be > 0")
    if args.num_aircraft < 1:
        raise ValueError("--num_aircraft must be >= 1")
    if args.pallet_interval <= 0:
        raise ValueError("--pallet_interval must be > 0")
    if args.pallet_expiration_time < 0:
        raise ValueError("--pallet_expiration_time must be >= 0")
    for k in ["flight_time", "unload_time", "return_time", "maintenance_time"]:
        if getattr(args, k) < 0:
            raise ValueError(f"--{k} must be >= 0")

    # Runtime safeguard: refuse extremely large configurations that could violate 10s constraint
    # (approximate event count upper bound).
    trip_cycle = args.flight_time + args.unload_time + args.return_time + args.maintenance_time
    trip_cycle = max(trip_cycle, 1e-9)
    est_pallets = args.duration / args.pallet_interval
    est_trips = (args.duration / trip_cycle) * args.num_aircraft
    # Each pallet yields ~3 events (generated, queued, then delivered/expired).
    # Each trip yields ~4 aircraft events + 1 delivery.
    est_events = 3.0 * est_pallets + 5.0 * est_trips
    if est_events > 500000:
        raise ValueError(
            "Configuration too large (estimated events > 500000). "
            "Adjust --duration/--pallet_interval or timing parameters."
        )


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")

    parser = argparse.ArgumentParser(description="Airfreight Logistics Operations (DEVS, xdevs.py)")
    parser.add_argument("--duration", type=float, default=10000.0)
    parser.add_argument("--num_aircraft", type=int, default=2)
    parser.add_argument("--pallet_interval", type=float, default=25.0)
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0)
    parser.add_argument("--flight_time", type=float, default=30.0)
    parser.add_argument("--unload_time", type=float, default=2.0)
    parser.add_argument("--return_time", type=float, default=30.0)
    parser.add_argument("--maintenance_time", type=float, default=10.0)
    args = parser.parse_args()

    try:
        _validate_args(args)
    except Exception as ex:
        print(f"ERROR: {ex}", file=sys.stderr, flush=True)
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