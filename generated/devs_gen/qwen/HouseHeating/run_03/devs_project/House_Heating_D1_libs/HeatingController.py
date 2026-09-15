"""Heating controller model implementing bang-bang temperature control."""

import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HeatingController(Atomic):
    """Atomic DEVS model for heating control with bang-bang strategy."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "value_in"))
        
        # Internal state
        self.room_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.previous_room_temp_c = 25.0
        self.previous_control_signal = 0
        self.previous_outdoor_temp = 25.0
        self.current_time = 0.0

    def initialize(self):
        # Initialize state as per requirements
        self.room_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.previous_room_temp_c = 25.0
        self.previous_control_signal = 0
        self.previous_outdoor_temp = 25.0
        self.current_time = 0.0
        
        # Passivate until first input arrives
        self.passivate("WAITING")

    def deltext(self, e):
        # Process all incoming values
        for received_value in self.input["value_in"].values:
            # Update current time to match the time of the received value
            self.current_time = get_current_time()
            
            # Apply the dynamics for the previous time step
            self._apply_dynamics(received_value)
            
            # Emit observation at integer seconds
            if self.current_time >= 1.0 and self.current_time == int(self.current_time):
                self._emit_observation()
            
            # Update state for next step
            self.previous_room_temp_c = self.room_temp_c
            self.previous_control_signal = self.control_signal
            self.previous_outdoor_temp = received_value
            
        # Passivate until next input
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports required per contract
        pass

    def deltint(self):
        # No internal events scheduled
        self.passivate("WAITING")

    def exit(self):
        # Emit final observation if needed
        if self.current_time >= 1.0 and self.current_time == int(self.current_time):
            self._emit_observation()

    def _apply_dynamics(self, outdoor_temp):
        """Apply the heating dynamics using the previous state."""
        # Cap outdoor temperature to prevent heat gain from outside
        effective_outdoor_temp = min(outdoor_temp, self.previous_room_temp_c)
        
        # Calculate heat loss (10% of the temperature difference)
        heat_loss = 0.1 * (self.previous_room_temp_c - effective_outdoor_temp)
        heat_loss_temp_c = self.previous_room_temp_c - heat_loss
        
        # Apply heater gain (delayed by one step)
        if self.previous_control_signal == 1:
            heater_output_c = 0.5
        else:
            heater_output_c = 0.0
            
        # Calculate new room temperature
        self.room_temp_c = heat_loss_temp_c + heater_output_c
        self.heater_output_c = heater_output_c
        
        # Set next control signal based on room temperature
        if self.room_temp_c < 24.9:
            self.control_signal = 1
        else:
            self.control_signal = 0

    def _emit_observation(self):
        """Emit one JSONL observation to stdout."""
        observation = {
            "time_sec": int(self.current_time),
            "room_temp_c": round(self.room_temp_c, 1),
            "heat_loss_temp_c": round(self.previous_room_temp_c - 0.1 * (self.previous_room_temp_c - min(self.previous_outdoor_temp, self.previous_room_temp_c)), 1),
            "control_signal": self.control_signal,
            "heater_output_c": self.heater_output_c
        }
        print(json.dumps(observation), flush=True)