"""ReportCollector model for aggregating events and operations from AlarmSystem."""

import json
import sys
from typing import List, Dict, Any

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ReportCollector(Atomic):
    """Collect event and operation records from AlarmSystem, derive final simulation state and time, and write exactly one combined JSON object to stdout when the simulation exits."""

    def __init__(self, name: str, parent: Coupled | None, test_name: str, initial_state: str):
        super().__init__(name)
        self.parent = parent
        self.test_name = test_name
        self.initial_state = initial_state
        self.add_in_port(Port(dict, "input_fact_in"))
        self.add_in_port(Port(dict, "event_fact_in"))
        self.add_in_port(Port(dict, "operation_fact_in"))
        self.events = []
        self.operations = []
        self.final_state = initial_state
        self.simulation_time = 0.0

    def initialize(self):
        self.events = []
        self.operations = []
        self.final_state = self.initial_state
        self.simulation_time = 0.0
        self.passivate("COLLECTING")

    def deltext(self, e):
        # Collect input facts
        for record in self.input["input_fact_in"].values:
            self.events.append(dict(record))
        
        # Collect event facts
        for record in self.input["event_fact_in"].values:
            self.events.append(dict(record))
            # Update final state if it's a display event with state
            if 'state' in record:
                self.final_state = record['state']
        
        # Collect operation facts
        for record in self.input["operation_fact_in"].values:
            self.operations.append(dict(record))
        
        self.passivate("COLLECTING")

    def lambdaf(self):
        # No DEVS outputs
        return None

    def deltint(self):
        self.passivate("COLLECTING")

    def exit(self):
        # Sort events by time
        self.events.sort(key=lambda item: float(item["time"]))
        
        # Sort operations by input_time
        self.operations.sort(key=lambda item: float(item["input_time"]))
        
        # Determine simulation_time
        # If there are events, simulation_time is the time of the last event
        # Otherwise, it's 0.0
        if self.events:
            self.simulation_time = float(self.events[-1]["time"])
        else:
            self.simulation_time = 0.0
            
        # Print final JSON object to stdout
        report = {
            "test_name": self.test_name,
            "simulation_time": self.simulation_time,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "events": self.events,
            "operations": self.operations
        }
        print(json.dumps(report), flush=True)