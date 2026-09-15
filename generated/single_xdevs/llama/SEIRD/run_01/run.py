import argparse
import json
import logging
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class SEIRDModel(Atomic):
    def __init__(self, name: str, parent: Coupled | None, 
                 total_population: int, 
                 initial_infective: int, 
                 transmission_rate: float, 
                 incubation_period: float, 
                 infectivity_period: float, 
                 mortality: float, 
                 dt: float):
        super().__init__(name)
        self.parent = parent
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.incubation_period = incubation_period
        self.infectivity_period = infectivity_period
        self.mortality = mortality
        self.dt = dt

        self.add_out_port(Port("Float", "seird_state"))

        self.susceptible = 0.0
        self.exposed = 0.0
        self.infective = 0.0
        self.recovered = 0.0
        self.deceased = 0.0

    def initialize(self):
        self.susceptible = self.total_population - self.initial_infective
        self.exposed = 0.0
        self.infective = self.initial_infective
        self.recovered = 0.0
        self.deceased = 0.0

        self.hold_in("SIM", self.dt)

    def lambdaf(self):
        state = {
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
        self.output["seird_state"].add(state)

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

        self.hold_in("SIM", self.dt)

    def deltext(self, e):
        pass

    def exit(self):
        logging.info(f"Final State - Susceptible: {self.susceptible}, Exposed: {self.exposed}, Infective: {self.infective}, Recovered: {self.recovered}, Deceased: {self.deceased}")


class SEIRDCoupled(Coupled):
    def __init__(self, name: str, parent: Coupled | None, 
                 test_name: str, 
                 total_population: int, 
                 initial_infective: int, 
                 transmission_rate: float, 
                 incubation_period: float, 
                 infectivity_period: float, 
                 mortality: float, 
                 dt: float, 
                 simulation_time: float):
        super().__init__(name)
        self.parent = parent

        self.seird_model = SEIRDModel(name="seird_model", 
                                      parent=self, 
                                      total_population=total_population, 
                                      initial_infective=initial_infective, 
                                      transmission_rate=transmission_rate, 
                                      incubation_period=incubation_period, 
                                      infectivity_period=infectivity_period, 
                                      mortality=mortality, 
                                      dt=dt)
        self.add_component(self.seird_model)

        self.add_out_port(Port("Float", "seird_state"), self.seird_model.output["seird_state"])

        self.test_name = test_name
        self.simulation_time = simulation_time

    def initialize(self):
        pass

    def exit(self):
        final_state = self.seird_model.output["seird_state"].values[-1]
        print(json.dumps({
            "time": self.simulation_time,
            "susceptible": final_state["susceptible"],
            "exposed": final_state["exposed"],
            "infective": final_state["infective"],
            "recovered": final_state["recovered"],
            "deceased": final_state["deceased"]
        }), file=sys.stdout, flush=True)


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

    root = SEIRDCoupled(name="seird_coupled", 
                        parent=None, 
                        test_name=args.test_name, 
                        total_population=args.total_population, 
                        initial_infective=args.initial_infective, 
                        transmission_rate=args.transmission_rate, 
                        incubation_period=args.incubation_period, 
                        infectivity_period=args.infectivity_period, 
                        mortality=args.mortality, 
                        dt=args.dt, 
                        simulation_time=args.simulation_time)

    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)
    root.exit()

if __name__ == "__main__":
    main()