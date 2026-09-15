"""ReportCollector: Aggregates simulation events and results, prints final JSON."""

import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ReportCollector(Atomic):
    """
    Aggregate event records and operation results throughout the simulation.
    Maintain an internal list of events received via `event_in` and a list of
    operation results received via `operation_result_in`. Track the system state
    by initializing an internal state variable to 'Disarmed' and updating it
    whenever an event with component 'display' is received.
    The model does not generate internal events or produce DEVS outputs.
    Upon simulation termination, determine the final simulation time: if the
    simulation reached `max_simulation_time`, use that value; otherwise, use the
    timestamp of the last received event. Construct the final JSON object
    containing `test_name`, `simulation_time`, `initial_state` ('Disarmed'),
    `final_state` (the tracked state), `events` (sorted by time), and
    `operations` (sorted by `input_time`). Write exactly one JSON object to
    `stdout`.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        test_name: str,
        max_simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.test_name = test_name
        self.max_simulation_time = max_simulation_time

        # Input ports
        self.add_in_port(Port(dict, "event_in"))
        self.add_in_port(Port(dict, "operation_result_in"))

        # Internal state
        self.initial_state = "Disarmed"
        self.current_state = "Disarmed"
        self.events = []
        self.operations = []
        self.last_event_time = 0.0

    def initialize(self):
        self.initial_state = "Disarmed"
        self.current_state = "Disarmed"
        self.events = []
        self.operations = []
        self.last_event_time = 0.0
        self.passivate("COLLECTING")

    def deltext(self, e: float):
        # Collect events from event_in
        for event in self.input["event_in"].values:
            self.events.append(event)
            # Update last event time
            if "time" in event:
                self.last_event_time = max(self.last_event_time, event["time"])
            # Update system state if display event
            if event.get("component") == "display" and "state" in event:
                self.current_state = event["state"]

        # Collect operations from operation_result_in
        for op in self.input["operation_result_in"].values:
            self.operations.append(op)

        # Remain passive, waiting for more inputs or termination
        self.passivate("COLLECTING")

    def lambdaf(self):
        # This model has no DEVS output ports.
        return None

    def deltint(self):
        # No internal transitions are scheduled by this model.
        self.passivate("COLLECTING")

    def exit(self):
        # Determine final simulation time
        current_sim_time = get_current_time()
        
        # Logic: if simulation reached max_simulation_time, use that value;
        # otherwise, use the timestamp of the last received event.
        # We check if current_sim_time is effectively at the max limit.
        if current_sim_time >= (self.max_simulation_time - 1e-9):
            final_time = self.max_simulation_time
        else:
            final_time = self.last_event_time

        # Sort events by time
        self.events.sort(key=lambda x: x["time"])

        # Sort operations by input_time
        self.operations.sort(key=lambda x: x["input_time"])

        # Construct final JSON
        output_record = {
            "test_name": self.test_name,
            "simulation_time": final_time,
            "initial_state": self.initial_state,
            "final_state": self.current_state,
            "events": self.events,
            "operations": self.operations,
        }

        # Write to stdout
        print(json.dumps(output_record), flush=True)