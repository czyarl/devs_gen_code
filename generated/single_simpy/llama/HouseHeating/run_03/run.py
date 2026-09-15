import argparse
import json
import logging
import sys
import time
from datetime import datetime

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

def parse_outdoor_temperature_schedule(stdin):
    schedule = {}
    for line in stdin:
        line = line.strip()
        if line:
            timestamp_str, temp_str = line.split()
            timestamp = datetime.strptime(timestamp_str, '%H:%M:%S')
            timestamp = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
            schedule[timestamp] = float(temp_str)
    return schedule

def get_effective_outdoor_temperature(schedule, t, current_room_temp):
    effective_temp = 25.0
    for timestamp in sorted(schedule.keys()):
        if timestamp <= t:
            effective_temp = schedule[timestamp]
    if effective_temp > current_room_temp:
        effective_temp = current_room_temp
    return effective_temp

def simulate(simulate_time, outdoor_temperature_schedule):
    room_temp_c = 25.0
    control_signal = 0
    heater_output_c = 0.0
    for t in range(int(simulate_time)):
        effective_outdoor_temp = get_effective_outdoor_temperature(outdoor_temperature_schedule, t, room_temp_c)
        heat_loss_temp_c = room_temp_c - 0.1 * (room_temp_c - effective_outdoor_temp)
        next_control_signal = 1 if room_temp_c < 24.9 else 0
        next_heater_output_c = 0.5 if control_signal == 1 else 0.0
        next_room_temp_c = heat_loss_temp_c + next_heater_output_c
        
        print(json.dumps({
            "time_sec": t + 1,
            "room_temp_c": room_temp_c,
            "heat_loss_temp_c": heat_loss_temp_c,
            "control_signal": control_signal,
            "heater_output_c": heater_output_c
        }))
        
        room_temp_c = next_room_temp_c
        control_signal = next_control_signal
        heater_output_c = next_heater_output_c

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True)
    args = parser.parse_args()
    
    outdoor_temperature_schedule = parse_outdoor_temperature_schedule(sys.stdin)
    simulate(args.simulate_time, outdoor_temperature_schedule)

if __name__ == "__main__":
    main()