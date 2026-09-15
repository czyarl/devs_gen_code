"""ReportCollector: Aggregate event and operation facts and write final JSON."""

import json

from xdevs.models import Atomic, Coupled, Port


class ReportCollector(Atomic):
    """Aggregate event and operation facts from InputSource and AlarmPipeline."""

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

        self.add_in_port(Port(dict, "input_fact_in"))
        self.add_in_port(Port(dict, "event_fact_in"))
        self.add_in_port(Port(dict, "operation_fact_in"))

        self.events: list[dict] = []
        self.operations: list[dict] = []

    def initialize(self):
        self.events = []
        self.operations = []
        self.passivate("COLLECTING")

    def deltext(self, e: float):
        # Collect input facts
        for record in self.input["input_fact_in"].values:
            self.events.append(dict(record))

        # Collect pipeline events
        for record in self.input["event_fact_in"].values:
            self.events.append(dict(record))

        # Collect operation results
        for record in self.input["operation_fact_in"].values:
            self.operations.append(dict(record))

        self.passivate("COLLECTING")

    def lambdaf(self):
        # No DEVS output ports
        pass

    def deltint(self):
        self.passivate("COLLECTING")

    def exit(self):
        # Sort events by time
        self.events.sort(key=lambda item: float(item["time"]))
        # Sort operations by input_time
        self.operations.sort(key=lambda item: float(item["input_time"]))

        # Determine final simulation time and final state
        simulation_time = 0.0
        final_state = "Disarmed"

        if self.events:
            simulation_time = max(float(ev["time"]) for ev in self.events)

        # Check if max_simulation_time was reached before completion
        # Condition: accepted request processed (alarmAdmin event or completed=True op)
        # but corresponding display event is missing.
        has_accepted = False
        has_display = False

        # Check operations for completed requests
        for op in self.operations:
            if op.get("completed"):
                has_accepted = True
                break

        # Check events for alarmAdmin (implies accepted)
        if not has_accepted:
            for ev in self.events:
                if ev.get("component") == "alarmAdmin":
                    has_accepted = True
                    break

        # Check for display events
        for ev in self.events:
            if ev.get("component") == "display":
                has_display = True
                # Update final_state from the last display event
                if "state" in ev:
                    final_state = ev["state"]

        if has_accepted and not has_display:
            simulation_time = self.max_simulation_time

        # Construct final JSON object
        output = {
            "test_name": self.test_name,
            "simulation_time": simulation_time,
            "initial_state": "Disarmed",
            "final_state": final_state,
            "events": self.events,
            "operations": self.operations,
        }

        print(json.dumps(output), flush=True)