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

    def initialize(self):
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                continue
            timestamp = parts[0]
            hour, minute, second = map(int, timestamp.split(':'))
            time_sec = hour * 3600 + minute * 60 + second
            temp = float(parts[1])
            self.temps[time_sec] = temp
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        pass

    def exit(self):
        pass

    def get_temperature(self, time_sec: int) -> float:
        temps = {t: temp for t, temp in self.temps.items() if t <= time_sec}
        if temps:
            latest_time = max(temps.keys())
            return temps[latest_time]
        return 25.0


class HeaterController(Atomic):
    def __init__(self, name: str, parent: Coupled | None, target_temperature: float):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "room_temperature"))
        self.add_out_port(Port(int, "control_signal"))
        self.target_temperature = target_temperature
        self.control_signal = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        self.output["control_signal"].add(self.control_signal)

    def deltint(self):
        self.hold_in("WAIT", 1)

    def deltext(self, e):
        if self.input["room_temperature"].has_value():
            room_temperature = self.input["room_temperature"].get_value()
            self.control_signal = 1 if room_temperature < self.target_temperature else 0
        self.hold_in("WAIT", 1)

    def exit(self):
        pass


class Room(Atomic):
    def __init__(self, name: str, parent: Coupled | None, initial_temperature: float):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "outdoor_temperature"))
        self.add_in_port(Port(int, "control_signal"))
        self.add_in_port(Port(float, "heater_output"))
        self.add_out_port(Port(float, "room_temperature"))
        self.add_out_port(Port(float, "heat_loss_temp_c"))
        self.add_out_port(Port(int, "control_signal_out"))
        self.add_out_port(Port(float, "heater_output_c"))
        self.temperature = initial_temperature
        self.heat_loss_temp_c = initial_temperature
        self.control_signal = 0
        self.heater_output_c = 0.0

    def initialize(self):
        self.output["room_temperature"].add(self.temperature)
        self.output["heat_loss_temp_c"].add(self.temperature)
        self.output["control_signal_out"].add(0)
        self.output["heater_output_c"].add(0.0)
        self.hold_in("INIT", 1)

    def lambdaf(self):
        self.output["room_temperature"].add(self.temperature)
        self.output["heat_loss_temp_c"].add(self.heat_loss_temp_c)
        self.output["control_signal_out"].add(self.control_signal)
        self.output["heater_output_c"].add(self.heater_output_c)

    def deltint(self):
        self.hold_in("WAIT", 1)

    def deltext(self, e):
        if self.input["outdoor_temperature"].has_value():
            outdoor_temperature = min(self.input["outdoor_temperature"].get_value(), self.temperature)
            self.heat_loss_temp_c = self.temperature - 0.1 * (self.temperature - outdoor_temperature)
        if self.input["control_signal"].has_value():
            self.control_signal = self.input["control_signal"].get_value()
            self.heater_output_c = 0.5 if self.control_signal == 1 else 0.0
            self.temperature = self.heat_loss_temp_c + self.heater_output_c
        if self.input["heater_output"].has_value():
            self.heater_output_c = self.input["heater_output"].get_value()
            self.temperature = self.heat_loss_temp_c + self.heater_output_c
        self.hold_in("WAIT", 1)

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, simulate_time: float, target_temperature: float):
        super().__init__(name)
        self.parent = parent
        self.outdoor_source = OutdoorTemperatureSource(name="outdoor_source", parent=self)
        self.heater_controller = HeaterController(name="heater_controller", parent=self, target_temperature=target_temperature)
        self.room = Room(name="room", parent=self, initial_temperature=25.0)
        self.add_component(self.outdoor_source)
        self.add_component(self.heater_controller)
        self.add_component(self.room)
        self.add_coupling(self.outdoor_source.output["outdoor_temperature"], self.room.input["outdoor_temperature"])
        self.add_coupling(self.room.output["room_temperature"], self.heater_controller.input["room_temperature"])
        self.add_coupling(self.heater_controller.output["control_signal"], self.room.input["control_signal"])
        self.simulate_time = simulate_time

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()

    with System(name="system", parent=None, simulate_time=args.simulate_time, target_temperature=24.9) as root:
        coord = Coordinator(root, clock=SimulationClock(0))
        coord.initialize()
        for time_sec in range(1, int(args.simulate_time) + 1):
            coord.simulate_time(1)
            state = {
                "time_sec": time_sec,
                "room_temp_c": root.room.temperature,
                "heat_loss_temp_c": root.room.heat_loss_temp_c,
                "control_signal": root.room.control_signal,
                "heater_output_c": root.room.heater_output_c
            }
            print(json.dumps(state), file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()