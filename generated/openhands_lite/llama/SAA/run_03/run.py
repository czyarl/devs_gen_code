import argparse
import json
import re
import sys
from datetime import datetime, timedelta
import simpy

# Constants
SIMULATION_TIME = 1000.0  # Default max simulation time

class AlarmSystem:
    def __init__(self, env, test_name, alarm_admin_delay, authentication_delay, display_delay):
        self.env = env
        self.test_name = test_name
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.state = "Disarmed"
        self.events = []
        self.operations = []
        self.alarm_admin_busy = False

    def input_reader(self, t, port, value):
        self.events.append({"time": t, "component": "input_reader", "message": f"{port} {value}"}))
        if not self.alarm_admin_busy:
            self.alarm_admin_busy = True
            self.env.process(self.alarm_admin(t, port, value))
        else:
            self.operations.append({
                "input_time": t,
                "action": "disarm" if value == 0 else "arm",
                "completed": False,
                "completion_time": None
            })

    def alarm_admin(self, t, port, value):
        yield self.env.timeout(self.alarm_admin_delay)
        self.events.append({"time": t + self.alarm_admin_delay, "component": "alarmAdmin", "message": f"{port} {value}"}))
        self.env.process(self.authentication(t + self.alarm_admin_delay, port, value))

    def authentication(self, t, port, value):
        yield self.env.timeout(self.authentication_delay)
        state = "DisarmValid" if value == 0 else "ArmValid"
        self.events.append({"time": t + self.authentication_delay, "component": "authentication", "message": f"{port} {value}", "state": state})
        self.env.process(self.display(t + self.authentication_delay + self.display_delay, value))
        self.alarm_admin_busy = False
        self.operations.append({
            "input_time": t,
            "action": "disarm" if value == 0 else "arm",
            "completed": True,
            "completion_time": t + self.authentication_delay
        })
        if value == 0:
            self.state = "Disarmed"
        else:
            self.state = "Armed"

    def display(self, t, value):
        yield self.env.timeout(self.display_delay)
        state = "Disarmed" if value == 0 else "Armed"
        self.events.append({"time": t, "component": "display", "message": f"{value}", "state": state})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", required=True)
    parser.add_argument("--input_file")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=SIMULATION_TIME)
    args = parser.parse_args()

    env = simpy.Environment()
    alarm_system = AlarmSystem(env, args.test_name, args.alarm_admin_delay, args.authentication_delay, args.display_delay)

    if args.input_file:
        with open(args.input_file, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    match = re.match(r"(\d\d:\d\d:\d\d) (\d) (\d)", line)
                    if match:
                        t = datetime.strptime(match.group(1), "%H:%M:%S") - datetime.strptime("00:00:00", "%H:%M:%S")
                        t = t.total_seconds()
                        port = int(match.group(2))
                        value = int(match.group(3))
                        env.process(alarm_system.input_reader(t, port, value))

    env.run(until=args.max_simulation_time)

    final_state = alarm_system.state
    simulation_time = env.now
    print(json.dumps({
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": alarm_system.events,
        "operations": alarm_system.operations
    }, indent=2))

if __name__ == "__main__":
    main()