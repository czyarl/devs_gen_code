"""Complete pattern: periodic state updates with exactly one final JSON record."""

import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class SeirdEpidemicModel(Atomic):
    """Advance SEIRD state and report it once at the horizon."""

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

        # State variables
        self.susceptible: float = 0.0
        self.exposed: float = 0.0
        self.infective: float = 0.0
        self.recovered: float = 0.0
        self.deceased: float = 0.0

    def initialize(self):
        # Initial State: S = N - I_0, E = 0, I = I_0, R = 0, D = 0
        self.susceptible = float(self.total_population - self.initial_infective)
        self.exposed = 0.0
        self.infective = float(self.initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0

        if self.simulation_time <= 0.0:
            self.hold_in("FINAL", 0.0)
        elif self.dt < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            self.hold_in("FINAL", self.simulation_time)

    def deltext(self, e):
        # This autonomous model has no input ports.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "FINAL":
            return
        
        print(json.dumps({
            "time": self.simulation_time,
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2),
        }), flush=True)

    def deltint(self):
        if self.phase == "FINAL":
            self.passivate("DONE")
            return

        # Calculate compartment transitions
        # S -> E
        new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
        new_exposed = min(new_exposed, self.susceptible)

        # E -> I
        new_infective = (self.exposed / self.incubation_period) * self.dt
        new_infective = min(new_infective, self.exposed)

        # I -> R and I -> D
        # Rate: I / infectivity_period per day
        # Split by mortality percentage
        flow_out_infective = (self.infective / self.infectivity_period) * self.dt
        
        new_deceased = flow_out_infective * (self.mortality / 100.0)
        new_recovered = flow_out_infective * (1.0 - self.mortality / 100.0)

        # Update states atomically
        self.susceptible -= new_exposed
        self.exposed = self.exposed + new_exposed - new_infective
        self.infective = self.infective + new_infective - new_deceased - new_recovered
        self.recovered += new_recovered
        self.deceased += new_deceased

        now = get_current_time()
        next_update = now + self.dt

        if next_update < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            # Do not apply another update at the right endpoint. Schedule a
            # separate final observation event there.
            self.hold_in("FINAL", max(0.0, self.simulation_time - now))

    def exit(self):
        pass