"""ReportCollector model for collecting and reporting simulation facts."""

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
        self.events: List[Dict[str, Any]] = []
        self.operations: List[Dict[str, Any]] = []
        self.initial_state = "Disarmed"
        self.final_state: Optional[str] = None
        self.simulation_time: Optional[float] = None

    def initialize(self):
        self.events = []
        self.operations = []
        self.final_state = "Disarmed"
        self.simulation_time = 0.0
        self.passivate("COLLECTING")

    def deltext(self, e):
        # Process input_fact_in
        for packet in self.input["input_fact_in"].values:
            self.events.append({
                "time": packet["time"],
                "component": "input_reader",
                "message": packet["message"]
            })

        # Process event_fact_in
        for packet in self.input["event_fact_in"].values:
            event_copy = dict(packet)
            # Ensure required fields are present
            if "state" in packet:
                event_copy["state"] = packet["state"]
            self.events.append(event_copy)

        # Process operation_fact_in
        for packet in self.input["operation_fact_in"].values:
            self.operations.append(dict(packet))

        self.passivate("COLLECTING")

    def lambdaf(self):
        # No DEVS output ports
        return None

    def deltint(self):
        self.passivate("COLLECTING")

    def exit(self):
        # Sort events by time
        self.events.sort(key=lambda x: x["time"])

        # Sort operations by input_time
        self.operations.sort(key=lambda x: x["input_time"])

        # Determine final state and simulation time
        final_event_time = 0.0
        last_accepted_operation = None

        # Determine the final state based on the last accepted operation
        for operation in reversed(self.operations):
            if operation["completed"]:
                last_accepted_operation = operation
                break

        if last_accepted_operation:
            # Determine action from value
            action = last_accepted_operation["action"]
            if action == "arm":
                self.final_state = "Armed"
            elif action == "disarm":
                self.final_state = "Disarmed"

        # Determine simulation time
        if self.events:
            final_event_time = self.events[-1]["time"]

        # Check if we reached max_simulation_time
        if final_event_time >= self.max_simulation_time:
            self.simulation_time = self.max_simulation_time
        else:
            # Find the last display event time if any
            display_times = []
            for event in self.events:
                if event.get("component") == "display":
                    display_times.append(event["time"])
            if display_times:
                self.simulation_time = max(display_times)
            else:
                self.simulation_time = final_event_time

        # Write final report to stdout
        report = {
            "test_name": self.test_name,
            "simulation_time": self.simulation_time,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "events": self.events,
            "operations": self.operations
        }
        print(json.dumps(report), flush=True)