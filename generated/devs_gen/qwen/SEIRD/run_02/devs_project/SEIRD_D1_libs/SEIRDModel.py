"""Complete SEIRD model implementation using xDEVS Atomic model."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class SEIRDModel(Atomic):
    """SEIRD compartmental model with fixed time steps."""

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

        # Schedule first update if needed
        if self.simulation_time <= 0.0:
            self.hold_in("FINAL", 0.0)
        elif self.dt < self.simulation_time:
            self.hold_in("UPDATE", self.dt)
        else:
            self.hold_in("FINAL", self.simulation_time)

    def deltext(self, e):
        # This model has no input ports
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "FINAL":
            # Emit final state record
            record = {
                "time": round(self.simulation_time, 2),
                "susceptible": round(self.susceptible, 2),
                "exposed": round(self.exposed, 2),
                "infective": round(self.infective, 2),
                "recovered": round(self.recovered, 2),
                "deceased": round(self.deceased, 2),
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "FINAL":
            self.passivate("DONE")
            return

        # Perform SEIRD update
        # S -> E
        new_exposed = min(
            (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt,
            self.susceptible
        )
        self.susceptible -= new_exposed

        # E -> I
        new_infective = min(self.exposed / self.incubation_period * self.dt, self.exposed)
        self.exposed += new_exposed - new_infective

        # I -> R/D
        new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        new_recovered = (self.infective / self.infectivity_period) * (1.0 - self.mortality / 100.0) * self.dt
        self.infective += new_infective - new_deceased - new_recovered
        self.recovered += new_recovered
        self.deceased += new_deceased

        # Update time and schedule next event
        now = get_current_time()
        next_update = now + self.dt
        if next_update < self.simulation_time:
            self.hold_in("UPDATE", self.dt)
        else:
            # Schedule final observation at simulation_time
            self.hold_in("FINAL", max(0.0, self.simulation_time - now))

    def exit(self):
        pass