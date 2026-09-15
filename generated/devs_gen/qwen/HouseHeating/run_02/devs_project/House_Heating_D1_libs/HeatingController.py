"""Heating controller model for house temperature simulation."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HeatingController(Atomic):
    """Atomic DEVS model for heating controller logic."""

    def __init__(self, name: str, parent: Coupled | None, target_temp_c: float, heater_gain: float, heat_loss_rate: float, initial_room_temp: float, initial_control_signal: int, initial_heater_output: float):
        super().__init__(name)
        self.parent = parent
        self.target_temp_c = target_temp_c
        self.heater_gain = heater_gain
        self.heat_loss_rate = heat_loss_rate
        self.initial_room_temp = initial_room_temp
        self.initial_control_signal = initial_control_signal
        self.initial_heater_output = initial_heater_output
        self.add_in_port(Port(float, "value_in"))

        # Internal state
        self.room_temp_c = 0.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.previous_room_temp_c = 0.0
        self.previous_control_signal = 0

    def initialize(self):
        self.room_temp_c = self.initial_room_temp
        self.control_signal = self.initial_control_signal
        self.heater_output_c = self.initial_heater_output
        self.previous_room_temp_c = self.initial_room_temp
        self.previous_control_signal = self.initial_control_signal
        self.passivate("WAITING")

    def deltext(self, e):
        for received_value in self.input["value_in"].values:
            # Process the received value
            # Effective outdoor temperature is capped to previous room temperature
            effective_outdoor_temp = min(received_value, self.previous_room_temp_c)
            
            # Heat loss calculation
            heat_loss = self.heat_loss_rate * (self.previous_room_temp_c - effective_outdoor_temp)
            heat_loss_temp_c = self.previous_room_temp_c - heat_loss
            
            # Heater output based on previous control signal
            if self.previous_control_signal == 1:
                heater_output = self.heater_gain
            else:
                heater_output = 0.0
            heater_output_c = heater_output
            
            # New room temperature
            new_room_temp_c = heat_loss_temp_c + heater_output_c
            
            # Determine next control signal
            next_control_signal = 1 if new_room_temp_c < self.target_temp_c else 0
            
            # Emit the observation record
            observation = {
                "time_sec": int(get_current_time()),
                "room_temp_c": new_room_temp_c,
                "heat_loss_temp_c": heat_loss_temp_c,
                "control_signal": next_control_signal,
                "heater_output_c": heater_output_c
            }
            print(json.dumps(observation), flush=True)
            
            # Update internal state for next iteration
            self.previous_room_temp_c = new_room_temp_c
            self.previous_control_signal = next_control_signal
            self.room_temp_c = new_room_temp_c
            self.control_signal = next_control_signal
            self.heater_output_c = heater_output_c
            
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output ports defined, so nothing to do here
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        # No cleanup needed for this model
        pass