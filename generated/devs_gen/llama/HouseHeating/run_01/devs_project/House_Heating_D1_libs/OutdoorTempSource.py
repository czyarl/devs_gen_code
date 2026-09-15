"""Complete pattern: Read the outdoor temperature schedule from stdin once. At each integer time from 1 through int(simulation_time), select the latest value whose timestamp is not later than that time, or the specified default when none exists, and send it through temperature_out."""

import sys
import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class OutdoorTempSource(Atomic):
    """Emit the latest scheduled scalar at each whole simulation second."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.simulation_time = simulation_time
        self.add_out_port(Port(float, "temperature_out"))
        self.schedule = []

    @staticmethod
    def _seconds(time_text: str) -> float:
        hours, minutes, seconds = (float(part) for part in time_text.split(":"))
        return hours * 3600.0 + minutes * 60.0 + seconds

    def _read_schedule(self) -> None:
        records = []
        for raw_line in sys.stdin:
            try:
                time_text, value_text = raw_line.split()
                records.append((self._seconds(time_text), float(value_text)))
            except (TypeError, ValueError):
                continue
        self.schedule = sorted(records)

    def _value_at(self, now: float) -> float:
        # Retain the last value at or before now. Do not replace this scan with
        # a for/else whose early break accidentally returns a future record.
        value = 25.0
        for timestamp, scheduled_value in self.schedule:
            if timestamp > now:
                break
            value = scheduled_value
        return value

    def initialize(self):
        self._read_schedule()
        if self.simulation_time >= 1.0:
            # The first required observation is t=1, not an initialization
            # side effect and not an invented t=0 port message.
            self.hold_in("EMIT", 1.0)
        else:
            self.passivate("DONE")

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            self.output["temperature_out"].add(self._value_at(get_current_time()))

    def deltint(self):
        if get_current_time() + 1.0 <= int(self.simulation_time):
            self.hold_in("EMIT", 1.0)
        else:
            self.passivate("DONE")

    def exit(self):
        pass