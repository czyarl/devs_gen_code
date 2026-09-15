"""Room state processor for house heating simulation."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class RoomStateProcessor(Atomic):
    """Processes room temperature state updates and outputs observations."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "value_in"))
        # Internal state
        self.room_temp_c = 25.0
        self.previous_control_signal = 0
        self.heater_output_c = 0.0
        self.previous_outdoor_temp = 25.0
        self.time_sec = 0

    def initialize(self):
        # Initial state at time 0
        self.room_temp_c = 25.0
        self.previous_control_signal = 0
        self.heater_output_c = 0.0
        self.previous_outdoor_temp = 25.0
        self.time_sec = 0
        # At t=1, the first outdoor temperature value will be received
        self.passivate("WAITING")

    def deltext(self, e):
        for received_value in self.input["value_in"].values:
            # Process the outdoor temperature value received at current time
            self.time_sec = int(get_current_time())
            # Apply heat loss and heater gain
            # First, compute effective outdoor temperature (capped to room temp)
            effective_outdoor_temp = min(received_value, self.room_temp_c)
            # Compute heat loss (10% of the gap)
            heat_loss = 0.1 * (self.room_temp_c - effective_outdoor_temp)
            heat_loss_temp_c = self.room_temp_c - heat_loss
            # Apply heater gain (delayed by one step)
            heater_output_c = 0.5 if self.previous_control_signal == 1 else 0.0
            new_room_temp_c = heat_loss_temp_c + heater_output_c
            # Determine next control signal
            next_control_signal = 1 if new_room_temp_c < 24.9 else 0
            # Emit observation
            observation = {
                "time_sec": self.time_sec,
                "room_temp_c": new_room_temp_c,
                "heat_loss_temp_c": heat_loss_temp_c,
                "control_signal": next_control_signal,
                "heater_output_c": heater_output_c
            }
            print(json.dumps(observation), flush=True)
            # Update internal state for next step
            self.room_temp_c = new_room_temp_c
            self.previous_control_signal = next_control_signal
            self.heater_output_c = heater_output_c
            self.previous_outdoor_temp = received_value
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        pass