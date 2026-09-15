import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CutHair(Atomic):
    """Simulates the hair cutting phase as a fixed-duration service processor."""

    def __init__(self, name: str, parent: Coupled | None, cutting_time: float):
        super().__init__(name)
        self.parent = parent
        self.cutting_time = cutting_time
        self.add_in_port(Port(str, "in_cust"))
        self.add_out_port(Port(str, "out"))
        
        self.total_customer_done = 0

    def initialize(self):
        self.total_customer_done = 0
        self.passivate("idle")

    def deltext(self, e: float):
        if self.phase == "busy":
            self.continuef(e)
            return

        for _ in self.input["in_cust"].values:
            if self.phase == "idle":
                self.hold_in("busy", self.cutting_time)
                return
        self.passivate("idle")

    def lambdaf(self):
        if self.phase == "busy":
            self.output["out"].add("done")
            
            # External IO: Type B: Communication Event
            time = get_current_time()
            record = {
                "time": time,
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done"
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "busy":
            self.total_customer_done += 1
            
            # External IO: Type A: State Change
            time = get_current_time()
            record = {
                "time": time,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_customer_done
            }
            print(json.dumps(record), flush=True)
            
            self.passivate("idle")

    def exit(self):
        pass