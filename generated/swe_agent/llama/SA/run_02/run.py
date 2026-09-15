import argparse
import sys
import json
import logging
import collections
import random

def main():
    parser = argparse.ArgumentParser(description='Airfreight Logistics Simulation')
    parser.add_argument('--duration', type=float, default=10000.0, help='Total simulation time')
    parser.add_argument('--num_aircraft', type=int, default=2, help='Number of aircraft')
    parser.add_argument('--pallet_interval', type=float, default=25.0, help='Time interval between pallet generations')
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0, help='Pallet expiration time')
    parser.add_argument('--flight_time', type=float, default=30.0, help='Flight duration')
    parser.add_argument('--unload_time', type=float, default=2.0, help='Unload time')
    parser.add_argument('--return_time', type=float, default=30.0, help='Return flight duration')
    parser.add_argument('--maintenance_time', type=float, default=10.0, help='Maintenance duration')
    args = parser.parse_args()

if __name__ == "__main__":
    main()