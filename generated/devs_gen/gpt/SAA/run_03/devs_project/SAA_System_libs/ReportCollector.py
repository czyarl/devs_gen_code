import json
import sys
from typing import Any

from xdevs.models import Atomic, Coupled, Port


class ReportCollector(Atomic):
    """
    Passive atomic sink that aggregates event/operation/state facts during a DEVS run
    and prints exactly one final JSON report to stdout in exit().
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        test_name: str,
        max_simulation_time: float,
        initial_state: str,
    ):
        super().__init__(name)
        self.parent = parent

        # Init args copied into final report
        self.test_name = test_name
        self.max_simulation_time = float(max_simulation_time)
        self.initial_state = initial_state

        # Input ports (no output ports)
        self.add_in_port(Port(dict, "input_event_in"))
        self.add_in_port(Port(dict, "alarmadmin_event_in"))
        self.add_in_port(Port(dict, "authentication_event_in"))
        self.add_in_port(Port(dict, "display_event_in"))
        self.add_in_port(Port(dict, "operation_fact_in"))
        self.add_in_port(Port(dict, "operation_update_in"))
        self.add_in_port(Port(dict, "state_update_in"))

        # Collections
        self.events: list[dict[str, Any]] = []
        self.operations: list[dict[str, Any]] = []

        # Temporary completion updates that may arrive before the corresponding fact
        self._pending_operation_updates: dict[float, float] = {}

        # Final state tracking
        self.final_state: str = "Disarmed"

    def initialize(self):
        self.events = []
        self.operations = []
        self._pending_operation_updates = {}
        self.final_state = "Disarmed"
        self.passivate("COLLECTING")

    def deltext(self, e: float):
        # Collect events exactly as received
        for record in self.input["input_event_in"].values:
            self.events.append(record)

        for record in self.input["alarmadmin_event_in"].values:
            self.events.append(record)

        for record in self.input["authentication_event_in"].values:
            self.events.append(record)

        for record in self.input["display_event_in"].values:
            self.events.append(record)

        # Operation facts: append, then apply any pending update by input_time
        for op in self.input["operation_fact_in"].values:
            self.operations.append(op)
            try:
                input_time = op["input_time"]
            except Exception:
                continue
            if input_time in self._pending_operation_updates:
                op["completion_time"] = self._pending_operation_updates[input_time]

        # Operation updates: update existing ops; if none exist yet, store pending
        for upd in self.input["operation_update_in"].values:
            input_time = upd["input_time"]
            completion_time = upd["completion_time"]

            # Last received wins (store regardless)
            self._pending_operation_updates[input_time] = completion_time

            found = False
            for op in self.operations:
                if op.get("input_time") == input_time:
                    op["completion_time"] = completion_time
                    found = True
            # If not found, pending map will be applied when fact arrives

        # State updates: last received wins
        for st in self.input["state_update_in"].values:
            self.final_state = st["state"]

        self.passivate("COLLECTING")

    def lambdaf(self):
        # No DEVS outputs.
        return None

    def deltint(self):
        self.passivate("COLLECTING")

    def exit(self):
        # Apply any pending updates to any matching operations (covers placeholders created later)
        if self._pending_operation_updates:
            for op in self.operations:
                it = op.get("input_time")
                if it in self._pending_operation_updates:
                    op["completion_time"] = self._pending_operation_updates[it]

        # Sort collections
        self.events.sort(key=lambda item: float(item["time"]))
        self.operations.sort(key=lambda item: float(item["input_time"]))

        # Derive simulation_time conservatively per contract
        if self.events:
            max_event_time = max(float(e["time"]) for e in self.events)
            simulation_time = min(self.max_simulation_time, max_event_time)
            if max_event_time > self.max_simulation_time:
                simulation_time = self.max_simulation_time
        else:
            simulation_time = 0.0

        report = {
            "test_name": self.test_name,
            "simulation_time": float(simulation_time),
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "events": self.events,
            "operations": self.operations,
        }

        # Exactly one JSON object to stdout; no other stdout output.
        print(json.dumps(report), flush=True)

        # Optional debug to stderr is allowed; do not print JSON there.
        # (No debug output by default.)
        _ = sys.stderr  # keep import used without emitting anything