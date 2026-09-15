import argparse
import sys
import json
import simpy

SIMULATION_TIME = 1000000.0

def reception_desk(env, reception_queue, checkhair_phase):
    pass

def hair_inspection_phase(env, reception_queue, cuthair_phase):
    pass

def hair_cutting_phase(env, cuthair_phase):
    pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=SIMULATION_TIME)
    args = parser.parse_args()

    env = simpy.Environment()
    reception_queue = simpy.Store(env)
    checkhair_phase = simpy.Resource(env)
    cuthair_phase = simpy.Resource(env)

    env.process(reception_desk(env, reception_queue, checkhair_phase))
    env.process(hair_inspection_phase(env, reception_queue, cuthair_phase))
    env.process(hair_cutting_phase(env, cuthair_phase))

    env.run(until=args.simulation_time)

if __name__ == '__main__':
    main()