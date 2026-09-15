#!/usr/bin/env python3
import argparse
import sys
import json

def simulate(simulate_time, outdoor_temps):
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    observations = []
    for t in range(int(simulate_time)):
        outdoor_temp = outdoor_temps.get(t, 25.0)
        if outdoor_temp > room_temp:
            outdoor_temp = room_temp
        heat_loss_temp = room_temp - 0.1 * (room_temp - outdoor_temp)
        heater_gain = 0.5 if control_signal == 1 else 0.0
        room_temp = heat_loss_temp + heater_gain
        control_signal = 1 if room_temp < 24.9 else 0
        observation = {
            'time_sec': t + 1,
            'room_temp_c': room_temp,
            'heat_loss_temp_c': heat_loss_temp,
            'control_signal': control_signal,
            'heater_output_c': heater_gain
        }
        observations.append(observation)
    return observations

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True)
    args = parser.parse_args()
    outdoor_temps = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            timestamp, temp = line.split()
            hour, minute, second = map(int, timestamp.split(':'))
            timestamp_in_seconds = hour * 3600 + minute * 60 + second
            outdoor_temps[timestamp_in_seconds] = float(temp)
        except ValueError:
            continue
    observations = simulate(args.simulate_time, outdoor_temps)
    for observation in observations:
        print(json.dumps(observation))
if __name__ == '__main__':
    main()