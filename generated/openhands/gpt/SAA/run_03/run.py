import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import simpy


TIME_PRECISION_DIGITS = 9


def _norm_time(t: float) -> float:
    return round(float(t), TIME_PRECISION_DIGITS)


def _parse_hhmmss_to_seconds(ts: str) -> int:
    parts = ts.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {ts!r}")
    h, m, s = (int(p) for p in parts)
    if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
        raise ValueError(f"Invalid timestamp value: {ts!r}")
    return h * 3600 + m * 60 + s


@dataclass(frozen=True)
class InputRequest:
    time: float
    index: int
    port: int
    value: int

    @property
    def action(self) -> str:
        return "disarm" if self.value == 0 else "arm"

    @property
    def message(self) -> str:
        return f"{{{self.port} {self.value}}}"


@dataclass(frozen=True)
class ScheduledEvent:
    time: float
    seq: int
    component: str
    message: str
    state: Optional[str] = None


def _emit_at(
    env: simpy.Environment,
    out_events: List[Dict[str, Any]],
    ev: ScheduledEvent,
) -> simpy.events.Event:
    delay = max(0.0, ev.time - env.now)

    def _proc():
        yield env.timeout(delay)
        record: Dict[str, Any] = {
            "time": _norm_time(ev.time),
            "component": ev.component,
            "message": ev.message,
        }
        if ev.state is not None:
            record["state"] = ev.state
        out_events.append(record)

    return env.process(_proc())


def _read_requests(path: Optional[str]) -> List[InputRequest]:
    if not path:
        return []

    requests: List[InputRequest] = []
    with open(path, "r", encoding="utf-8") as f:
        for idx, raw in enumerate(f):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 3:
                raise ValueError(f"Invalid input line (expected 3 fields): {raw!r}")
            ts, port_s, value_s = parts
            t = float(_parse_hhmmss_to_seconds(ts))
            port = int(port_s)
            value = int(value_s)
            if port != 0:
                raise ValueError(f"Invalid port (expected 0): {port}")
            if value not in (0, 1):
                raise ValueError(f"Invalid value (expected 0 or 1): {value}")
            requests.append(InputRequest(time=t, index=idx, port=port, value=value))

    requests.sort(key=lambda r: (r.time, r.index))
    return requests


def simulate(
    *,
    test_name: str,
    requests: List[InputRequest],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float,
) -> Dict[str, Any]:
    initial_state = "Disarmed"

    seq = 0
    busy_until = 0.0
    scheduled: List[ScheduledEvent] = []
    operations: List[Dict[str, Any]] = []

    last_input_time = 0.0
    last_display_time = 0.0

    last_accepted_value: Optional[int] = None

    for req in requests:
        last_input_time = max(last_input_time, req.time)

        scheduled.append(
            ScheduledEvent(
                time=req.time,
                seq=seq,
                component="input_reader",
                message=req.message,
            )
        )
        seq += 1

        accepted = not (req.time < busy_until)
        if not accepted:
            operations.append(
                {
                    "input_time": _norm_time(req.time),
                    "action": req.action,
                    "completed": False,
                    "completion_time": None,
                }
            )
            continue

        alarm_admin_time = req.time + alarm_admin_delay
        authentication_time = alarm_admin_time + authentication_delay
        display_time = authentication_time + display_delay

        busy_until = authentication_time
        last_display_time = max(last_display_time, display_time)
        last_accepted_value = req.value

        scheduled.append(
            ScheduledEvent(
                time=alarm_admin_time,
                seq=seq,
                component="alarmAdmin",
                message=req.message,
            )
        )
        seq += 1

        scheduled.append(
            ScheduledEvent(
                time=authentication_time,
                seq=seq,
                component="authentication",
                message=req.message,
                state="DisarmValid" if req.value == 0 else "ArmValid",
            )
        )
        seq += 1

        scheduled.append(
            ScheduledEvent(
                time=display_time,
                seq=seq,
                component="display",
                message=req.message,
                state="Disarmed" if req.value == 0 else "Armed",
            )
        )
        seq += 1

        operations.append(
            {
                "input_time": _norm_time(req.time),
                "action": req.action,
                "completed": True,
                "completion_time": _norm_time(authentication_time),
            }
        )

    final_state = initial_state
    if last_accepted_value is not None:
        final_state = "Disarmed" if last_accepted_value == 0 else "Armed"

    nominal_end_time = max(last_input_time, last_display_time)
    simulation_time = min(float(max_simulation_time), float(nominal_end_time))

    scheduled.sort(key=lambda e: (e.time, e.seq))
    scheduled = [e for e in scheduled if e.time <= simulation_time]

    env = simpy.Environment()
    events: List[Dict[str, Any]] = []

    for ev in scheduled:
        _emit_at(env, events, ev)

    if scheduled:
        eps = 1e-12
        run_until = (simulation_time + eps) if simulation_time > 0.0 else eps
        env.run(until=run_until)

    events.sort(key=lambda e: e["time"])
    operations.sort(key=lambda o: o["input_time"])

    return {
        "test_name": test_name,
        "simulation_time": _norm_time(simulation_time),
        "initial_state": initial_state,
        "final_state": final_state,
        "events": events,
        "operations": operations,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Secure area access control DES simulation")
    p.add_argument("--test_name", type=str, required=True)
    p.add_argument("--input_file", type=str, default=None)
    p.add_argument("--alarm_admin_delay", type=float, default=10.0)
    p.add_argument("--authentication_delay", type=float, default=2.0)
    p.add_argument("--display_delay", type=float, default=3.0)
    p.add_argument("--max_simulation_time", type=float, default=1000.0)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        requests = _read_requests(args.input_file)
        result = simulate(
            test_name=args.test_name,
            requests=requests,
            alarm_admin_delay=float(args.alarm_admin_delay),
            authentication_delay=float(args.authentication_delay),
            display_delay=float(args.display_delay),
            max_simulation_time=float(args.max_simulation_time),
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    json.dump(result, sys.stdout, separators=(",", ":"), sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
