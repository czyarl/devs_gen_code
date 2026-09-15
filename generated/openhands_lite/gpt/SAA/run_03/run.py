import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import simpy


@dataclass(frozen=True)
class InputRequest:
    time: float
    port: int
    value: int
    idx: int


def _parse_hhmmss(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp '{ts}', expected HH:MM:SS")
    h, m, s = (int(p) for p in parts)
    return float(h * 3600 + m * 60 + s)


def read_requests(path: Optional[str]) -> List[InputRequest]:
    if not path:
        return []

    requests: List[InputRequest] = []
    with open(path, "r", encoding="utf-8") as f:
        idx = 0
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"Invalid input line: '{raw.rstrip()}'")
            t = _parse_hhmmss(parts[0])
            port = int(parts[1])
            value = int(parts[2])
            requests.append(InputRequest(time=t, port=port, value=value, idx=idx))
            idx += 1

    requests.sort(key=lambda r: (r.time, r.idx))
    return requests


def _msg(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


def _action(value: int) -> str:
    if value == 0:
        return "disarm"
    if value == 1:
        return "arm"
    raise ValueError(f"Invalid value '{value}', expected 0 or 1")


def _auth_state(value: int) -> str:
    return "DisarmValid" if value == 0 else "ArmValid"


def _display_state(value: int) -> str:
    return "Disarmed" if value == 0 else "Armed"


def precompute_acceptance(
    requests: List[InputRequest],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, float]]]:
    admin_free_time = 0.0
    operations: List[Dict[str, Any]] = []
    accepted_timings: Dict[int, Dict[str, float]] = {}

    for r in requests:
        act = _action(r.value)
        if r.time < admin_free_time:
            operations.append(
                {
                    "input_time": r.time,
                    "action": act,
                    "completed": False,
                    "completion_time": None,
                }
            )
            continue

        alarm_time = r.time + alarm_admin_delay
        auth_time = alarm_time + authentication_delay
        display_time = auth_time + display_delay
        admin_free_time = auth_time

        operations.append(
            {
                "input_time": r.time,
                "action": act,
                "completed": True,
                "completion_time": auth_time,
            }
        )
        accepted_timings[r.idx] = {
            "alarm": alarm_time,
            "auth": auth_time,
            "display": display_time,
        }

    return operations, accepted_timings


class EventLog:
    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []
        self._seq = 0

    def add(self, event: Dict[str, Any]) -> None:
        event["_seq"] = self._seq
        self._seq += 1
        self._events.append(event)

    def to_sorted_list(self) -> List[Dict[str, Any]]:
        self._events.sort(key=lambda e: (e["time"], e["_seq"]))
        for e in self._events:
            e.pop("_seq", None)
        return self._events

    def max_time(self) -> float:
        if not self._events:
            return 0.0
        return max(e["time"] for e in self._events)


def simulate(
    requests: List[InputRequest],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float,
) -> Tuple[List[Dict[str, Any]], str, float]:
    operations, accepted_timings = precompute_acceptance(
        requests, alarm_admin_delay, authentication_delay, display_delay
    )

    env = simpy.Environment()
    log = EventLog()
    system_state = {"value": "Disarmed"}

    def handle_request(r: InputRequest) -> Any:
        yield env.timeout(alarm_admin_delay)
        log.add(
            {
                "time": float(env.now),
                "component": "alarmAdmin",
                "message": _msg(r.port, r.value),
            }
        )

        yield env.timeout(authentication_delay)
        system_state["value"] = _display_state(r.value)
        log.add(
            {
                "time": float(env.now),
                "component": "authentication",
                "message": _msg(r.port, r.value),
                "state": _auth_state(r.value),
            }
        )

        yield env.timeout(display_delay)
        log.add(
            {
                "time": float(env.now),
                "component": "display",
                "message": _msg(r.port, r.value),
                "state": _display_state(r.value),
            }
        )

    def input_reader() -> Any:
        for r in requests:
            if r.time > env.now:
                yield env.timeout(r.time - env.now)

            log.add(
                {
                    "time": float(env.now),
                    "component": "input_reader",
                    "message": _msg(r.port, r.value),
                }
            )

            if r.idx in accepted_timings:
                env.process(handle_request(r))

    env.process(input_reader())

    expected_last_time = 0.0
    if requests:
        expected_last_time = max(expected_last_time, max(r.time for r in requests))
    if accepted_timings:
        expected_last_time = max(
            expected_last_time, max(t["display"] for t in accepted_timings.values())
        )

    run_until = min(max_simulation_time, expected_last_time)
    env.run(until=run_until)

    truncated = expected_last_time > max_simulation_time
    simulation_time = float(max_simulation_time if truncated else log.max_time())

    return log.to_sorted_list(), system_state["value"], simulation_time


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Secure Area Access Control simulation (DES with SimPy)."
    )
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str, default=None)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)

    args = parser.parse_args(argv)

    requests = read_requests(args.input_file)

    events, final_state, simulation_time = simulate(
        requests=requests,
        alarm_admin_delay=float(args.alarm_admin_delay),
        authentication_delay=float(args.authentication_delay),
        display_delay=float(args.display_delay),
        max_simulation_time=float(args.max_simulation_time),
    )

    operations, _ = precompute_acceptance(
        requests,
        float(args.alarm_admin_delay),
        float(args.authentication_delay),
        float(args.display_delay),
    )

    output: Dict[str, Any] = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": events,
        "operations": operations,
    }

    json.dump(output, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
