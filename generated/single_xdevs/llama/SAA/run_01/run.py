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
        self.add_out_port(Port(str, "output"))

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
                if line:
                    time_str, port, value = line.split()
                    hours, minutes, seconds = map(int, time_str.split(':'))
                    time = hours * 3600 + minutes * 60 + seconds
                    self.output["output"].add(f"{{{port} {value}}}")
                    logging.debug(f"Input at {time}: {port} {value}")

class AlarmAdmin(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(str, "input"))
        self.add_out_port(Port(str, "output"))
        self.busy = False

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        if self.busy:
            self.output["output"].add("")

    def deltint(self):
        self.busy = False
        self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        if not self.busy:
            for msg in self.input["input"].values:
                port, value = msg.split()
                self.busy = True
                self.output["output"].add(f"{{{port} {value}}}")
                logging.debug(f"AlarmAdmin output: {port} {value}")
                self.hold_in("BUSY", self.delay)

class Authentication(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(str, "input"))
        self.add_out_port(Port(Dict, "output"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for msg in self.input["input"].values:
            port, value = msg.split()
            state = {"disarm": "DisarmValid", "arm": "ArmValid"}[value]
            self.output["output"].add({"state": state})
            logging.debug(f"Authentication output: {state}")
            self.hold_in("IDLE", self.delay)

class Display(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(Dict, "input"))
        self.add_out_port(Port(Dict, "output"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for msg in self.input["input"].values:
            state = msg["state"]
            self.output["output"].add({"state": state})
            logging.debug(f"Display output: {state}")
            self.hold_in("IDLE", self.delay)

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
        "final_state": "Armed",  # or "Disarmed"
        "events": events,
        "operations": operations
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()