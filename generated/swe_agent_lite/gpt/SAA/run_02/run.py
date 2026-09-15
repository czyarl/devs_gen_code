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

    def add_event(
        self,
        time: float,
        component: str,
        message: str,
        state: Optional[str] = None,
    ) -> None:
        ev: Dict[str, Any] = {
            "time": float(time),
            "component": component,
            "message": message,
        }
        if state is not None:
            ev["state"] = state
        self.events.append(ev)


def simulate(
    *,
    test_name: str,
    requests: List[InputRequest],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float,
) -> Dict[str, Any]:
    env = simpy.Environment()
    rec = Recorder()

    initial_state = "Disarmed"
    current_state = initial_state

    # AlarmAdmin busy until this time (authentication output time of last accepted request)
    busy_until: float = 0.0

    operations: List[Dict[str, Any]] = []

    # Track last emitted event time (for simulation_time)
    last_emitted_time: float = 0.0

    def emit(time: float, component: str, message: str, state: Optional[str] = None) -> None:
        nonlocal last_emitted_time
        if time > max_simulation_time:
            return
        rec.add_event(time, component, message, state)
        if time > last_emitted_time:
            last_emitted_time = time

    def process_request(req: InputRequest) -> None:
        nonlocal busy_until, current_state

        t = req.input_time
        msg = format_message(req.port, req.value)

        # Always record input_reader event
        emit(t, "input_reader", msg)

        action = "arm" if req.value == 1 else "disarm"

        # Determine acceptance: accepted if not busy at time t.
        # Busy ends exactly at authentication time; input at exactly busy_until is accepted.
        accepted = t >= busy_until

        if not accepted:
            operations.append(
                {
                    "input_time": float(t),
                    "action": action,
                    "completed": False,
                    "completion_time": None,
                }
            )
            return

        # Accepted: schedule pipeline events
        alarm_t = t + alarm_admin_delay
        auth_t = alarm_t + authentication_delay
        disp_t = auth_t + display_delay

        # AlarmAdmin becomes busy until authentication output time
        busy_until = auth_t

        operations.append(
            {
                "input_time": float(t),
                "action": action,
                "completed": True,
                "completion_time": float(auth_t) if auth_t <= max_simulation_time else float(auth_t),
            }
        )

        def pipeline() -> simpy.events.Event:
            nonlocal current_state
            # alarmAdmin output
            yield env.timeout(max(0.0, alarm_t - env.now))
            emit(env.now, "alarmAdmin", msg)

            # authentication output
            yield env.timeout(max(0.0, auth_t - env.now))
            auth_state = "ArmValid" if req.value == 1 else "DisarmValid"
            emit(env.now, "authentication", msg, state=auth_state)

            # display output
            yield env.timeout(max(0.0, disp_t - env.now))
            current_state = "Armed" if req.value == 1 else "Disarmed"
            emit(env.now, "display", msg, state=current_state)

        env.process(pipeline())

    # Create processes that wait until each input time and then handle request
    for req in requests:
        def make_input_proc(r: InputRequest):
            def input_proc():
                yield env.timeout(max(0.0, r.input_time - env.now))
                process_request(r)
            return input_proc
        env.process(make_input_proc(req)())

    # Run simulation until max_simulation_time or until no more events
    env.run(until=max_simulation_time)

    # Sort events by time (stable for same time)
    rec.events.sort(key=lambda e: e["time"])
    operations.sort(key=lambda o: o["input_time"])

    # Determine final simulation_time
    simulation_time = min(max_simulation_time, last_emitted_time)

    return {
        "test_name": test_name,
        "simulation_time": float(simulation_time),
        "initial_state": initial_state,
        "final_state": current_state,
        "events": rec.events,
        "operations": operations,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", required=True, type=str)
    parser.add_argument("--input_file", required=False, type=str, default=None)
    parser.add_argument("--alarm_admin_delay", required=False, type=float, default=10.0)
    parser.add_argument("--authentication_delay", required=False, type=float, default=2.0)
    parser.add_argument("--display_delay", required=False, type=float, default=3.0)
    parser.add_argument("--max_simulation_time", required=False, type=float, default=1000.0)

    args = parser.parse_args(argv)

    try:
        requests = read_requests(args.input_file)
        result = simulate(
            test_name=args.test_name,
            requests=requests,
            alarm_admin_delay=float(args.alarm_admin_delay),
            authentication_delay=float(args.authentication_delay),
            display_delay=float(args.display_delay),
            max_simulation_time=float(args.max_simulation_time),
        )
    except Exception as e:
        print(str(e), file=sys.stderr)
        raise

    json.dump(result, sys.stdout, separators=(",", ":"), sort_keys=False)


if __name__ == "__main__":
    main()
