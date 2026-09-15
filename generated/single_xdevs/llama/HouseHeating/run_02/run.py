import argparse
import json
import sys
import logging
from typing import Dict, List
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Parse outdoor temperature schedule from stdin
outdoor_temps: Dict[int, float] = {}
for line in sys.stdin:
    line = line.strip()
    if line:
        time_str, temp_str = line.split()
        hours, minutes, seconds = map(int, time_str.split(':'))
        time_sec = hours * 3600 + minutes * 60 + seconds
        outdoor_temps[time_sec] = float(temp_str)

class HouseHeatingModel(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port("observation", "out"))
        self.room_temp_c = 25.0
        self.heat_loss_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.time_sec = 0

    def initialize(self):
        self.time_sec = 0
        self.room_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.heat_loss_temp_c = 25.0
        self.output["out"].add({
            "time_sec": self.time_sec,
            "room_temp_c": self.room_temp_c,
            "heat_loss_temp_c": self.heat_loss_temp_c,
            "control_signal": self.control_signal,
            "heater_output_c": self.heater_output_c
        })
        self.hold_in("WAIT", 1)

    def lambdaf(self):
        pass

    def deltint(self):
        self.time_sec += 1
        outdoor_temp = outdoor_temps.get(self.time_sec, 25.0)
        outdoor_temp = min(outdoor_temp, self.room_temp_c)
        self.heat_loss_temp_c = self.room_temp_c - 0.1 * (self.room_temp_c - outdoor_temp)
        self.heater_output_c = 0.5 if self.control_signal == 1 else 0.0
        self.room_temp_c = self.heat_loss_temp_c + self.heater_output_c
        self.control_signal = 1 if self.room_temp_c < 24.9 else 0
        self.output["out"].add({
            "time_sec": self.time_sec,
            "room_temp_c": self.room_temp_c,
            "heat_loss_temp_c": self.heat_loss_temp_c,
            "control_signal": self.control_signal,
            "heater_output_c": self.heater_output_c
        })
        self.hold_in("WAIT", 1)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, simulate_time: float):
        super().__init__(name)
        self.parent = parent
        self.house_heating_model = HouseHeatingModel(name="house_heating_model", parent=self)
        self.add_component(self.house_heating_model)
        self.add_coupling(self.house_heating_model.output["out"], self.output["out"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    root = System(name="system", parent=None, simulate_time=args.simulate_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(int(args.simulate_time))

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    main()