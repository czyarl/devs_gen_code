from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class AlarmSystem(Atomic):
    """Atomic DEVS model implementing the alarm system with three-stage pipeline."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
        max_simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        self.add_in_port(Port(dict, "input_event_in"))
        self.add_out_port(Port(dict, "event_fact_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))
        self.current_request = None
        self.is_busy = False
        self.state = "Disarmed"
        self.events = []
        self.operations = []
        self.last_display_time = 0.0
        self.final_simulation_time = 0.0

    def initialize(self):
        self.current_request = None
        self.is_busy = False
        self.state = "Disarmed"
        self.events = []
        self.operations = []
        self.last_display_time = 0.0
        self.final_simulation_time = 0.0
        self.passivate("IDLE")

    def deltext(self, e):
        was_busy = self.is_busy
        remaining = max(0.0, self.ta() - e) if was_busy else None
        for input_event in self.input["input_event_in"].values:
            input_time = input_event["input_time"]
            port = input_event["port"]
            value = input_event["value"]
            message = f"{{{port} {value}}}"
            
            # Record input reader event
            self.events.append({
                "time": input_time,
                "component": "input_reader",
                "message": message
            })
            
            # Check if we are busy
            if self.is_busy:
                # Ignore new request
                self.operations.append({
                    "input_time": input_time,
                    "action": "disarm" if value == 0 else "arm",
                    "completed": False,
                    "completion_time": None
                })
                continue
            
            # Accept the request
            self.is_busy = True
            self.current_request = {
                "input_time": input_time,
                "port": port,
                "value": value,
                "message": message
            }
            self.operations.append({
                "input_time": input_time,
                "action": "disarm" if value == 0 else "arm",
                "completed": True,
                "completion_time": None
            })
            self.hold_in("ALARM_ADMIN", self.alarm_admin_delay)
            break
        
        if remaining is not None and self.is_busy:
            # Preserve remaining time if already busy
            self.hold_in(self.phase, remaining)

    def lambdaf(self):
        if self.current_request is None:
            return
        now = get_current_time()
        value = self.current_request["value"]
        message = self.current_request["message"]
        input_time = self.current_request["input_time"]
        port = self.current_request["port"]
        
        if self.phase == "ALARM_ADMIN":
            self.events.append({
                "time": now,
                "component": "alarmAdmin",
                "message": message
            })
        elif self.phase == "AUTHENTICATION":
            state = "DisarmValid" if value == 0 else "ArmValid"
            self.events.append({
                "time": now,
                "component": "authentication",
                "message": message,
                "state": state
            })
            # Update completion time in operations
            for op in self.operations:
                if op["input_time"] == input_time and op["completed"]:
                    op["completion_time"] = now
                    break
        elif self.phase == "DISPLAY":
            state = "Disarmed" if value == 0 else "Armed"
            self.events.append({
                "time": now,
                "component": "display",
                "message": message,
                "state": state
            })
            # Update state
            self.state = state
            self.last_display_time = now

    def deltint(self):
        if self.phase == "ALARM_ADMIN":
            self.hold_in("AUTHENTICATION", self.authentication_delay)
        elif self.phase == "AUTHENTICATION":
            self.hold_in("DISPLAY", self.display_delay)
        elif self.phase == "DISPLAY":
            self.is_busy = False
            self.current_request = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        self.final_simulation_time = max(self.last_display_time, self.max_simulation_time)
        # The parent model (SAA_System) will collect all events and operations
        # and construct the final JSON report.
        pass