"""Complete pattern: retain facts and print one final combined document."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ReportCollector(Atomic):
    """Collect event and result facts without printing intermediate JSONL."""

    def __init__(self, name: str, parent: Coupled | None, test_name: str):
        super().__init__(name)
        self.parent = parent
        self.test_name = test_name
        self.add_in_port(Port(dict, "input_fact_in"))
        self.add_in_port(Port(dict, "event_fact_in"))
        self.add_in_port(Port(dict, "operation_fact_in"))
        self.input_facts = []
        self.event_facts = []
        self.operation_facts = []

    def initialize(self):
        self.input_facts = []
        self.event_facts = []
        self.operation_facts = []
        self.passivate("COLLECTING")

    def deltext(self, e):
        for packet in self.input["input_fact_in"].values:
            self.input_facts.append(dict(packet))
        for packet in self.input["event_fact_in"].values:
            self.event_facts.append(dict(packet))
        for packet in self.input["operation_fact_in"].values:
            self.operation_facts.append(dict(packet))
        self.passivate("COLLECTING")

    def lambdaf(self):
        # This sink has no DEVS output ports and no per-event stdout output.
        return None

    def deltint(self):
        self.passivate("COLLECTING")

    def exit(self):
        self.input_facts.sort(key=lambda item: float(item["time"]))
        self.event_facts.sort(key=lambda item: float(item["time"]))
        self.operation_facts.sort(key=lambda item: float(item["input_time"]))
        print(json.dumps({
            "test_name": self.test_name,
            "simulation_time": get_current_time(),
            "initial_state": "TODO",  # TO DO: derive initial state
            "final_state": "TODO",  # TO DO: derive final state
            "events": self.event_facts,
            "operations": self.operation_facts,
        }), flush=True)