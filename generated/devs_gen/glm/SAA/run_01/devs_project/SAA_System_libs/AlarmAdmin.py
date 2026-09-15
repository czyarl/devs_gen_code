from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class AlarmAdmin(Atomic):
    """Manage the busy state of the alarm system."""

    def __init__(self, name: str, parent: Coupled | None, alarm_admin_delay: float):
        super().__init__(name)
        self.parent = parent
        self.alarm_admin_delay = alarm_admin_delay
        
        # Input Ports
        self.add_in_port(Port(dict, "request_in"))
        self.add_in_port(Port(dict, "auth_complete_in"))
        
        # Output Ports
        self.add_out_port(Port(dict, "alarm_event_out"))
        self.add_out_port(Port(dict, "auth_request_out"))
        self.add_out_port(Port(dict, "operation_status_out"))

        # Internal State
        self.current_request = None
        self._ignored_request_info = None

    def initialize(self):
        self.current_request = None
        self._ignored_request_info = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Handle incoming requests
        for request in self.input["request_in"].values:
            if self.phase == "IDLE":
                # Accept the request
                self.current_request = dict(request)
                # Schedule internal transition for output
                self.hold_in("BUSY", self.alarm_admin_delay)
            else:
                # Already BUSY, ignore the request
                # Store info to emit operation status immediately
                self._ignored_request_info = {
                    "input_time": request["input_time"],
                    "value": request["value"]
                }
                # Schedule immediate output for the ignore status
                self.hold_in("EMIT_IGNORE", 0.0)
            return

        # Handle auth completion
        # Only check auth_complete if we are BUSY (or passively BUSY)
        if self.phase == "BUSY":
            for complete in self.input["auth_complete_in"].values:
                # Check if this matches the current request
                if self.current_request and complete["input_time"] == self.current_request["input_time"]:
                    # Transition back to IDLE
                    self.current_request = None
                    self.passivate("IDLE")
                    return

    def lambdaf(self):
        if self.phase == "BUSY" and self.current_request is not None:
            # Emit alarm event
            msg = f"{{{self.current_request['port']} {self.current_request['value']}}}"
            current_time = get_current_time()

            self.output["alarm_event_out"].add({
                "time": current_time,
                "component": "alarmAdmin",
                "message": msg
            })

            # Forward request to Authentication
            self.output["auth_request_out"].add(dict(self.current_request))

        elif self.phase == "EMIT_IGNORE":
            # Emit operation status for ignored request
            info = self._ignored_request_info
            action = "disarm" if info["value"] == 0 else "arm"
            
            self.output["operation_status_out"].add({
                "input_time": info["input_time"],
                "action": action,
                "completed": False,
                "completion_time": None
            })

    def deltint(self):
        if self.phase == "BUSY":
            # After outputting, we remain BUSY waiting for auth_complete_in
            # Passivate to wait indefinitely for external input
            self.passivate("BUSY")
            
        elif self.phase == "EMIT_IGNORE":
            # Return to BUSY state waiting for auth_complete_in
            self.passivate("BUSY")

    def exit(self):
        pass