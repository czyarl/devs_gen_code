import argparse
import json
import logging
import math
import re
import simpy
import sys
from typing import List, Dict

# Constants
PORT = 0

class Event:
    def __init__(self, time: float, component: str, message: str, state: str = None):
        self.time = time
        self.component = component
        self.message = message
        self.state = state

    def to_dict(self):
        event_dict = {
            "time": self.time,
            "component": self.component,
            "message": self.message,
        }
        if self.state:
            event_dict["state"] = self.state
        return event_dict

class Operation:
    def __init__(self, input_time: float, action: str, completed: bool, completion_time: float = None):
        self.input_time = input_time
        self.action = action
        self.completed = completed
        self.completion_time = completion_time

    def to_dict(self):
        operation_dict = {
            "input_time": self.input_time,
            "action": self.action,
            "completed": self.completed,
        }
        if self.completion_time is not None:
            operation_dict["completion_time"] = self.completion_time
        return operation_dict

def parse_time(time_str: str) -> float:
    match = re.match(r"(\d+):(\d+):(\d+)", time_str)
    if match:
        hours, minutes, seconds = map(int, match.groups())
        return hours * 3600 + minutes * 60 + seconds
    else:
        raise ValueError("Invalid time format")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    env = simpy.Environment()
    events: List[Event] = []
    operations: List[Operation] = []
    state = "Disarmed"
    alarm_admin_busy = False

    def input_reader():
        if args.input_file:
            with open(args.input_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        time_str, port, value = line.split()
                        input_time = parse_time(time_str)
                        value = int(value)
                        events.append(Event(input_time, "input_reader", f"{{{PORT} {value}}}"))
                        env.process(process_input(input_time, value))
        else:
            logging.error("Input file not provided")

    def process_input(input_time: float, value: int):
        nonlocal alarm_admin_busy, state
        if alarm_admin_busy:
            return
        alarm_admin_busy = True
        action = "disarm" if value == 0 else "arm"
        operations.append(Operation(input_time, action, True))
        env.process(alarm_admin(input_time, value))

    def alarm_admin(input_time: float, value: int):
        nonlocal alarm_admin_busy, state
        yield env.timeout(args.alarm_admin_delay)
        events.append(Event(env.now, "alarmAdmin", f"{{{PORT} {value}}}", None))
        env.process(authentication(input_time, value))

    def authentication(input_time: float, value: int):
        nonlocal alarm_admin_busy, state
        state = "Disarmed" if value == 0 else "Armed"
        yield env.timeout(args.authentication_delay)
        events.append(Event(env.now, "authentication", f"{{{PORT} {value}}}", "DisarmValid" if value == 0 else "ArmValid"))
        env.process(display(input_time, value))

    def display(input_time: float, value: int):
        nonlocal alarm_admin_busy
        yield env.timeout(args.display_delay)
        events.append(Event(env.now, "display", f"{{{PORT} {value}}}", state))
        alarm_admin_busy = False

    env.process(input_reader())
    try:
        while env.now < args.max_simulation_time:
            env.step()
    except simpy.Interrupt:
        pass

    final_state = state
    simulation_time = env.now

    output = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": sorted([event.to_dict() for event in events], key=lambda x: x["time"]),
        "operations": sorted([operation.to_dict() for operation in operations], key=lambda x: x["input_time"]),
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()