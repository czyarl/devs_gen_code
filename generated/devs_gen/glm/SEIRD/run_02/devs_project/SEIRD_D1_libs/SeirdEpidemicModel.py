"""Atomic DEVS model for SEIRD epidemic simulation."""

import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class SeirdEpidemicModel(Atomic):
    """Autonomously simulate the SEIRD epidemic model using discrete-time numerical integration."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        dt: float,
        simulation_time: float,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        incubation_period: float,
        infectivity_period: float,
        mortality: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.dt = dt
        self.simulation_time = simulation_time
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.incubation_period = incubation_period
        self.infectivity_period = infectivity_period
        self.mortality = mortality

        # State variables
        self.susceptible: float = 0.0
        self.exposed: float = 0.0
        self.infective: float = 0.0
        self.recovered: float = 0.0
        self.deceased: float = 0.0

    def initialize(self):
        # Initialize compartmental states
        self.susceptible = float(self.total_population - self.initial_infective)
        self.exposed = 0.0
        self.infective = float(self.initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0

        # Schedule the first update or immediate final state if simulation_time is 0
        if self.simulation_time <= 0.0:
            self.hold_in("FINAL", 0.0)
        elif self.dt < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            # If dt >= simulation_time, we just wait to report the initial state at simulation_time
            self.hold_in("FINAL", self.simulation_time)

    def deltext(self, e: float):
        # This autonomous model has no input ports.
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "FINAL":
            # Write exactly one JSON object to stdout representing the final state
            print(
                json.dumps(
                    {
                        "time": self.simulation_time,
                        "susceptible": round(self.susceptible, 2),
                        "exposed": round(self.exposed, 2),
                        "infective": round(self.infective, 2),
                        "recovered": round(self.recovered, 2),
                        "deceased": round(self.deceased, 2),
                    }
                ),
                flush=True,
            )

    def deltint(self):
        if self.phase == "FINAL":
            self.passivate("DONE")
            return

        # Calculate transitions based on current state
        # S -> E
        # Rate: beta * S * I / N
        # new_exposed = (beta * S * I / N) * dt
        if self.total_population > 0:
            new_exposed = (
                (self.transmission_rate * self.susceptible * self.infective / self.total_population)
                * self.dt
            )
        else:
            new_exposed = 0.0
        
        # Clamp to prevent negative counts
        new_exposed = min(new_exposed, self.susceptible)

        # E -> I
        # Rate: E / incubation_period
        # new_infective = (E / incubation_period) * dt
        if self.incubation_period > 0:
            new_infective = (self.exposed / self.incubation_period) * self.dt
        else:
            new_infective = 0.0
        
        # Clamp to prevent negative counts
        new_infective = min(new_infective, self.exposed)

        # I -> R and I -> D
        # Rate I -> R: I / infectivity_period * (1 - mortality/100)
        # Rate I -> D: I / infectivity_period * (mortality/100)
        if self.infectivity_period > 0:
            new_deceased = (
                (self.infective / self.infectivity_period) * (self.mortality / 100.0) * self.dt
            )
            new_recovered = (
                (self.infective / self.infectivity_period) * (1.0 - self.mortality / 100.0) * self.dt
            )
        else:
            new_deceased = 0.0
            new_recovered = 0.0

        # Update states
        # S_new = S_old - new_exposed
        self.susceptible -= new_exposed

        # E_new = E_old + new_exposed - new_infective
        self.exposed += new_exposed - new_infective

        # I_new = I_old + new_infective - new_deceased - new_recovered
        self.infective += new_infective - new_deceased - new_recovered

        # R_new = R_old + new_recovered
        self.recovered += new_recovered

        # D_new = D_old + new_deceased
        self.deceased += new_deceased

        # Schedule next event
        now = get_current_time()
        next_update_time = now + self.dt

        if next_update_time < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            # No additional state update at the right endpoint.
            # Schedule final observation event at simulation_time.
            self.hold_in("FINAL", max(0.0, self.simulation_time - now))

    def exit(self):
        pass