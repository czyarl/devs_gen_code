import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Optional, List, Dict, Tuple

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


# -----------------------------
# Helpers
# -----------------------------
def hhmmss_to_seconds(s: str) -> float:
    s = s.strip()
    if not s:
        raise ValueError("Empty timestamp")
    parts = s.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {s}")
    h, m, sec = parts
    return int(h) * 3600 + int(m) * 60 + int(sec)


def msg_str(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


@dataclass(frozen=True)
class Request:
    time: float
    port: int
    value: int


# -----------------------------
# Atomic models
# -----------------------------
class InputReader(Atomic):
    """
    Emits each input line at its scheduled time.
    Also forwards the request to AlarmAdmin.
    """
    def __init__(self, name: str, parent: Optional[Coupled], requests: List[Request]):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "out"))       # to AlarmAdmin
        self.add_out_port(Port(dict, "log"))       # to Logger

        self._requests = sorted(list(requests), key=lambda r: r.time)
        self._idx = 0
        self._pending: Optional[Request] = None

        self.hold_in("INIT", 0.0)

    def initialize(self):
        self._idx = 0
        self._pending = None
        if self._requests:
            # schedule first request
            self.hold_in("WAIT", max(0.0, self._requests[0].time))
        else:
            self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self._pending is None:
            return
        payload = {"port": self._pending.port, "value": self._pending.value}
        # forward to admin and log input_reader event
        self.output["out"].add(payload)
        self.output["log"].add({"component": "input_reader", "message": msg_str(payload["port"], payload["value"])})

    def deltint(self):
        if self.phase == "WAIT":
            # time to emit current request
            if self._idx < len(self._requests):
                self._pending = self._requests[self._idx]
                self._idx += 1
                self.hold_in("EMIT", 0.0)
            else:
                self._pending = None
                self.hold_in("PASSIVE", float("inf"))
        elif self.phase == "EMIT":
            # after emitting, schedule next request
            self._pending = None
            if self._idx < len(self._requests):
                next_t = self._requests[self._idx].time
                # current time is already at the emitted request time
                # so sigma is the difference to next request time
                cur_t = self._requests[self._idx - 1].time
                sigma = max(0.0, next_t - cur_t)
                self.hold_in("WAIT", sigma)
            else:
                self.hold_in("PASSIVE", float("inf"))
        else:
            self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        # no external inputs
        self.continuef(e)

    def exit(self):
        pass


class AlarmAdmin(Atomic):
    """
    Accepts request if not busy. If accepted, emits to Authentication after alarm_admin_delay.
    Busy until authentication response time (signaled back via 'done' input).
    Logs accepted admin output event at emission time.
    Also logs operation records (accepted/ignored) at input time.
    """
    def __init__(self, name: str, parent: Optional[Coupled], alarm_admin_delay: float):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in"))         # from InputReader
        self.add_in_port(Port(dict, "done"))       # from Authentication (signals completion)
        self.add_out_port(Port(dict, "out"))       # to Authentication
        self.add_out_port(Port(dict, "log"))       # to Logger (events)
        self.add_out_port(Port(dict, "oplog"))     # to Logger (operations)

        self.alarm_admin_delay = float(alarm_admin_delay)

        self._busy = False
        self._pending_emit: Optional[dict] = None  # payload to emit to Authentication

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self._busy = False
        self._pending_emit = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase == "EMIT" and self._pending_emit is not None:
            payload = dict(self._pending_emit)
            self.output["out"].add(payload)
            self.output["log"].add({"component": "alarmAdmin", "message": msg_str(payload["port"], payload["value"])})

    def deltint(self):
        if self.phase == "EMIT":
            self._pending_emit = None
            self.hold_in("PASSIVE", float("inf"))
        else:
            self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        # Completion signals can arrive at same time as new inputs; rule says new input at exactly
        # authentication time is accepted, so process 'done' first to clear busy.
        if self.input["done"].values:
            # any done clears busy (deterministic single pipeline)
            self._busy = False
            self.input["done"].clear()

        # Process incoming requests
        if self.input["in"].values:
            # There can be multiple at same time; handle in arrival order
            # Accept at most one if not busy; others ignored.
            for payload in list(self.input["in"].values):
                port = int(payload["port"])
                value = int(payload["value"])
                action = "disarm" if value == 0 else "arm"
                if self._busy:
                    # ignored
                    self.output["oplog"].add({
                        "input_time": None,  # logger will fill with current sim time
                        "action": action,
                        "completed": False,
                        "completion_time": None
                    })
                else:
                    # accepted
                    self._busy = True
                    self._pending_emit = {"port": port, "value": value}
                    self.output["oplog"].add({
                        "input_time": None,  # logger will fill with current sim time
                        "action": action,
                        "completed": True,
                        "completion_time": None  # logger will fill when done arrives
                    })
                    # schedule admin output
                    self.hold_in("EMIT", self.alarm_admin_delay)
                    # only one accepted while becoming busy; remaining ignored
            self.input["in"].clear()

        # If we didn't schedule EMIT above, remain passive
        if self.phase != "EMIT":
            self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


class Authentication(Atomic):
    """
    Receives request, after authentication_delay emits validation to Display,
    logs authentication event with state DisarmValid/ArmValid.
    Also signals AlarmAdmin 'done' at same time as authentication output.
    """
    def __init__(self, name: str, parent: Optional[Coupled], authentication_delay: float):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in"))        # from AlarmAdmin
        self.add_out_port(Port(dict, "out"))      # to Display
        self.add_out_port(Port(dict, "done"))     # to AlarmAdmin
        self.add_out_port(Port(dict, "log"))      # to Logger
        self.add_out_port(Port(dict, "opdone"))   # to Logger (completion time)

        self.authentication_delay = float(authentication_delay)

        self._pending: Optional[dict] = None

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self._pending = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase == "EMIT" and self._pending is not None:
            payload = dict(self._pending)
            value = int(payload["value"])
            state = "DisarmValid" if value == 0 else "ArmValid"
            self.output["out"].add(payload)
            self.output["done"].add({"done": True})
            self.output["log"].add({
                "component": "authentication",
                "message": msg_str(int(payload["port"]), value),
                "state": state
            })
            self.output["opdone"].add({"done": True})  # logger will map to last accepted op

    def deltint(self):
        if self.phase == "EMIT":
            self._pending = None
            self.hold_in("PASSIVE", float("inf"))
        else:
            self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        if self.input["in"].values:
            # process first; pipeline ensures at most one outstanding from admin
            payload = list(self.input["in"].values)[0]
            self._pending = {"port": int(payload["port"]), "value": int(payload["value"])}
            self.input["in"].clear()
            self.hold_in("EMIT", self.authentication_delay)
        else:
            self.continuef(e)

    def exit(self):
        pass


class Display(Atomic):
    """
    Receives validated request, after display_delay logs display event with state Armed/Disarmed.
    """
    def __init__(self, name: str, parent: Optional[Coupled], display_delay: float):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in"))        # from Authentication
        self.add_out_port(Port(dict, "log"))      # to Logger

        self.display_delay = float(display_delay)
        self._pending: Optional[dict] = None

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self._pending = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase == "EMIT" and self._pending is not None:
            payload = dict(self._pending)
            value = int(payload["value"])
            state = "Disarmed" if value == 0 else "Armed"
            self.output["log"].add({
                "component": "display",
                "message": msg_str(int(payload["port"]), value),
                "state": state
            })

    def deltint(self):
        if self.phase == "EMIT":
            self._pending = None
            self.hold_in("PASSIVE", float("inf"))
        else:
            self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        if self.input["in"].values:
            payload = list(self.input["in"].values)[0]
            self._pending = {"port": int(payload["port"]), "value": int(payload["value"])}
            self.input["in"].clear()
            self.hold_in("EMIT", self.display_delay)
        else:
            self.continuef(e)

    def exit(self):
        pass


class Logger(Atomic):
    """
    Collects events and operations with timestamps.
    Receives:
      - event logs from components (dict with component/message[/state])
      - operation logs from AlarmAdmin (accepted/ignored)
      - operation completion signals from Authentication
    """
    def __init__(self, name: str, parent: Optional[Coupled]):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "event"))     # event record
        self.add_in_port(Port(dict, "op"))        # operation record (input_time filled here)
        self.add_in_port(Port(dict, "opdone"))    # completion marker

        self.events: List[dict] = []
        self.operations: List[dict] = []
        self._accepted_op_indices: List[int] = []

        self.hold_in("PASSIVE", float("inf"))

    def initialize(self):
        self.events = []
        self.operations = []
        self._accepted_op_indices = []
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        # no outputs
        return

    def deltint(self):
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        # current simulation time is available as self.time (xdevs sets it)
        now = float(self.time)

        if self.input["event"].values:
            for rec in list(self.input["event"].values):
                out = {"time": now, "component": rec["component"], "message": rec["message"]}
                if "state" in rec:
                    out["state"] = rec["state"]
                self.events.append(out)
            self.input["event"].clear()

        if self.input["op"].values:
            for rec in list(self.input["op"].values):
                op = {
                    "input_time": now,
                    "action": rec["action"],
                    "completed": bool(rec["completed"]),
                    "completion_time": None
                }
                idx = len(self.operations)
                self.operations.append(op)
                if op["completed"]:
                    self._accepted_op_indices.append(idx)
            self.input["op"].clear()

        if self.input["opdone"].values:
            # mark completion time for the earliest accepted op without completion_time
            for _ in list(self.input["opdone"].values):
                # find first accepted op lacking completion_time
                for idx in self._accepted_op_indices:
                    if self.operations[idx]["completion_time"] is None:
                        self.operations[idx]["completion_time"] = now
                        break
            self.input["opdone"].clear()

        self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


# -----------------------------
# Coupled system
# -----------------------------
class SecureAreaSystem(Coupled):
    def __init__(
        self,
        name: str,
        parent: Optional[Coupled],
        requests: List[Request],
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Components
        self.reader = InputReader("input_reader_model", self, requests=requests)
        self.admin = AlarmAdmin("alarm_admin_model", self, alarm_admin_delay=alarm_admin_delay)
        self.auth = Authentication("authentication_model", self, authentication_delay=authentication_delay)
        self.display = Display("display_model", self, display_delay=display_delay)
        self.logger = Logger("logger", self)

        for c in [self.reader, self.admin, self.auth, self.display, self.logger]:
            self.add_component(c)

        # Couplings
        self.add_coupling(self.reader.output["out"], self.admin.input["in"])
        self.add_coupling(self.reader.output["log"], self.logger.input["event"])

        self.add_coupling(self.admin.output["out"], self.auth.input["in"])
        self.add_coupling(self.admin.output["log"], self.logger.input["event"])
        self.add_coupling(self.admin.output["oplog"], self.logger.input["op"])

        self.add_coupling(self.auth.output["out"], self.display.input["in"])
        self.add_coupling(self.auth.output["done"], self.admin.input["done"])
        self.add_coupling(self.auth.output["log"], self.logger.input["event"])
        self.add_coupling(self.auth.output["opdone"], self.logger.input["opdone"])

        self.add_coupling(self.display.output["log"], self.logger.input["event"])


# -----------------------------
# Input parsing
# -----------------------------
def read_requests(path: Optional[str]) -> List[Request]:
    if not path:
        return []
    reqs: List[Request] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"Invalid input line {line_no}: {line}")
            t_s, port_s, val_s = parts
            t = float(hhmmss_to_seconds(t_s))
            port = int(port_s)
            val = int(val_s)
            if port != 0:
                raise ValueError(f"Invalid port at line {line_no}: {port}")
            if val not in (0, 1):
                raise ValueError(f"Invalid value at line {line_no}: {val}")
            reqs.append(Request(time=t, port=port, value=val))
    return reqs


def compute_final_state(initial_state: str, operations: List[dict]) -> str:
    state = initial_state
    for op in operations:
        if op["completed"]:
            state = "Disarmed" if op["action"] == "disarm" else "Armed"
    return state


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
        name="system",
        parent=None,
        requests=requests,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
    )

    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(args.max_simulation_time))

    # Gather results from logger
    logger: Logger = root.logger
    events = sorted(logger.events, key=lambda e: (e["time"], e["component"], e["message"]))
    operations = sorted(logger.operations, key=lambda o: o["input_time"])

    initial_state = "Disarmed"
    final_state = compute_final_state(initial_state, operations)

    # Determine simulation_time per spec
    if events:
        last_event_time = max(e["time"] for e in events)
    else:
        last_event_time = 0.0
    simulation_time = min(float(args.max_simulation_time), float(last_event_time))

    out = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": initial_state,
        "final_state": final_state,
        "events": events,
        "operations": operations,
    }

    sys.stdout.write(json.dumps(out, separators=(",", ":")))
    sys.stdout.flush()


if __name__ == "__main__":
    main()