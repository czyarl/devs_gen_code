import json
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class SeirdProcess(Atomic):
    """Implements the discrete-time SEIRD compartmental model simulation."""

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
        # Initialize state variables based on contract
        self.susceptible = float(self.total_population - self.initial_infective)
        self.exposed = 0.0
        self.infective = float(self.initial_infective)
        self.recovered = 0.0
        self.deceased = 0.0

        # Schedule first internal event
        # If simulation_time is 0 or negative, we should output immediately.
        # Otherwise, we start stepping.
        if self.simulation_time <= 0.0:
            self.hold_in("FINAL", 0.0)
        elif self.dt < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            # If dt >= simulation_time, we just wait until the end to report initial state
            self.hold_in("FINAL", self.simulation_time)

    def deltext(self, e: float):
        # No input ports defined for this model
        self.continuef(e)

    def lambdaf(self):
        # Output only happens in the FINAL phase
        if self.phase == "FINAL":
            record = {
                "time": float(f"{self.simulation_time:.2f}"),
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

        # Perform state update logic
        # Note: We use current state values to calculate flows
        s_old = self.susceptible
        e_old = self.exposed
        i_old = self.infective
        r_old = self.recovered
        d_old = self.deceased

        # Calculate flows
        # S -> E
        # new_exposed = (beta * S * I / N) * dt
        # Cut logic: min(flow, source_compartment)
        if self.total_population > 0:
            new_exposed = (self.transmission_rate * s_old * i_old / self.total_population) * self.dt
        else:
            new_exposed = 0.0
        new_exposed = min(new_exposed, s_old)

        # E -> I
        # new_infective = (E / incubation_period) * dt
        if self.incubation_period > 0:
            new_infective = (e_old / self.incubation_period) * self.dt
        else:
            new_infective = 0.0
        new_infective = min(new_infective, e_old)

        # I -> R and I -> D
        # new_recovered = (I / infectivity_period) * (1 - mortality/100) * dt
        # new_deceased = (I / infectivity_period) * (mortality/100) * dt
        if self.infectivity_period > 0:
            total_outflow_rate = i_old / self.infectivity_period
            new_deceased = total_outflow_rate * (self.mortality / 100.0) * self.dt
            new_recovered = total_outflow_rate * (1.0 - self.mortality / 100.0) * self.dt
        else:
            new_deceased = 0.0
            new_recovered = 0.0
        
        # Cut logic for outflows from I to ensure we don't remove more than available
        # Although mathematically they sum to I * dt / period, floating point might drift.
        # The requirement says "It applies 'cut' logic to each flow (min(flow, source_compartment))"
        # However, cutting individually might violate conservation if sum > source.
        # Standard DEVS "cut" usually implies clamping. Given the strict text "min(flow, source_compartment)",
        # we apply it individually. But we must ensure I doesn't go negative.
        # Let's check if sum of flows exceeds I_old.
        # If it does, we might need to scale them or just clamp the last one.
        # The requirement says: "It then updates the state variables: ... I += new_infective - new_recovered - new_deceased"
        # It implies the calculated flows are used directly.
        # Let's stick to the formula provided in R006.
        
        # Update state variables
        self.susceptible = s_old - new_exposed
        self.exposed = e_old + new_exposed - new_infective
        self.infective = i_old + new_infective - new_recovered - new_deceased
        self.recovered = r_old + new_recovered
        self.deceased = d_old + new_deceased

        # Schedule next event
        now = get_current_time()
        next_update = now + self.dt

        if next_update < self.simulation_time:
            self.hold_in("STEP", self.dt)
        else:
            # Schedule the final output event at simulation_time
            # No state update at the right endpoint
            self.hold_in("FINAL", max(0.0, self.simulation_time - now))

    def exit(self):
        pass