#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Optional, List, Dict, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# -----------------------------
# Utilities
# -----------------------------
def parse_hhmmss_to_seconds(s: str) -> float:
    s = s.strip()
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp '{s}', expected HH:MM:SS")
    hh, mm, ss = parts
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


def msg_str(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


@dataclass(frozen=True)
class Request:
    time: float
    port: int
    value: int


@dataclass
class EventRecord:
    time: float
    component: str
    message: str
    state: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        d = {"time": float(self.time), "component": self.component, "message": self.message}
        if self.state is not None:
            d["state"] = self.state
        return d


# -----------------------------
# Atomic Models
# -----------------------------
class EventLogger(Atomic):
    """
    Collects event records from other components.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in"))
        self.records: List[EventRecord] = []
        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self.records = []
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        # No outputs
        return

    def deltint(self):
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        for payload in self.input["in"].values:
            # payload: dict with keys time, component, message, optional state
            try:
                rec = EventRecord(
                    time=float(payload["time"]),
                    component=str(payload["component"]),
                    message=str(payload["message"]),
                    state=payload.get("state", None),
                )
                self.records.append(rec)
            except Exception as ex:
                print(f"[logger] bad payload {payload}: {ex}", file=sys.stderr)
        self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


class InputReader(Atomic):
    """
    Emits each input request at its specified simulation time.
    Also emits a log event for every input line.
    """
    def __init__(self, name: str, parent: Coupled | None, requests: List[Request]):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "out_req"))   # to AlarmAdmin
        self.add_out_port(Port(dict, "out_log"))   # to EventLogger

        self._requests = sorted(list(requests), key=lambda r: (r.time, r.port, r.value))
        self._idx = 0
        self._pending_req: Optional[dict] = None
        self._pending_log: Optional[dict] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._idx = 0
        self._pending_req = None
        self._pending_log = None
        # schedule first emission
        if self._requests:
            self.hold_in("WAIT", self._requests[0].time)
        else:
            self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self._pending_log is not None:
            self.output["out_log"].add(self._pending_log)
        if self._pending_req is not None:
            self.output["out_req"].add(self._pending_req)

    def deltint(self):
        # After emitting one request, schedule next
        self._pending_req = None
        self._pending_log = None

        self._idx += 1
        if self._idx >= len(self._requests):
            self.hold_in("PASSIVE", float("inf"))
            return

        next_t = self._requests[self._idx].time
        prev_t = self._requests[self._idx - 1].time
        sigma = max(0.0, next_t - prev_t)
        self.hold_in("WAIT", sigma)

    def deltext(self, e):
        # No inputs expected
        self.hold_in(self.phase, self.sigma - e if self.sigma != float("inf") else float("inf"))

    def exit(self):
        pass

    # xdevs uses phase/sigma; prepare payload right before output by using phase "WAIT" internal event.
    @property
    def phase(self):
        return getattr(self, "_phase", "PASSIVE")

    @phase.setter
    def phase(self, v):
        self._phase = v

    @property
    def sigma(self):
        return getattr(self, "_sigma", float("inf"))

    @sigma.setter
    def sigma(self, v):
        self._sigma = v

    def hold_in(self, phase, sigma):
        self.phase = phase
        self.sigma = sigma
        super().hold_in(phase, sigma)
        # If we are scheduling an internal event that corresponds to emitting a request, prepare payload.
        # We prepare for the *current* index request when phase is WAIT and sigma is 0 at the event time.
        # But we don't know if sigma is 0 now; instead, prepare whenever we enter WAIT (including after init),
        # and update at internal transition time by reading current index.
        if phase == "WAIT":
            # Prepare payload for current request (self._idx)
            if 0 <= self._idx < len(self._requests):
                r = self._requests[self._idx]
                m = msg_str(r.port, r.value)
                self._pending_req = {"port": r.port, "value": r.value, "message": m}
                # log event at same time as request emission (the internal event time)
                # We don't have direct access to current simulation time here; xdevs will set it.
                # We'll fill time in lambdaf by reading self.time_last + self.sigma? Not safe.
                # Instead, include only component/message here; System will override time? Not possible.
                # So we will compute event time as (t_last + sigma) using self.time_last.
                t_emit = float(getattr(self, "time_last", 0.0)) + float(sigma if sigma != float("inf") else 0.0)
                self._pending_log = {"time": t_emit, "component": "input_reader", "message": m}


class AlarmAdmin(Atomic):
    """
    Accepts requests if not busy. Outputs accepted request after alarm_admin_delay.
    Becomes free at authentication response time (received from Authentication).
    """
    def __init__(self, name: str, parent: Coupled | None, alarm_admin_delay: float):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in_req"))      # from InputReader
        self.add_in_port(Port(dict, "in_auth_done"))  # from Authentication (completion notification)
        self.add_out_port(Port(dict, "out_to_auth"))  # to Authentication
        self.add_out_port(Port(dict, "out_log"))      # to EventLogger

        self.delay = float(alarm_admin_delay)

        self.busy = False
        self._pending_out: Optional[dict] = None
        self._pending_log: Optional[dict] = None

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self.busy = False
        self._pending_out = None
        self._pending_log = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self._pending_log is not None:
            self.output["out_log"].add(self._pending_log)
        if self._pending_out is not None:
            self.output["out_to_auth"].add(self._pending_out)

    def deltint(self):
        # emitted the accepted request to authentication
        self._pending_out = None
        self._pending_log = None
        # remain busy until auth_done arrives
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        # Process completion notifications first: if auth_done arrives at same time, free up before handling req.
        auth_done_arrived = len(self.input["in_auth_done"].values) > 0
        if auth_done_arrived:
            self.busy = False

        # Handle incoming requests (could be multiple at same time; only first can be accepted if free)
        # Ignored requests produce no further events (already logged by InputReader).
        if len(self.input["in_req"].values) > 0:
            # accept at most one if free
            if not self.busy:
                req = list(self.input["in_req"].values)[0]
                port = int(req["port"])
                value = int(req["value"])
                m = msg_str(port, value)

                # schedule output after delay
                t_emit = float(getattr(self, "time_last", 0.0)) + float(e) + self.delay
                self._pending_out = {"port": port, "value": value, "message": m}
                self._pending_log = {"time": t_emit, "component": "alarmAdmin", "message": m}

                self.busy = True
                self.hold_in("SEND", self.delay)
                return

        self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


class Authentication(Atomic):
    """
    On request, outputs successful validation after authentication_delay.
    Also notifies AlarmAdmin that operation is completed at the same time.
    """
    def __init__(self, name: str, parent: Coupled | None, authentication_delay: float):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in_req"))
        self.add_out_port(Port(dict, "out_valid"))    # to Display
        self.add_out_port(Port(dict, "out_done"))     # to AlarmAdmin
        self.add_out_port(Port(dict, "out_log"))      # to EventLogger

        self.delay = float(authentication_delay)
        self._pending_valid: Optional[dict] = None
        self._pending_done: Optional[dict] = None
        self._pending_log: Optional[dict] = None

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self._pending_valid = None
        self._pending_done = None
        self._pending_log = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self._pending_log is not None:
            self.output["out_log"].add(self._pending_log)
        if self._pending_valid is not None:
            self.output["out_valid"].add(self._pending_valid)
        if self._pending_done is not None:
            self.output["out_done"].add(self._pending_done)

    def deltint(self):
        self._pending_valid = None
        self._pending_done = None
        self._pending_log = None
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        if len(self.input["in_req"].values) == 0:
            self.hold_in("PASSIVE", float("inf"))
            return

        req = list(self.input["in_req"].values)[0]
        port = int(req["port"])
        value = int(req["value"])
        m = msg_str(port, value)
        state = "DisarmValid" if value == 0 else "ArmValid"

        t_emit = float(getattr(self, "time_last", 0.0)) + float(e) + self.delay
        self._pending_valid = {"port": port, "value": value, "message": m, "state": state}
        self._pending_done = {"done": True}
        self._pending_log = {"time": t_emit, "component": "authentication", "message": m, "state": state}

        self.hold_in("SEND", self.delay)

    def exit(self):
        pass


class Display(Atomic):
    """
    On validation, outputs visible state after display_delay.
    """
    def __init__(self, name: str, parent: Coupled | None, display_delay: float):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in_valid"))
        self.add_out_port(Port(dict, "out_log"))

        self.delay = float(display_delay)
        self._pending_log: Optional[dict] = None

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self._pending_log = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self._pending_log is not None:
            self.output["out_log"].add(self._pending_log)

    def deltint(self):
        self._pending_log = None
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        if len(self.input["in_valid"].values) == 0:
            self.hold_in("PASSIVE", float("inf"))
            return

        valid = list(self.input["in_valid"].values)[0]
        port = int(valid["port"])
        value = int(valid["value"])
        m = msg_str(port, value)
        state = "Disarmed" if value == 0 else "Armed"

        t_emit = float(getattr(self, "time_last", 0.0)) + float(e) + self.delay
        self._pending_log = {"time": t_emit, "component": "display", "message": m, "state": state}
        self.hold_in("SHOW", self.delay)

    def exit(self):
        pass


# -----------------------------
# Coupled System
# -----------------------------
class SecureAreaSystem(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        requests: List[Request],
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.reader = InputReader("input_reader_model", parent=self, requests=requests)
        self.admin = AlarmAdmin("alarm_admin_model", parent=self, alarm_admin_delay=alarm_admin_delay)
        self.auth = Authentication("authentication_model", parent=self, authentication_delay=authentication_delay)
        self.display = Display("display_model", parent=self, display_delay=display_delay)
        self.logger = EventLogger("event_logger", parent=self)

        for c in (self.reader, self.admin, self.auth, self.display, self.logger):
            self.add_component(c)

        # Couplings
        self.add_coupling(self.reader.output["out_req"], self.admin.input["in_req"])
        self.add_coupling(self.reader.output["out_log"], self.logger.input["in"])

        self.add_coupling(self.admin.output["out_to_auth"], self.auth.input["in_req"])
        self.add_coupling(self.admin.output["out_log"], self.logger.input["in"])

        self.add_coupling(self.auth.output["out_valid"], self.display.input["in_valid"])
        self.add_coupling(self.auth.output["out_done"], self.admin.input["in_auth_done"])
        self.add_coupling(self.auth.output["out_log"], self.logger.input["in"])

        self.add_coupling(self.display.output["out_log"], self.logger.input["in"])


# -----------------------------
# Offline operation computation (per spec)
# -----------------------------
def compute_operations_and_final_state(
    requests: List[Request],
    alarm_admin_delay: float,
    authentication_delay: float,
) -> Tuple[List[Dict[str, Any]], str]:
    ops: List[Dict[str, Any]] = []
    state = "Disarmed"
    busy_until = -1.0  # authentication completion time of current accepted op

    for r in sorted(requests, key=lambda x: (x.time, x.port, x.value)):
        action = "disarm" if r.value == 0 else "arm"
        accepted = r.time >= busy_until  # accepted if admin not working; equality accepted
        if accepted:
            completion_time = r.time + alarm_admin_delay + authentication_delay
            busy_until = completion_time
            # state changes logically at completion, but final state depends on last accepted request value
            state = "Disarmed" if r.value == 0 else "Armed"
            ops.append({
                "input_time": float(r.time),
                "action": action,
                "completed": True,
                "completion_time": float(completion_time),
            })
        else:
            ops.append({
                "input_time": float(r.time),
                "action": action,
                "completed": False,
                "completion_time": None,
            })

    return ops, state


def read_requests(input_file: Optional[str]) -> List[Request]:
    if not input_file:
        return []
    reqs: List[Request] = []
    with open(input_file, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"Invalid input line {line_no}: '{line}' (expected 'HH:MM:SS port value')")
            t = parse_hhmmss_to_seconds(parts[0])
            port = int(parts[1])
            value = int(parts[2])
            reqs.append(Request(time=float(t), port=port, value=value))
    return reqs


# -----------------------------
# Main
# -----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str, default=None)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = parser.parse_args()

    requests = read_requests(args.input_file)

    root = SecureAreaSystem(
        name="secure_area_system",
        parent=None,
        requests=requests,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
    )

    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.max_simulation_time))

    # Gather events from logger
    logger_model: EventLogger = root.logger
    events = sorted(logger_model.records, key=lambda r: (r.time, r.component, r.message, "" if r.state is None else r.state))

    # Determine actual final simulated time: last emitted event time, or max_simulation_time if truncated
    last_event_time = max([0.0] + [ev.time for ev in events])
    simulation_time = min(float(args.max_simulation_time), float(last_event_time))

    # Operations and final state per spec
    operations, final_state = compute_operations_and_final_state(
        requests=requests,
        alarm_admin_delay=float(args.alarm_admin_delay),
        authentication_delay=float(args.authentication_delay),
    )

    # If simulation truncated before last display events, simulation_time should be max_simulation_time
    # We can detect truncation by checking if any event time > max_simulation_time (shouldn't be logged),
    # or if there exist accepted operations whose display time exceeds max_simulation_time.
    max_t = float(args.max_simulation_time)
    truncated = False
    for op, r in zip(operations, sorted(requests, key=lambda x: (x.time, x.port, x.value))):
        if op["completed"]:
            display_time = r.time + float(args.alarm_admin_delay) + float(args.authentication_delay) + float(args.display_delay)
            if display_time > max_t:
                truncated = True
                break
    if truncated:
        simulation_time = max_t

    out = {
        "test_name": args.test_name,
        "simulation_time": float(simulation_time),
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": [ev.to_json() for ev in events if ev.time <= max_t + 1e-12],
        "operations": operations,
    }

    print(json.dumps(out, separators=(",", ":")), file=sys.stdout)


if __name__ == "__main__":
    main()