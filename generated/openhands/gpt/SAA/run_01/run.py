from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Optional

import simpy


@dataclass(frozen=True)
class InputLine:
    seq: int
    input_time: float
    port: int
    value: int

    @property
    def action(self) -> str:
        return "disarm" if self.value == 0 else "arm"

    @property
    def message(self) -> str:
        return f"{{{self.port} {self.value}}}"


@dataclass
class OperationPlan:
    line: InputLine
    accepted: bool
    alarm_time: Optional[float] = None
    auth_time: Optional[float] = None
    display_time: Optional[float] = None


def _parse_hhmmss_to_seconds(text: str) -> float:
    parts = text.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp (expected HH:MM:SS): {text!r}")
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + int(s)


def _read_input_lines(path: Path) -> list[InputLine]:
    lines: list[InputLine] = []
    raw = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(raw):
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) != 3:
            raise ValueError(
                f"Invalid input line {idx + 1}: expected '<HH:MM:SS> <port> <value>'"
            )
        ts_s, port_s, value_s = parts
        t = _parse_hhmmss_to_seconds(ts_s)
        port = int(port_s)
        value = int(value_s)
        if port != 0:
            raise ValueError(f"Invalid port on line {idx + 1}: expected 0, got {port}")
        if value not in (0, 1):
            raise ValueError(
                f"Invalid value on line {idx + 1}: expected 0 or 1, got {value}"
            )
        lines.append(InputLine(seq=len(lines), input_time=float(t), port=port, value=value))
    return lines


def _plan_operations(
    inputs: list[InputLine],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
) -> list[OperationPlan]:
    ordered = sorted(inputs, key=lambda x: (x.input_time, x.seq))

    busy_until = 0.0
    plans_by_seq: dict[int, OperationPlan] = {}

    for line in ordered:
        if line.input_time < busy_until:
            plans_by_seq[line.seq] = OperationPlan(line=line, accepted=False)
            continue

        alarm_time = line.input_time + alarm_admin_delay
        auth_time = alarm_time + authentication_delay
        display_time = auth_time + display_delay

        plans_by_seq[line.seq] = OperationPlan(
            line=line,
            accepted=True,
            alarm_time=alarm_time,
            auth_time=auth_time,
            display_time=display_time,
        )
        busy_until = auth_time

    return [plans_by_seq[i] for i in range(len(inputs))]


def run_simulation(
    test_name: str,
    inputs: list[InputLine],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float,
) -> dict:
    initial_state = "Disarmed"
    current_state = initial_state

    plans = _plan_operations(
        inputs=inputs,
        alarm_admin_delay=alarm_admin_delay,
        authentication_delay=authentication_delay,
        display_delay=display_delay,
    )

    max_input_time = max((line.input_time for line in inputs), default=0.0)
    max_display_time = max(
        (p.display_time for p in plans if p.accepted and p.display_time is not None),
        default=0.0,
    )
    planned_end = max(max_input_time, max_display_time)

    truncated = planned_end > max_simulation_time
    run_until = max_simulation_time if truncated else planned_end

    # SimPy's env.run(until=0) won't process events scheduled at t=0.
    if run_until == 0.0 and any(line.input_time == 0.0 for line in inputs):
        run_until = math.nextafter(0.0, 1.0)

    env = simpy.Environment()
    event_seq = count(0)
    recorded_events: list[tuple[float, int, dict]] = []

    def record(component: str, message: str, state: Optional[str] = None) -> None:
        e = {
            "time": float(env.now),
            "component": component,
            "message": message,
        }
        if state is not None:
            e["state"] = state
        recorded_events.append((float(env.now), next(event_seq), e))

    def wait_until(t: float):
        delay = t - env.now
        if delay < 0:
            delay = 0
        return env.timeout(delay)

    def input_reader_process(line: InputLine):
        yield wait_until(line.input_time)
        record("input_reader", line.message)

    def pipeline_process(plan: OperationPlan):
        nonlocal current_state
        assert plan.accepted
        assert plan.alarm_time is not None and plan.auth_time is not None and plan.display_time is not None

        yield wait_until(plan.alarm_time)
        record("alarmAdmin", plan.line.message)

        yield wait_until(plan.auth_time)
        auth_state = "DisarmValid" if plan.line.value == 0 else "ArmValid"
        record("authentication", plan.line.message, state=auth_state)
        current_state = "Disarmed" if plan.line.value == 0 else "Armed"

        yield wait_until(plan.display_time)
        display_state = "Disarmed" if plan.line.value == 0 else "Armed"
        record("display", plan.line.message, state=display_state)

    for line in inputs:
        env.process(input_reader_process(line))

    for plan in plans:
        if plan.accepted:
            env.process(pipeline_process(plan))

    if run_until > 0.0:
        env.run(until=run_until)
    else:
        # run() processes all events; if there are none, time stays at 0.
        env.run()

    recorded_events.sort(key=lambda x: (x[0], x[1]))
    events = [e for _, __, e in recorded_events]

    if truncated:
        simulation_time = float(max_simulation_time)
    else:
        simulation_time = max((e["time"] for e in events), default=0.0)

    operations = []
    for plan in plans:
        operations.append(
            {
                "input_time": float(plan.line.input_time),
                "action": plan.line.action,
                "completed": bool(plan.accepted),
                "completion_time": float(plan.auth_time) if plan.accepted else None,
                "_seq": plan.line.seq,
            }
        )
    operations.sort(key=lambda r: (r["input_time"], r["_seq"]))
    for r in operations:
        r.pop("_seq", None)

    return {
        "test_name": test_name,
        "simulation_time": simulation_time,
        "initial_state": initial_state,
        "final_state": current_state,
        "events": events,
        "operations": operations,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Secure Area Access Control DES simulation")
    p.add_argument("--test_name", required=True, type=str)
    p.add_argument("--input_file", required=False, type=str)
    p.add_argument("--alarm_admin_delay", required=False, type=float, default=10.0)
    p.add_argument("--authentication_delay", required=False, type=float, default=2.0)
    p.add_argument("--display_delay", required=False, type=float, default=3.0)
    p.add_argument("--max_simulation_time", required=False, type=float, default=1000.0)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    input_lines: list[InputLine] = []
    if args.input_file:
        path = Path(args.input_file)
        if not path.exists():
            print(f"Input file not found: {args.input_file}", file=sys.stderr)
            return 2
        try:
            input_lines = _read_input_lines(path)
        except Exception as e:
            print(str(e), file=sys.stderr)
            return 2

    result = run_simulation(
        test_name=args.test_name,
        inputs=input_lines,
        alarm_admin_delay=float(args.alarm_admin_delay),
        authentication_delay=float(args.authentication_delay),
        display_delay=float(args.display_delay),
        max_simulation_time=float(args.max_simulation_time),
    )

    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
