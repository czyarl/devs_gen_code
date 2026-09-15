import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import simpy


@dataclass(frozen=True)
class Request:
    idx: int
    time_s: float
    port: int
    value: int


def _hhmmss_to_seconds(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {ts!r}")
    h, m, s = (int(p) for p in parts)
    if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
        raise ValueError(f"Invalid timestamp (out of range): {ts!r}")
    return float(h * 3600 + m * 60 + s)


def _parse_requests(input_file: Optional[str]) -> list[Request]:
    if not input_file:
        return []

    path = Path(input_file)
    lines = path.read_text(encoding="utf-8").splitlines()

    requests: list[Request] = []
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line (expected 3 fields): {raw!r}")
        time_s = _hhmmss_to_seconds(parts[0])
        port = int(parts[1])
        value = int(parts[2])
        requests.append(Request(idx=idx, time_s=time_s, port=port, value=value))

    requests.sort(key=lambda r: (r.time_s, r.idx))
    return requests


def _msg(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", required=True, type=str)
    parser.add_argument("--input_file", required=False, type=str)
    parser.add_argument("--alarm_admin_delay", required=False, type=float, default=10.0)
    parser.add_argument("--authentication_delay", required=False, type=float, default=2.0)
    parser.add_argument("--display_delay", required=False, type=float, default=3.0)
    parser.add_argument("--max_simulation_time", required=False, type=float, default=1000.0)
    args = parser.parse_args()

    alarm_admin_delay = float(args.alarm_admin_delay)
    authentication_delay = float(args.authentication_delay)
    display_delay = float(args.display_delay)
    max_simulation_time = float(args.max_simulation_time)

    requests = _parse_requests(args.input_file)

    events: list[dict[str, Any]] = []
    event_seq = 0

    def add_event(time_s: float, component: str, message: str, state: Optional[str] = None) -> None:
        nonlocal event_seq
        event_seq += 1
        rec: dict[str, Any] = {
            "time": float(time_s),
            "component": component,
            "message": message,
            "_seq": event_seq,
        }
        if state is not None:
            rec["state"] = state
        events.append(rec)

    operations: list[dict[str, Any]] = []
    initial_state = "Disarmed"

    # Acceptance logic is deterministic and based only on request times.
    admin_available_time = 0.0
    accepted_info: dict[int, dict[str, float]] = {}
    final_state = initial_state
    max_needed_event_time = 0.0
    max_accepted_display_time = 0.0

    for r in requests:
        action = "disarm" if r.value == 0 else "arm"

        accepted = r.time_s >= admin_available_time
        completion_time: Optional[float]
        if accepted:
            alarm_time = r.time_s + alarm_admin_delay
            auth_time = alarm_time + authentication_delay
            display_time = auth_time + display_delay

            accepted_info[r.idx] = {
                "alarm_time": alarm_time,
                "auth_time": auth_time,
                "display_time": display_time,
            }

            admin_available_time = auth_time
            completion_time = auth_time
            final_state = "Disarmed" if r.value == 0 else "Armed"
            max_accepted_display_time = max(max_accepted_display_time, display_time)
            max_needed_event_time = max(max_needed_event_time, display_time)
        else:
            completion_time = None
            max_needed_event_time = max(max_needed_event_time, r.time_s)

        operations.append(
            {
                "input_time": float(r.time_s),
                "action": action,
                "completed": bool(accepted),
                "completion_time": float(completion_time) if completion_time is not None else None,
            }
        )

    if requests:
        max_needed_event_time = max(max_needed_event_time, max(r.time_s for r in requests))

    env = simpy.Environment(initial_time=0.0)

    def emit_input(req: Request):
        yield env.timeout(req.time_s)
        add_event(env.now, "input_reader", _msg(req.port, req.value))

    def pipeline(req: Request, alarm_time: float, auth_time: float, display_time: float):
        yield env.timeout(req.time_s)
        yield env.timeout(alarm_time - req.time_s)
        add_event(env.now, "alarmAdmin", _msg(req.port, req.value))

        yield env.timeout(auth_time - alarm_time)
        auth_state = "DisarmValid" if req.value == 0 else "ArmValid"
        add_event(env.now, "authentication", _msg(req.port, req.value), state=auth_state)

        yield env.timeout(display_time - auth_time)
        disp_state = "Disarmed" if req.value == 0 else "Armed"
        add_event(env.now, "display", _msg(req.port, req.value), state=disp_state)

    for r in requests:
        env.process(emit_input(r))
        info = accepted_info.get(r.idx)
        if info is not None:
            env.process(pipeline(r, info["alarm_time"], info["auth_time"], info["display_time"]))

    truncated = max_accepted_display_time > max_simulation_time

    def _run_env_through(t: float) -> None:
        if t <= 0.0:
            env.run()
            return
        env.run(until=math.nextafter(float(t), math.inf))

    if truncated:
        _run_env_through(max_simulation_time)
    else:
        _run_env_through(max_needed_event_time)

    events.sort(key=lambda e: (e["time"], e["_seq"]))
    for e in events:
        e.pop("_seq", None)

    if truncated:
        simulation_time = float(max_simulation_time)
    else:
        simulation_time = float(events[-1]["time"]) if events else 0.0

    out = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": initial_state,
        "final_state": final_state,
        "events": events,
        "operations": operations,
    }

    try:
        json.dump(out, sys.stdout)
    except BrokenPipeError:
        # Allow piping to tools like `head` without noisy tracebacks.
        return


if __name__ == "__main__":
    main()
