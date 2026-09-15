"""SEIRD Model implementation in Python using xdevs.py.

This model simulates the spread of an infectious disease using the SEIRD
compartmental model. It accepts parameters such as mortality rate,
infectivity period, time step for numerical integration, incubation period,
total population, initial number of infected individuals, transmission rate,
and simulation time.

The model outputs the final state of the system in JSONL format, including
the time, susceptible population, exposed population, infective population,
recovered population, and deceased population.
"""

import argparse
import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class SEIRD_Model(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        mortality: float,
        infectivity_period: float,
        dt: float,
        incubation_period: float,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.mortality = mortality
        self.infectivity_period = infectivity_period
        self.dt = dt
        self.incubation_period = incubation_period
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.simulation_time = simulation_time

        self.susceptible = total_population - initial_infective
        self.exposed = 0.0
        self.infective = initial_infective
        self.recovered = 0.0
        self.deceased = 0.0

        self.time = 0.0

        self.add_out_port(Port(dict, "out"))

    def initialize(self):
        self.time = 0.0
        self.hold_in("SIMULATE", self.dt)

    def deltext(self, e):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "SIMULATE":
            new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
            new_exposed = min(new_exposed, self.susceptible)

            self.susceptible -= new_exposed
            self.exposed += new_exposed

            new_infective = (self.exposed / self.incubation_period) * self.dt
            new_infective = min(new_infective, self.exposed)

            self.exposed -= new_infective
            self.infective += new_infective

            new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100) * self.dt
            self.deceased += new_deceased
            self.infective -= new_deceased

            new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100) * self.dt
            self.recovered += new_recovered
            self.infective -= new_recovered

            self.time += self.dt

            if self.time < self.simulation_time:
                self.hold_in("SIMULATE", self.dt)
            else:
                self.output["out"].add({
                    "time": self.time,
                    "susceptible": self.susceptible,
                    "exposed": self.exposed,
                    "infective": self.infective,
                    "recovered": self.recovered,
                    "deceased": self.deceased,
                })
                self.passivate("DONE")

    def exit(self):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--mortality", type=float, default=10.0)
    parser.add_argument("--infectivity_period", type=float, default=14.0)
    parser.add_argument("--dt", type=float, default=0.1)
    parser.add_argument("--incubation_period", type=float, default=5.0)
    parser.add_argument("--total_population", type=int, default=1000)
    parser.add_argument("--initial_infective", type=int, default=10)
    parser.add_argument("--transmission_rate", type=float, default=2.5)
    parser.add_argument("--simulation_time", type=float, default=10.0)
    args = parser.parse_args()

    model = SEIRD_Model(
        name=args.test_name,
        parent=None,
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        dt=args.dt,
        incubation_period=args.incubation_period,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        simulation_time=args.simulation_time,
    )
    model.initialize()

    model.deltint()

if __name__ == "__main__":
    main()