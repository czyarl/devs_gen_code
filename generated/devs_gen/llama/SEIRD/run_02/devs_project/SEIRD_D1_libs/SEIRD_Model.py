"""SEIRD Model implementation in xDEVS.

This model simulates the SEIRD (Susceptible, Exposed, Infective, Recovered, Deceased)
compartmental model for infectious disease spread. It advances the state at fixed time
steps (dt) and writes the final state as a JSONL record to stdout at the end of the
simulation.
"""

import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SEIRD_Model(Atomic):
    """SEIRD Model implementation."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        test_name: str,
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
        self.test_name = test_name
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

    def initialize(self):
        self.time = 0.0
        self.hold_in("STEP", self.dt)

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "STEP":
            return

        # Calculate new state
        new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
        new_exposed = min(new_exposed, self.susceptible)
        self.susceptible -= new_exposed
        self.exposed += new_exposed

        new_infective = (self.exposed / self.incubation_period) * self.dt
        new_infective = min(new_infective, self.exposed)
        self.exposed -= new_infective
        self.infective += new_infective

        new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100) * self.dt
        self.infective -= new_deceased
        self.deceased += new_deceased

        new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100) * self.dt
        self.infective -= new_recovered
        self.recovered += new_recovered

        self.time += self.dt
        if self.time >= self.simulation_time:
            self.output["stdout"].add({
                "time": self.time,
                "susceptible": self.susceptible,
                "exposed": self.exposed,
                "infective": self.infective,
                "recovered": self.recovered,
                "deceased": self.deceased,
            })
            self.passivate("FINISHED")
        else:
            self.hold_in("STEP", self.dt)

    def deltint(self):
        pass

    def exit(self):
        pass