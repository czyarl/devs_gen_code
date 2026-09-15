import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import simpy


@dataclass(frozen=True)
class InputRequest:
    input_time: float
    port: int
    value: int


def _ts_to_seconds(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {ts!r}")
    h, m, s = (int(p) for p in parts)
    return float(h * 3600 + m * 60 + s)


def _parse_input_file(path: Path) -> list[InputRequest]:
    requests: list[InputRequest] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(
                f"Invalid input line {line_no}: expected 3 fields, got {len(parts)}"
            )
        ts, port_s, value_s = parts
        t = _ts_to_seconds(ts)
        port = int(port_s)
        value = int(value_s)
        if port != 0:
            raise ValueError(f"Invalid port on line {line_no}: {port} (expected 0)")
        if value not in (0, 1):
            raise ValueError(
                f"Invalid value on line {line_no}: {value} (expected 0 or 1)"
            )
        requests.append(InputRequest(input_time=t, port=port, value=value))

    # Preserve file order for equal timestamps, but ensure nondecreasing time overall.
    # (Input is typically already sorted; this makes behavior deterministic.)
    return sorted(requests, key=lambda r: r.input_time)


def _msg(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


def _action(value: int) -> str:
    return "disarm" if value == 0 else "arm"


def _auth_state(value: int) -> str:
    return "DisarmValid" if value == 0 else "ArmValid"


def _display_state(value: int) -> str:
    return "Disarmed" if value == 0 else "Armed"


def _schedule_event(
    env: simpy.Environment,
    events: list[dict[str, Any]],
    *,
    at: float,
    component: str,
    message: str,
    state: Optional[str] = None,
) -> None:
    def _proc() -> simpy.events.Event:
        delay = at - env.now
        if delay < 0:
            delay = 0
        yield env.timeout(delay)
        ev: dict[str, Any] = {"time": float(at), "component": component, "message": message}
        if state is not None:
            ev["state"] = state
        events.append(ev)

    env.process(_proc())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", required=True, type=str)
    parser.add_argument("--input_file", required=False, type=str)
    parser.add_argument("--alarm_admin_delay", required=False, type=float, default=10.0)
    parser.add_argument("--authentication_delay", required=False, type=float, default=2.0)
    parser.add_argument("--display_delay", required=False, type=float, default=3.0)
    parser.add_argument("--max_simulation_time", required=False, type=float, default=1000.0)
    args = parser.parse_args(argv)

    initial_state = "Disarmed"

    requests: list[InputRequest] = []
    if args.input_file:
        requests = _parse_input_file(Path(args.input_file))

    # Precompute acceptance/ignoring and completion times deterministically.
    operations: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []

    busy_until = 0.0
    current_state = initial_state
    theoretical_last_time = 0.0

    for req in requests:
        t = float(req.input_time)
        theoretical_last_time = max(theoretical_last_time, t)

        op: dict[str, Any] = {
            "input_time": t,
            "action": _action(req.value),
            "completed": False,
            "completion_time": None,
        }

        if t >= busy_until:
            admin_time = t + float(args.alarm_admin_delay)
            auth_time = admin_time + float(args.authentication_delay)
            display_time = auth_time + float(args.display_delay)

            op["completed"] = True
            op["completion_time"] = float(auth_time)

            accepted.append(
                {
                    "input_time": t,
                    "port": req.port,
                    "value": req.value,
                    "admin_time": float(admin_time),
                    "auth_time": float(auth_time),
                    "display_time": float(display_time),
                }
            )

            busy_until = float(auth_time)
            current_state = _display_state(req.value)
            theoretical_last_time = max(theoretical_last_time, float(display_time))

        operations.append(op)

    final_state = current_state

    # Schedule and run the DES.
    env = simpy.Environment()
    events: list[dict[str, Any]] = []

    for req in requests:
        _schedule_event(
            env,
            events,
            at=float(req.input_time),
            component="input_reader",
            message=_msg(req.port, req.value),
        )

    for acc in accepted:
        port = int(acc["port"])
        value = int(acc["value"])
        message = _msg(port, value)

        _schedule_event(
            env,
            events,
            at=float(acc["admin_time"]),
            component="alarmAdmin",
            message=message,
        )
        _schedule_event(
            env,
            events,
            at=float(acc["auth_time"]),
            component="authentication",
            message=message,
            state=_auth_state(value),
        )
        _schedule_event(
            env,
            events,
            at=float(acc["display_time"]),
            component="display",
            message=message,
            state=_display_state(value),
        )

    max_sim_time = float(args.max_simulation_time)
    run_until = min(theoretical_last_time, max_sim_time)

    # If theoretical_last_time > max, we stop at max (some events won't emit).
    # If there are no events at all, run_until stays 0.0 and env.run() is fine.
    if theoretical_last_time > max_sim_time:
        env.run(until=max_sim_time)
        simulation_time = max_sim_time
    else:
        if run_until == 0.0:
            env.run()
        else:
            env.run(until=run_until)
        simulation_time = float(theoretical_last_time)

    events.sort(key=lambda e: (e["time"], e["component"], e["message"]))
    operations.sort(key=lambda o: o["input_time"])

    out: dict[str, Any] = {
        "test_name": args.test_name,
        "simulation_time": float(simulation_time),
        "initial_state": initial_state,
        "final_state": final_state,
        "events": events,
        "operations": operations,
    }

    json.dump(out, sys.stdout, separators=(",", ":"), ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
