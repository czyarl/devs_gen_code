import argparse
import json
import logging
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock
import random

class SEIRDModel(Atomic):
    def __init__(self, name: str, parent: Coupled | None, 
                 mortality: float, infectivity_period: float, 
                 incubation_period: float, transmission_rate: float,
                 total_population: int, initial_infective: int):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("Float", "in"))
        self.add_out_port(Port("Float", "out"))
        self.mortality = mortality
        self.infectivity_period = infectivity_period
        self.incubation_period = incubation_period
        self.transmission_rate = transmission_rate
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.susceptible = total_population - initial_infective
        self.exposed = 0
        self.infective = initial_infective
        self.recovered = 0
        self.deceased = 0
        self.dt = 0.1
        self.time = 0.0

    def initialize(self):
        logging.info("SEIRD Model initialized")
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
        new_exposed = min(new_exposed, self.susceptible)
        self.susceptible -= new_exposed
        self.exposed += new_exposed

        new_infective = (self.exposed / self.incubation_period) * self.dt
        new_infective = min(new_infective, self.exposed)
        self.exposed -= new_infective
        self.infective += new_infective

        new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100) * self.dt
        new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100) * self.dt
        self.infective -= new_deceased + new_recovered
        self.recovered += new_recovered
        self.deceased += new_deceased

        self.time += self.dt
        self.hold_in("RUNNING", self.dt)

    def deltext(self, e):
        pass

    def exit(self):
        print(json.dumps({
            "time": self.time,
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }), file=sys.stdout, flush=True)

class SEIRDSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, 
                 mortality: float, infectivity_period: float, 
                 incubation_period: float, transmission_rate: float,
                 total_population: int, initial_infective: int, simulation_time: float):
        super().__init__(name)
        self.parent = parent
        self.seird_model = SEIRDModel(name="seird_model", parent=self, 
                                      mortality=mortality, infectivity_period=infectivity_period, 
                                      incubation_period=incubation_period, transmission_rate=transmission_rate,
                                      total_population=total_population, initial_infective=initial_infective)
        self.add_component(self.seird_model)

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

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    root = SEIRDSystem(name="system", parent=None, 
                       mortality=args.mortality, infectivity_period=args.infectivity_period, 
                       incubation_period=args.incubation_period, transmission_rate=args.transmission_rate,
                       total_population=args.total_population, initial_infective=args.initial_infective, simulation_time=args.simulation_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()