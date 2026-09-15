"""Complete pattern: update retained state from each input and write JSONL."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class HeatingController(Atomic):
    """Update room temperature from outdoor temperature and control signal; write JSONL."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "outdoor_temp"))

    def initialize(self):
        self.room_temp_c = 25.0
        self.heat_loss_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.previous_control_signal = 0
        self.passivate("WAITING")

    def deltext(self, e):
        for outdoor_temp in self.input["outdoor_temp"].values:
            effective_outdoor_temp = min(outdoor_temp, self.room_temp_c)
            heat_loss_gap = self.room_temp_c - effective_outdoor_temp
            self.heat_loss_temp_c = self.room_temp_c - 0.1 * heat_loss_gap
            self.heater_output_c = 0.5 if self.previous_control_signal == 1 else 0.0
            self.room_temp_c = self.heat_loss_temp_c + self.heater_output_c
            self.control_signal = 1 if self.room_temp_c < 24.9 else 0
            self.previous_control_signal = self.control_signal
            record = {
                "time_sec": int(get_current_time()),
                "room_temp_c": self.room_temp_c,
                "heat_loss_temp_c": self.heat_loss_temp_c,
                "control_signal": self.control_signal,
                "heater_output_c": self.heater_output_c,
            }
            print(json.dumps(record), flush=True)
        self.passivate("WAITING")

    def lambdaf(self):
        # No DEVS output port
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        pass