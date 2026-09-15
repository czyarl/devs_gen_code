import argparse
import sys
import json

def simulate_room_temperature(outdoor_temps, simulate_time):
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    for t in range(int(simulate_time)):
        # Apply heat loss
        effective_outdoor_temp = outdoor_temps.get(t, 25.0)
        if effective_outdoor_temp > room_temp:
            effective_outdoor_temp = room_temp
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)

        # Apply heater gain
        if control_signal == 1:
            heater_output = 0.5
        else:
            heater_output = 0.0
        room_temp = heat_loss_temp + heater_output

        # Update control signal
        if room_temp < 24.9:
            control_signal = 1
        else:
            control_signal = 0

        # Print JSONL record
        print(json.dumps({
            'time_sec': t + 1,
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
            timestamp_in_seconds = hour * 3600 + minute * 60 + second
            outdoor_temps[timestamp_in_seconds] = float(temp)

    simulate_room_temperature(outdoor_temps, args.simulate_time)

if __name__ == '__main__':
    main()