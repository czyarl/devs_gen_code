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

class Operation:
    def __init__(self, input_time: float, action: str, completed: bool, completion_time: float = None):
        self.input_time = input_time
        self.action = action
        self.completed = completed
        self.completion_time = completion_time

def parse_time(time_str: str) -> float:
    match = re.match(r'(\d+):(\d+):(\d+)', time_str)
    if match:
        hours, minutes, seconds = map(int, match.groups())
        return hours * 3600 + minutes * 60 + seconds
    else:
        raise ValueError("Invalid time format")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_name', required=True)
    parser.add_argument('--input_file')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0)
    parser.add_argument('--authentication_delay', type=float, default=2.0)
    parser.add_argument('--display_delay', type=float, default=3.0)
    parser.add_argument('--max_simulation_time', type=float, default=1000.0)
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    env = simpy.Environment()
    events: List[Event] = []
    operations: List[Operation] = []
    state = "Disarmed"
    alarm_admin_busy = False

    def input_reader():
        if args.input_file:
            with open(args.input_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        time_str, port, value = line.split()
                        time = parse_time(time_str)
                        value = int(value)
                        while env.now < time:
                            yield env.timeout(1)
                        if alarm_admin_busy:
                            operations.append(Operation(env.now, "arm" if value == 1 else "disarm", False))
                            events.append(Event(env.now, "input_reader", f"{{{PORT} {value}}}", ))
                            logging.debug(f"Ignored request at {env.now}")
                        else:
                            alarm_admin_busy = True
                            operations.append(Operation(env.now, "arm" if value == 1 else "disarm", True))
                            events.append(Event(env.now, "input_reader", f"{{{PORT} {value}}}", ))
                            env.process(alarm_admin(time, value, env))
        else:
            logging.error("No input file provided")

    def alarm_admin(time: float, value: int, env):
        yield env.timeout(args.alarm_admin_delay)
        events.append(Event(env.now, "alarmAdmin", f"{{{PORT} {value}}}", ))
        env.process(authentication(env.now, value, env))

    def authentication(time: float, value: int, env):
        yield env.timeout(args.authentication_delay)
        events.append(Event(env.now, "authentication", f"{{{PORT} {value}}}", "DisarmValid" if value == 0 else "ArmValid"))
        state = "Disarmed" if value == 0 else "Armed"
        env.process(display(env.now, state, env))
        alarm_admin_busy = False

    def display(time: float, state: str, env):
        yield env.timeout(args.display_delay)
        events.append(Event(env.now, "display", f"{{{PORT} {value}}}", state))

    env.process(input_reader())
    try:
        while env.now < args.max_simulation_time:
            yield env.timeout(1)
    except simpy.Interrupt:
        pass

    events.sort(key=lambda x: x.time)
    final_state = state
    simulation_time = env.now

    output = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": [{"time": e.time, "component": e.component, "message": e.message, "state": e.state} for e in events],
        "operations": [{"input_time": o.input_time, "action": o.action, "completed": o.completed, "completion_time": o.completion_time} for o in operations]
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()