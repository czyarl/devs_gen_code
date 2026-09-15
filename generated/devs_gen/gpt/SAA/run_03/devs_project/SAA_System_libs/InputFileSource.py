"""InputFileSource: schedule-driven DEVS source reading HH:MM:SS port value lines from a file."""

from __future__ import annotations

from dataclasses import dataclass

from xdevs.models import Atomic, Coupled, Port


@dataclass(frozen=True)
class _ScheduledRequest:
    t: float
    port: int
    value: int
    message: str


class InputFileSource(Atomic):
    """
    Leaf atomic DEVS source that preloads a schedule of input requests from an optional text file
    and emits two DEVS outputs at the exact scheduled simulation times for each request.
    """

    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file

        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_event_out"))

        self._schedule: list[_ScheduledRequest] = []
        self._next_index: int = 0
        self._sim_time: float = 0.0

        # Prepared batch for the next internal firing (all items at the same time t).
        self._emit_batch: list[_ScheduledRequest] = []

    @staticmethod
    def _parse_hhmmss_to_seconds(text: str) -> float:
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError("timestamp must be HH:MM:SS")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return float(hours * 3600 + minutes * 60 + seconds)

    def _read_and_parse_schedule(self) -> None:
        # If input_file is omitted/empty, treat as no input and perform no file read.
        if not isinstance(self.input_file, str) or self.input_file.strip() == "":
            self._schedule = []
            return

        parsed: list[tuple[int, _ScheduledRequest]] = []
        with open(self.input_file, "r", encoding="utf-8") as f:
            for line_no, raw_line in enumerate(f, start=1):
                if raw_line.strip() == "":
                    continue
                fields = raw_line.split()
                if len(fields) < 3:
                    # Deterministically ignore malformed non-empty lines.
                    continue
                try:
                    t = self._parse_hhmmss_to_seconds(fields[0])
                    port = int(fields[1])
                    value = int(fields[2])
                except ValueError:
                    continue

                message = f"{{{port} {value}}}"
                parsed.append((line_no, _ScheduledRequest(t=t, port=port, value=value, message=message)))

        # Sort by nondecreasing t, stable for identical t (line_no tie-breaker).
        parsed.sort(key=lambda item: (item[1].t, item[0]))
        self._schedule = [item for _, item in parsed]

    def _prepare_next_batch(self) -> None:
        self._emit_batch = []
        if self._next_index >= len(self._schedule):
            return
        t0 = self._schedule[self._next_index].t
        i = self._next_index
        while i < len(self._schedule) and self._schedule[i].t == t0:
            self._emit_batch.append(self._schedule[i])
            i += 1

    def initialize(self):
        # Read once during initialization (before first internal event scheduling).
        self._read_and_parse_schedule()

        self._next_index = 0
        self._sim_time = 0.0
        self._emit_batch = []

        if not self._schedule:
            self.passivate("DONE")
            return

        self._prepare_next_batch()
        first_t = self._emit_batch[0].t
        self.hold_in("EMIT", max(0.0, first_t - self._sim_time))

    def deltext(self, e: float):
        # No input ports; purely schedule-driven.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT":
            return

        # Emit one pair of outputs per scheduled line in the batch (same time instant).
        for item in self._emit_batch:
            self.output["request_out"].add(
                {
                    "input_time": float(item.t),
                    "port": int(item.port),
                    "value": int(item.value),
                    "message": item.message,
                }
            )
            self.output["input_event_out"].add(
                {
                    "time": float(item.t),
                    "component": "input_reader",
                    "message": item.message,
                }
            )

    def deltint(self):
        # Advance simulated time by sigma and move cursor past the emitted batch.
        self._sim_time += float(self.sigma)
        self._next_index += len(self._emit_batch)
        self._emit_batch = []

        if self._next_index >= len(self._schedule):
            self.passivate("DONE")
            return

        self._prepare_next_batch()
        next_t = self._emit_batch[0].t
        self.hold_in("EMIT", max(0.0, next_t - self._sim_time))

    def exit(self):
        # No finalization I/O required.
        pass