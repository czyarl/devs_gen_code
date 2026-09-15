```python
import argparse
import json
import logging
import sys
import time

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

def parse_outdoor_temperature_schedule(stdin):
    schedule = {}
    for line in stdin:
        line = line.strip()
        if line:
            timestamp, temp = line.split()
            hours, minutes, seconds = map(int, timestamp.split(':'))
            timestamp_sec = hours * 3600 + minutes * 60 + seconds
            schedule[timestamp_sec] = float(temp)
    return schedule

def get_effective_outdoor_temperature(schedule, t):
    if not schedule:
        return 25.0
    effective_temp = 25.0
    for timestamp_sec, temp in schedule.items():
        if timestamp_sec <= t:
            effective_temp = temp
    return effective_temp

def simulate_house_heating(simulate_time, outdoor_temperature_schedule):
    room_temp_c = 25.0
    control_signal = 0
    heater_output_c = 0.0
    observations = []

    for t in range(int(simulate_time)):
        effective_outdoor_temp = get_effective_outdoor_temperature(outdoor_temperature_schedule, t)
        if effective_outdoor_temp > room_temp_c:
            effective_outdoor_temp = room_temp_c
        heat_loss_temp_c = room_temp_c - 0.1 * (room_temp_c - effective_outdoor_temp)
        
        if control_signal == 1:
            heater_output_c = 0.5
        else:
            heater_output_c = 0.0

        room_temp_c = heat_loss_temp_c + heater_output_c

        control_signal = 1 if room_temp_c < 24.9 else 0

        observation = {
            "time_sec": t + 1,
            "room_temp_c": room_temp_c,
            "heat_loss_temp_c": heat_loss_temp_c,
            "control_signal": control_signal,
            "heater_output_c": heater_output_c
        }
        observations.append(observation)

    return observations

def main():
    parser = argparse.ArgumentParser(description='House Heating Temperature Control Simulation')
    parser.add_argument('--simulate_time', type=float, required=True, help='Total simulation duration in seconds')
    args = parser.parse_args()

    outdoor_temperature_schedule = parse_outdoor_temperature_schedule(sys.stdin)
    observations = simulate_house_heating(args.simulate_time, outdoor_temperature_schedule)

    for observation in observations:
        print(json.dumps(observation))

if __name__ == "__main__":
    start_time = time.time()
    main()
    logging.debug(f"Simulation finished in {time.time() - start_time} seconds")
</python_code>
```