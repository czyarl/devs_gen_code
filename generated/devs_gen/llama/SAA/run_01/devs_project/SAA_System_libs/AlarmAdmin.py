"""Atomic DEVS model: AlarmAdmin"""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class AlarmAdmin(Atomic):
    """Apply the alarm admin delay, send each resulting event and operation fact to ReportCollector, and does not write stdout."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "event_fact_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))

    def initialize(self):
        self.request_time = None
        self.request_value = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "IDLE":
            for request in self.input["request_in"].values:
                self.request_time = request["input_time"]
                self.request_value = request["value"]
                self.hold_in("PROCESSING", 0.0)
                return
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            current_time = get_current_time()
            event = {
                "time": current_time,
                "component": "alarmAdmin",
                "message": f"{{{self.request_value} {self.request_value}}}"
            }
            self.output["event_fact_out"].add(event)

            operation = {
                "input_time": self.request_time,
                "action": "arm" if self.request_value == 1 else "disarm",
                "completed": True,
                "completion_time": current_time
            }
            self.output["operation_fact_out"].add(operation)

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass