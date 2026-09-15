#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# ----------------------------
# Utilities
# ----------------------------
def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def hhmmss_to_seconds(s: str) -> float:
    s = s.strip()
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp '{s}', expected HH:MM:SS")
    h, m, sec = parts
    return int(h) * 3600 + int(m) * 60 + int(sec)


def msg_str(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


# ----------------------------
# Data structures for logging
# ----------------------------
@dataclass
class EventRecord:
    time: float
    component: str
    message: str
    state: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"time": float(self.time), "component": self.component, "message": self.message}
        if self.state is not None:
            d["state"] = self.state
        return d


@dataclass
class OperationRecord:
    input_time: float
    action: str
    completed: bool
    completion_time: Optional[float]

    def to_dict(self) -> dict:
        return {
            "input_time": float(self.input_time),
            "action": self.action,
            "completed": bool(self.completed),
            "completion_time": None if self.completion_time is None else float(self.completion_time),
        }


class Logger:
    def __init__(self):
        self.events: List[EventRecord] = []
        self.operations: List[OperationRecord] = []

    def add_event(self, time: float, component: str, message: str, state: Optional[str] = None):
        self.events.append(EventRecord(time=time, component=component, message=message, state=state))

    def add_operation(self, input_time: float, action: str, completed: bool, completion_time: Optional[float]):
        self.operations.append(
            OperationRecord(
                input_time=input_time,
                action=action,
                completed=completed,
                completion_time=completion_time,
            )
        )


# ----------------------------
# Atomic Models
# ----------------------------
class InputReader(Atomic):
    """
    Emits each input line at its scheduled simulation time.
    Also logs an 'input_reader' event for every input line at that time.
    """
    def __init__(self, name: str, parent: Coupled | None, schedule: List[Tuple[float, int, int]], logger: Logger):
        super().__init__(name)
        self.parent = parent
        self.logger = logger

        self.add_out_port(Port(dict, "out"))  # payload: {"time": t, "port": p, "value": v}

        self._schedule = sorted(schedule, key=lambda x: x[0])
        self._idx = 0
        self._next_payload: Optional[dict] = None

        self.hold_in("IDLE", float("inf"))

    def initialize(self):
        if self._idx < len(self._schedule):
            t, p, v = self._schedule[self._idx]
            self._next_payload = {"time": float(t), "port": int(p), "value": int(v)}
            self.hold_in("EMIT", float(t))  # from time 0
        else:
            self._next_payload = None
            self.hold_in("IDLE", float("inf"))

    def lambdaf(self):
        if self.phase == "EMIT" and self._next_payload is not None:
            t = self._next_payload["time"]
            p = self._next_payload["port"]
            v = self._next_payload["value"]
            self.logger.add_event(time=t, component="input_reader", message=msg_str(p, v))
            self.output["out"].add(self._next_payload)

    def deltint(self):
        if self.phase == "EMIT":
            self._idx += 1
            if self._idx < len(self._schedule):
                t, p, v = self._schedule[self._idx]
                self._next_payload = {"time": float(t), "port": int(p), "value": int(v)}
                # schedule next emit relative to current time
                # current time is previous t; next sigma is delta
                prev_t = self._schedule[self._idx - 1][0]
                self.hold_in("EMIT", float(t - prev_t))
            else:
                self._next_payload = None
                self.hold_in("IDLE", float("inf"))
        else:
            self.hold_in("IDLE", float("inf"))

    def deltext(self, e):
        # No inputs
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class AlarmAdmin(Atomic):
    """
    Accepts requests if not busy. If busy, ignores.
    If accepted: emits request after alarm_admin_delay to Authentication.
    Busy until authentication response time (handled via 'auth_done' input).
    Also logs operations and alarmAdmin events.
    """
    def __init__(self, name: str, parent: Coupled | None, alarm_admin_delay: float, logger: Logger):
        super().__init__(name)
        self.parent = parent
        self.logger = logger
        self.alarm_admin_delay = float(alarm_admin_delay)

        self.add_in_port(Port(dict, "in"))         # from InputReader: {"time", "port", "value"}
        self.add_in_port(Port(dict, "auth_done"))  # from Authentication: {"time", "port", "value"}

        self.add_out_port(Port(dict, "out"))       # to Authentication: {"time", "port", "value"}

        self._busy = False
        self._pending_out: Optional[dict] = None
        self._pending_msg_str: Optional[str] = None
        self._pending_out_time: Optional[float] = None

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self._busy = False
        self._pending_out = None
        self._pending_msg_str = None
        self._pending_out_time = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase == "EMIT" and self._pending_out is not None and self._pending_out_time is not None:
            p = self._pending_out["port"]
            v = self._pending_out["value"]
            self.logger.add_event(time=self._pending_out_time, component="alarmAdmin", message=msg_str(p, v))
            self.output["out"].add(self._pending_out)

    def deltint(self):
        if self.phase == "EMIT":
            # After emitting, go passive while remaining busy until auth_done arrives
            self._pending_out = None
            self._pending_msg_str = None
            self._pending_out_time = None
            self.hold_in("PASSIVE", float("inf"))
        else:
            self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        # Process auth_done first to allow acceptance at exactly auth time.
        if self.input["auth_done"].values:
            # Any auth_done means operation completed, admin becomes not busy
            # There should be at most one at a time.
            self._busy = False

        # Process new requests
        if self.input["in"].values:
            # In case multiple arrive at same time, process in given order:
            for req in list(self.input["in"].values):
                t = float(req["time"])
                p = int(req["port"])
                v = int(req["value"])
                action = "disarm" if v == 0 else "arm"

                if self._busy:
                    # ignored
                    self.logger.add_operation(input_time=t, action=action, completed=False, completion_time=None)
                    continue

                # accepted
                completion_time = t + self.alarm_admin_delay  # not final; actual completion is at auth time
                # We'll set completion_time to auth time per spec: t + admin + auth_delay.
                # AlarmAdmin doesn't know auth_delay; Authentication will send auth_done with time.
                # So store as None now and patch? Instead, compute in Authentication and send to a logger model?
                # Requirement: operations record completion_time = authentication event time.
                # We'll compute it here by assuming Authentication delay is known? It's not passed.
                # We'll handle by sending auth_done back with exact time and include original input_time/value,
                # and AlarmAdmin will log accepted operation on input with completion_time computed when auth_done arrives.
                # But we must output operations sorted by input_time; logging later is ok.
                # We'll store a pending accepted op to finalize on auth_done.
                # However multiple accepted ops cannot overlap due to busy, so single slot is enough.
                self._accepted_op = {"input_time": t, "action": action}  # type: ignore[attr-defined]

                self._busy = True
                out_time = t + self.alarm_admin_delay
                self._pending_out_time = out_time
                self._pending_out = {"time": out_time, "port": p, "value": v}
                self._pending_msg_str = msg_str(p, v)

                # schedule internal emit at out_time
                # current time is t; elapsed e is provided; schedule relative to now:
                # In DEVS, sigma counts from current time; after deltext, time advances by e already.
                # So remaining time to out_time is (alarm_admin_delay - (current_time - t)) = alarm_admin_delay - (e - 0)
                # But req["time"] equals current time of event; thus remaining is alarm_admin_delay.
                self.hold_in("EMIT", self.alarm_admin_delay)
                # Only one accepted at a time; ignore any additional in same time after becoming busy
                # (spec: if already working on previous request, new request ignored after input event)
                # Since we just accepted one, any further in same deltext should be ignored.
                # So continue loop with busy True; they will be ignored.
        else:
            # no new request; keep current phase/sigma
            self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class Authentication(Atomic):
    """
    Receives request, outputs successful validation after authentication_delay.
    Also notifies AlarmAdmin via auth_done at the same time (completion time).
    Logs authentication event with state DisarmValid/ArmValid.
    """
    def __init__(self, name: str, parent: Coupled | None, authentication_delay: float, logger: Logger):
        super().__init__(name)
        self.parent = parent
        self.logger = logger
        self.authentication_delay = float(authentication_delay)

        self.add_in_port(Port(dict, "in"))          # {"time","port","value"} at admin output time
        self.add_out_port(Port(dict, "out"))        # to Display: {"time","port","value"}
        self.add_out_port(Port(dict, "auth_done"))  # to AlarmAdmin: {"time","port","value","input_time"}

        self._pending: Optional[dict] = None
        self._pending_out_time: Optional[float] = None

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self._pending = None
        self._pending_out_time = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase == "EMIT" and self._pending is not None and self._pending_out_time is not None:
            p = int(self._pending["port"])
            v = int(self._pending["value"])
            t = float(self._pending_out_time)
            state = "DisarmValid" if v == 0 else "ArmValid"
            self.logger.add_event(time=t, component="authentication", message=msg_str(p, v), state=state)

            out_payload = {"time": t, "port": p, "value": v}
            self.output["out"].add(out_payload)

            # completion notification includes original input_time for operation logging
            auth_done_payload = {"time": t, "port": p, "value": v, "input_time": float(self._pending["input_time"])}
            self.output["auth_done"].add(auth_done_payload)

    def deltint(self):
        if self.phase == "EMIT":
            self._pending = None
            self._pending_out_time = None
            self.hold_in("PASSIVE", float("inf"))
        else:
            self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        if self.input["in"].values:
            # Should not overlap due to admin busy, but handle last-one-wins safely
            req = list(self.input["in"].values)[-1]
            admin_out_time = float(req["time"])
            p = int(req["port"])
            v = int(req["value"])
            # carry original input_time if present; else infer by subtracting admin delay is unknown, so require present
            input_time = float(req.get("input_time", req.get("orig_time", admin_out_time)))
            # If AlarmAdmin didn't include input_time, we can't reconstruct reliably; so we include it in coupling
            # by letting AlarmAdmin forward it. We'll enforce it there.
            self._pending = {"port": p, "value": v, "input_time": input_time}
            self._pending_out_time = admin_out_time + self.authentication_delay
            self.hold_in("EMIT", self.authentication_delay)
        else:
            self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class Display(Atomic):
    """
    Receives validated request, outputs visible state after display_delay.
    Logs display event with state Armed/Disarmed.
    """
    def __init__(self, name: str, parent: Coupled | None, display_delay: float, logger: Logger):
        super().__init__(name)
        self.parent = parent
        self.logger = logger
        self.display_delay = float(display_delay)

        self.add_in_port(Port(dict, "in"))    # {"time","port","value"} at auth output time
        self.add_out_port(Port(dict, "out"))  # unused externally

        self._pending: Optional[dict] = None
        self._pending_out_time: Optional[float] = None

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self._pending = None
        self._pending_out_time = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase == "EMIT" and self._pending is not None and self._pending_out_time is not None:
            p = int(self._pending["port"])
            v = int(self._pending["value"])
            t = float(self._pending_out_time)
            state = "Disarmed" if v == 0 else "Armed"
            self.logger.add_event(time=t, component="display", message=msg_str(p, v), state=state)
            self.output["out"].add({"time": t, "port": p, "value": v})

    def deltint(self):
        if self.phase == "EMIT":
            self._pending = None
            self._pending_out_time = None
            self.hold_in("PASSIVE", float("inf"))
        else:
            self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        if self.input["in"].values:
            req = list(self.input["in"].values)[-1]
            auth_time = float(req["time"])
            p = int(req["port"])
            v = int(req["value"])
            self._pending = {"port": p, "value": v}
            self._pending_out_time = auth_time + self.display_delay
            self.hold_in("EMIT", self.display_delay)
        else:
            self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class OperationTracker(Atomic):
    """
    Receives auth_done notifications and logs completion_time for accepted operations.
    Also tracks final alarm state based on last accepted request (value 0/1).
    """
    def __init__(self, name: str, parent: Coupled | None, logger: Logger):
        super().__init__(name)
        self.parent = parent
        self.logger = logger

        self.add_in_port(Port(dict, "auth_done"))  # {"time","port","value","input_time"}

        self.final_state = "Disarmed"
        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self.final_state = "Disarmed"
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        # no outputs
        return

    def deltint(self):
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        if self.input["auth_done"].values:
            for done in list(self.input["auth_done"].values):
                t = float(done["time"])
                v = int(done["value"])
                input_time = float(done["input_time"])
                action = "disarm" if v == 0 else "arm"
                self.logger.add_operation(input_time=input_time, action=action, completed=True, completion_time=t)
                self.final_state = "Disarmed" if v == 0 else "Armed"
        self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


# ----------------------------
# Coupled System
# ----------------------------
class SecureAreaSystem(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        schedule: List[Tuple[float, int, int]],
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
        logger: Logger,
    ):
        super().__init__(name)
        self.parent = parent

        # Components
        self.reader = InputReader("input_reader_model", parent=self, schedule=schedule, logger=logger)
        self.admin = AlarmAdmin("alarm_admin_model", parent=self, alarm_admin_delay=alarm_admin_delay, logger=logger)
        self.auth = Authentication("authentication_model", parent=self, authentication_delay=authentication_delay, logger=logger)
        self.display = Display("display_model", parent=self, display_delay=display_delay, logger=logger)
        self.tracker = OperationTracker("operation_tracker_model", parent=self, logger=logger)

        self.add_component(self.reader)
        self.add_component(self.admin)
        self.add_component(self.auth)
        self.add_component(self.display)
        self.add_component(self.tracker)

        # Couplings
        self.add_coupling(self.reader.output["out"], self.admin.input["in"])

        # AlarmAdmin -> Authentication
        # Ensure input_time is forwarded: modify payload at source by including input_time in AlarmAdmin output.
        # We'll do it by having AlarmAdmin output include input_time when it accepts.
        # To enforce, we adjust AlarmAdmin to include it in _pending_out if present.
        # (Implemented below by monkey patching in-place is ugly; instead, we already store accepted op in AlarmAdmin,
        # but didn't include input_time in output. We'll fix by subclassing? Not allowed. We'll patch via attribute.)
        # We'll handle by setting admin._pending_out to include input_time at acceptance time.
        # That requires code change above: set _pending_out with input_time.
        # We'll do it now by relying on that field existing; ensure it does in AlarmAdmin.deltext.
        self.add_coupling(self.admin.output["out"], self.auth.input["in"])

        # Authentication -> Display
        self.add_coupling(self.auth.output["out"], self.display.input["in"])

        # Authentication -> AlarmAdmin (auth_done) and -> Tracker
        self.add_coupling(self.auth.output["auth_done"], self.admin.input["auth_done"])
        self.add_coupling(self.auth.output["auth_done"], self.tracker.input["auth_done"])


# Patch AlarmAdmin.deltext to include input_time in output payload (must be done in class definition ideally).
# We'll redefine AlarmAdmin.deltext properly by replacing method here (still single-file).
def _alarmadmin_deltext(self: AlarmAdmin, e):
    if self.input["auth_done"].values:
        self._busy = False

    if self.input["in"].values:
        for req in list(self.input["in"].values):
            t = float(req["time"])
            p = int(req["port"])
            v = int(req["value"])
            action = "disarm" if v == 0 else "arm"

            if self._busy:
                self.logger.add_operation(input_time=t, action=action, completed=False, completion_time=None)
                continue

            # accepted
            self._busy = True
            out_time = t + self.alarm_admin_delay
            self._pending_out_time = out_time
            self._pending_out = {"time": out_time, "port": p, "value": v, "input_time": t}
            self._pending_msg_str = msg_str(p, v)
            self.hold_in("EMIT", self.alarm_admin_delay)
    else:
        self.hold_in(self.phase, self.sigma)

AlarmAdmin.deltext = _alarmadmin_deltext  # type: ignore[assignment]


# ----------------------------
# Main
# ----------------------------
def read_input_file(path: Optional[str]) -> List[Tuple[float, int, int]]:
    if not path:
        return []
    schedule: List[Tuple[float, int, int]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"Invalid input line {line_no}: '{line}' (expected: HH:MM:SS port value)")
            ts, port_s, val_s = parts
            t = hhmmss_to_seconds(ts)
            port = int(port_s)
            val = int(val_s)
            schedule.append((t, port, val))
    return schedule


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str, default=None)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = parser.parse_args()

    schedule = read_input_file(args.input_file)

    logger = Logger()
    root = SecureAreaSystem(
        name="secure_area_system",
        parent=None,
        schedule=schedule,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        logger=logger,
    )

    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(float(args.max_simulation_time))

    # Sort events by nondecreasing time (stable for same time)
    logger.events.sort(key=lambda ev: ev.time)
    # Operations must be sorted by input_time
    logger.operations.sort(key=lambda op: op.input_time)

    # Determine final_state from tracker (if accessible)
    final_state = root.tracker.final_state if hasattr(root, "tracker") else "Disarmed"

    # Determine actual final simulated time:
    # normally last emitted event time, else max_simulation_time if max reached before all display events.
    if logger.events:
        last_event_time = max(ev.time for ev in logger.events)
        simulation_time = min(float(args.max_simulation_time), float(last_event_time))
        # If max_simulation_time is less than last_event_time, those events wouldn't have occurred.
        # But since we only log when events occur, last_event_time cannot exceed simulated time.
        # Keep as last_event_time.
        simulation_time = float(last_event_time)
    else:
        simulation_time = 0.0

    out = {
        "test_name": args.test_name,
        "simulation_time": float(simulation_time),
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": [ev.to_dict() for ev in logger.events],
        "operations": [op.to_dict() for op in logger.operations],
    }

    print(json.dumps(out, separators=(",", ":")))


if __name__ == "__main__":
    main()