import argparse
import sys
import json
import logging
import collections
import random
import simpy
import xdevs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=10000)
    args = parser.parse_args()
    print(f'Simulation time: {args.simulation_time}')

if __name__ == '__main__':
    main()