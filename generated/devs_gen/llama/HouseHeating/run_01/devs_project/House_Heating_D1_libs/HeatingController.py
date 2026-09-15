"""Complete pattern: update retained state from each input and write JSONL."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class HeatingController(Atomic):
    """Update the room temperature and control signal based on the outdoor temperature and sends the observation record to stdout."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "temperature_in"))
        self.room_temp_c = 25.0
        self.heat_loss_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.previous_control_signal = 0

    def initialize(self):
        self.room_temp_c = 25.0
        self.heat_loss_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.previous_control_signal = 0
        self.passivate("WAITING")

    def deltext(self, e):
        for outdoor_temperature in self.input["temperature_in"].values:
            self.heat_loss_temp_c = min(self.room_temp_c, outdoor_temperature)
            heat_loss_gap = self.room_temp_c - self.heat_loss_temp_c
            self.room_temp_c = self.heat_loss_temp_c - 0.1 * heat_loss_gap
            self.heater_output_c = 0.5 if self.previous_control_signal == 1 else 0.0
            self.room_temp_c += self.heater_output_c
            self.previous_control_signal = self.control_signal
            self.control_signal = 1 if self.room_temp_c < 24.9 else 0
            print(json.dumps({
                "time_sec": int(get_current_time()),
                "room_temp_c": self.room_temp_c,
                "heat_loss_temp_c": self.heat_loss_temp_c,
                "control_signal": self.control_signal,
                "heater_output_c": self.heater_output_c,
            }), flush=True)
        self.passivate("WAITING")

    def lambdaf(self):
        # This contract has external JSONL output but no DEVS output port.
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        pass