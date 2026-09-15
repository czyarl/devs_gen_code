from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys

class AlarmSystem(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "event_fact_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))
        self.add_out_port(Port(dict, "alarm_admin_out"))
        self.add_out_port(Port(dict, "authentication_out"))
        self.add_out_port(Port(dict, "display_out"))
        self.current_request = None
        self.state = "Disarmed"
        self.events = []
        self.operations = []
        self.last_completed_time = 0.0
        self.max_simulation_time = 1000.0

    def initialize(self):
        self.current_request = None
        self.state = "Disarmed"
        self.events = []
        self.operations = []
        self.last_completed_time = 0.0
        self.passivate("IDLE")

    def deltext(self, e):
        was_busy = self.phase != "IDLE"
        remaining = max(0.0, self.ta() - e) if was_busy else None
        
        if not was_busy:
            for request in self.input["request_in"].values:
                # Record input_reader event
                input_time = request["input_time"]
                port = request["port"]
                value = request["value"]
                message = f"{{{port} {value}}}"
                
                self.events.append({
                    "time": input_time,
                    "component": "input_reader",
                    "message": message
                })
                
                # Check if we can accept this request
                if self.current_request is not None:
                    # Ignore the new request
                    self.operations.append({
                        "input_time": input_time,
                        "action": "disarm" if value == 0 else "arm",
                        "completed": False,
                        "completion_time": None
                    })
                else:
                    # Accept the request
                    self.current_request = dict(request)
                    self.operations.append({
                        "input_time": input_time,
                        "action": "disarm" if value == 0 else "arm",
                        "completed": True,
                        "completion_time": None
                    })
                    # Schedule alarm_admin event
                    self.hold_in("ALARM_ADMIN", self.alarm_admin_delay)
                break
        elif remaining is not None:
            # Preserve the old stage deadline
            self.hold_in(self.phase, remaining)

    def lambdaf(self):
        now = get_current_time()
        if self.current_request is None:
            return
            
        if self.phase == "ALARM_ADMIN":
            # Emit alarm_admin event
            input_time = self.current_request["input_time"]
            port = self.current_request["port"]
            value = self.current_request["value"]
            message = f"{{{port} {value}}}"
            
            self.output["alarm_admin_out"].add({
                "time": now,
                "component": "alarmAdmin",
                "message": message
            })
            
            self.events.append({
                "time": now,
                "component": "alarmAdmin",
                "message": message
            })
            
        elif self.phase == "AUTHENTICATION":
            # Emit authentication event
            input_time = self.current_request["input_time"]
            port = self.current_request["port"]
            value = self.current_request["value"]
            message = f"{{{port} {value}}}"
            state = "DisarmValid" if value == 0 else "ArmValid"
            
            self.output["authentication_out"].add({
                "time": now,
                "component": "authentication",
                "message": message,
                "state": state
            })
            
            self.events.append({
                "time": now,
                "component": "authentication",
                "message": message,
                "state": state
            })
            
            # Update state
            if value == 1:
                self.state = "Armed"
            else:
                self.state = "Disarmed"
                
        elif self.phase == "DISPLAY":
            # Emit display event
            input_time = self.current_request["input_time"]
            port = self.current_request["port"]
            value = self.current_request["value"]
            message = f"{{{port} {value}}}"
            state = "Armed" if value == 1 else "Disarmed"
            
            self.output["display_out"].add({
                "time": now,
                "component": "display",
                "message": message,
                "state": state
            })
            
            self.events.append({
                "time": now,
                "component": "display",
                "message": message,
                "state": state
            })
            
            # Update operation completion time
            for op in self.operations:
                if op["input_time"] == input_time and op["completed"]:
                    op["completion_time"] = now
                    break

    def deltint(self):
        if self.current_request is None:
            self.passivate("IDLE")
            return
            
        if self.phase == "ALARM_ADMIN":
            self.hold_in("AUTHENTICATION", self.authentication_delay)
        elif self.phase == "AUTHENTICATION":
            self.hold_in("DISPLAY", self.display_delay)
        elif self.phase == "DISPLAY":
            self.current_request = None
            self.passivate("IDLE")

    def exit(self):
        # No external IO required as per the contract
        pass