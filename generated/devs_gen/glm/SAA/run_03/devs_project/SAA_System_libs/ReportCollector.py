import json

from xdevs.models import Atomic, Coupled, Port


class ReportCollector(Atomic):
    """Accumulate all incoming event and operation records and write final JSON report."""

    def __init__(self, name: str, parent: Coupled | None, test_name: str, max_simulation_time: float):
        super().__init__(name)
        self.parent = parent
        self.test_name = test_name
        self.max_simulation_time = max_simulation_time

        # Ports defined in locked contract
        self.add_in_port(Port(dict, "event_in"))
        self.add_in_port(Port(dict, "operation_in"))

        # Internal storage
        self.events = []
        self.operations = []
        
        # State tracking
        # "Track the current system state, initializing it to 'Disarmed'"
        self.current_state = "Disarmed"

    def initialize(self):
        # Reset internal lists
        self.events = []
        self.operations = []
        self.current_state = "Disarmed"
        
        # This model is passive; it only reacts to incoming messages via deltext.
        # It has no internal transitions or outputs to generate during simulation.
        self.passivate("COLLECTING")

    def deltext(self, e):
        # Accumulate events
        for record in self.input["event_in"].values:
            # Make a copy to avoid reference issues if the sender reuses the dict
            self.events.append(dict(record))
            
            # "updating it to the state field of any received 'display' event"
            if record.get("component") == "display":
                state_val = record.get("state")
                if state_val is not None:
                    self.current_state = state_val

        # Accumulate operations
        for record in self.input["operation_in"].values:
            self.operations.append(dict(record))

        # Remain passive
        self.passivate("COLLECTING")

    def lambdaf(self):
        # No DEVS output ports defined for this model
        pass

    def deltint(self):
        # Should not be called if passive, but defined for completeness
        self.passivate("COLLECTING")

    def exit(self):
        # Sort events by nondecreasing time
        self.events.sort(key=lambda item: float(item["time"]))
        
        # Sort operations by input_time
        self.operations.sort(key=lambda item: float(item["input_time"]))

        # Determine final state
        # "Determine the final state as the last recorded state from display events (or 'Disarmed' if none)"
        # Note: self.current_state was updated in deltext, so it holds the last state seen.
        final_state = self.current_state

        # Determine simulation time
        # "Determine the simulation time as the maximum of the last event timestamp 
        # and the provided max_simulation_time."
        
        last_event_time = 0.0
        if self.events:
            # Get the time of the last event in the sorted list
            last_event_time = float(self.events[-1]["time"])
        
        simulation_time = max(last_event_time, self.max_simulation_time)

        # Construct JSON object
        output_record = {
            "test_name": self.test_name,
            "simulation_time": simulation_time,
            "initial_state": "Disarmed",
            "final_state": final_state,
            "events": self.events,
            "operations": self.operations
        }

        # Write to stdout
        print(json.dumps(output_record), flush=True)