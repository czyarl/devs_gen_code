"""ReportCollector model for aggregating events and operations, and writing final JSON report."""

import json
import sys
from typing import List, Dict, Any, Optional

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ReportCollector(Atomic):
    """Collect input facts, stage events, and operation results from the simulation pipeline."""

    def __init__(self, name: str, parent: Coupled | None, test_name: str, max_simulation_time: float):
        super().__init__(name)
        self.parent = parent
        self.test_name = test_name
        self.max_simulation_time = max_simulation_time
        self.add_in_port(Port(dict, "input_fact_in"))
        self.add_in_port(Port(dict, "event_fact_in"))
        self.add_in_port(Port(dict, "operation_fact_in"))
        self.input_facts = []
        self.events = []
        self.operations = []
        self.current_state = "Disarmed"
        self.last_accepted_operation_time = 0.0
        self.simulation_time = 0.0

    def initialize(self):
        self.input_facts = []
        self.events = []
        self.operations = []
        self.current_state = "Disarmed"
        self.last_accepted_operation_time = 0.0
        self.simulation_time = 0.0
        self.passivate("COLLECTING")

    def deltext(self, e):
        # Process input facts
        for packet in self.input["input_fact_in"].values:
            self.input_facts.append(dict(packet))
            # Add input_reader event
            event = {
                "time": packet["time"],
                "component": "input_reader",
                "message": packet["message"]
            }
            self.events.append(event)

        # Process event facts
        for packet in self.input["event_fact_in"].values:
            self.events.append(dict(packet))

        # Process operation facts
        for packet in self.input["operation_fact_in"].values:
            self.operations.append(dict(packet))
            if packet["completed"]:
                self.last_accepted_operation_time = packet["input_time"]
                # Update state based on the action
                if packet["action"] == "arm":
                    self.current_state = "Armed"
                elif packet["action"] == "disarm":
                    self.current_state = "Disarmed"

        self.passivate("COLLECTING")

    def lambdaf(self):
        # No DEVS outputs
        return None

    def deltint(self):
        self.passivate("COLLECTING")

    def exit(self):
        # Sort events by time
        self.events.sort(key=lambda x: float(x["time"]))

        # Sort operations by input_time
        self.operations.sort(key=lambda x: float(x["input_time"]))

        # Determine simulation_time
        if self.events:
            # Find the time of the last display event if it exists
            display_events = [e for e in self.events if e["component"] == "display"]
            if display_events:
                last_display_time = max(float(e["time"]) for e in display_events)
                self.simulation_time = last_display_time
            else:
                # If no display events, use the last event time
                self.simulation_time = max(float(e["time"]) for e in self.events)
        else:
            self.simulation_time = self.max_simulation_time

        # Ensure simulation_time does not exceed max_simulation_time
        self.simulation_time = min(self.simulation_time, self.max_simulation_time)

        # Construct final report
        report = {
            "test_name": self.test_name,
            "simulation_time": self.simulation_time,
            "initial_state": "Disarmed",
            "final_state": self.current_state,
            "events": self.events,
            "operations": self.operations
        }

        # Print the final JSON report to stdout
        print(json.dumps(report), flush=True)