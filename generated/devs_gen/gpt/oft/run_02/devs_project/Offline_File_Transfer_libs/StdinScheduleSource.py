import sys
from dataclasses import dataclass

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


@dataclass(frozen=True)
class _ScheduledItem:
    t_ms: float
    order: int
    kind: str  # 'control' | 'request'
    payload: dict


class StdinScheduleSource(Atomic):
    """
    Atomic DEVS model that reads all stdin at initialization, parses scheduled commands,
    and emits them at their absolute simulation timestamps (ms).
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "control_out"))
        self.add_out_port(Port(dict, "request_out"))

        self._schedule: list[_ScheduledItem] = []
        self._next_index: int = 0
        self._insertion_counter: int = 0

        self._sim_time_ms: float = 0.0
        self._pending_emit: _ScheduledItem | None = None

    @staticmethod
    def _diag(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    @staticmethod
    def _parse_timestamp_to_ms(text: str) -> float:
        parts = text.split(":")
        if len(parts) not in (3, 4):
            raise ValueError("timestamp must be HH:MM:SS or HH:MM:SS:mmm")

        try:
            hh = int(parts[0])
            mm = int(parts[1])
            ss = int(parts[2])
        except ValueError as exc:
            raise ValueError("timestamp fields HH,MM,SS must be integers") from exc

        if hh < 0:
            raise ValueError("HH must be >= 0")
        if not (0 <= mm <= 59):
            raise ValueError("MM must be in [0,59]")
        if not (0 <= ss <= 59):
            raise ValueError("SS must be in [0,59]")

        mmm = 0
        if len(parts) == 4:
            try:
                mmm = int(parts[3])
            except ValueError as exc:
                raise ValueError("mmm must be an integer") from exc
            if not (0 <= mmm <= 999):
                raise ValueError("mmm must be in [0,999]")

        return float((hh * 3600 + mm * 60 + ss) * 1000 + mmm)

    def _read_schedule_from_stdin(self) -> None:
        parsed: list[_ScheduledItem] = []
        for line_no, raw_line in enumerate(sys.stdin, start=1):
            line = raw_line.strip()
            if not line:
                continue

            fields = line.split()
            if len(fields) != 3:
                self._diag(
                    f"StdinScheduleSource: malformed line {line_no}: expected 3 fields "
                    f"'<timestamp> <type> <value>', got {len(fields)}; skipping"
                )
                continue

            ts_text, kind, value_text = fields

            try:
                t_ms = self._parse_timestamp_to_ms(ts_text)
            except ValueError as exc:
                self._diag(
                    f"StdinScheduleSource: invalid timestamp on line {line_no}: {exc}; skipping"
                )
                continue

            if kind not in ("control", "request"):
                self._diag(
                    f"StdinScheduleSource: invalid type on line {line_no}: {kind!r}; skipping"
                )
                continue

            if kind == "control":
                try:
                    n = int(value_text)
                except ValueError:
                    self._diag(
                        f"StdinScheduleSource: invalid control value on line {line_no}: "
                        f"{value_text!r} (expected int); skipping"
                    )
                    continue
                payload = {"n": n}
            else:
                try:
                    v = int(value_text)
                except ValueError:
                    self._diag(
                        f"StdinScheduleSource: invalid request value on line {line_no}: "
                        f"{value_text!r} (expected 0 or 1); skipping"
                    )
                    continue
                if v not in (0, 1):
                    self._diag(
                        f"StdinScheduleSource: invalid request value on line {line_no}: "
                        f"{v!r} (expected 0 or 1); skipping"
                    )
                    continue
                payload = {"allowed": (v == 1)}

            parsed.append(
                _ScheduledItem(
                    t_ms=t_ms,
                    order=self._insertion_counter,
                    kind=kind,
                    payload=payload,
                )
            )
            self._insertion_counter += 1

        parsed.sort(key=lambda item: (item.t_ms, item.order))
        self._schedule = parsed

    def _prepare_next_emit_and_schedule(self) -> None:
        if self._next_index >= len(self._schedule):
            self._pending_emit = None
            self.passivate("PASSIVE")
            return

        current_time_ms = float(get_current_time())
        self._sim_time_ms = current_time_ms

        item = self._schedule[self._next_index]
        self._pending_emit = item

        delay = item.t_ms - current_time_ms
        if delay < 0.0:
            delay = 0.0
        self.hold_in("EMIT", delay)

    def initialize(self):
        self._schedule = []
        self._next_index = 0
        self._insertion_counter = 0
        self._pending_emit = None
        self._sim_time_ms = 0.0

        self._read_schedule_from_stdin()
        self._prepare_next_emit_and_schedule()

    def deltext(self, e: float):
        # No input ports; ignore external DEVS inputs.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT" or self._pending_emit is None:
            return

        if self._pending_emit.kind == "control":
            self.output["control_out"].add(self._pending_emit.payload)
        elif self._pending_emit.kind == "request":
            self.output["request_out"].add(self._pending_emit.payload)
        else:
            # Should not happen; keep silent on stdout, diagnostic on stderr.
            self._diag(
                f"StdinScheduleSource: internal error: unknown kind {self._pending_emit.kind!r}"
            )

    def deltint(self):
        # Advance internal notion of time by elapsed sigma for deterministic scheduling.
        self._sim_time_ms += float(self.sigma)

        # Consume the emitted item.
        if self.phase == "EMIT" and self._pending_emit is not None:
            self._next_index += 1
            self._pending_emit = None

        self._prepare_next_emit_and_schedule()

    def exit(self):
        pass