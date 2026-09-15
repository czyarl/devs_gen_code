import argparse
import json
import sys
from datetime import datetime
import simpy

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_name', type=str, required=True)
    parser.add_argument('--input_file', type=str, required=True)
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0)
    parser.add_argument('--authentication_delay', type=float, default=2.0)
    parser.add_argument('--display_delay', type=float, default=3.0)
    parser.add_argument('--max_simulation_time', type=float, default=1000.0)
    return parser.parse_args()

def convert_time_to_seconds(time_str):
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def simulate(alarm_admin_delay, authentication_delay, display_delay, max_simulation_time, input_file):
    env = simpy.Environment()
    events = []
    operations = []
    state = "Disarmed"
    alarm_admin_busy = False

    def input_reader():
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    time_str, port, value = line.split()
                    input_time = convert_time_to_seconds(time_str)
                    while env.now < input_time:
                        yield env.timeout(0.01)
                    if alarm_admin_busy:
                        operations.append({
                            'input_time': input_time,
                            'action': 'disarm' if int(value) == 0 else 'arm',
                            'completed': False,
                            'completion_time': None
                        })
                    else:
                        alarm_admin_busy = True
                        events.append({
                            'time': env.now,
                            'component': 'input_reader',
                            'message': f'{{{port} {value}}}'
                        })
                        env.process(alarm_admin(input_time, int(value), alarm_admin_delay, authentication_delay, display_delay))

    def alarm_admin(input_time, value, alarm_admin_delay, authentication_delay, display_delay):
        yield env.timeout(alarm_admin_delay)
        events.append({
            'time': env.now,
            'component': 'alarmAdmin',
            'message': f'{{{0} {value}}}'
        })
        auth_value = 'DisarmValid' if value == 0 else 'ArmValid'
        yield env.timeout(authentication_delay)
        events.append({
            'time': env.now,
            'component': 'authentication',
            'message': f'{{{0} {value}}}' ,
            'state': auth_value
        })
        display_value = 'Disarmed' if value == 0 else 'Armed'
        state = display_value
        yield env.timeout(display_delay)
        events.append({
            'time': env.now,
            'component': 'display',
            'message': f'{{{0} {value}}}' ,
            'state': display_value
        })
        operations.append({
            'input_time': input_time,
            'action': 'disarm' if value == 0 else 'arm',
            'completed': True,
            'completion_time': env.now
        })
        alarm_admin_busy = False

    env.process(input_reader())
    try:
        while True:
            if env.now > max_simulation_time:
                break
            yield env.timeout(0.01)
    except simpy.Interrupt:
        pass

    output = {
        'test_name': args.test_name,
        'simulation_time': env.now,
        'initial_state': 'Disarmed',
        'final_state': state,
        'events': events,
        'operations': operations
    }

    print(json.dumps(output))

if __name__ == "__main__":
    args = parse_args()
    simulate(**vars(args))