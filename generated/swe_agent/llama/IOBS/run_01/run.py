import argparse
import sys
import json
import logging
import collections
import random
import simpy
import xdevs

def main():
    env = simpy.Environment()
    logging.basicConfig(level=logging.INFO)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=1000000.0)
    args = parser.parse_args()
    main()