from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Display(Atomic):
    """Atomic model for the final stage of the access control pipeline.

    Updates the visible system state after a delay.
    """

    def __init__(self, name: str, parent: Coupled | None, display_delay: float):
        super().__init__(name)
        self.parent = parent
        self.display_delay = display_delay

        # Ports
        self.add_in_port(Port(dict, "display_request_in"))
        self.add_out_port(Port(dict, "display_event_out"))

        # Internal state
        self.stored_port = None
        self.stored_value = None
        self.current_time = 0.0

    def initialize(self):
        """Initialize the model to IDLE state."""
        self.stored_port = None
        self.stored_value = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external input on display_request_in."""
        if self.phase == "BUSY":
            # If busy, discard new request and continue processing current one
            self.continuef(e)
            return

        # If idle, check for input
        if self.phase == "IDLE":
            for request in self.input["display_request_in"].values:
                # Store request details
                self.stored_port = request.get("port")
                self.stored_value = request.get("value")
                # Schedule internal transition after display_delay
                self.hold_in("BUSY", self.display_delay)
                return
            # No input received, remain idle
            self.passivate("IDLE")

    def lambdaf(self):
        """Generate output on display_event_out when internal transition fires."""
        if self.phase == "BUSY":
            # Get current simulation time
            sim_time = get_current_time()

            # Determine state string
            state_str = "Disarmed" if self.stored_value == 0 else "Armed"

            # Format message string as '{port value}'
            message_str = f"{{{self.stored_port} {self.stored_value}}}"

            # Create output dictionary
            output_payload = {
                "time": sim_time,
                "component": "display",
                "message": message_str,
                "state": state_str
            }

            self.output["display_event_out"].add(output_payload)

    def deltint(self):
        """Handle internal transition."""
        if self.phase == "BUSY":
            # Reset internal state and return to idle
            self.stored_port = None
            self.stored_value = None
            self.passivate("IDLE")

    def exit(self):
        """Cleanup on simulation exit."""
        pass