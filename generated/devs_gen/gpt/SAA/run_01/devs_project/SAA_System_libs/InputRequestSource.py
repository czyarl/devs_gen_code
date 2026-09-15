"""Atomic DEVS model: InputRequestSource.

Reads a timestamped request file once at initialization and emits scheduled
requests and corresponding input_reader event facts at the specified simulation
times.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xdevs.models import Atomic, Coupled, Port


@dataclass(frozen=True)
class _RequestRecord:
    input_time: float
    port: int
    value: int
    order: int  # stable tie-breaker to preserve file order for equal times


class InputRequestSource(Atomic):
    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file

        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_event_fact_out"))

        self._schedule: list[_RequestRecord] = []
        self._next_index: int = 0
        self._sim_time: float = 0.0

        # Prepared batch for the next emission time (filled before EMIT phase).
        self._emit_time: float | None = None
        self._emit_batch: list[_RequestRecord] = []

    @staticmethod
    def _hms_to_seconds(hms: str) -> float:
        parts = hms.split(":")
        if len(parts) != 3:
            raise ValueError("timestamp must be HH:MM:SS")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return float(hours * 3600 + minutes * 60 + seconds)

    def _read_schedule_from_file(self) -> None:
        self._schedule = []
        self._next_index = 0

        if self.input_file is None:
            return
        path_text = str(self.input_file).strip()
        if not path_text:
            return

        path = Path(path_text)
        if not path.exists() or not path.is_file():
            return

        order = 0
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    fields = line.split()
                    if len(fields) < 3:
                        continue

                    try:
                        t = self._hms_to_seconds(fields[0])
                        # Per contract, port is assumed always '0' and emitted as int 0.
                        # Still parse to int for robustness, but output always uses 0.
                        _ = int(fields[1])
                        value = int(fields[2])
                    except Exception:
                        continue

                    rec = _RequestRecord(input_time=t, port=0, value=value, order=order)
                    self._schedule.append(rec)
                    order += 1
        except OSError:
            # If file can't be read, behave as having no requests.
            self._schedule = []
            return

        # Sort by time; preserve file order for ties via 'order'.
        self._schedule.sort(key=lambda r: (r.input_time, r.order))

    def _prepare_next_batch(self) -> None:
        self._emit_batch = []
        self._emit_time = None

        if self._next_index >= len(self._schedule):
            return

        t = self._schedule[self._next_index].input_time
        self._emit_time = t
        i = self._next_index
        while i < len(self._schedule) and self._schedule[i].input_time == t:
            self._emit_batch.append(self._schedule[i])
            i += 1

    def initialize(self):
        self._sim_time = 0.0
        self._read_schedule_from_file()

        if not self._schedule:
            self.passivate("DONE")
            return

        self._prepare_next_batch()
        if self._emit_time is None:
            self.passivate("DONE")
            return

        self.hold_in("EMIT", max(0.0, self._emit_time - self._sim_time))

    def deltext(self, e: float):
        # No input ports; remain consistent with DEVS semantics.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT":
            return
        if not self._emit_batch:
            return
        if self._emit_time is None:
            return

        t = float(self._emit_time)
        # Emit in deterministic file order for ties.
        for rec in self._emit_batch:
            req = {"input_time": float(rec.input_time), "port": int(rec.port), "value": int(rec.value)}
            self.output["request_out"].add(req)

            msg = "{0 0}" if int(rec.value) == 0 else "{0 1}"
            fact = {"time": t, "component": "input_reader", "message": msg}
            self.output["input_event_fact_out"].add(fact)

    def deltint(self):
        # Advance simulated time by elapsed sigma.
        self._sim_time += float(self.sigma)

        # Consume the emitted batch.
        self._next_index += len(self._emit_batch)
        self._emit_batch = []
        self._emit_time = None

        if self._next_index >= len(self._schedule):
            self.passivate("DONE")
            return

        self._prepare_next_batch()
        if self._emit_time is None:
            self.passivate("DONE")
            return

        self.hold_in("EMIT", max(0.0, self._emit_time - self._sim_time))

    def exit(self):
        # No required external IO on exit.
        pass