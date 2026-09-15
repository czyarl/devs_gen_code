#!/usr/bin/env python3
import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def parse_hhmmss_to_seconds(ts: str) -> float:
    ts = ts.strip()
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format (expected HH:MM:SS): {ts!r}")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


@dataclass
class InputRequest:
    time: float
    port: int
    value: int
    line_no: int


@dataclass
class OperationRecord:
    input_time: float
    action: str
    completed: bool
    completion_time: Optional[float]


@dataclass
class EventRecord:
    time: float
    component: str
    message: str
    state: Optional[str] = None

    def to_json_obj(self) -> Dict[str, Any]:
        obj = {
            "time": self.time,
            "component": self.component,
            "message": self.message,
        }
        if self.state is not None:
            obj["state"] = self.state
        return obj


def read_requests(input_file: Optional[str]) -> List[InputRequest]:
    if not input_file:
        return []
    reqs: List[InputRequest] = []
    with open(input_file, "r", encoding="utf-8") as f:
        for idx, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"Invalid input line {idx}: {raw!r}")
            ts_s, port_s, value_s = parts
            t = float(parse_hhmmss_to_seconds(ts_s))
            port = int(port_s)
            value = int(value_s)
            if port != 0:
                raise ValueError(f"Invalid port on line {idx}: expected 0, got {port}")
            if value not in (0, 1):
                raise ValueError(f"Invalid value on line {idx}: expected 0/1, got {value}")
            reqs.append(InputRequest(time=t, port=port, value=value, line_no=idx))
    # Stable sort by time; preserve file order for ties
    reqs.sort(key=lambda r: (r.time, r.line_no))
    return reqs


def action_from_value(v: int) -> str:
    return "disarm" if v == 0 else "arm"


def auth_state_from_value(v: int) -> str:
    return "DisarmValid" if v == 0 else "ArmValid"


def display_state_from_value(v: int) -> str:
    return "Disarmed" if v == 0 else "Armed"


def msg_for(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


def simulate(
    requests: List[InputRequest],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float,
) -> Tuple[str, float, List[EventRecord], List[OperationRecord]]:
    # System state
    current_state = "Disarmed"
    initial_state = current_state

    events: List[EventRecord] = []
    operations: List[OperationRecord] = []

    # AlarmAdmin busy until this time (authentication response time of last accepted request)
    busy_until = 0.0

    # Track last emitted event time (subject to max_simulation_time truncation)
    last_emitted_time = 0.0

    for req in requests:
        t = req.time
        # Always record input_reader event at t (if within max time)
        if t <= max_simulation_time:
            events.append(EventRecord(time=t, component="input_reader", message=msg_for(req.port, req.value)))
            last_emitted_time = max(last_emitted_time, t)

        # Determine acceptance: accepted if not busy at time t (busy ends at auth time)
        accepted = t >= busy_until

        if not accepted:
            operations.append(
                OperationRecord(
                    input_time=t,
                    action=action_from_value(req.value),
                    completed=False,
                    completion_time=None,
                )
            )
            continue

        # Accepted: schedule pipeline times
        admin_out_t = t + alarm_admin_delay
        auth_out_t = admin_out_t + authentication_delay
        display_out_t = auth_out_t + display_delay

        # AlarmAdmin is working until authentication response time
        busy_until = auth_out_t

        # Operation completion time is authentication time (even if beyond max_simulation_time)
        operations.append(
            OperationRecord(
                input_time=t,
                action=action_from_value(req.value),
                completed=True,
                completion_time=auth_out_t,
            )
        )

        # Emit component events if within max_simulation_time
        if admin_out_t <= max_simulation_time:
            events.append(EventRecord(time=admin_out_t, component="alarmAdmin", message=msg_for(req.port, req.value)))
            last_emitted_time = max(last_emitted_time, admin_out_t)

        if auth_out_t <= max_simulation_time:
            events.append(
                EventRecord(
                    time=auth_out_t,
                    component="authentication",
                    message=msg_for(req.port, req.value),
                    state=auth_state_from_value(req.value),
                )
            )
            last_emitted_time = max(last_emitted_time, auth_out_t)

        if display_out_t <= max_simulation_time:
            events.append(
                EventRecord(
                    time=display_out_t,
                    component="display",
                    message=msg_for(req.port, req.value),
                    state=display_state_from_value(req.value),
                )
            )
            last_emitted_time = max(last_emitted_time, display_out_t)

        # Update final state after accepted request (regardless of max time)
        # Redundant requests still "set" the state to same value.
        current_state = display_state_from_value(req.value)

    # Sort events by nondecreasing time; stable within same time by insertion order
    events.sort(key=lambda ev: ev.time)

    # Operations must be sorted by input_time (requests already sorted)
    # Ensure stable ordering for ties by preserving append order (already).
    operations_sorted = operations

    # simulation_time:
    # - normally time of last emitted event after all accepted display events are produced
    # - or max_simulation_time only if max time is reached before all accepted display events can be produced.
    #
    # We can detect if any accepted display event would occur after max_simulation_time.
    any_truncated = False
    for op, req in zip(operations_sorted, [r for r in requests]):
        if op.completed:
            # display time for this request
            display_out_t = req.time + alarm_admin_delay + authentication_delay + display_delay
            if display_out_t > max_simulation_time:
                any_truncated = True
                break

    if any_truncated:
        simulation_time = max_simulation_time
    else:
        simulation_time = last_emitted_time

    return initial_state, current_state, simulation_time, events, operations_sorted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test_name", type=str, required=True)
    ap.add_argument("--input_file", type=str, default=None)
    ap.add_argument("--alarm_admin_delay", type=float, default=10.0)
    ap.add_argument("--authentication_delay", type=float, default=2.0)
    ap.add_argument("--display_delay", type=float, default=3.0)
    ap.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = ap.parse_args()

    try:
        requests = read_requests(args.input_file)
        initial_state, final_state, sim_time, events, operations = simulate(
            requests=requests,
            alarm_admin_delay=args.alarm_admin_delay,
            authentication_delay=args.authentication_delay,
            display_delay=args.display_delay,
            max_simulation_time=args.max_simulation_time,
        )

        out = {
            "test_name": args.test_name,
            "simulation_time": sim_time,
            "initial_state": initial_state,
            "final_state": final_state,
            "events": [ev.to_json_obj() for ev in events],
            "operations": [
                {
                    "input_time": op.input_time,
                    "action": op.action,
                    "completed": op.completed,
                    "completion_time": op.completion_time,
                }
                for op in operations
            ],
        }

        # Exactly one JSON object to stdout
        sys.stdout.write(json.dumps(out, separators=(",", ":"), ensure_ascii=False))
        sys.stdout.write("\n")
    except Exception as ex:
        eprint(f"ERROR: {ex}")
        raise


if __name__ == "__main__":
    main()