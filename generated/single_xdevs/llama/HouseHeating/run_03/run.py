import argparse
import json
import logging
import sys
from typing import Dict

import numpy as np
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

class OutdoorTemperatureSource(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(float, "outdoor_temperature"))
        self.temps: Dict[int, float] = {}
        self.time = 0

    def initialize(self):
        for line in sys.stdin:
            line = line.strip()
            if line:
                time_str, temp_str = line.split()
                hours, minutes, seconds = map(int, time_str.split(':'))
                time_in_seconds = hours * 3600 + minutes * 60 + seconds
                self.temps[time_in_seconds] = float(temp_str)
        self.hold_in("INIT", 0)

    def lambdaf(self):
        temp = 25.0
        for t, value in self.temps.items():
            if t <= self.time:
                temp = value
            else:
                break
        self.output["outdoor_temperature"].add(temp)

    def deltint(self):
        self.time += 1
        self.hold_in("WAIT", 1)

    def deltext(self, e):
        self.hold_in("WAIT", 1)

    def exit(self):
        pass

class HeaterController(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "room_temperature"))
        self.add_out_port(Port(int, "control_signal"))
        self.target_temperature = 24.9
        self.control_signal = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        self.output["control_signal"].add(self.control_signal)

    def deltint(self):
        room_temperature = self.input["room_temperature"].last()
        if room_temperature < self.target_temperature:
            self.control_signal = 1
        else:
            self.control_signal = 0
        self.hold_in("WAIT", 1)

    def deltext(self, e):
        self.hold_in("WAIT", 1)

    def exit(self):
        pass

class HouseModel(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "outdoor_temperature"))
        self.add_in_port(Port(int, "control_signal"))
        self.add_out_port(Port(Dict[str, float], "state"))
        self.room_temperature = 25.0
        self.heat_loss_temperature = 25.0
        self.heater_output = 0.0
        self.control_signal = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        state = {
            "time_sec": self.time,
            "room_temp_c": self.room_temperature,
            "heat_loss_temp_c": self.heat_loss_temperature,
            "control_signal": self.control_signal,
            "heater_output_c": self.heater_output
        }
        self.output["state"].add(state)

    def deltint(self):
        outdoor_temperature = self.input["outdoor_temperature"].last()
        effective_outdoor_temperature = min(outdoor_temperature, self.room_temperature)
        self.heat_loss_temperature = self.room_temperature - 0.1 * (self.room_temperature - effective_outdoor_temperature)
        self.room_temperature = self.heat_loss_temperature + self.heater_output
        self.heater_output = 0.5 if self.control_signal == 1 else 0.0
        self.time += 1
        self.hold_in("WAIT", 1)

    def deltext(self, e):
        if "control_signal" in self.input:
            self.control_signal = self.input["control_signal"].last()
        self.hold_in("WAIT", 1)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, simulate_time: float):
        super().__init__(name)
        self.parent = parent
        self.add_component(OutdoorTemperatureSource(name="outdoor_source", parent=self))
        self.add_component(HeaterController(name="heater_controller", parent=self))
        self.add_component(HouseModel(name="house", parent=self))
        self.add_coupling(self.components["outdoor_source"].output["outdoor_temperature"], self.components["house"].input["outdoor_temperature"])
        self.add_coupling(self.components["house"].output["state"], self.output["state"])
        self.add_coupling(self.components["house"].input["control_signal"], self.components["heater_controller"].input["room_temperature"])
        self.add_coupling(self.components["heater_controller"].output["control_signal"], self.components["house"].input["control_signal"])
        self.simulate_time = simulate_time

    def __str__(self):
        return f"System(simulate_time={self.simulate_time})"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    root = System(name="system", parent=None, simulate_time=args.simulate_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()