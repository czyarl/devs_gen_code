import os
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
    Atomic DEVS source that reads a deterministic schedule of input requests from a text file
    during initialization and emits them at their specified simulation times.
    """

    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file

        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_event_fact_out"))

        self._schedule: list[_ScheduledRequest] = []
        self._next_index: int = 0
        self._sim_time: float = 0.0
        self._emit_batch: list[_ScheduledRequest] = []

    @staticmethod
    def _hhmmss_to_seconds(token: str) -> float:
        parts = token.split(":")
        hours, minutes, seconds = (int(p) for p in parts)
        return float(hours * 3600 + minutes * 60 + seconds)

    def _read_schedule(self) -> None:
        self._schedule = []
        self._next_index = 0
        self._emit_batch = []

        if self.input_file is None or str(self.input_file).strip() == "":
            return

        path = str(self.input_file)
        if not os.path.exists(path):
            # Format violations and IO errors are outside specified observable behavior.
            # We choose to behave as if there are zero requests.
            return

        parsed: list[_ScheduledRequest] = []
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                if raw_line.strip() == "":
                    continue
                fields = raw_line.split()
                if len(fields) < 3:
                    continue
                t_token, _port_token, value_token = fields[0], fields[1], fields[2]
                try:
                    t = self._hhmmss_to_seconds(t_token)
                    value = int(value_token)
                except (ValueError, TypeError):
                    continue
                if value not in (0, 1):
                    continue
                port = 0
                message = f"{{{port} {value}}}"
                parsed.append(_ScheduledRequest(t=t, port=port, value=value, message=message))

        # Stable sort preserves file order for ties.
        self._schedule = sorted(parsed, key=lambda r: r.t)

    def _prepare_emit_batch(self) -> None:
        self._emit_batch = []
        if self._next_index >= len(self._schedule):
            return
        t = self._schedule[self._next_index].t
        i = self._next_index
        while i < len(self._schedule) and self._schedule[i].t == t:
            self._emit_batch.append(self._schedule[i])
            i += 1

    def initialize(self):
        self._sim_time = 0.0
        self._read_schedule()

        if not self._schedule:
            self.passivate("DONE")
            return

        self._next_index = 0
        self._prepare_emit_batch()
        first_t = self._schedule[0].t
        self.hold_in("EMIT", max(0.0, first_t - self._sim_time))

    def deltext(self, e: float):
        # No input ports; ignore external messages while preserving timing.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT":
            return

        # Emit all requests scheduled for the current simulation time.
        for req in self._emit_batch:
            self.output["request_out"].add(
                {
                    "input_time": req.t,
                    "port": req.port,
                    "value": req.value,
                    "message": req.message,
                }
            )
            self.output["input_event_fact_out"].add(
                {
                    "time": req.t,
                    "component": "input_reader",
                    "message": req.message,
                }
            )

    def deltint(self):
        # Advance simulated time by sigma.
        self._sim_time += self.sigma

        # Consume the emitted batch.
        self._next_index += len(self._emit_batch)
        self._emit_batch = []

        if self._next_index >= len(self._schedule):
            self.passivate("DONE")
            return

        # Schedule next emission at the next distinct request time.
        self._prepare_emit_batch()
        next_t = self._schedule[self._next_index].t
        self.hold_in("EMIT", max(0.0, next_t - self._sim_time))

    def exit(self):
        pass