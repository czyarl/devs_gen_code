import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HairInspection(Atomic):
    """Coordinates between Reception and Cutting phases, manages customer processing time, and sends notifications back to Reception upon completion."""

    def __init__(self, name: str, parent: Coupled | None, consultation_time: float):
        super().__init__(name)
        self.parent = parent
        self.consultation_time = consultation_time
        self.add_in_port(Port(str, "to_cut"))
        self.add_in_port(Port(str, "to_reception"))
        self.add_out_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))
        self.customer = "none"  # "none", "newcust", "done"
        self.state_change_record = {
            "time": 0.0,
            "type": "state",
            "model": "checkhair",
            "field": "customer",
            "value": ""
        }

    def initialize(self):
        self.customer = "none"
        self.state_change_record["value"] = self.customer
        self.state_change_record["time"] = get_current_time()
        print(json.dumps(self.state_change_record), flush=True)
        self.passivate("AVAILABLE")

    def deltext(self, e):
        if self.phase == "BUSY":
            self.continuef(e)
            return

        # Handle incoming customer from Reception
        for newcust in self.input["to_cut"].values:
            if self.customer == "none":
                self.customer = "newcust"
                self.state_change_record["value"] = self.customer
                self.state_change_record["time"] = get_current_time()
                print(json.dumps(self.state_change_record), flush=True)
                self.hold_in("BUSY", self.consultation_time)
                return

        # Handle completion signal from Cutting
        for done in self.input["to_reception"].values:
            if self.customer == "done":
                self.customer = "none"
                self.state_change_record["value"] = self.customer
                self.state_change_record["time"] = get_current_time()
                print(json.dumps(self.state_change_record), flush=True)
                self.passivate("AVAILABLE")
                return

        self.passivate("AVAILABLE")

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "BUSY":
            # Send customer to Cutting phase
            self.output["to_cut"].add("newcust")
            print(json.dumps({
                "time": now,
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust"
            }), flush=True)
        elif self.phase == "AVAILABLE":
            # No action needed here
            pass

    def deltint(self):
        now = get_current_time()
        if self.phase == "BUSY":
            # Customer processing complete, notify Reception
            self.customer = "done"
            self.state_change_record["value"] = self.customer
            self.state_change_record["time"] = now
            print(json.dumps(self.state_change_record), flush=True)
            self.output["to_reception"].add("done")
            print(json.dumps({
                "time": now,
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            }), flush=True)
            self.passivate("AVAILABLE")
        else:
            self.passivate("AVAILABLE")

    def exit(self):
        pass