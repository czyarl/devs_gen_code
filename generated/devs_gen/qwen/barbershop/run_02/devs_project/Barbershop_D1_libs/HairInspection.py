from xdevs.models import Atomic, Coupled, Port
import json
import sys
from devs_project.devs_utils.devs_context import get_current_time


class HairInspection(Atomic):
    def __init__(self, name: str, parent: Coupled | None, inspection_time: float):
        super().__init__(name)
        self.parent = parent
        self.inspection_time = inspection_time
        self.add_in_port(Port(dict, "cust"))
        self.add_in_port(Port(str, "out"))
        self.add_out_port(Port(dict, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))
        self.customer = None
        self.in_flight = None

    def initialize(self):
        self.customer = "done"
        self.in_flight = None
        self.passivate("AVAILABLE")

    def deltext(self, e):
        if self.phase == "BUSY":
            self.continuef(e)
            return

        # Handle customer from Reception
        for cust in self.input["cust"].values:
            self.customer = "newcust"
            self.in_flight = dict(cust)
            self.hold_in("BUSY", self.inspection_time)
            # Emit state change record
            record = {
                "time": get_current_time(),
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": "newcust"
            }
            print(json.dumps(record), flush=True)
            return

        # Handle 'done' signal from HairCutting
        for signal in self.input["out"].values:
            if signal == "done":
                self.customer = "done"
                self.in_flight = None
                self.hold_in("AVAILABLE", 0.0)
                # Emit state change record
                record = {
                    "time": get_current_time(),
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "done"
                }
                print(json.dumps(record), flush=True)
                return

        self.passivate("AVAILABLE")

    def lambdaf(self):
        if self.phase == "BUSY" and self.in_flight is not None:
            self.output["to_cut"].add(dict(self.in_flight))
            # Emit message record
            record = {
                "time": get_current_time(),
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust"
            }
            print(json.dumps(record), flush=True)

        elif self.phase == "AVAILABLE" and self.in_flight is not None:
            self.output["to_reception"].add("done")
            # Emit message record
            record = {
                "time": get_current_time(),
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "BUSY":
            self.in_flight = None
            self.passivate("AVAILABLE")
        elif self.phase == "AVAILABLE":
            self.passivate("AVAILABLE")

    def exit(self):
        pass