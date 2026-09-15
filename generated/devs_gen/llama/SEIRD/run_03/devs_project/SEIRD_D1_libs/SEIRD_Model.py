import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import sys
import argparse

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
        self.add_out_port(Port(dict, "stdout"))

    def initialize(self):
        self.time = 0.0
        self.susceptible = self.total_population - self.initial_infective
        self.exposed = 0.0
        self.infective = self.initial_infective
        self.recovered = 0.0
        self.deceased = 0.0
        self.hold_in("ACTIVE", self.dt)

    def deltext(self, e):
        self.time += e

    def lambdaf(self):
        if self.time < self.simulation_time:
            # Calculate new exposed
            new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
            new_exposed = min(new_exposed, self.susceptible)

            # Update states
            self.susceptible -= new_exposed
            self.exposed += new_exposed

            # Calculate new infective
            new_infective = (self.exposed / self.incubation_period) * self.dt
            new_infective = min(new_infective, self.exposed)

            # Calculate new deceased and recovered
            new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100) * self.dt
            new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100) * self.dt

            # Update states
            self.exposed -= new_infective
            self.infective += new_infective - new_deceased - new_recovered
            self.recovered += new_recovered
            self.deceased += new_deceased

            self.hold_in("ACTIVE", self.dt)
        else:
            self.output["stdout"].add({
                "time": self.time,
                "susceptible": round(self.susceptible, 2),
                "exposed": round(self.exposed, 2),
                "infective": round(self.infective, 2),
                "recovered": round(self.recovered, 2),
                "deceased": round(self.deceased, 2),
            })

    def deltint(self):
        pass

    def exit(self):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", type=str, default="SEIRD_Model")
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
        name=args.name,
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

    try:
        while model.ta() > 0:
            model.continuef(model.ta())
            model.lambdaf()
            model.deltint()
    except:
        import traceback
        traceback.print_exc()
    finally:
        model.exit()

if __name__ == "__main__":
    main()