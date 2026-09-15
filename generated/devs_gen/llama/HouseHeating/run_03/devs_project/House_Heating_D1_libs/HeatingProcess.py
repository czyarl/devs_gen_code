"""Complete pattern: update retained state from each input and write JSONL."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class HeatingProcess(Atomic):
    """Updates the room temperature based on the outdoor temperature and control signal, and write the observation record to stdout."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "outdoor_temperature"))

    def initialize(self):
        self.room_temp_c = 25.0
        self.heat_loss_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.time_sec = 0
        self.passivate("WAITING")

    def deltext(self, e):
        for outdoor_temperature in self.input["outdoor_temperature"].values:
            self.time_sec += 1
            effective_outdoor_temperature = min(outdoor_temperature, self.room_temp_c)
            heat_loss_gap = 0.1 * (self.room_temp_c - effective_outdoor_temperature)
            self.heat_loss_temp_c = self.room_temp_c - heat_loss_gap
            self.heater_output_c = 0.5 if self.control_signal == 1 else 0.0
            self.room_temp_c = self.heat_loss_temp_c + self.heater_output_c
            self.control_signal = 1 if self.room_temp_c < 24.9 else 0
            self._write_observation()

    def _write_observation(self):
        observation = {
            "time_sec": self.time_sec,
            "room_temp_c": self.room_temp_c,
            "heat_loss_temp_c": self.heat_loss_temp_c,
            "control_signal": self.control_signal,
            "heater_output_c": self.heater_output_c,
        }
        print(json.dumps(observation), flush=True)

    def lambdaf(self):
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        pass