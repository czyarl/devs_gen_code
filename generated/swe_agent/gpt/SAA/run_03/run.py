#!/usr/bin/env python3
"""Secure Area Access Control with PIN Authentication (DES simulation).

Entry point: python run.py

Reads operation requests from a text file and simulates a pipeline:
input_reader -> alarmAdmin -> authentication -> display.

Outputs exactly one JSON object to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import simpy


def _parse_hhmmss_to_seconds(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp '{ts}', expected HH:MM:SS")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


def _msg(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


@dataclass(frozen=True)
class InputRequest:
    time: float
    port: int
    value: int


class Recorder:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def add_event(self, *, time: float, component: str, message: str, state: Optional[str] = None) -> None:
        ev: Dict[str, Any] = {"time": float(time), "component": component, "message": message}
        if state is not None:
            ev["state"] = state
        self.events.append(ev)


class SecureAreaSimulation:
    def __init__(
        self,
        env: simpy.Environment,
        recorder: Recorder,
        *,
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

        # AlarmAdmin busy until this time (authentication completion time of last accepted request)
        self._busy_until: float = 0.0

        self.operations: List[Dict[str, Any]] = []

    def schedule_request(self, req: InputRequest) -> None:
        self.env.process(self._handle_request(req))

    def _handle_request(self, req: InputRequest):
        # Wait until input time
        yield self.env.timeout(req.time - self.env.now)

        # Always record input_reader event
        self.recorder.add_event(time=self.env.now, component="input_reader", message=_msg(req.port, req.value))

        action = "disarm" if req.value == 0 else "arm"

        # If busy strictly after now, ignore. If busy_until == now, accept.
        if self._busy_until > self.env.now:
            self.operations.append(
                {
                    "input_time": float(req.time),
                    "action": action,
                    "completed": False,
                    "completion_time": None,
                }
            )
            return

        # Accept
        alarm_time = req.time + self.alarm_admin_delay
        auth_time = alarm_time + self.authentication_delay
        display_time = auth_time + self.display_delay

        self._busy_until = auth_time

        self.operations.append(
            {
                "input_time": float(req.time),
                "action": action,
                "completed": True,
                "completion_time": float(auth_time),
            }
        )

        # alarmAdmin event
        yield self.env.timeout(alarm_time - self.env.now)
        self.recorder.add_event(time=self.env.now, component="alarmAdmin", message=_msg(req.port, req.value))

        # authentication event
        yield self.env.timeout(auth_time - self.env.now)
        auth_state = "DisarmValid" if req.value == 0 else "ArmValid"
        self.recorder.add_event(
            time=self.env.now,
            component="authentication",
            message=_msg(req.port, req.value),
            state=auth_state,
        )

        # Update internal state at authentication completion
        self.state = "Disarmed" if req.value == 0 else "Armed"

        # display event
        yield self.env.timeout(display_time - self.env.now)
        self.recorder.add_event(
            time=self.env.now,
            component="display",
            message=_msg(req.port, req.value),
            state=self.state,
        )


def _read_requests(path: Optional[str]) -> List[InputRequest]:
    if not path:
        return []
    reqs: List[InputRequest] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ts, port_s, value_s = line.split()
            t = _parse_hhmmss_to_seconds(ts)
            port = int(port_s)
            value = int(value_s)
            reqs.append(InputRequest(time=float(t), port=port, value=value))
    # Ensure deterministic ordering for same-time inputs: preserve file order.
    return reqs


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str, required=False)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)

    args = parser.parse_args(argv)

    requests = _read_requests(args.input_file)

    env = simpy.Environment()
    recorder = Recorder()
    sim = SecureAreaSimulation(
        env,
        recorder,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time,
    )

    for req in requests:
        sim.schedule_request(req)

    # Run until max_simulation_time or until all events processed.
    env.run(until=args.max_simulation_time)

    # Determine simulation_time: last emitted event time if any, else 0.0.
    if recorder.events:
        last_event_time = max(ev["time"] for ev in recorder.events)
    else:
        last_event_time = 0.0

    simulation_time = float(min(last_event_time, args.max_simulation_time))

    # Sort events by nondecreasing time (stable for same-time)
    recorder.events.sort(key=lambda e: e["time"])
    sim.operations.sort(key=lambda o: o["input_time"])

    out = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": sim.initial_state,
        "final_state": sim.state,
        "events": recorder.events,
        "operations": sim.operations,
    }

    json.dump(out, sys.stdout, separators=(",", ":"), sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
