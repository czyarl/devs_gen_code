import argparse
import sys
import json

def simulate_room_temperature(simulate_time, outdoor_temperatures):
    room_temperature = 25.0
    control_signal = 0
    heater_output = 0.0
    observations = []

    for t in range(int(simulate_time)):
        outdoor_temperature = outdoor_temperatures.get(t, 25.0)
        outdoor_temperature = min(outdoor_temperature, room_temperature)
        heat_loss_temperature = room_temperature - 0.1 * (room_temperature - outdoor_temperature)
        heater_gain = 0.5 if control_signal == 1 else 0.0
        room_temperature = heat_loss_temperature + heater_gain
        control_signal = 1 if room_temperature < 24.9 else 0

        observations.append({
            "time_sec": t + 1,
            "room_temp_c": room_temperature,
            "heat_loss_temp_c": heat_loss_temperature,
            "control_signal": control_signal,
            "heater_output_c": heater_gain
        })

    return observations

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True)
    args = parser.parse_args()

    outdoor_temperatures = {}
    for line in sys.stdin:
        line = line.strip()
        if line:
            timestamp, temperature = line.split()
            hours, minutes, seconds = map(int, timestamp.split(':'))
            timestamp_in_seconds = hours * 3600 + minutes * 60 + seconds
            outdoor_temperatures[timestamp_in_seconds] = float(temperature)

    observations = simulate_room_temperature(args.simulate_time, outdoor_temperatures)

    for observation in observations:
        print(json.dumps(observation))

if __name__ == '__main__':
    main()