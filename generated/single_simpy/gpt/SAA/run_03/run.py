import argparse
import json
import sys
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def parse_hhmmss_to_seconds(ts: str) -> float:
    ts = ts.strip()
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format (expected HH:MM:SS): {ts}")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


@dataclass
class InputRequest:
    input_time: float
    port: int
    value: int
    line_no: int


@dataclass
class OperationRecord:
    input_time: float
    action: str
    completed: bool
    completion_time: Optional[float]


def msg_for(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


def action_for(value: int) -> str:
    if value == 0:
        return "disarm"
    if value == 1:
        return "arm"
    raise ValueError(f"Invalid value (expected 0 or 1): {value}")


def auth_state_for(value: int) -> str:
    return "DisarmValid" if value == 0 else "ArmValid"


def display_state_for(value: int) -> str:
    return "Disarmed" if value == 0 else "Armed"


def read_requests(path: Optional[str]) -> List[InputRequest]:
    if not path:
        return []
    reqs: List[InputRequest] = []
    with open(path, "r", encoding="utf-8") as f:
        for i, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"Invalid input line {i}: {raw!r}")
            ts_s, port_s, value_s = parts
            t = float(parse_hhmmss_to_seconds(ts_s))
            port = int(port_s)
            value = int(value_s)
            if port != 0:
                raise ValueError(f"Invalid port on line {i} (expected 0): {port}")
            if value not in (0, 1):
                raise ValueError(f"Invalid value on line {i} (expected 0 or 1): {value}")
            reqs.append(InputRequest(input_time=t, port=port, value=value, line_no=i))

    # Stable sort by time then line number (deterministic ordering for same timestamps)
    reqs.sort(key=lambda r: (r.input_time, r.line_no))
    return reqs


def add_event(events: List[Dict[str, Any]], time: float, component: str, message: str, state: Optional[str] = None):
    ev = {"time": float(time), "component": component, "message": message}
    if state is not None:
        ev["state"] = state
    events.append(ev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test_name", type=str, required=True)
    ap.add_argument("--input_file", type=str, default=None)
    ap.add_argument("--alarm_admin_delay", type=float, default=10.0)
    ap.add_argument("--authentication_delay", type=float, default=2.0)
    ap.add_argument("--display_delay", type=float, default=3.0)
    ap.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = ap.parse_args()

    test_name: str = args.test_name
    alarm_admin_delay: float = float(args.alarm_admin_delay)
    authentication_delay: float = float(args.authentication_delay)
    display_delay: float = float(args.display_delay)
    max_time: float = float(args.max_simulation_time)

    if alarm_admin_delay < 0 or authentication_delay < 0 or display_delay < 0 or max_time < 0:
        raise ValueError("Delays and max_simulation_time must be non-negative.")

    requests = read_requests(args.input_file)

    initial_state = "Disarmed"
    current_state = initial_state

    events: List[Dict[str, Any]] = []
    operations: List[OperationRecord] = []

    # AlarmAdmin busy-until time is the authentication output time of the accepted request.
    admin_busy_until: float = 0.0  # free at time 0.0

    # We'll schedule accepted pipeline events, but only emit those with time <= max_time.
    scheduled_events: List[Tuple[float, int, Dict[str, Any]]] = []
    # tuple: (time, seq, event_dict). seq ensures deterministic ordering for same time.
    seq_counter = 0

    def schedule_event(ev_time: float, ev: Dict[str, Any]):
        nonlocal seq_counter
        seq_counter += 1
        scheduled_events.append((float(ev_time), seq_counter, ev))

    # Process each input request in time order, applying acceptance/ignore rules.
    for req in requests:
        t = req.input_time
        m = msg_for(req.port, req.value)

        # input_reader event always recorded (subject to max_time cutoff later)
        schedule_event(t, {"time": float(t), "component": "input_reader", "message": m})

        accepted = t >= admin_busy_until  # accepted if admin not working; equality accepted
        if not accepted:
            operations.append(OperationRecord(
                input_time=float(t),
                action=action_for(req.value),
                completed=False,
                completion_time=None
            ))
            continue

        # Accepted: compute pipeline times
        alarm_t = t + alarm_admin_delay
        auth_t = alarm_t + authentication_delay
        disp_t = auth_t + display_delay

        # Admin becomes busy until authentication output time
        admin_busy_until = auth_t

        # Operation record: completion time is authentication time
        operations.append(OperationRecord(
            input_time=float(t),
            action=action_for(req.value),
            completed=True,
            completion_time=float(auth_t)
        ))

        # Schedule component events
        schedule_event(alarm_t, {"time": float(alarm_t), "component": "alarmAdmin", "message": m})
        schedule_event(auth_t, {
            "time": float(auth_t),
            "component": "authentication",
            "message": m,
            "state": auth_state_for(req.value)
        })
        schedule_event(disp_t, {
            "time": float(disp_t),
            "component": "display",
            "message": m,
            "state": display_state_for(req.value)
        })

        # Update final state after last accepted request (state changes logically after completion,
        # but final_state definition is after last accepted request; value determines it).
        current_state = display_state_for(req.value)

    # Emit scheduled events in time order, respecting max_simulation_time cutoff.
    scheduled_events.sort(key=lambda x: (x[0], x[1]))

    last_emitted_time = 0.0
    for ev_time, _seq, ev in scheduled_events:
        if ev_time > max_time:
            break
        # Ensure numeric time field is consistent
        ev_out = dict(ev)
        ev_out["time"] = float(ev_time)
        events.append(ev_out)
        last_emitted_time = float(ev_time)

    # simulation_time: last emitted event time, unless no events emitted then 0.0.
    # If cutoff prevented later events, simulation_time is max_simulation_time (per spec).
    # Determine whether we cut off any scheduled event.
    cut_off = any(ev_time > max_time for ev_time, _seq, _ev in scheduled_events)
    if cut_off:
        simulation_time = float(max_time)
    else:
        simulation_time = float(last_emitted_time) if events else 0.0

    # Sort operations by input_time (they already are, but enforce)
    operations.sort(key=lambda o: o.input_time)

    output = {
        "test_name": test_name,
        "simulation_time": simulation_time,
        "initial_state": initial_state,
        "final_state": current_state,
        "events": events,
        "operations": [
            {
                "input_time": float(op.input_time),
                "action": op.action,
                "completed": bool(op.completed),
                "completion_time": (float(op.completion_time) if op.completion_time is not None else None),
            }
            for op in operations
        ],
    }

    # Print exactly one JSON object to stdout
    json.dump(output, sys.stdout, separators=(",", ":"), ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()