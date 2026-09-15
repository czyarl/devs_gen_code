"""SEIRD Model Implementation using xDEVS."""

import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SEIRDModel(Atomic):
    """SEIRD compartmental model for infectious disease simulation."""

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

        # Internal state
        self.susceptible = 0.0
        self.exposed = 0.0
        self.infective = 0.0
        self.recovered = 0.0
        self.deceased = 0.0
        self.time = 0.0

    def initialize(self):
        # Validate inputs
        if not (0 <= self.initial_infective <= self.total_population):
            raise ValueError("Invalid initial_infective value")
        if self.dt <= 0:
            raise ValueError("dt must be positive")
        if self.incubation_period <= 0:
            raise ValueError("incubation_period must be positive")
        if self.infectivity_period <= 0:
            raise ValueError("infectivity_period must be positive")

        # Initialize compartments
        self.susceptible = float(self.total_population - self.initial_infective)
        self.exposed = 0.0
        self.infective = float(self.initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0
        self.time = 0.0

        # Schedule first update if applicable
        if self.simulation_time <= 0.0:
            self.hold_in("FINAL", 0.0)
        else:
            self.hold_in("UPDATE", self.dt)

    def deltext(self, e):
        # This model has no input ports
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "FINAL":
            # Output final state
            final_state = {
                "time": self.time,
                "susceptible": round(self.susceptible, 2),
                "exposed": round(self.exposed, 2),
                "infective": round(self.infective, 2),
                "recovered": round(self.recovered, 2),
                "deceased": round(self.deceased, 2),
            }
            print(json.dumps(final_state), flush=True)

    def deltint(self):
        if self.phase == "FINAL":
            self.passivate("DONE")
            return

        # Compute transition rates
        beta = self.transmission_rate
        gamma = 1.0 / self.infectivity_period
        sigma = 1.0 / self.incubation_period
        mu = self.mortality / 100.0

        # Calculate new transitions
        # S -> E
        new_exposed = min(
            (beta * self.susceptible * self.infective / self.total_population) * self.dt,
            self.susceptible
        )
        new_exposed = round(new_exposed, 6)  # Prevent floating point issues

        # E -> I
        new_infective = min(sigma * self.exposed * self.dt, self.exposed)
        new_infective = round(new_infective, 6)

        # I -> R and I -> D
        new_recovered = min(gamma * (1.0 - mu) * self.infective * self.dt, self.infective)
        new_recovered = round(new_recovered, 6)
        new_deceased = min(gamma * mu * self.infective * self.dt, self.infective)
        new_deceased = round(new_deceased, 6)

        # Update compartments
        self.susceptible -= new_exposed
        self.exposed += new_exposed - new_infective
        self.infective += new_infective - new_recovered - new_deceased
        self.recovered += new_recovered
        self.deceased += new_deceased

        # Update time
        self.time += self.dt

        # Check if we should finalize
        now = get_current_time()
        if now + self.dt >= self.simulation_time:
            # Finalize at the simulation time
            self.hold_in("FINAL", max(0.0, self.simulation_time - now))
        else:
            # Schedule next update
            self.hold_in("UPDATE", self.dt)

    def exit(self):
        pass