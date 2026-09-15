import argparse
import sys
import json
import logging
from collections import defaultdict
import random
import simpy
import numpy as np
from scipy.integrate import odeint

# CLI Arguments
parser = argparse.ArgumentParser(description='SEIRD Epidemic Compartmental Model')
parser.add_argument('--test_name', type=str, required=True, help='Name of the test case being run')
parser.add_argument('--mortality', type=float, default=10.0, help='Mortality rate as percentage (0-100)')
parser.add_argument('--infectivity_period', type=float, default=14.0, help='Average days a person stays infectious')
parser.add_argument('--dt', type=float, default=0.1, help='Time step for numerical integration in days')
parser.add_argument('--incubation_period', type=float, default=5.0, help='Average days from exposure to becoming infectious')
parser.add_argument('--total_population', type=int, default=1000, help='Total population size')
parser.add_argument('--initial_infective', type=int, default=10, help='Initial number of infected individuals')
parser.add_argument('--transmission_rate', type=float, default=2.5, help='Transmission rate (β) per day')
parser.add_argument('--simulation_time', type=float, default=10.0, help='Total simulation time in days')
args = parser.parse_args()

# Model Parameters
mortality = args.mortality / 100
infectivity_period = args.infectivity_period
dt = args.dt
incubation_period = args.incubation_period
total_population = args.total_population
initial_infective = args.initial_infective
transmission_rate = args.transmission_rate
simulation_time = args.simulation_time

# Initial Conditions
S0 = total_population - initial_infective
E0 = 0
I0 = initial_infective
R0 = 0
D0 = 0

# Time Points
t = np.arange(0, simulation_time + dt, dt)

# SEIRD Model
def seird_model(y, t, N, beta, mortality, infectivity_period, incubation_period):
    S, E, I, R, D = y
    dSdt = -beta * S * I / N * dt
    dEdt = beta * S * I / N * dt - E / incubation_period * dt
    dIdt = E / incubation_period * dt - I / infectivity_period * (1 - mortality) * dt - I / infectivity_period * mortality * dt
    dRdt = I / infectivity_period * (1 - mortality) * dt
    dDdt = I / infectivity_period * mortality * dt
    return [S + dSdt, E + dEdt, I + dIdt, R + dRdt, D + dDdt]

# Solve ODE
y0 = [S0, E0, I0, R0, D0]
solution = odeint(seird_model, y0, t, args=(total_population, transmission_rate, mortality, infectivity_period, incubation_period))

# Output
final_state = solution[-1]
print(json.dumps({'time': simulation_time, 'susceptible': round(final_state[0], 2), 'exposed': round(final_state[1], 2), 'infective': round(final_state[2], 2), 'recovered': round(final_state[3], 2), 'deceased': round(final_state[4], 2)}))