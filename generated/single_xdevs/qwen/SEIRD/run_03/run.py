import argparse
import sys
import json
import logging
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class SEIRDEvent:
    def __init__(self, time, susceptible, exposed, infective, recovered, deceased):
        self.time = time
        self.susceptible = susceptible
        self.exposed = exposed
        self.infective = infective
        self.recovered = recovered
        self.deceased = deceased

class SEIRDModel(Atomic):
    def __init__(self, name, parent, mortality, infectivity_period, dt, incubation_period, 
                 total_population, initial_infective, transmission_rate, simulation_time):
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

        # Initialize state variables
        self.susceptible = total_population - initial_infective
        self.exposed = 0.0
        self.infective = initial_infective
        self.recovered = 0.0
        self.deceased = 0.0

        # Initialize ports
        self.add_in_port(Port(float, "input_time"))
        self.add_out_port(Port(SEIRDEvent, "output_state"))

        # Start simulation at time 0.0
        self.hold_in("INIT", 0.0)

    def initialize(self):
        self.hold_in("UPDATE", 0.0)

    def lambdaf(self):
        # Output current state
        event = SEIRDEvent(
            time=self.clock,
            susceptible=round(self.susceptible, 2),
            exposed=round(self.exposed, 2),
            infective=round(self.infective, 2),
            recovered=round(self.recovered, 2),
            deceased=round(self.deceased, 2)
        )
        self.output["output_state"].add(event)

    def deltint(self):
        # Internal transition: update simulation state
        if self.clock >= self.simulation_time:
            self.hold_in("DONE", float('inf'))
            return

        # Calculate transitions
        # S -> E
        new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
        new_exposed = min(new_exposed, self.susceptible)
        new_susceptible = self.susceptible - new_exposed

        # E -> I
        new_infective = (self.exposed / self.incubation_period) * self.dt
        new_infective = min(new_infective, self.exposed)
        new_exposed = self.exposed + new_exposed - new_infective

        # I -> R or D
        new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        new_recovered = (self.infective / self.infectivity_period) * (1.0 - self.mortality / 100.0) * self.dt

        new_infective = self.infective + new_infective - new_deceased - new_recovered

        # Update state
        self.susceptible = new_susceptible
        self.exposed = new_exposed
        self.infective = new_infective
        self.recovered = self.recovered + new_recovered
        self.deceased = self.deceased + new_deceased

        # Schedule next update
        self.hold_in("UPDATE", self.dt)

    def deltext(self, e):
        # External transition (should not happen in this model)
        self.hold_in("UPDATE", self.dt)

    def exit(self):
        # Final state output
        final_event = SEIRDEvent(
            time=round(self.clock, 2),
            susceptible=round(self.susceptible, 2),
            exposed=round(self.exposed, 2),
            infective=round(self.infective, 2),
            recovered=round(self.recovered, 2),
            deceased=round(self.deceased, 2)
        )
        print(json.dumps({
            "time": final_event.time,
            "susceptible": final_event.susceptible,
            "exposed": final_event.exposed,
            "infective": final_event.infective,
            "recovered": final_event.recovered,
            "deceased": final_event.deceased
        }), file=sys.stdout, flush=True)

class SEIRDSimulation(Coupled):
    def __init__(self, name, parent, mortality, infectivity_period, dt, incubation_period, 
                 total_population, initial_infective, transmission_rate, simulation_time):
        super().__init__(name)
        self.parent = parent

        # Create SEIRD model
        self.seird = SEIRDModel(
            name="seird",
            parent=self,
            mortality=mortality,
            infectivity_period=infectivity_period,
            dt=dt,
            incubation_period=incubation_period,
            total_population=total_population,
            initial_infective=initial_infective,
            transmission_rate=transmission_rate,
            simulation_time=simulation_time
        )
        self.add_component(self.seird)

        # Define couplings
        self.add_coupling(self.seird.output["output_state"], self.output["state_output"])

    def initialize(self):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
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

    # Create simulation system
    root = SEIRDSimulation(
        name="seird_system",
        parent=None,
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        dt=args.dt,
        incubation_period=args.incubation_period,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        simulation_time=args.simulation_time
    )

    # Run simulation
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()