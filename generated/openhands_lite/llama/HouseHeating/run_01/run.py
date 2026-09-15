#!/usr/bin/env python3
import argparse
import sys
import json

def simulate(simulate_time, outdoor_temps):
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    time_sec = 0
    while time_sec < int(simulate_time):
        time_sec += 1
        outdoor_temp = outdoor_temps.get(time_sec, 25.0)
        if outdoor_temp > room_temp:
            outdoor_temp = room_temp
        heat_loss_temp = room_temp - 0.1 * (room_temp - outdoor_temp)
        heater_output = 0.5 if control_signal == 1 else 0.0
        room_temp = heat_loss_temp + heater_output
        control_signal = 1 if room_temp < 24.9 else 0
        print(json.dumps({
            'time_sec': time_sec,
            'room_temp_c': room_temp,
            'heat_loss_temp_c': heat_loss_temp,
            'control_signal': control_signal,
            'heater_output_c': heater_output
        }))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True)
    args = parser.parse_args()
    outdoor_temps = {}
    for line in sys.stdin:
        line = line.strip()
        if line:
            timestamp, temp = line.split()
            hour, minute, second = map(int, timestamp.split(':'))
            time_sec = hour * 3600 + minute * 60 + second
            outdoor_temps[time_sec] = float(temp)
    simulate(args.simulate_time, outdoor_temps)

if __name__ == '__main__':
    main()