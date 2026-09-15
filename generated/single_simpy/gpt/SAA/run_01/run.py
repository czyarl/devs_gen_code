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
        raise ValueError(f"Invalid timestamp '{ts}', expected HH:MM:SS")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


@dataclass(frozen=True)
class InputRequest:
    time: float
    port: int
    value: int
    line_no: int


def read_requests(path: Optional[str]) -> List[InputRequest]:
    if not path:
        return []
    reqs: List[InputRequest] = []
    with open(path, "r", encoding="utf-8") as f:
        for idx, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"Invalid input line {idx}: '{raw.rstrip()}' (expected: HH:MM:SS port value)")
            ts_s, port_s, value_s = parts
            t = float(parse_hhmmss_to_seconds(ts_s))
            port = int(port_s)
            value = int(value_s)
            if port != 0:
                raise ValueError(f"Invalid port on line {idx}: {port} (expected 0)")
            if value not in (0, 1):
                raise ValueError(f"Invalid value on line {idx}: {value} (expected 0 or 1)")
            reqs.append(InputRequest(time=t, port=port, value=value, line_no=idx))
    # Stable sort by time then line number (file order for ties)
    reqs.sort(key=lambda r: (r.time, r.line_no))
    return reqs


def msg_for(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


def action_for(value: int) -> str:
    return "disarm" if value == 0 else "arm"


def auth_state_for(value: int) -> str:
    return "DisarmValid" if value == 0 else "ArmValid"


def display_state_for(value: int) -> str:
    return "Disarmed" if value == 0 else "Armed"


def main() -> None:
    ap = argparse.ArgumentParser(description="Secure Area Access Control with PIN Authentication simulation")
    ap.add_argument("--test_name", type=str, required=True)
    ap.add_argument("--input_file", type=str, default=None)
    ap.add_argument("--alarm_admin_delay", type=float, default=10.0)
    ap.add_argument("--authentication_delay", type=float, default=2.0)
    ap.add_argument("--display_delay", type=float, default=3.0)
    ap.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = ap.parse_args()

    # Read inputs
    try:
        requests = read_requests(args.input_file)
    except Exception as ex:
        # Fail fast with stderr message; still exit non-zero
        eprint(f"Error reading input file: {ex}")
        raise

    alarm_admin_delay = float(args.alarm_admin_delay)
    authentication_delay = float(args.authentication_delay)
    display_delay = float(args.display_delay)
    max_time = float(args.max_simulation_time)

    # System state
    initial_state = "Disarmed"
    current_state = initial_state

    # AlarmAdmin "busy until" time (authentication completion time of last accepted request)
    busy_until = 0.0  # free at t=0.0

    events: List[Dict[str, Any]] = []
    operations: List[Dict[str, Any]] = []

    def emit_event(time: float, component: str, message: str, state: Optional[str] = None) -> None:
        if time > max_time:
            return
        ev: Dict[str, Any] = {"time": float(time), "component": component, "message": message}
        if state is not None:
            ev["state"] = state
        events.append(ev)

    # Track last emitted event time to compute simulation_time
    last_emitted_time = 0.0

    for req in requests:
        t = float(req.time)
        message = msg_for(req.port, req.value)

        # Always record input_reader event at t (if within max_time)
        emit_event(t, "input_reader", message)
        if t <= max_time:
            last_emitted_time = max(last_emitted_time, t)

        # Determine acceptance: accepted if AlarmAdmin not working at time t.
        # "A new input at exactly that authentication time is accepted."
        accepted = t >= busy_until

        op_record: Dict[str, Any] = {
            "input_time": float(t),
            "action": action_for(req.value),
            "completed": bool(accepted),
            "completion_time": None,
        }

        if not accepted:
            operations.append(op_record)
            continue

        # Schedule pipeline times
        t_admin = t + alarm_admin_delay
        t_auth = t_admin + authentication_delay
        t_disp = t_auth + display_delay

        # AlarmAdmin becomes busy until authentication output time
        busy_until = t_auth

        # Emit alarmAdmin event (if within max_time)
        emit_event(t_admin, "alarmAdmin", message)
        if t_admin <= max_time:
            last_emitted_time = max(last_emitted_time, t_admin)

        # Emit authentication event (if within max_time)
        emit_event(t_auth, "authentication", message, state=auth_state_for(req.value))
        if t_auth <= max_time:
            last_emitted_time = max(last_emitted_time, t_auth)

        # Update system state at authentication completion time (operation considered completed here)
        # Redundant accepted requests still go through; state remains same if already in that state.
        current_state = display_state_for(req.value)

        # Emit display event (if within max_time)
        emit_event(t_disp, "display", message, state=display_state_for(req.value))
        if t_disp <= max_time:
            last_emitted_time = max(last_emitted_time, t_disp)

        op_record["completion_time"] = float(t_auth)
        operations.append(op_record)

    # Sort events by nondecreasing time; stable for same-time insertion order
    events.sort(key=lambda e: e["time"])

    # operations already in nondecreasing input_time due to request sort
    # Determine simulation_time
    # If any events were clipped by max_time, simulation_time should be max_time only if
    # the last required display event would have occurred after max_time.
    # We can compute the max scheduled event time (including those beyond max_time) for accepted requests.
    max_scheduled_event_time = 0.0
    for op in operations:
        if op["completed"]:
            # completion_time is auth time; display time = auth + display_delay
            auth_t = float(op["completion_time"])
            disp_t = auth_t + display_delay
            max_scheduled_event_time = max(max_scheduled_event_time, disp_t)
        else:
            # ignored: only input event at input_time
            max_scheduled_event_time = max(max_scheduled_event_time, float(op["input_time"]))

    if max_scheduled_event_time > max_time:
        simulation_time = max_time
    else:
        # actual final simulated time is time of last emitted event
        simulation_time = last_emitted_time

    out = {
        "test_name": args.test_name,
        "simulation_time": float(simulation_time),
        "initial_state": initial_state,
        "final_state": current_state,
        "events": events,
        "operations": operations,
    }

    # Output exactly one JSON object (one line)
    sys.stdout.write(json.dumps(out, separators=(",", ":"), sort_keys=False))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()