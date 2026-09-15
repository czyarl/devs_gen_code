import argparse
import json
import sys
import simpy

def simulate(test_name, input_file, alarm_admin_delay, authentication_delay, display_delay, max_simulation_time):
    # Simulation logic here
    pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_name', required=True)
    parser.add_argument('--input_file', required=True)
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0)
    parser.add_argument('--authentication_delay', type=float, default=2.0)
    parser.add_argument('--display_delay', type=float, default=3.0)
    parser.add_argument('--max_simulation_time', type=float, default=1000.0)
    args = parser.parse_args()
    simulate(**vars(args))