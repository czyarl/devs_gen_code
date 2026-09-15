from xdevs.models import Atomic, Coupled, Port
import sys
import json
from devs_project.devs_utils.devs_context import get_current_time

class HairCutter(Atomic):
    def __init__(self, name: str, parent: Coupled | None, process_time: float):
        super().__init__(name)
        self.parent = parent
        self.process_time = process_time
        
        # Ports
        self.add_in_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "out"))
        
        # State variables
        self.total_customer_done = 0

    def initialize(self):
        self.total_customer_done = 0
        self.passivate("idle")

    def deltext(self, e: float):
        # If busy, ignore input and continue processing
        if self.phase == "busy":
            self.continuef(e)
            return
        
        # If idle, check for input
        if self.phase == "idle":
            for val in self.input["to_cut"].values:
                # Transition to busy state upon receiving 'newcust'
                if val == "newcust":
                    self.hold_in("busy", self.process_time)
                    return
        
        # If no input or invalid input, stay idle
        self.passivate("idle")

    def lambdaf(self):
        # Emit 'done' message via output port when busy phase ends
        if self.phase == "busy":
            self.output["out"].add("done")

    def deltint(self):
        # Internal transition: processing finished
        if self.phase == "busy":
            # Increment counter
            self.total_customer_done += 1
            
            # External IO: State change JSONL record
            time = get_current_time()
            state_record = {
                "time": time,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_customer_done
            }
            print(json.dumps(state_record), flush=True)
            
            # External IO: Message JSONL record for the 'done' send
            # Note: The DEVS output 'done' was sent in lambdaf() at the same simulation time.
            # The requirement R005 says "Emit Type message on send".
            message_record = {
                "time": time,
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done"
            }
            print(json.dumps(message_record), flush=True)
            
            # Transition back to idle
            self.passivate("idle")

    def exit(self):
        pass