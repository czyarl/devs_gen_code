import argparse
import sys
import json
import logging
import collections
import random
import xdevs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=float, default=10000.0)
    parser.add_argument('--num_aircraft', type=int, default=2)
    parser.add_argument('--pallet_interval', type=float, default=25.0)
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0)
    parser.add_argument('--flight_time', type=float, default=30.0)
    parser.add_argument('--unload_time', type=float, default=2.0)
    parser.add_argument('--return_time', type=float, default=30.0)
    parser.add_argument('--maintenance_time', type=float, default=10.0)
    args = parser.parse_args()

    # Simulation code here
    print(json.dumps({
        "time": 0.0,
        "entity": "facility",
        "event": "pallet_generated",
        "payload": {
            "pallet_id": 1,
            "expiration_time": 10.0
        }
    }))
if __name__ == '__main__':
    main()