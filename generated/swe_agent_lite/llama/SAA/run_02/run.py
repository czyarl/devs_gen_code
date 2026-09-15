import argparse
import json
import sys
from datetime import datetime
import simpy

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_name', required=True)
    parser.add_argument('--input_file')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0)
    parser.add_argument('--authentication_delay', type=float, default=2.0)
    parser.add_argument('--display_delay', type=float, default=3.0)
    parser.add_argument('--max_simulation_time', type=float, default=1000.0)
    return parser.parse_args()

def parse_input_file(input_file):
    requests = []
    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            timestamp = datetime.strptime(parts[0], '%H:%M:%S')
            requests.append((timestamp, int(parts[1]), int(parts[2])))
    return requests

def simulate(env, requests, alarm_admin_delay, authentication_delay, display_delay):
    state = 'Disarmed'
    events = []
    operations = []
    alarm_admin_busy = False

    for timestamp, port, value in requests:
        if alarm_admin_busy:
            operations.append({'input_time': timestamp, 'action': 'disarm' if value == 0 else 'arm', 'completed': False, 'completion_time': None})
            continue

        alarm_admin_busy = True
        env.process(alarm_admin(env, timestamp, port, value, alarm_admin_delay, authentication_delay, display_delay, state, events, operations))

    yield env.timeout(max_simulation_time)
    final_state = state
    return events, operations, state, env.now

def alarm_admin(env, timestamp, port, value, alarm_admin_delay, authentication_delay, display_delay, state, events, operations):
    events.append({'time': env.now, 'component': 'input_reader', 'message': f'{port} {value}'})
    operations.append({'input_time': timestamp, 'action': 'disarm' if value == 0 else 'arm', 'completed': True, 'completion_time': env.now + alarm_admin_delay + authentication_delay})

    yield env.timeout(alarm_admin_delay)
    events.append({'time': env.now, 'component': 'alarmAdmin', 'message': f'{port} {value}'})

    auth_state = 'DisarmValid' if value == 0 else 'ArmValid'
    yield env.timeout(authentication_delay)
    events.append({'time': env.now, 'component': 'authentication', 'message': f'{port} {value}', 'state': auth_state})

    if auth_state == 'DisarmValid':
        state = 'Disarmed'
    else:
        state = 'Armed'

    yield env.timeout(display_delay)
    events.append({'time': env.now, 'component': 'display', 'message': f'{port} {value}', 'state': state})

def main():
    args = parse_args()
    if args.input_file:
        requests = parse_input_file(args.input_file)
    else:
        requests = []

    env = simpy.Environment()
    events, operations, final_state, simulation_time = env.run(until=simulate(env, requests, args.alarm_admin_delay, args.authentication_delay, args.display_delay))

    output = {
        'test_name': args.test_name,
        'simulation_time': simulation_time,
        'initial_state': 'Disarmed',
        'final_state': final_state,
        'events': events,
        'operations': operations
    }
    print(json.dumps(output))

if __name__ == '__main__':
    main()