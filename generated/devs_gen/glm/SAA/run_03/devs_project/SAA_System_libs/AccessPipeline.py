"""Atomic DEVS model for the Access Pipeline."""

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class AccessPipeline(Atomic):
    """
    Implements the three-stage access control pipeline (AlarmAdmin, Authentication, Display)
    with busy-state exclusion.
    """

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

        # Ports
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "event_out"))
        self.add_out_port(Port(dict, "operation_out"))

        # Internal State
        self.state = "Disarmed"  # "Disarmed" or "Armed"
        self.current_request = None  # Stores the accepted request dict
        self.operation_record = None  # Stores the operation record to emit
        self.ignored_buffer = None  # Buffer for ignored requests during interruption
        self.previous_phase = None  # To resume interrupted phase
        self.remaining_time = None  # To resume interrupted phase timing

    def initialize(self):
        self.state = "Disarmed"
        self.current_request = None
        self.operation_record = None
        self.ignored_buffer = None
        self.previous_phase = None
        self.remaining_time = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """
        Handle incoming requests.
        If busy, ignore the request (emit operation record with completed: false).
        If idle, accept the request, update system state, and start the pipeline.
        """
        is_busy = self.phase != "IDLE"
        
        # If busy, calculate remaining time for the current stage
        if is_busy:
            remaining = max(0.0, self.ta() - e)
        
        # Collect requests
        # We need to distinguish between accepted and ignored requests.
        # If IDLE, we accept the first one and ignore the rest (if any in the same bag).
        # If BUSY, we ignore all.
        
        accepted_request = None
        ignored_requests = []
        
        # Iterate through all requests in the input bag
        for req in self.input["request_in"].values:
            if not is_busy and accepted_request is None:
                # Accept this request
                accepted_request = req
                # Once we accept one, we effectively become busy for subsequent requests in this bag
                is_busy = True 
            else:
                # Ignore this request
                ignored_requests.append(req)

        # Process Accepted Request
        if accepted_request:
            self.current_request = accepted_request
            value = accepted_request["value"]
            action = "arm" if value == 1 else "disarm"
            input_time = accepted_request["input_time"]
            
            # Calculate completion time (authentication event time)
            completion_time = input_time + self.alarm_admin_delay + self.authentication_delay
            
            self.operation_record = {
                "input_time": input_time,
                "action": action,
                "completed": True,
                "completion_time": completion_time
            }
            
            # Update system state immediately upon acceptance
            new_state = "Armed" if value == 1 else "Disarmed"
            self.state = new_state
            
            # Schedule emission of accepted operation record
            self.hold_in("EMIT_OP_ACCEPTED", 0.0)
            
        # Process Ignored Requests
        elif ignored_requests:
            # Store ignored requests to emit records
            self.ignored_buffer = ignored_requests
            self.previous_phase = self.phase
            self.remaining_time = remaining
            
            # Schedule emission of ignored operation records
            self.hold_in("EMIT_OP_IGNORED", 0.0)
            
        # No new requests, but we were busy, so continue processing
        elif is_busy:
            self.hold_in(self.phase, remaining)

    def lambdaf(self):
        now = get_current_time()
        
        if self.phase == "EMIT_OP_ACCEPTED":
            # Emit the accepted operation record
            if self.operation_record:
                self.output["operation_out"].add(self.operation_record)
                
        elif self.phase == "EMIT_OP_IGNORED":
            # Emit all ignored operation records
            if self.ignored_buffer:
                for req in self.ignored_buffer:
                    action = "arm" if req["value"] == 1 else "disarm"
                    record = {
                        "input_time": req["input_time"],
                        "action": action,
                        "completed": False,
                        "completion_time": None
                    }
                    self.output["operation_out"].add(record)
                    
        elif self.phase == "ALARM_ADMIN":
            # Emit alarmAdmin event
            if self.current_request:
                msg = f"{{{self.current_request['port']} {self.current_request['value']}}}"
                self.output["event_out"].add({
                    "time": now,
                    "component": "alarmAdmin",
                    "message": msg,
                    "state": None
                })
                
        elif self.phase == "AUTHENTICATION":
            # Emit authentication event
            if self.current_request:
                msg = f"{{{self.current_request['port']} {self.current_request['value']}}}"
                val = self.current_request["value"]
                state_str = "ArmValid" if val == 1 else "DisarmValid"
                
                self.output["event_out"].add({
                    "time": now,
                    "component": "authentication",
                    "message": msg,
                    "state": state_str
                })
                
        elif self.phase == "DISPLAY":
            # Emit display event
            if self.current_request:
                msg = f"{{{self.current_request['port']} {self.current_request['value']}}}"
                self.output["event_out"].add({
                    "time": now,
                    "component": "display",
                    "message": msg,
                    "state": self.state
                })

    def deltint(self):
        if self.phase == "EMIT_OP_ACCEPTED":
            # Emission done, start the pipeline with AlarmAdmin delay
            self.hold_in("ALARM_ADMIN", self.alarm_admin_delay)
            
        elif self.phase == "EMIT_OP_IGNORED":
            # Emission done, resume previous busy state
            self.ignored_buffer = None
            prev = self.previous_phase
            rem = self.remaining_time
            self.previous_phase = None
            self.remaining_time = None
            self.hold_in(prev, rem)
                
        elif self.phase == "ALARM_ADMIN":
            # Move to Authentication stage
            self.hold_in("AUTHENTICATION", self.authentication_delay)
            
        elif self.phase == "AUTHENTICATION":
            # Move to Display stage
            self.hold_in("DISPLAY", self.display_delay)
            
        elif self.phase == "DISPLAY":
            # Pipeline finished, return to idle
            self.current_request = None
            self.operation_record = None
            self.passivate("IDLE")

    def exit(self):
        pass