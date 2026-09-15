import argparse
import json
import logging
import sys
from typing import List, Dict

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

class InputReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file
        self.add_out_port(Port(int, "output"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        pass

    def exit(self):
        with open(self.input_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                time = parts[0].split(":")
                hours, minutes, seconds = map(int, time)
                time_in_seconds = hours * 3600 + minutes * 60 + seconds
                port = int(parts[1])
                value = int(parts[2])
                self.output["output"].add((time_in_seconds, port, value))
        self.hold_in("WAIT", float('inf'))

class AlarmAdmin(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(tuple, "input"))
        self.add_out_port(Port(tuple, "output"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.input["input"].has_value():
            time, port, value = self.input["input"].get_value()
            self.output["output"].add((time, port, value))
            self.hold_in("PROCESSING", self.delay)

    def exit(self):
        pass

class Authentication(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(tuple, "input"))
        self.add_out_port(Port(tuple, "output"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.input["input"].has_value():
            time, port, value = self.input["input"].get_value()
            state = "DisarmValid" if value == 0 else "ArmValid"
            self.output["output"].add((time, port, state))
            self.hold_in("WAIT", self.delay)

    def exit(self):
        pass

class Display(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(tuple, "input"))
        self.add_out_port(Port(tuple, "output"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.input["input"].has_value():
            time, port, state = self.input["input"].get_value()
            self.output["output"].add((time, port, state))
            self.hold_in("WAIT", self.delay)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, input_file: str, alarm_admin_delay: float, authentication_delay: float, display_delay: float):
        super().__init__(name)
        self.parent = parent
        self.input_reader = InputReader(name="input_reader", parent=self, input_file=input_file)
        self.alarm_admin = AlarmAdmin(name="alarm_admin", parent=self, delay=alarm_admin_delay)
        self.authentication = Authentication(name="authentication", parent=self, delay=authentication_delay)
        self.display = Display(name="display", parent=self, delay=display_delay)
        self.add_component(self.input_reader)
        self.add_component(self.alarm_admin)
        self.add_component(self.authentication)
        self.add_component(self.display)
        self.add_coupling(self.input_reader.output["output"], self.alarm_admin.input["input"])
        self.add_coupling(self.alarm_admin.output["output"], self.authentication.input["input"])
        self.add_coupling(self.authentication.output["output"], self.display.input["input"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = parser.parse_args()

    root = System(name="system", parent=None, input_file=args.input_file, alarm_admin_delay=args.alarm_admin_delay, authentication_delay=args.authentication_delay, display_delay=args.display_delay)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.max_simulation_time)

    events = []
    operations = []

    # Collect events and operations
    # ...

    output = {
        "test_name": args.test_name,
        "simulation_time": args.max_simulation_time,
        "initial_state": "Disarmed",
        "final_state": "Armed",  # Replace with actual final state
        "events": events,
        "operations": operations
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()