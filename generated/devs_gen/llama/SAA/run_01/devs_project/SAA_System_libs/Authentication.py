"""Complete pattern: one request advances through authentication delay."""

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Authentication(Atomic):
    """Emit each stage fact when that stage's internal event actually fires."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
    ):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "event_fact_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))
        self.current_request = None

    def initialize(self):
        self.current_request = None
        self.passivate("IDLE")

    def deltext(self, e):
        was_busy = self.phase != "IDLE"
        remaining = max(0.0, self.ta() - e) if was_busy else None
        if not was_busy:
            for request in self.input["request_in"].values:
                self.current_request = dict(request)
                self.hold_in("PROCESSING", 2.0)
                break
        elif remaining is not None:
            # Preserve the old stage deadline. Do not subtract elapsed time
            # from a timer newly started in this same external transition.
            self.hold_in(self.phase, remaining)

    def lambdaf(self):
        if self.current_request is None:
            return
        now = get_current_time()
        if self.phase == "PROCESSING":
            self.output["event_fact_out"].add({
                "time": now,
                "component": "authentication",
                "message": f"{{0 {self.current_request['value']}}}",
                "state": "ArmValid" if self.current_request['value'] == 1 else "DisarmValid",
            })
            self.output["operation_fact_out"].add({
                "input_time": self.current_request['input_time'],
                "action": "arm" if self.current_request['value'] == 1 else "disarm",
                "completed": True,
                "completion_time": now,
            })

    def deltint(self):
        if self.phase == "PROCESSING":
            self.current_request = None
            self.passivate("IDLE")

    def exit(self):
        pass