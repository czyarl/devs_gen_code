from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class AccessPipeline(Atomic):
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
        
        # Internal state
        self.system_state = "Disarmed"
        self.is_alarm_admin_busy = False
        self.pending_request = None
        self.completion_time = None

    def initialize(self):
        self.system_state = "Disarmed"
        self.is_alarm_admin_busy = False
        self.pending_request = None
        self.completion_time = None
        self.passivate("IDLE")

    def deltext(self, e):
        # Handle incoming requests
        for request in self.input["request_in"].values:
            self.handle_request(request)
            break  # Only process one request per external transition

        # Continue with existing processing if needed
        if self.phase != "IDLE":
            remaining = max(0.0, self.ta() - e)
            self.hold_in(self.phase, remaining)

    def handle_request(self, request):
        now = get_current_time()
        input_time = request['input_time']
        value = request['value']
        port = request['port']
        
        # Emit input_reader event immediately
        message = f"{{{port} {value}}}"
        self.output["event_fact_out"].add({
            "time": input_time,
            "component": "input_reader",
            "message": message
        })
        
        # Determine if request is accepted
        accepted = not self.is_alarm_admin_busy
        
        # Record operation fact for all requests
        action = "disarm" if value == 0 else "arm"
        operation_fact = {
            "input_time": input_time,
            "action": action,
            "completed": accepted,
            "completion_time": None
        }
        self.output["operation_fact_out"].add(operation_fact)
        
        if not accepted:
            # Request ignored
            return
            
        # Accept the request
        self.is_alarm_admin_busy = True
        self.pending_request = dict(request)
        self.completion_time = None
        
        # Schedule alarmAdmin event
        alarm_admin_time = input_time + self.alarm_admin_delay
        self.hold_in("ALARM_ADMIN_DELAY", self.alarm_admin_delay)
        
    def lambdaf(self):
        now = get_current_time()
        if self.phase == "ALARM_ADMIN_DELAY":
            if self.pending_request is not None:
                value = self.pending_request['value']
                port = self.pending_request['port']
                message = f"{{{port} {value}}}"
                self.output["event_fact_out"].add({
                    "time": now,
                    "component": "alarmAdmin",
                    "message": message
                })
                
    def deltint(self):
        now = get_current_time()
        if self.phase == "ALARM_ADMIN_DELAY":
            # Move to authentication delay
            self.hold_in("AUTHENTICATION_DELAY", self.authentication_delay)
        elif self.phase == "AUTHENTICATION_DELAY":
            # Authentication completed
            if self.pending_request is not None:
                value = self.pending_request['value']
                port = self.pending_request['port']
                message = f"{{{port} {value}}}"
                state = "DisarmValid" if value == 0 else "ArmValid"
                self.output["event_fact_out"].add({
                    "time": now,
                    "component": "authentication",
                    "message": message,
                    "state": state
                })
                self.completion_time = now
                
                # Update system state
                if value == 1:
                    self.system_state = "Armed"
                else:
                    self.system_state = "Disarmed"
                
                # Schedule display event
                self.hold_in("DISPLAY_DELAY", self.display_delay)
        elif self.phase == "DISPLAY_DELAY":
            # Display completed
            if self.pending_request is not None:
                value = self.pending_request['value']
                port = self.pending_request['port']
                message = f"{{{port} {value}}}"
                state = "Disarmed" if value == 0 else "Armed"
                self.output["event_fact_out"].add({
                    "time": now,
                    "component": "display",
                    "message": message,
                    "state": state
                })
            
            # Reset for next request
            self.is_alarm_admin_busy = False
            self.pending_request = None
            self.completion_time = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass