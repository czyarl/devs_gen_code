#!/usr/bin/env python3
"""Secure Area Access Control with PIN Authentication (DES simulation).

Entry point: python run.py

Reads operation requests from a text file and simulates a simple
pipeline: input_reader -> alarmAdmin -> authentication -> display.

Outputs exactly one JSON object to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import simpy


def hhmmss_to_seconds(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp '{ts}', expected HH:MM:SS")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


def parse_input_file(path: Optional[str]) -> List[Tuple[float, int, int]]:
    if not path:
        return []
    reqs: List[Tuple[float, int, int]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ts, port_s, val_s = line.split()
            t = float(hhmmss_to_seconds(ts))
            port = int(port_s)
            val = int(val_s)
            reqs.append((t, port, val))
    reqs.sort(key=lambda x: x[0])
    return reqs


@dataclass
class EventRecord:
    time: float
    component: str
    message: str
    state: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "time": self.time,
            "component": self.component,
            "message": self.message,
        }
        if self.state is not None:
            d["state"] = self.state
        return d


@dataclass
class OperationRecord:
    input_time: float
    action: str
    completed: bool
    completion_time: Optional[float]

    def to_json(self) -> Dict[str, Any]:
        return {
            "input_time": self.input_time,
            "action": self.action,
            "completed": self.completed,
            "completion_time": self.completion_time,
        }


class SecureAreaSim:
    def __init__(
        self,
        env: simpy.Environment,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
        max_simulation_time: float,
    ) -> None:
        self.env = env
        self.alarm_admin_delay = float(alarm_admin_delay)
        self.authentication_delay = float(authentication_delay)
        self.display_delay = float(display_delay)
        self.max_simulation_time = float(max_simulation_time)

        self.events: List[EventRecord] = []
        self.operations: List[OperationRecord] = []

        self.initial_state = "Disarmed"
        self.current_state = self.initial_state

        # AlarmAdmin busy until this time (authentication output time).
        self.admin_busy_until: float = 0.0

    @staticmethod
    def msg(port: int, value: int) -> str:
        return f"{{{port} {value}}}"

    def record_event(
        self, time: float, component: str, message: str, state: Optional[str] = None
    ) -> None:
        self.events.append(EventRecord(time=time, component=component, message=message, state=state))

    def schedule_request(self, t: float, port: int, value: int) -> None:
        self.env.process(self._handle_request(t, port, value))

    def _handle_request(self, t: float, port: int, value: int):
        # Wait until request time
        if t > self.max_simulation_time:
            return
        yield self.env.timeout(max(0.0, t - self.env.now))

        # input_reader event always
        self.record_event(self.env.now, "input_reader", self.msg(port, value))

        action = "disarm" if value == 0 else "arm"

        # Busy check: accepted if env.now >= admin_busy_until
        if self.env.now < self.admin_busy_until:
            self.operations.append(
                OperationRecord(
                    input_time=self.env.now,
                    action=action,
                    completed=False,
                    completion_time=None,
                )
            )
            return

        # Accept
        alarm_time = self.env.now + self.alarm_admin_delay
        auth_time = alarm_time + self.authentication_delay
        disp_time = auth_time + self.display_delay

        self.admin_busy_until = auth_time

        self.operations.append(
            OperationRecord(
                input_time=self.env.now,
                action=action,
                completed=True,
                completion_time=auth_time,
            )
        )

        # alarmAdmin event
        if alarm_time <= self.max_simulation_time:
            yield self.env.timeout(self.alarm_admin_delay)
            self.record_event(self.env.now, "alarmAdmin", self.msg(port, value))
        else:
            return

        # authentication event
        if auth_time <= self.max_simulation_time:
            yield self.env.timeout(self.authentication_delay)
            auth_state = "DisarmValid" if value == 0 else "ArmValid"
            self.record_event(
                self.env.now,
                "authentication",
                self.msg(port, value),
                state=auth_state,
            )
            # Operation completes here; update system state.
            self.current_state = "Disarmed" if value == 0 else "Armed"
        else:
            return

        # display event
        if disp_time <= self.max_simulation_time:
            yield self.env.timeout(self.display_delay)
            disp_state = "Disarmed" if value == 0 else "Armed"
            self.record_event(
                self.env.now,
                "display",
                self.msg(port, value),
                state=disp_state,
            )
        else:
            return


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--test_name", type=str, required=True)
    p.add_argument("--input_file", type=str, default=None)
    p.add_argument("--alarm_admin_delay", type=float, default=10.0)
    p.add_argument("--authentication_delay", type=float, default=2.0)
    p.add_argument("--display_delay", type=float, default=3.0)
    p.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = p.parse_args(argv)

    requests = parse_input_file(args.input_file)

    env = simpy.Environment(initial_time=0.0)
    sim = SecureAreaSim(
        env,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time,
    )

    for t, port, value in requests:
        sim.schedule_request(t, port, value)

    # Run until max_simulation_time or until no events remain.
    env.run(until=args.max_simulation_time)

    # Sort outputs
    sim.events.sort(key=lambda e: (e.time, e.component))
    sim.operations.sort(key=lambda o: o.input_time)

    # Determine simulation_time: last emitted event time, or max_simulation_time if clipped.
    last_event_time = max((e.time for e in sim.events), default=0.0)
    simulation_time = min(args.max_simulation_time, last_event_time)
    if last_event_time > args.max_simulation_time:
        simulation_time = args.max_simulation_time

    out = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": sim.initial_state,
        "final_state": sim.current_state,
        "events": [e.to_json() for e in sim.events if e.time <= args.max_simulation_time],
        "operations": [o.to_json() for o in sim.operations],
    }

    json.dump(out, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
