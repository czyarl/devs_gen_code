"""
Atomic DEVS model: StdinScheduleSource

Sole stdin reader for the simulation. Parses timestamped plaintext commands and
emits scheduled DEVS outputs on two ports:
- control_out: {'added': int}
- request_out: {'allowed': bool}

This model never writes stdout JSONL records.
"""

import sys
from dataclasses import dataclass

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


@dataclass(frozen=True, slots=True)
class _ScheduledCmd:
    due_time_ms: float
    kind: str  # 'control' | 'request'
    payload: dict
    seq: int   # stdin order tie-breaker


class StdinScheduleSource(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "control_out"))
        self.add_out_port(Port(dict, "request_out"))

        self._schedule: list[_ScheduledCmd] = []
        self._next_index: int = 0
        self._eof_reached: bool = False

        # Internal bookkeeping for time progression (ms)
        self._sim_time_ms: float = 0.0

        # Prepared emission for the next internal event (set before hold_in)
        self._pending_emit: _ScheduledCmd | None = None

        # Sequence counter to preserve stdin order for equal timestamps
        self._seq_counter: int = 0

    @staticmethod
    def _diag(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    @staticmethod
    def _parse_timestamp_to_ms(ts: str) -> float:
        parts = ts.split(":")
        if len(parts) not in (3, 4):
            raise ValueError("timestamp must be HH:MM:SS or HH:MM:SS:mmm")

        try:
            hh = int(parts[0])
            mm = int(parts[1])
            ss = int(parts[2])
        except ValueError as exc:
            raise ValueError("HH/MM/SS must be integers") from exc

        if mm < 0 or mm > 59 or ss < 0 or ss > 59:
            raise ValueError("MM and SS must be in [0,59]")

        mmm = 0
        if len(parts) == 4:
            try:
                mmm = int(parts[3])
            except ValueError as exc:
                raise ValueError("mmm must be an integer") from exc
            if mmm < 0 or mmm > 999:
                raise ValueError("mmm must be in [0,999]")

        base_ms = ((hh * 3600 + mm * 60 + ss) * 1000)
        return float(base_ms + mmm)

    def _try_parse_line(self, raw_line: str) -> _ScheduledCmd | None:
        line = raw_line.strip()
        if not line:
            return None

        fields = line.split()
        if len(fields) != 3:
            self._diag(f"[StdinScheduleSource] Malformed line (expected 3 tokens): {line!r}")
            return None

        ts_text, kind, value_text = fields

        try:
            due_ms = self._parse_timestamp_to_ms(ts_text)
        except ValueError as exc:
            self._diag(f"[StdinScheduleSource] Malformed timestamp in line {line!r}: {exc}")
            return None

        if kind not in ("control", "request"):
            self._diag(f"[StdinScheduleSource] Unknown type in line {line!r}: {kind!r}")
            return None

        try:
            value_int = int(value_text)
        except ValueError:
            self._diag(f"[StdinScheduleSource] Non-integer value in line {line!r}: {value_text!r}")
            return None

        if kind == "control":
            payload = {"added": int(value_int)}
        else:
            # request: only 0 or 1 are valid
            if value_int not in (0, 1):
                self._diag(
                    f"[StdinScheduleSource] Malformed request value (must be 0 or 1) in line {line!r}"
                )
                return None
            payload = {"allowed": (value_int == 1)}

        cmd = _ScheduledCmd(due_time_ms=float(due_ms), kind=kind, payload=payload, seq=self._seq_counter)
        self._seq_counter += 1
        return cmd

    def _read_all_stdin(self) -> None:
        parsed: list[_ScheduledCmd] = []
        for raw_line in sys.stdin:
            cmd = self._try_parse_line(raw_line)
            if cmd is not None:
                parsed.append(cmd)

        self._eof_reached = True
        # Stable sort by due time then stdin order
        parsed.sort(key=lambda c: (c.due_time_ms, c.seq))
        self._schedule = parsed
        self._next_index = 0

    def _plan_next_internal(self) -> None:
        if self._next_index >= len(self._schedule):
            self._pending_emit = None
            if self._eof_reached:
                self.passivate("DONE")
            else:
                self.passivate("WAITING")
            return

        cmd = self._schedule[self._next_index]

        # Late command handling: if discovered time is earlier than current sim time, fire ASAP.
        if cmd.due_time_ms < self._sim_time_ms:
            self._diag(
                "[StdinScheduleSource] Late command adjusted to current time: "
                f"due={cmd.due_time_ms}ms now={self._sim_time_ms}ms kind={cmd.kind} payload={cmd.payload}"
            )
            due_ms = self._sim_time_ms
            cmd = _ScheduledCmd(due_time_ms=due_ms, kind=cmd.kind, payload=cmd.payload, seq=cmd.seq)
            self._schedule[self._next_index] = cmd

        sigma = max(0.0, cmd.due_time_ms - self._sim_time_ms)
        self._pending_emit = cmd
        self.hold_in("EMIT", sigma)

    def initialize(self):
        # Preload all stdin at time 0 (allowed by contract).
        self._sim_time_ms = float(get_current_time())
        self._read_all_stdin()
        self._plan_next_internal()

    def deltext(self, e: float):
        # No input ports; just preserve timing.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT" or self._pending_emit is None:
            return

        cmd = self._pending_emit
        if cmd.kind == "control":
            self.output["control_out"].add(cmd.payload)
        elif cmd.kind == "request":
            self.output["request_out"].add(cmd.payload)
        else:
            # Should never happen; ignore silently (no stdout).
            self._diag(f"[StdinScheduleSource] Internal error: unknown kind {cmd.kind!r}")

    def deltint(self):
        # Advance simulated time by sigma.
        self._sim_time_ms += float(self.sigma)

        if self.phase == "EMIT":
            # Consume exactly one scheduled emission per internal event.
            self._pending_emit = None
            self._next_index += 1

        self._plan_next_internal()

    def exit(self):
        # No required termination actions.
        pass