#!/usr/bin/env python3
"""Secure Area Access Control with PIN Authentication (DES simulation).

Entry point: python run.py

Reads operation requests from --input_file and simulates a pipeline:
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


def parse_hhmmss_to_seconds(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp '{ts}', expected HH:MM:SS")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


def msg_for(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


@dataclass
class EventRecord:
    time: float
    component: str
    message: str
    state: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "time": float(self.time),
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
            "input_time": float(self.input_time),
            "action": self.action,
            "completed": bool(self.completed),
            "completion_time": None if self.completion_time is None else float(self.completion_time),
        }


class SecureAreaSim:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
        max_simulation_time: float,
    ):
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

        # Track last emitted event time for simulation_time.
        self.last_event_time: float = 0.0

    def record_event(self, ev: EventRecord) -> None:
        self.events.append(ev)
        if ev.time > self.last_event_time:
            self.last_event_time = ev.time

    def schedule_pipeline(self, t: float, port: int, value: int) -> None:
        """Schedule alarmAdmin/authentication/display events for an accepted request."""

        msg = msg_for(port, value)
        admin_t = t + self.alarm_admin_delay
        auth_t = admin_t + self.authentication_delay
        disp_t = auth_t + self.display_delay

        # AlarmAdmin event
        def alarm_admin_proc():
            yield self.env.timeout(admin_t - self.env.now)
            self.record_event(EventRecord(time=self.env.now, component="alarmAdmin", message=msg))

        # Authentication event (also completion time)
        def authentication_proc():
            yield self.env.timeout(auth_t - self.env.now)
            state = "DisarmValid" if value == 0 else "ArmValid"
            self.record_event(
                EventRecord(time=self.env.now, component="authentication", message=msg, state=state)
            )

        # Display event (visible state)
        def display_proc():
            yield self.env.timeout(disp_t - self.env.now)
            state = "Disarmed" if value == 0 else "Armed"
            self.record_event(EventRecord(time=self.env.now, component="display", message=msg, state=state))

        self.env.process(alarm_admin_proc())
        self.env.process(authentication_proc())
        self.env.process(display_proc())

        # Update final state immediately for bookkeeping (state transition occurs logically after auth,
        # but final_state depends only on last accepted request value).
        self.current_state = "Disarmed" if value == 0 else "Armed"

        # Mark admin busy until authentication time.
        self.admin_busy_until = auth_t

        # Record operation
        action = "disarm" if value == 0 else "arm"
        self.operations.append(
            OperationRecord(input_time=t, action=action, completed=True, completion_time=auth_t)
        )

    def handle_input(self, t: float, port: int, value: int) -> None:
        msg = msg_for(port, value)
        # input_reader event always
        self.record_event(EventRecord(time=t, component="input_reader", message=msg))

        # Determine acceptance: accepted if not busy at time t.
        if t < self.admin_busy_until:
            action = "disarm" if value == 0 else "arm"
            self.operations.append(
                OperationRecord(input_time=t, action=action, completed=False, completion_time=None)
            )
            return

        self.schedule_pipeline(t, port, value)


def read_requests(path: Optional[str]) -> List[Tuple[float, int, int]]:
    if not path:
        return []
    reqs: List[Tuple[float, int, int]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ts, port_s, val_s = line.split()
            t = float(parse_hhmmss_to_seconds(ts))
            port = int(port_s)
            value = int(val_s)
            reqs.append((t, port, value))
    reqs.sort(key=lambda x: x[0])
    return reqs


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test_name", required=True, type=str)
    ap.add_argument("--input_file", required=False, type=str, default=None)
    ap.add_argument("--alarm_admin_delay", required=False, type=float, default=10.0)
    ap.add_argument("--authentication_delay", required=False, type=float, default=2.0)
    ap.add_argument("--display_delay", required=False, type=float, default=3.0)
    ap.add_argument("--max_simulation_time", required=False, type=float, default=1000.0)
    args = ap.parse_args(argv)

    requests = read_requests(args.input_file)

    env = simpy.Environment(initial_time=0.0)
    sim = SecureAreaSim(
        env,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time,
    )

    # Schedule input handling at their timestamps.
    for t, port, value in requests:
        def make_proc(tt: float, p: int, v: int):
            def proc():
                yield env.timeout(tt - env.now)
                sim.handle_input(tt, p, v)
            return proc
        env.process(make_proc(t, port, value)())

    # Run until either all events processed or max_simulation_time.
    env.run(until=args.max_simulation_time)

    # Determine simulation_time: last emitted event time unless max reached before completion.
    # If max_simulation_time is less than last_event_time, cap it.
    simulation_time = min(sim.last_event_time, float(args.max_simulation_time))
    if simulation_time < sim.last_event_time:
        # Some events would have occurred after max time; ensure we don't report beyond max.
        simulation_time = float(args.max_simulation_time)

    # Sort events by time (stable for same time).
    sim.events.sort(key=lambda e: e.time)
    sim.operations.sort(key=lambda o: o.input_time)

    out = {
        "test_name": args.test_name,
        "simulation_time": float(simulation_time),
        "initial_state": sim.initial_state,
        "final_state": sim.current_state,
        "events": [e.to_json() for e in sim.events if e.time <= float(args.max_simulation_time)],
        "operations": [o.to_json() for o in sim.operations],
    }

    json.dump(out, sys.stdout, separators=(",", ":"), sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
