#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from typing import List, Optional

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# -----------------------
# JSONL emission helpers
# -----------------------

def _emit(obj: dict) -> None:
    # STDOUT must contain ONLY JSON objects (JSONL)
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _t_round(t: float) -> float:
    # Keep stable timestamps for JSON
    return round(float(t), 6)


def emit_state(time_s: float, model: str, field: str, value) -> None:
    _emit({
        "time": _t_round(time_s),
        "type": "state",
        "model": model,
        "field": field,
        "value": value
    })


def emit_message(time_s: float, model: str, port: str, content: str) -> None:
    _emit({
        "time": _t_round(time_s),
        "type": "message",
        "model": model,
        "port": port,
        "content": content
    })


# -----------------------
# Utilities
# -----------------------

def parse_time_to_ticks(hhmmssmm: str) -> int:
    """
    Parse 'HH:MM:SS:mm' into integer centiseconds (ticks of 0.01 s).
    """
    parts = hhmmssmm.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format (expected HH:MM:SS:mm): {hhmmssmm!r}")
    hh, mm, ss, cs = (int(x) for x in parts)
    if not (0 <= mm < 60 and 0 <= ss < 60 and 0 <= cs < 100 and hh >= 0):
        raise ValueError(f"Out-of-range time fields: {hhmmssmm!r}")
    return ((hh * 60 + mm) * 60 + ss) * 100 + cs


def ticks_to_seconds(ticks: int) -> float:
    return ticks / 100.0


# -----------------------
# Atomic Models
# -----------------------

class ArrivalGenerator(Atomic):
    """
    Generates 'newcust' events at scheduled times (read entirely from stdin before start).
    Silent model (does not emit JSON logs), per required output contract focusing on business modules.
    """
    def __init__(self, name: str, parent: Optional[Coupled], schedule_ticks: List[int]):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(str, "out"))

        self.schedule_ticks = schedule_ticks
        self.idx = 0
        self._curr_tick = 0  # current event tick for internal processing

    def initialize(self):
        self.idx = 0
        self._curr_tick = 0
        if self.idx < len(self.schedule_ticks):
            next_tick = self.schedule_ticks[self.idx]
            sigma = max(0.0, ticks_to_seconds(next_tick - 0))
            self.hold_in("GEN", sigma)
        else:
            self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase != "GEN":
            return
        # At this internal time, output all arrivals scheduled for the same tick
        if self.idx >= len(self.schedule_ticks):
            return

        # Determine current tick from the schedule itself (avoid float drift)
        curr_tick = self.schedule_ticks[self.idx]
        j = self.idx
        while j < len(self.schedule_ticks) and self.schedule_ticks[j] == curr_tick:
            self.output["out"].add("newcust")
            j += 1

    def deltint(self):
        if self.phase != "GEN":
            self.hold_in("PASSIVE", float("inf"))
            return

        if self.idx >= len(self.schedule_ticks):
            self.hold_in("PASSIVE", float("inf"))
            return

        curr_tick = self.schedule_ticks[self.idx]
        j = self.idx
        while j < len(self.schedule_ticks) and self.schedule_ticks[j] == curr_tick:
            j += 1
        self.idx = j
        self._curr_tick = curr_tick

        if self.idx < len(self.schedule_ticks):
            next_tick = self.schedule_ticks[self.idx]
            sigma = max(0.0, ticks_to_seconds(next_tick - curr_tick))
            self.hold_in("GEN", sigma)
        else:
            self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        # No inputs
        rem = float("inf")
        if self.sigma != float("inf"):
            rem = max(0.0, self.sigma - float(e))
        self.hold_in(self.phase, rem)

    def exit(self):
        pass


class Reception(Atomic):
    """
    Reception Desk:
      - Capacity 8 in waiting area
      - Check-in: 5 seconds per customer (first in queue)
      - After check-in: handoff to checkhair ONLY when checkhair is available
      - Receives "done" from checkhair as availability signal
    """
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "in"))        # arrivals: "newcust"
        self.add_in_port(Port(str, "done"))      # from checkhair: "done"
        self.add_out_port(Port(str, "cust"))     # to checkhair: "newcust"

        self.queue_count = 0
        self.checkhair_available = True

    def _now_int(self) -> float:
        return _t_round(getattr(self, "t_next", 0.0))

    def _now_ext(self, e: float) -> float:
        t_last = float(getattr(self, "t_last", 0.0))
        return _t_round(t_last + float(e))

    def initialize(self):
        self.queue_count = 0
        self.checkhair_available = True
        self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        now = self._now_int()
        # Output only in SEND, or at CHECKIN completion if available
        if self.phase == "SEND":
            self.output["cust"].add("newcust")
            emit_message(now, "reception", "cust", "newcust")
        elif self.phase == "CHECKIN":
            if self.queue_count > 0 and self.checkhair_available:
                self.output["cust"].add("newcust")
                emit_message(now, "reception", "cust", "newcust")

    def deltint(self):
        now = self._now_int()

        if self.phase == "IDLE":
            # Shouldn't have internal events here
            self.hold_in("IDLE", float("inf"))
            return

        if self.phase == "CHECKIN":
            if self.queue_count > 0 and self.checkhair_available:
                # Handoff occurs
                self.queue_count -= 1
                emit_state(now, "reception", "total customers num", self.queue_count)
                self.checkhair_available = False

                if self.queue_count > 0:
                    self.hold_in("CHECKIN", 5.0)
                else:
                    self.hold_in("IDLE", float("inf"))
            else:
                # Check-in completed but barber not available
                self.hold_in("WAIT_BARBER", float("inf"))
            return

        if self.phase == "WAIT_BARBER":
            # No internal transitions expected while waiting
            self.hold_in("WAIT_BARBER", float("inf"))
            return

        if self.phase == "SEND":
            # After immediate send, update queue and schedule next check-in (or idle)
            if self.queue_count > 0:
                self.queue_count -= 1
                emit_state(now, "reception", "total customers num", self.queue_count)
                self.checkhair_available = False
            else:
                # Nothing to send (shouldn't happen)
                logging.warning("Reception SEND phase but queue_count==0 at t=%.6f", now)

            if self.queue_count > 0:
                self.hold_in("CHECKIN", 5.0)
            else:
                self.hold_in("IDLE", float("inf"))
            return

        # Fallback
        self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        now = self._now_ext(e)

        # Adjust remaining time if staying in same phase
        rem = float("inf")
        if self.sigma != float("inf"):
            rem = max(0.0, float(self.sigma) - float(e))

        # Process done signals (availability)
        done_vals = list(self.input["done"].values) if "done" in self.input else []
        if done_vals:
            # Any "done" means checkhair becomes available
            self.checkhair_available = True

        # Process arrivals
        arrivals = list(self.input["in"].values) if "in" in self.input else []
        if arrivals:
            for msg in arrivals:
                if msg != "newcust":
                    continue
                if self.queue_count < 8:
                    self.queue_count += 1
                    emit_state(now, "reception", "total customers num", self.queue_count)
                else:
                    # Ignore if full
                    pass

        # State/phase logic after inputs
        if self.phase == "IDLE":
            if self.queue_count > 0:
                self.hold_in("CHECKIN", 5.0)
            else:
                self.hold_in("IDLE", float("inf"))
            return

        if self.phase == "WAIT_BARBER":
            # If barber became available and we have a checked-in customer waiting, send immediately
            if self.checkhair_available and self.queue_count > 0:
                self.hold_in("SEND", 0.0)
            else:
                self.hold_in("WAIT_BARBER", float("inf"))
            return

        if self.phase == "CHECKIN":
            # Continue check-in; availability may have changed but does not preempt check-in
            self.hold_in("CHECKIN", rem)
            return

        if self.phase == "SEND":
            # Already scheduled to send immediately; keep it
            self.hold_in("SEND", 0.0)
            return

        # Fallback
        if self.queue_count > 0:
            self.hold_in("CHECKIN", 5.0)
        else:
            self.hold_in("IDLE", float("inf"))

    def exit(self):
        pass


class CheckHair(Atomic):
    """
    Hair Inspection:
      - Receives newcust from reception when available
      - Consultation 7 sec
      - Forwards to cutting
      - Waits for done from cuthair
      - Then notifies reception ("done") and becomes available again
    """
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "cust"))          # from reception: "newcust"
        self.add_in_port(Port(str, "done"))          # from cuthair: "done"
        self.add_out_port(Port(str, "to_cut"))       # to cuthair: "newcust"
        self.add_out_port(Port(str, "to_reception")) # to reception: "done"

        self.customer_status: Optional[str] = None  # tracked state: "newcust" or "done"

    def _now_int(self) -> float:
        return _t_round(getattr(self, "t_next", 0.0))

    def _now_ext(self, e: float) -> float:
        t_last = float(getattr(self, "t_last", 0.0))
        return _t_round(t_last + float(e))

    def initialize(self):
        self.customer_status = None
        self.hold_in("AVAILABLE", float("inf"))

    def lambdaf(self):
        now = self._now_int()
        if self.phase == "CONSULT":
            # Consultation complete => forward to cutting
            self.output["to_cut"].add("newcust")
            emit_message(now, "checkhair", "to_cut", "newcust")
        elif self.phase == "NOTIFY":
            # Notify reception that full service done
            self.output["to_reception"].add("done")
            emit_message(now, "checkhair", "to_reception", "done")

    def deltint(self):
        if self.phase == "CONSULT":
            self.hold_in("WAIT_DONE", float("inf"))
            return
        if self.phase == "NOTIFY":
            # Become available only AFTER notification
            self.customer_status = None
            self.hold_in("AVAILABLE", float("inf"))
            return
        if self.phase == "AVAILABLE":
            self.hold_in("AVAILABLE", float("inf"))
            return
        if self.phase == "WAIT_DONE":
            self.hold_in("WAIT_DONE", float("inf"))
            return
        self.hold_in("AVAILABLE", float("inf"))

    def deltext(self, e):
        now = self._now_ext(e)

        rem = float("inf")
        if self.sigma != float("inf"):
            rem = max(0.0, float(self.sigma) - float(e))

        # Handle incoming customer
        cust_vals = list(self.input["cust"].values) if "cust" in self.input else []
        if cust_vals:
            for msg in cust_vals:
                if msg != "newcust":
                    continue
                if self.phase == "AVAILABLE":
                    self.customer_status = "newcust"
                    emit_state(now, "checkhair", "customer", "newcust")
                    self.hold_in("CONSULT", 7.0)
                    return
                else:
                    # Should not happen given reception gating; ignore
                    logging.warning("checkhair received newcust while busy (phase=%s) at t=%.6f", self.phase, now)

        # Handle done from cuthair
        done_vals = list(self.input["done"].values) if "done" in self.input else []
        if done_vals:
            for msg in done_vals:
                if msg != "done":
                    continue
                if self.phase == "WAIT_DONE":
                    self.customer_status = "done"
                    emit_state(now, "checkhair", "customer", "done")
                    self.hold_in("NOTIFY", 0.0)
                    return
                else:
                    # If done arrives unexpectedly, ignore
                    logging.warning("checkhair received done while phase=%s at t=%.6f", self.phase, now)

        # No relevant input; continue current phase with remaining time
        self.hold_in(self.phase, rem)

    def exit(self):
        pass


class CutHair(Atomic):
    """
    Hair Cutting:
      - Receives newcust from checkhair
      - Cutting 20 sec
      - Signals done back to checkhair
      - Tracks cumulative count of total customer done
    """
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "in"))     # from checkhair: "newcust"
        self.add_out_port(Port(str, "out"))   # to checkhair: "done"

        self.total_done = 0

    def _now_int(self) -> float:
        return _t_round(getattr(self, "t_next", 0.0))

    def _now_ext(self, e: float) -> float:
        t_last = float(getattr(self, "t_last", 0.0))
        return _t_round(t_last + float(e))

    def initialize(self):
        self.total_done = 0
        self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        now = self._now_int()
        if self.phase == "CUT":
            self.output["out"].add("done")
            emit_message(now, "cuthair", "out", "done")

    def deltint(self):
        now = self._now_int()
        if self.phase == "CUT":
            self.total_done += 1
            emit_state(now, "cuthair", "total customer done", self.total_done)
            self.hold_in("IDLE", float("inf"))
            return
        self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        now = self._now_ext(e)

        rem = float("inf")
        if self.sigma != float("inf"):
            rem = max(0.0, float(self.sigma) - float(e))

        in_vals = list(self.input["in"].values) if "in" in self.input else []
        if in_vals:
            for msg in in_vals:
                if msg != "newcust":
                    continue
                if self.phase == "IDLE":
                    self.hold_in("CUT", 20.0)
                    return
                else:
                    logging.warning("cuthair received newcust while busy (phase=%s) at t=%.6f", self.phase, now)

        # no relevant input
        self.hold_in(self.phase, rem)

    def exit(self):
        pass


# -----------------------
# Coupled System
# -----------------------

class System(Coupled):
    def __init__(self, name: str, parent: Optional[Coupled], schedule_ticks: List[int]):
        super().__init__(name)
        self.parent = parent

        gen = ArrivalGenerator(name="generator", parent=self, schedule_ticks=schedule_ticks)
        reception = Reception(name="reception", parent=self)
        checkhair = CheckHair(name="checkhair", parent=self)
        cuthair = CutHair(name="cuthair", parent=self)

        self.add_component(gen)
        self.add_component(reception)
        self.add_component(checkhair)
        self.add_component(cuthair)

        # Internal couplings
        self.add_coupling(gen.output["out"], reception.input["in"])
        self.add_coupling(reception.output["cust"], checkhair.input["cust"])
        self.add_coupling(checkhair.output["to_cut"], cuthair.input["in"])
        self.add_coupling(cuthair.output["out"], checkhair.input["done"])
        self.add_coupling(checkhair.output["to_reception"], reception.input["done"])


# -----------------------
# Main
# -----------------------

def main():
    parser = argparse.ArgumentParser(description="Barbershop simulation (xdevs.py)")
    parser.add_argument("--simulation_time", type=float, default=1000000.0,
                        help="Total simulation time in seconds (default: 1000000.0)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    # Consume ALL stdin lines to build initial schedule BEFORE simulation starts
    schedule_ticks: List[int] = []
    line_num = 0
    for raw in sys.stdin:
        line_num += 1
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            logging.warning("Skipping malformed line %d: %r", line_num, line)
            continue
        t_str, event = parts
        if event != "newcust":
            logging.warning("Skipping unsupported event on line %d: %r", line_num, event)
            continue
        try:
            tick = parse_time_to_ticks(t_str)
        except Exception as ex:
            logging.warning("Skipping line %d due to time parse error: %r (%s)", line_num, line, ex)
            continue
        schedule_ticks.append(tick)

    schedule_ticks.sort()

    root = System(name="system", parent=None, schedule_ticks=schedule_ticks)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))


if __name__ == "__main__":
    main()