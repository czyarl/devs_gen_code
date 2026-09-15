from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class Authentication(Atomic):
    def __init__(self, name: str, parent: Coupled | None, authentication_delay: float):
        super().__init__(name)
        self.parent = parent
        self.authentication_delay = authentication_delay
        
        # Input Ports
        self.add_in_port(Port(dict, "auth_request_in"))
        
        # Output Ports
        self.add_out_port(Port(dict, "auth_event_out"))
        self.add_out_port(Port(dict, "display_request_out"))
        self.add_out_port(Port(dict, "auth_complete_out"))
        self.add_out_port(Port(dict, "operation_status_out"))
        
        # Internal state
        self.current_payload = None
        self.validation_state = None
        self.action_string = None
        self.completion_time = None

    def initialize(self):
        self.current_payload = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # The model processes requests sequentially without queuing.
        # If we are already processing (DELAYING), we ignore new inputs.
        if self.phase == "DELAYING":
            self.continuef(e)
            return

        # If idle, accept the request
        if self.phase == "IDLE":
            for payload in self.input["auth_request_in"].values:
                self.current_payload = payload
                # Schedule internal transition after authentication_delay
                self.hold_in("DELAYING", self.authentication_delay)
                return

    def lambdaf(self):
        if self.phase == "DELAYING" and self.current_payload is not None:
            # Determine validation state and action string
            value = self.current_payload.get("value", 0)
            if value == 0:
                self.validation_state = "DisarmValid"
                self.action_string = "disarm"
            else:
                self.validation_state = "ArmValid"
                self.action_string = "arm"
            
            # Get current simulation time for completion time
            self.completion_time = get_current_time()
            
            # Prepare outputs
            
            # 1. auth_event_out: {'time': float, 'component': 'authentication', 'message': str, 'state': str}
            message = f"{{{self.current_payload['port']} {self.current_payload['value']}}}"
            self.output["auth_event_out"].add({
                "time": self.completion_time,
                "component": "authentication",
                "message": message,
                "state": self.validation_state
            })
            
            # 2. display_request_out: Forward original payload
            self.output["display_request_out"].add(dict(self.current_payload))
            
            # 3. auth_complete_out: {'input_time': float}
            self.output["auth_complete_out"].add({
                "input_time": self.current_payload["input_time"]
            })
            
            # 4. operation_status_out: {'input_time': float, 'action': str, 'completed': bool, 'completion_time': float}
            self.output["operation_status_out"].add({
                "input_time": self.current_payload["input_time"],
                "action": self.action_string,
                "completed": True,
                "completion_time": self.completion_time
            })

    def deltint(self):
        # Reset internal state and go back to IDLE
        self.current_payload = None
        self.validation_state = None
        self.action_string = None
        self.completion_time = None
        self.passivate("IDLE")

    def exit(self):
        pass