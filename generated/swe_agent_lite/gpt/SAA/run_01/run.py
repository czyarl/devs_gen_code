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


class Recorder:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def record(self, time: float, component: str, message: str, state: Optional[str] = None) -> None:
        ev: Dict[str, Any] = {
            "time": float(time),
            "component": component,
            "message": message,
        }
        if state is not None:
            ev["state"] = state
        self.events.append(ev)


class SecureAreaSimulation:
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

        self.initial_state = "Disarmed"
        self.state = self.initial_state

        # AlarmAdmin busy until this time (authentication output time of last accepted request)
        self.admin_busy_until: float = 0.0

    def _auth_state(self, value: int) -> str:
        return "DisarmValid" if value == 0 else "ArmValid"

    def _display_state(self, value: int) -> str:
        return "Disarmed" if value == 0 else "Armed"

    def handle_request(self, req: InputRequest) -> Tuple[bool, Optional[float]]:
        """Called at req.input_time. Records input_reader event always.

        Returns (accepted, completion_time).
        """
        msg = format_message(req.port, req.value)
        self.recorder.record(self.env.now, "input_reader", msg)

        # If admin is working on a previous request, ignore.
        # A new input at exactly admin_busy_until is accepted.
        if self.env.now < self.admin_busy_until:
            return False, None

        accepted_time = self.env.now
        completion_time = accepted_time + self.alarm_admin_delay + self.authentication_delay
        self.admin_busy_until = completion_time

        # Schedule pipeline events
        self.env.process(self._pipeline(req, accepted_time))
        return True, completion_time

    def _pipeline(self, req: InputRequest, accepted_time: float):
        msg = format_message(req.port, req.value)

        # alarmAdmin output
        yield self.env.timeout(self.alarm_admin_delay)
        self.recorder.record(self.env.now, "alarmAdmin", msg)

        # authentication output
        yield self.env.timeout(self.authentication_delay)
        self.recorder.record(self.env.now, "authentication", msg, state=self._auth_state(req.value))

        # Update internal state at completion (authentication time)
        self.state = self._display_state(req.value)

        # display output
        yield self.env.timeout(self.display_delay)
        self.recorder.record(self.env.now, "display", msg, state=self._display_state(req.value))


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


def main(argv: Optional[List[str]] = None) -> None:
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
    sim = SecureAreaSimulation(
        env=env,
        recorder=recorder,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time,
    )

    operations: List[Dict[str, Any]] = []

    def input_process():
        for req in requests:
            # Stop injecting new inputs beyond max_simulation_time
            if req.input_time > sim.max_simulation_time:
                break
            yield env.timeout(req.input_time - env.now)
            accepted, completion_time = sim.handle_request(req)
            operations.append(
                {
                    "input_time": float(req.input_time),
                    "action": "disarm" if req.value == 0 else "arm",
                    "completed": bool(accepted),
                    "completion_time": float(completion_time) if completion_time is not None else None,
                }
            )

    env.process(input_process())

    # Run until max_simulation_time; events scheduled after are not produced.
    env.run(until=sim.max_simulation_time)

    # Determine simulation_time: last emitted event time if any, else current env.now
    if recorder.events:
        last_event_time = max(ev["time"] for ev in recorder.events)
        simulation_time = float(min(last_event_time, sim.max_simulation_time))
    else:
        simulation_time = float(env.now)

    # Sort events by nondecreasing time (stable for same-time insertion order)
    recorder.events.sort(key=lambda e: e["time"])
    operations.sort(key=lambda o: o["input_time"])

    output = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": sim.initial_state,
        "final_state": sim.state,
        "events": recorder.events,
        "operations": operations,
    }

    json.dump(output, sys.stdout, separators=(",", ":"), sort_keys=False)


if __name__ == "__main__":
    main()
