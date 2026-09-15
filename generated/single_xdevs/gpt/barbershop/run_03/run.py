#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

INF = float("inf")


def _safe_sim_time(model) -> float:
    # Try several known xdevs time locations
    for attr in ("time", "t"):
        if hasattr(model, attr):
            v = getattr(model, attr)
            if isinstance(v, (int, float)):
                return float(v)
    for clock_attr in ("clock", "_clock"):
        if hasattr(model, clock_attr):
            c = getattr(model, clock_attr)
            if c is None:
                continue
            if hasattr(c, "time"):
                try:
                    return float(getattr(c, "time"))
                except Exception:
                    pass
            if hasattr(c, "get_time") and callable(getattr(c, "get_time")):
                try:
                    return float(c.get_time())
                except Exception:
                    pass
    return 0.0


def emit_json(obj: dict) -> None:
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


def emit_state(model, field: str, value):
    emit_json(
        {
            "time": _safe_sim_time(model),
            "type": "state",
            "model": model.name,
            "field": field,
            "value": value,
        }
    )


def emit_message(model, port: str, content: str):
    emit_json(
        {
            "time": _safe_sim_time(model),
            "type": "message",
            "model": model.name,
            "port": port,
            "content": content,
        }
    )


def parse_hhmmssmm_to_seconds(s: str) -> float:
    # Format: HH:MM:SS:mm, interpret "mm" as centiseconds (0..99)
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Bad time format: {s!r}")
    hh, mm, ss, cs = (int(x) for x in parts)
    return hh * 3600.0 + mm * 60.0 + ss + (cs / 100.0)


class EventSource(Atomic):
    """
    Reads a prebuilt schedule and emits 'newcust' at specified absolute times.
    """
    def __init__(self, name: str, parent: Coupled | None, schedule_times: list[float]):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(str, "out"))

        self.times = sorted(float(t) for t in schedule_times)
        self.idx = 0
        self._pending = False  # if True, lambdaf will output one 'newcust'

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.idx = 0
        self._pending = False
        if self.times:
            # Schedule first emission at absolute time times[0]
            t0 = self.times[0]
            if t0 < 0:
                t0 = 0.0
            self.hold_in("WAIT", t0 - _safe_sim_time(self))
        else:
            self.hold_in("PASSIVE", INF)

    def lambdaf(self):
        if self._pending:
            self.output["out"].add("newcust")
            # Not required to log the source, and it is not among the three required module names.
            # Keep stdout reserved for required modules' logs; do not emit here.

    def deltint(self):
        if self.phase == "WAIT":
            # Time to emit one event
            self._pending = True
            self.hold_in("EMIT", 0.0)
            return

        if self.phase == "EMIT":
            # One event has been emitted
            self._pending = False
            self.idx += 1
            if self.idx >= len(self.times):
                self.hold_in("PASSIVE", INF)
                return
            now = _safe_sim_time(self)
            nxt = self.times[self.idx]
            dt = max(0.0, nxt - now)
            self.hold_in("WAIT", dt)
            return

        self.hold_in("PASSIVE", INF)

    def deltext(self, e):
        # No inputs
        if self.phase == "WAIT":
            rem = INF if self.sigma == INF else max(0.0, self.sigma - e)
            self.hold_in("WAIT", rem)
        else:
            # Keep current scheduling
            self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class Reception(Atomic):
    """
    reception:
      - queue capacity 8
      - check-in takes 5 seconds per customer (sequential)
      - after check-in completes, handoff to checkhair only if available; else wait.
      - upon done signal from checkhair, mark available.
    """
    def __init__(self, name: str, parent: Coupled | None, capacity: int = 8, checkin_time: float = 5.0):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "in"))      # newcust arrivals
        self.add_in_port(Port(str, "done"))    # from checkhair, content "done" indicates availability
        self.add_out_port(Port(str, "cust"))   # to checkhair, content "newcust"

        self.capacity = capacity
        self.checkin_time = float(checkin_time)

        self.queue = deque()
        self.checkhair_available = True

        self._pending_send = False

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.queue.clear()
        self.checkhair_available = True
        self._pending_send = False
        # Start idle
        self.hold_in("PASSIVE", INF)

    def lambdaf(self):
        if self.phase == "SEND" and self._pending_send:
            self.output["cust"].add("newcust")
            emit_message(self, "cust", "newcust")

    def _accept_arrivals(self, arrivals: list[str]):
        for a in arrivals:
            if a != "newcust":
                continue
            if len(self.queue) < self.capacity:
                self.queue.append("newcust")
                emit_state(self, "total customers num", len(self.queue))
            else:
                logging.warning("reception: queue full (%d), ignoring arrival", self.capacity)

    def deltint(self):
        if self.phase == "CHECKIN":
            # Check-in completed for head-of-line customer (still in queue).
            if len(self.queue) == 0:
                self.hold_in("PASSIVE", INF)
                return
            if self.checkhair_available:
                self._pending_send = True
                self.hold_in("SEND", 0.0)
            else:
                self.hold_in("WAIT_AVAIL", INF)
            return

        if self.phase == "SEND":
            # After output, actually remove customer and mark checkhair unavailable.
            if self._pending_send:
                self._pending_send = False
                if self.queue:
                    self.queue.popleft()
                    emit_state(self, "total customers num", len(self.queue))
                self.checkhair_available = False

            # Start next check-in if queue non-empty
            if len(self.queue) > 0:
                self.hold_in("CHECKIN", self.checkin_time)
            else:
                self.hold_in("PASSIVE", INF)
            return

        # PASSIVE or WAIT_AVAIL internal shouldn't happen (INF), but keep safe
        if len(self.queue) > 0 and self.phase == "PASSIVE":
            self.hold_in("CHECKIN", self.checkin_time)
        else:
            self.hold_in(self.phase, INF)

    def deltext(self, e):
        # Maintain remaining time if we were in a timed phase
        rem = INF if self.sigma == INF else max(0.0, self.sigma - e)

        arrivals = list(self.input["in"].values)
        dones = list(self.input["done"].values)

        if arrivals:
            self._accept_arrivals(arrivals)

        if dones:
            # Any done means checkhair is available again
            for d in dones:
                if d == "done":
                    self.checkhair_available = True

        # Decide next scheduling
        if self.phase == "PASSIVE":
            if len(self.queue) > 0:
                self.hold_in("CHECKIN", self.checkin_time)
            else:
                self.hold_in("PASSIVE", INF)
            return

        if self.phase == "CHECKIN":
            # Continue check-in
            self.hold_in("CHECKIN", rem)
            return

        if self.phase == "WAIT_AVAIL":
            if self.checkhair_available and len(self.queue) > 0:
                self._pending_send = True
                self.hold_in("SEND", 0.0)
            else:
                self.hold_in("WAIT_AVAIL", INF)
            return

        if self.phase == "SEND":
            # Keep immediate output
            self.hold_in("SEND", rem)
            return

        self.hold_in(self.phase, rem)

    def exit(self):
        pass


class CheckHair(Atomic):
    """
    checkhair:
      - available initially
      - receive customer from reception -> busy for 7 seconds
      - forward to cuthair
      - wait for done from cuthair
      - send done to reception, become available
    """
    def __init__(self, name: str, parent: Coupled | None, inspect_time: float = 7.0):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "cust"))       # from reception
        self.add_in_port(Port(str, "done_in"))    # from cuthair, "done"
        self.add_out_port(Port(str, "to_cut"))    # to cuthair, "newcust"
        self.add_out_port(Port(str, "to_reception"))  # to reception, "done"

        self.inspect_time = float(inspect_time)

        self._pending_to_cut = False
        self._pending_to_reception = False
        self.customer_state = None  # tracked via "customer" field; values: "newcust" or "done"

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._pending_to_cut = False
        self._pending_to_reception = False
        self.customer_state = None
        self.hold_in("AVAILABLE", INF)

    def lambdaf(self):
        if self.phase == "SEND_TO_CUT" and self._pending_to_cut:
            self.output["to_cut"].add("newcust")
            emit_message(self, "to_cut", "newcust")
        elif self.phase == "SEND_TO_RECEPTION" and self._pending_to_reception:
            self.output["to_reception"].add("done")
            emit_message(self, "to_reception", "done")

    def deltint(self):
        if self.phase == "INSPECT":
            self._pending_to_cut = True
            self.hold_in("SEND_TO_CUT", 0.0)
            return

        if self.phase == "SEND_TO_CUT":
            self._pending_to_cut = False
            self.hold_in("WAIT_DONE", INF)
            return

        if self.phase == "SEND_TO_RECEPTION":
            self._pending_to_reception = False
            # Now available again
            self.hold_in("AVAILABLE", INF)
            return

        # AVAILABLE / WAIT_DONE should be passive
        self.hold_in(self.phase, INF)

    def deltext(self, e):
        rem = INF if self.sigma == INF else max(0.0, self.sigma - e)

        incoming = list(self.input["cust"].values)
        done_in = list(self.input["done_in"].values)

        # Handle done from cutter
        if done_in:
            for d in done_in:
                if d == "done" and self.phase == "WAIT_DONE":
                    self.customer_state = "done"
                    emit_state(self, "customer", "done")
                    self._pending_to_reception = True
                    self.hold_in("SEND_TO_RECEPTION", 0.0)
                    return

        # Handle new customer from reception
        if incoming:
            # Accept only if currently AVAILABLE
            for c in incoming:
                if c != "newcust":
                    continue
                if self.phase == "AVAILABLE":
                    self.customer_state = "newcust"
                    emit_state(self, "customer", "newcust")
                    self.hold_in("INSPECT", self.inspect_time)
                    return
                else:
                    logging.warning("checkhair: received newcust while busy (%s); ignoring", self.phase)

        # Otherwise, keep current schedule
        if self.phase in ("INSPECT", "SEND_TO_CUT", "SEND_TO_RECEPTION"):
            self.hold_in(self.phase, rem)
        elif self.phase in ("AVAILABLE", "WAIT_DONE"):
            self.hold_in(self.phase, INF)
        else:
            self.hold_in(self.phase, rem)

    def exit(self):
        pass


class CutHair(Atomic):
    """
    cuthair:
      - receive customer from checkhair
      - process 20 seconds
      - signal done back to checkhair
      - maintain cumulative total done
    """
    def __init__(self, name: str, parent: Coupled | None, cut_time: float = 20.0):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "in"))    # from checkhair, "newcust"
        self.add_out_port(Port(str, "out"))  # to checkhair, "done"

        self.cut_time = float(cut_time)
        self.total_done = 0
        self._pending_done = False

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.total_done = 0
        self._pending_done = False
        self.hold_in("IDLE", INF)

    def lambdaf(self):
        if self.phase == "SEND_DONE" and self._pending_done:
            self.output["out"].add("done")
            emit_message(self, "out", "done")

    def deltint(self):
        if self.phase == "CUT":
            self.total_done += 1
            emit_state(self, "total customer done", self.total_done)
            self._pending_done = True
            self.hold_in("SEND_DONE", 0.0)
            return

        if self.phase == "SEND_DONE":
            self._pending_done = False
            self.hold_in("IDLE", INF)
            return

        self.hold_in(self.phase, INF)

    def deltext(self, e):
        rem = INF if self.sigma == INF else max(0.0, self.sigma - e)
        incoming = list(self.input["in"].values)

        if incoming:
            for c in incoming:
                if c != "newcust":
                    continue
                if self.phase == "IDLE":
                    self.hold_in("CUT", self.cut_time)
                    return
                else:
                    logging.warning("cuthair: received newcust while busy (%s); ignoring", self.phase)

        if self.phase in ("CUT", "SEND_DONE"):
            self.hold_in(self.phase, rem)
        else:
            self.hold_in(self.phase, INF)

    def exit(self):
        pass


class BarbershopSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, schedule_times: list[float]):
        super().__init__(name)
        self.parent = parent

        source = EventSource("source", parent=self, schedule_times=schedule_times)
        reception = Reception("reception", parent=self, capacity=8, checkin_time=5.0)
        checkhair = CheckHair("checkhair", parent=self, inspect_time=7.0)
        cuthair = CutHair("cuthair", parent=self, cut_time=20.0)

        self.add_component(source)
        self.add_component(reception)
        self.add_component(checkhair)
        self.add_component(cuthair)

        # Internal couplings
        self.add_coupling(source.output["out"], reception.input["in"])
        self.add_coupling(reception.output["cust"], checkhair.input["cust"])
        self.add_coupling(checkhair.output["to_cut"], cuthair.input["in"])
        self.add_coupling(cuthair.output["out"], checkhair.input["done_in"])
        self.add_coupling(checkhair.output["to_reception"], reception.input["done"])


def read_schedule_from_stdin() -> list[float]:
    times = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            time_str, event_name = line.split(None, 1)
        except ValueError:
            raise ValueError(f"Bad input line (expected 'HH:MM:SS:mm EventName'): {line!r}")
        event_name = event_name.strip()
        if event_name != "newcust":
            raise ValueError(f"Unsupported event name: {event_name!r} (only 'newcust' allowed)")
        t = parse_hhmmssmm_to_seconds(time_str)
        times.append(t)
    return times


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")

    # Consume ALL stdin lines BEFORE starting simulation
    try:
        schedule_times = read_schedule_from_stdin()
    except Exception as ex:
        logging.error("Failed to parse stdin schedule: %s", ex)
        raise

    schedule_times.sort()
    n = len(schedule_times)
    if n == 0:
        computed_upper = 0.0
    else:
        last_t = schedule_times[-1]
        computed_upper = last_t + 32.0 * n + 100.0  # safe bound

    sim_end = float(args.simulation_time)
    if computed_upper > 0 and sim_end > computed_upper:
        sim_end = computed_upper

    root = BarbershopSystem(name="system", parent=None, schedule_times=schedule_times)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(sim_end)


if __name__ == "__main__":
    main()