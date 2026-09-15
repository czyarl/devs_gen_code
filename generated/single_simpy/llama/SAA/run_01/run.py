import argparse
import json
import logging
import math
import re
import simpy
import sys
from typing import List, Dict

# Constants
ENV = simpy.Environment()
TEST_NAME = ""
INPUT_FILE = ""
ALARM_ADMIN_DELAY = 10.0
AUTHENTICATION_DELAY = 2.0
DISPLAY_DELAY = 3.0
MAX_SIMULATION_TIME = 1000.0

# Event and Operation types
EVENT_TYPES = ["input_reader", "alarmAdmin", "authentication", "display"]
OPERATION_TYPES = ["disarm", "arm"]

class Event:
    def __init__(self, time: float, component: str, message: str, state: str = None):
        self.time = time
        self.component = component
        self.message = message
        self.state = state

    def to_dict(self):
        event_dict = {"time": self.time, "component": self.component, "message": self.message}
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
        operation_dict = {"input_time": self.input_time, "action": self.action, "completed": self.completed}
        if self.completion_time is not None:
            operation_dict["completion_time"] = self.completion_time
        return operation_dict

def parse_time(time_str: str) -> float:
    hours, minutes, seconds = map(int, time_str.split(':'))
    return hours * 3600 + minutes * 60 + seconds

def main():
    global TEST_NAME, INPUT_FILE, ALARM_ADMIN_DELAY, AUTHENTICATION_DELAY, DISPLAY_DELAY, MAX_SIMULATION_TIME

    parser = argparse.ArgumentParser(description='Secure Area Access Control Simulation')
    parser.add_argument('--test_name', type=str, required=True)
    parser.add_argument('--input_file', type=str)
    parser.add_argument('--alarm_admin_delay', type=float, default=ALARM_ADMIN_DELAY)
    parser.add_argument('--authentication_delay', type=float, default=AUTHENTICATION_DELAY)
    parser.add_argument('--display_delay', type=float, default=DISPLAY_DELAY)
    parser.add_argument('--max_simulation_time', type=float, default=MAX_SIMULATION_TIME)

    args = parser.parse_args()

    TEST_NAME = args.test_name
    INPUT_FILE = args.input_file
    ALARM_ADMIN_DELAY = args.alarm_admin_delay
    AUTHENTICATION_DELAY = args.authentication_delay
    DISPLAY_DELAY = args.display_delay
    MAX_SIMULATION_TIME = args.max_simulation_time

    # Initialize logging
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    # Read input file
    try:
        with open(INPUT_FILE, 'r') as f:
            input_lines = f.readlines()
    except FileNotFoundError:
        logging.error(f"Input file {INPUT_FILE} not found.")
        return

    # Parse input lines
    input_requests = []
    for line in input_lines:
        line = line.strip()
        if not line:
            continue
        match = re.match(r'(\d\d:\d\d:\d\d) 0 (\d)', line)
        if match:
            time_str, value = match.groups()
            input_time = parse_time(time_str)
            input_requests.append((input_time, int(value)))
        else:
            logging.warning(f"Ignoring invalid input line: {line}")

    # Simulation
    env = simpy.Environment()
    events: List[Event] = []
    operations: List[Operation] = []
    state = "Disarmed"
    alarm_admin_busy = False

    def process_input_request(input_time: float, value: int):
        nonlocal alarm_admin_busy, state
        event = Event(input_time, "input_reader", f"{{{0} {value}}}")
        events.append(event)

        if alarm_admin_busy:
            operations.append(Operation(input_time, OPERATION_TYPES[value], False))
            return

        alarm_admin_busy = True
        action = OPERATION_TYPES[value]

        # AlarmAdmin
        alarm_admin_time = input_time + ALARM_ADMIN_DELAY
        alarm_admin_event = Event(alarm_admin_time, "alarmAdmin", f"{{{0} {value}}}")
        events.append(alarm_admin_event)

        # Authentication
        authentication_time = alarm_admin_time + AUTHENTICATION_DELAY
        authentication_state = f"DisarmValid" if value == 0 else "ArmValid"
        authentication_event = Event(authentication_time, "authentication", f"{{{0} {value}}}", authentication_state)
        events.append(authentication_event)

        # Display
        display_time = authentication_time + DISPLAY_DELAY
        display_state = "Disarmed" if value == 0 else "Armed"
        display_event = Event(display_time, "display", f"{{{0} {value}}}", display_state)
        events.append(display_event)

        # Update state and operation
        state = display_state
        operations.append(Operation(input_time, action, True, authentication_time))
        alarm_admin_busy = False

    for input_time, value in input_requests:
        env.process(process_input_request(input_time, value))

    # Run simulation
    simpy_time = 0.0
    while simpy_time < MAX_SIMULATION_TIME:
        simpy_time = env.now
        if simpy_time >= MAX_SIMULATION_TIME:
            break
        env.step()

    # Output
    final_state = state
    output = {
        "test_name": TEST_NAME,
        "simulation_time": simpy_time,
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": [event.to_dict() for event in sorted(events, key=lambda x: x.time)],
        "operations": [operation.to_dict() for operation in sorted(operations, key=lambda x: x.input_time)]
    }

    print(json.dumps(output))

if __name__ == "__main__":
    main()