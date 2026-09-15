"""Complete implementation of the Display model."""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Display(Atomic):
    """Atomic DEVS model for Display."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "event_fact_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "IDLE":
            self.continuef(e)
            return

        for request in self.input["request_in"].values:
            input_time = request["input_time"]
            port = request["port"]
            value = request["value"]

            # Record input_reader event
            event_time = get_current_time()
            event_message = f"{{{port} {value}}}"
            self.output["event_fact_out"].add({
                "time": event_time,
                "component": "input_reader",
                "message": event_message
            })

            # Process the request
            self.hold_in("PROCESSING", 0.0)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING":
            # Get the input request
            request = self.input["request_in"].get()
            input_time = request["input_time"]
            port = request["port"]
            value = request["value"]

            # Calculate the display delay
            display_delay = 3.0  # Default display delay

            # Prepare the event_fact_out
            event_time = get_current_time() + display_delay
            event_state = "Disarmed" if value == 0 else "Armed"
            event_message = f"{{{port} {value}}}"
            self.output["event_fact_out"].add({
                "time": event_time,
                "component": "display",
                "message": event_message,
                "state": event_state
            })

            # Prepare the operation_fact_out
            operation_action = "disarm" if value == 0 else "arm"
            operation_completed = True
            operation_completion_time = event_time
            self.output["operation_fact_out"].add({
                "input_time": input_time,
                "action": operation_action,
                "completed": operation_completed,
                "completion_time": operation_completion_time
            })

            self.passivate("IDLE")

    def deltint(self):
        pass

    def exit(self):
        pass