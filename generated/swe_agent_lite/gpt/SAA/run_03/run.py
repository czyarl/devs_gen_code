import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import simpy


def hhmmss_to_seconds(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp: {ts}")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


def format_message(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


@dataclass
class InputRequest:
    input_time: float
    port: int
    value: int


def read_requests(path: Optional[str]) -> List[InputRequest]:
    if not path:
        return []
    reqs: List[InputRequest] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ts, port_s, value_s = line.split()
            reqs.append(
                InputRequest(
                    input_time=float(hhmmss_to_seconds(ts)),
                    port=int(port_s),
                    value=int(value_s),
                )
            )
    reqs.sort(key=lambda r: r.input_time)
    return reqs


class Recorder:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def add(self, time: float, component: str, message: str, state: Optional[str] = None) -> None:
        ev: Dict[str, Any] = {
            "time": float(time),
            "component": component,
            "message": message,
        }
        if state is not None:
            ev["state"] = state
        self.events.append(ev)


class SecureAreaSim:
    def __init__(
        self,
        env: simpy.Environment,
        recorder: Recorder,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
        max_simulation_time: float,
    ) -> None:
        self.env = env
        self.recorder = recorder
        self.alarm_admin_delay = float(alarm_admin_delay)
        self.authentication_delay = float(authentication_delay)
        self.display_delay = float(display_delay)
        self.max_simulation_time = float(max_simulation_time)

        self.state: str = "Disarmed"
        self.admin_busy_until: float = 0.0  # authentication time of current accepted op

        self.operations: List[Dict[str, Any]] = []

    def action_for_value(self, value: int) -> str:
        return "disarm" if value == 0 else "arm"

    def auth_state_for_value(self, value: int) -> str:
        return "DisarmValid" if value == 0 else "ArmValid"

    def display_state_for_value(self, value: int) -> str:
        return "Disarmed" if value == 0 else "Armed"

    def handle_request(self, req: InputRequest) -> None:
        # input_reader event always
        msg = format_message(req.port, req.value)
        self.recorder.add(self.env.now, "input_reader", msg)

        accepted = self.env.now >= self.admin_busy_until
        op: Dict[str, Any] = {
            "input_time": float(req.input_time),
            "action": self.action_for_value(req.value),
            "completed": bool(accepted),
            "completion_time": None,
        }

        if not accepted:
            self.operations.append(op)
            return

        t_alarm_admin = self.env.now + self.alarm_admin_delay
        t_auth = t_alarm_admin + self.authentication_delay
        t_display = t_auth + self.display_delay

        # AlarmAdmin becomes busy until authentication time
        self.admin_busy_until = t_auth
        op["completion_time"] = float(t_auth)
        self.operations.append(op)

        def pipeline() -> simpy.events.Event:
            # alarmAdmin output
            yield self.env.timeout(self.alarm_admin_delay)
            if self.env.now > self.max_simulation_time:
                return
            self.recorder.add(self.env.now, "alarmAdmin", msg)

            # authentication output
            yield self.env.timeout(self.authentication_delay)
            if self.env.now > self.max_simulation_time:
                return
            self.recorder.add(self.env.now, "authentication", msg, state=self.auth_state_for_value(req.value))

            # update internal state at authentication completion
            self.state = self.display_state_for_value(req.value)

            # display output
            yield self.env.timeout(self.display_delay)
            if self.env.now > self.max_simulation_time:
                return
            self.recorder.add(self.env.now, "display", msg, state=self.display_state_for_value(req.value))

        self.env.process(pipeline())


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", required=True, type=str)
    parser.add_argument("--input_file", required=False, type=str, default=None)
    parser.add_argument("--alarm_admin_delay", required=False, type=float, default=10.0)
    parser.add_argument("--authentication_delay", required=False, type=float, default=2.0)
    parser.add_argument("--display_delay", required=False, type=float, default=3.0)
    parser.add_argument("--max_simulation_time", required=False, type=float, default=1000.0)
    args = parser.parse_args(argv)

    requests = read_requests(args.input_file)

    env = simpy.Environment()
    recorder = Recorder()
    sim = SecureAreaSim(
        env=env,
        recorder=recorder,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time,
    )

    initial_state = sim.state

    # schedule input arrivals
    for req in requests:
        def make_proc(r: InputRequest):
            def proc():
                yield env.timeout(r.input_time - env.now)
                sim.handle_request(r)
            return proc
        env.process(make_proc(req)())

    # run until max_simulation_time
    env.run(until=args.max_simulation_time)

    # Determine simulation_time: last emitted event time if any, else 0.0; but capped by max_simulation_time
    if recorder.events:
        last_event_time = max(ev["time"] for ev in recorder.events)
        simulation_time = min(float(args.max_simulation_time), float(last_event_time))
    else:
        simulation_time = 0.0

    # sort outputs
    recorder.events.sort(key=lambda e: (e["time"], e["component"]))
    sim.operations.sort(key=lambda o: o["input_time"])

    out: Dict[str, Any] = {
        "test_name": args.test_name,
        "simulation_time": float(simulation_time),
        "initial_state": initial_state,
        "final_state": sim.state,
        "events": recorder.events,
        "operations": sim.operations,
    }

    json.dump(out, sys.stdout, separators=(",", ":"), sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
