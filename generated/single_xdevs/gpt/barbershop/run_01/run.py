#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import math
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# ----------------------------
# JSONL emission helpers
# ----------------------------
def emit_state(time: float, model: str, field: str, value):
    obj = {
        "time": float(time),
        "type": "state",
        "model": model,
        "field": field,
        "value": value,
    }
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


def emit_message(time: float, model: str, port: str, content: str):
    obj = {
        "time": float(time),
        "type": "message",
        "model": model,
        "port": port,
        "content": content,
    }
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


# ----------------------------
# Utility: parse schedule time
# ----------------------------
def parse_hhmmssff_to_seconds(s: str) -> float:
    # Format: HH:MM:SS:mm where mm is centiseconds (0.01s)
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {s!r}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    ff = int(parts[3])
    return hh * 3600.0 + mm * 60.0 + ss * 1.0 + (ff / 100.0)


class LoggedAtomic(Atomic):
    """Atomic with robust 'current time' helpers for xdevs."""

    def _now_int(self) -> float:
        # Internal transition time (imminent time)
        if hasattr(self, "t_next") and self.t_next is not None:
            try:
                return float(self.t_next)
            except Exception:
                pass
        if hasattr(self, "t_last") and self.t_last is not None:
            try:
                return float(self.t_last)
            except Exception:
                pass
        return 0.0

    def _now_ext(self, e: float) -> float:
        # External transition occurs at t_last + e
        t_last = 0.0
        if hasattr(self, "t_last") and self.t_last is not None:
            try:
                t_last = float(self.t_last)
            except Exception:
                t_last = 0.0
        return float(t_last + float(e))


# ----------------------------
# Event Source
# ----------------------------
class EventSource(LoggedAtomic):
    """
    Emits "newcust" events at times given by a schedule.
    Output port: out (str)
    """

    def __init__(self, name: str, parent: Coupled | None, schedule_times: list[float]):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(str, "out"))

        self.schedule_times = sorted([float(t) for t in schedule_times if t >= 0.0])
        self.idx = 0
        self.pending_emits = 0
        self._next_time = math.inf

    def initialize(self):
        self.idx = 0
        self.pending_emits = 0
        self._next_time = self.schedule_times[0] if self.schedule_times else math.inf
        sigma = self._next_time - 0.0 if self._next_time < math.inf else math.inf
        if sigma < 0.0:
            sigma = 0.0
        self.hold_in("WAIT", sigma)

    def lambdaf(self):
        if self.phase == "EMIT" and self.pending_emits > 0:
            for _ in range(self.pending_emits):
                self.output["out"].add("newcust")

    def deltint(self):
        if self.phase == "WAIT":
            t = self._now_int()
            # Gather all events at this same simulation time
            cnt = 0
            while self.idx < len(self.schedule_times) and abs(self.schedule_times[self.idx] - t) < 1e-9:
                cnt += 1
                self.idx += 1
            self.pending_emits = cnt
            self.hold_in("EMIT", 0.0)
            return

        if self.phase == "EMIT":
            self.pending_emits = 0
            if self.idx >= len(self.schedule_times):
                self._next_time = math.inf
                self.hold_in("WAIT", math.inf)
                return

            self._next_time = self.schedule_times[self.idx]
            t = self._now_int()
            sigma = self._next_time - t
            if sigma < 0.0:
                sigma = 0.0
            self.hold_in("WAIT", sigma)
            return

        self.hold_in("WAIT", math.inf)

    def deltext(self, e):
        # No inputs
        # Keep remaining time if any.
        if hasattr(self, "sigma") and self.sigma is not None and self.phase in ("WAIT",):
            rem = float(self.sigma) - float(e)
            if rem < 0.0:
                rem = 0.0
            self.hold_in(self.phase, rem)
        else:
            self.hold_in(self.phase, getattr(self, "sigma", math.inf))

    def exit(self):
        pass


# ----------------------------
# Reception Desk
# ----------------------------
class Reception(LoggedAtomic):
    """
    Inputs:
      - arrive: new customers from source ("newcust")
      - done_in: completion notification from checkhair ("done")
    Output:
      - cust: to checkhair ("newcust")
    State variable tracked:
      - total customers num: queue length
    """

    CAPACITY = 8
    CHECKIN_TIME = 5.0

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "arrive"))
        self.add_in_port(Port(str, "done_in"))
        self.add_out_port(Port(str, "cust"))

        self.queue = deque()
        self.checkhair_available = True

        self.pending_send = False
        self.pending_content = None  # "newcust"

    def initialize(self):
        self.queue.clear()
        self.checkhair_available = True
        self.pending_send = False
        self.pending_content = None
        self.hold_in("IDLE", math.inf)

    def _start_checkin_if_possible(self):
        if len(self.queue) > 0 and self.phase == "IDLE":
            self.hold_in("CHECKIN", self.CHECKIN_TIME)
        else:
            # Keep current schedule
            pass

    def lambdaf(self):
        if self.phase == "SEND" and self.pending_send and self.pending_content:
            # Emit message to checkhair
            self.output["cust"].add(self.pending_content)
            emit_message(self._now_int(), self.name, "cust", self.pending_content)

    def deltint(self):
        # Internal transitions
        if self.phase == "CHECKIN":
            # Check-in time finished; attempt to handoff if possible
            if len(self.queue) > 0 and self.checkhair_available:
                # Pop and schedule immediate send
                self.queue.popleft()
                emit_state(self._now_int(), self.name, "total customers num", len(self.queue))

                self.pending_send = True
                self.pending_content = "newcust"
                self.checkhair_available = False
                self.hold_in("SEND", 0.0)
            else:
                # Wait until checkhair becomes available
                self.hold_in("WAIT_AVAIL", math.inf)
            return

        if self.phase == "SEND":
            # Output already produced in lambdaf
            self.pending_send = False
            self.pending_content = None
            # Start next check-in if queue nonempty; otherwise idle
            if len(self.queue) > 0:
                self.hold_in("CHECKIN", self.CHECKIN_TIME)
            else:
                self.hold_in("IDLE", math.inf)
            return

        # IDLE or WAIT_AVAIL shouldn't have internal events
        self.hold_in(self.phase, math.inf)

    def deltext(self, e):
        now = self._now_ext(e)

        # Collect inputs
        arrivals = list(getattr(self.input["arrive"], "values", []))
        dones = list(getattr(self.input["done_in"], "values", []))

        # Update remaining time if needed (default: keep same phase timing)
        rem = None
        if hasattr(self, "sigma") and self.sigma is not None:
            try:
                rem = float(self.sigma) - float(e)
            except Exception:
                rem = None
        if rem is not None and rem < 0.0:
            rem = 0.0

        # Process done signals (checkhair became available)
        for v in dones:
            if v == "done":
                self.checkhair_available = True

        # Process arrivals
        for v in arrivals:
            if v != "newcust":
                continue
            if len(self.queue) < self.CAPACITY:
                self.queue.append("newcust")
                emit_state(now, self.name, "total customers num", len(self.queue))
            else:
                # Ignore if full
                pass

        # If waiting for availability and now available, handoff immediately (no extra check-in)
        if self.phase == "WAIT_AVAIL" and self.checkhair_available and len(self.queue) > 0:
            self.queue.popleft()
            emit_state(now, self.name, "total customers num", len(self.queue))

            self.pending_send = True
            self.pending_content = "newcust"
            self.checkhair_available = False
            self.hold_in("SEND", 0.0)
            return

        # If idle and have customers, start check-in
        if self.phase == "IDLE":
            if len(self.queue) > 0:
                self.hold_in("CHECKIN", self.CHECKIN_TIME)
            else:
                self.hold_in("IDLE", math.inf)
            return

        # Otherwise keep current timing/phase
        if self.phase in ("CHECKIN",) and rem is not None:
            self.hold_in("CHECKIN", rem)
        else:
            # WAIT_AVAIL stays passive until done arrives; SEND should not accept external normally,
            # but to be safe, keep it immediate if already scheduled.
            if self.phase == "SEND":
                self.hold_in("SEND", 0.0)
            else:
                self.hold_in(self.phase, math.inf)

    def exit(self):
        pass


# ----------------------------
# Hair Inspection (Coordinator)
# ----------------------------
class CheckHair(LoggedAtomic):
    """
    Input:
      - inp: from reception ("newcust")
      - from_cut: from cuthair ("done")
    Outputs:
      - to_cut ("newcust")
      - to_reception ("done")
    State tracked:
      - customer: "newcust" on start, "done" when cut completed
    """

    CONSULT_TIME = 7.0

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "inp"))
        self.add_in_port(Port(str, "from_cut"))
        self.add_out_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))

        self.busy = False
        self.pending_out_port = None
        self.pending_out_content = None

    def initialize(self):
        self.busy = False
        self.pending_out_port = None
        self.pending_out_content = None
        self.hold_in("AVAILABLE", math.inf)

    def lambdaf(self):
        if self.phase == "SEND" and self.pending_out_port and self.pending_out_content:
            self.output[self.pending_out_port].add(self.pending_out_content)
            emit_message(self._now_int(), self.name, self.pending_out_port, self.pending_out_content)

    def deltint(self):
        if self.phase == "CONSULT":
            # Consultation done; forward to cutter
            self.pending_out_port = "to_cut"
            self.pending_out_content = "newcust"
            self.hold_in("SEND", 0.0)
            return

        if self.phase == "SEND":
            # After sending:
            if self.pending_out_port == "to_cut":
                # Now wait for done from cutter
                self.pending_out_port = None
                self.pending_out_content = None
                self.hold_in("WAIT_DONE", math.inf)
                return

            if self.pending_out_port == "to_reception":
                # Finished full service, now available
                self.pending_out_port = None
                self.pending_out_content = None
                self.busy = False
                self.hold_in("AVAILABLE", math.inf)
                return

            self.pending_out_port = None
            self.pending_out_content = None
            self.hold_in("AVAILABLE", math.inf)
            return

        # AVAILABLE or WAIT_DONE should not have internal events
        self.hold_in(self.phase, math.inf)

    def deltext(self, e):
        now = self._now_ext(e)

        inp_vals = list(getattr(self.input["inp"], "values", []))
        done_vals = list(getattr(self.input["from_cut"], "values", []))

        # Keep remaining time if consulting
        rem = None
        if hasattr(self, "sigma") and self.sigma is not None:
            try:
                rem = float(self.sigma) - float(e)
            except Exception:
                rem = None
        if rem is not None and rem < 0.0:
            rem = 0.0

        # If we get a 'done' from cutter while waiting
        if self.phase == "WAIT_DONE":
            for v in done_vals:
                if v == "done":
                    emit_state(now, self.name, "customer", "done")
                    self.pending_out_port = "to_reception"
                    self.pending_out_content = "done"
                    self.hold_in("SEND", 0.0)
                    return

        # If available, accept one customer
        if self.phase == "AVAILABLE":
            for v in inp_vals:
                if v == "newcust":
                    self.busy = True
                    emit_state(now, self.name, "customer", "newcust")
                    self.hold_in("CONSULT", self.CONSULT_TIME)
                    return
            # Nothing relevant
            self.hold_in("AVAILABLE", math.inf)
            return

        # If consulting, ignore new customers (reception should not send), but keep timer.
        if self.phase == "CONSULT":
            self.hold_in("CONSULT", rem if rem is not None else 0.0)
            return

        # If sending, keep immediate
        if self.phase == "SEND":
            self.hold_in("SEND", 0.0)
            return

        # If waiting done but got stray inputs, remain waiting
        self.hold_in(self.phase, math.inf)

    def exit(self):
        pass


# ----------------------------
# Hair Cutting
# ----------------------------
class CutHair(LoggedAtomic):
    """
    Input:
      - inp: from checkhair ("newcust")
    Output:
      - out: to checkhair ("done")
    State tracked:
      - total customer done: cumulative count
    """

    CUT_TIME = 20.0

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(str, "inp"))
        self.add_out_port(Port(str, "out"))

        self.busy = False
        self.total_done = 0
        self.pending_send_done = False

    def initialize(self):
        self.busy = False
        self.total_done = 0
        self.pending_send_done = False
        self.hold_in("IDLE", math.inf)

    def lambdaf(self):
        if self.phase == "SEND" and self.pending_send_done:
            self.output["out"].add("done")
            emit_message(self._now_int(), self.name, "out", "done")

    def deltint(self):
        if self.phase == "CUT":
            # Cutting finished: update KPI and schedule immediate done message
            self.total_done += 1
            emit_state(self._now_int(), self.name, "total customer done", self.total_done)
            self.pending_send_done = True
            self.hold_in("SEND", 0.0)
            return

        if self.phase == "SEND":
            self.pending_send_done = False
            self.busy = False
            self.hold_in("IDLE", math.inf)
            return

        self.hold_in(self.phase, math.inf)

    def deltext(self, e):
        now = self._now_ext(e)
        inp_vals = list(getattr(self.input["inp"], "values", []))

        # Keep remaining time if cutting
        rem = None
        if hasattr(self, "sigma") and self.sigma is not None:
            try:
                rem = float(self.sigma) - float(e)
            except Exception:
                rem = None
        if rem is not None and rem < 0.0:
            rem = 0.0

        if self.phase == "IDLE":
            for v in inp_vals:
                if v == "newcust":
                    self.busy = True
                    self.hold_in("CUT", self.CUT_TIME)
                    return
            self.hold_in("IDLE", math.inf)
            return

        if self.phase == "CUT":
            # Ignore inputs while busy, keep timer
            self.hold_in("CUT", rem if rem is not None else 0.0)
            return

        if self.phase == "SEND":
            self.hold_in("SEND", 0.0)
            return

        self.hold_in(self.phase, math.inf)

    def exit(self):
        pass


# ----------------------------
# Coupled system
# ----------------------------
class BarbershopSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, schedule_times: list[float]):
        super().__init__(name)
        self.parent = parent

        src = EventSource("source", parent=self, schedule_times=schedule_times)
        reception = Reception("reception", parent=self)
        checkhair = CheckHair("checkhair", parent=self)
        cuthair = CutHair("cuthair", parent=self)

        self.add_component(src)
        self.add_component(reception)
        self.add_component(checkhair)
        self.add_component(cuthair)

        # Couplings
        self.add_coupling(src.output["out"], reception.input["arrive"])
        self.add_coupling(reception.output["cust"], checkhair.input["inp"])
        self.add_coupling(checkhair.output["to_cut"], cuthair.input["inp"])
        self.add_coupling(cuthair.output["out"], checkhair.input["from_cut"])
        self.add_coupling(checkhair.output["to_reception"], reception.input["done_in"])


# ----------------------------
# Main
# ----------------------------
def main():
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    # Read ALL stdin lines before simulation starts
    schedule_times: list[float] = []
    line_count = 0
    for raw in sys.stdin:
        line_count += 1
        line = raw.strip()
        if not line:
            continue
        try:
            time_str, event_name = line.split(None, 1)
        except ValueError:
            logging.warning("Skipping malformed line %d: %r", line_count, line)
            continue
        event_name = event_name.strip()
        if event_name != "newcust":
            logging.warning("Skipping unsupported event on line %d: %r", line_count, event_name)
            continue
        try:
            t = parse_hhmmssff_to_seconds(time_str)
        except Exception as ex:
            logging.warning("Skipping invalid time on line %d: %r (%s)", line_count, time_str, ex)
            continue
        schedule_times.append(t)

    logging.info("Loaded %d scheduled newcust events from stdin (%d lines).", len(schedule_times), line_count)

    root = BarbershopSystem(name="system", parent=None, schedule_times=schedule_times)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))


if __name__ == "__main__":
    main()