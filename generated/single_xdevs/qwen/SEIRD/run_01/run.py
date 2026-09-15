import argparse
import sys
import json
import logging
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class SEIRDEntity(Atomic):
    def __init__(self, name: str, parent: Coupled | None, 
                 mortality: float, infectivity_period: float, 
                 incubation_period: float, transmission_rate: float,
                 dt: float, total_population: int, initial_infective: int):
        super().__init__(name)
        self.parent = parent
        
        # Parameters
        self.mortality = mortality
        self.infectivity_period = infectivity_period
        self.incubation_period = incubation_period
        self.transmission_rate = transmission_rate
        self.dt = dt
        self.total_population = total_population
        self.initial_infective = initial_infective
        
        # State variables
        self.susceptible = total_population - initial_infective
        self.exposed = 0
        self.infective = initial_infective
        self.recovered = 0
        self.deceased = 0
        
        # Ports
        self.add_in_port(Port(float, "input"))
        self.add_out_port(Port(float, "output"))
        
        # Initialize
        self.hold_in("INIT", 0.0)
        
    def initialize(self):
        self.hold_in("ACTIVE", self.dt)
        
    def lambdaf(self):
        # Output current state
        payload = {
            "time": self.clock,
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
        self.output["output"].add(payload)
        
    def deltint(self):
        # Internal transition
        # Calculate transitions
        # S -> E
        new_exposed = (self.transmission_rate * self.susceptible * self.infective / self.total_population) * self.dt
        new_exposed = min(new_exposed, self.susceptible)
        
        # E -> I
        new_infective = (self.exposed / self.incubation_period) * self.dt
        new_infective = min(new_infective, self.exposed)
        
        # I -> R and I -> D
        new_deceased = (self.infective / self.infectivity_period) * (self.mortality / 100.0) * self.dt
        new_recovered = (self.infective / self.infectivity_period) * (1 - self.mortality / 100.0) * self.dt
        
        # Update compartments
        self.susceptible -= new_exposed
        self.exposed += new_exposed - new_infective
        self.infective += new_infective - new_deceased - new_recovered
        self.recovered += new_recovered
        self.deceased += new_deceased
        
        # Ensure non-negative values
        self.susceptible = max(0, self.susceptible)
        self.exposed = max(0, self.exposed)
        self.infective = max(0, self.infective)
        self.recovered = max(0, self.recovered)
        self.deceased = max(0, self.deceased)
        
        self.hold_in("ACTIVE", self.dt)
        
    def deltext(self, e):
        self.hold_in("ACTIVE", self.dt)
        
    def exit(self):
        # Final output
        payload = {
            "time": self.clock,
            "susceptible": round(self.susceptible, 2),
            "exposed": round(self.exposed, 2),
            "infective": round(self.infective, 2),
            "recovered": round(self.recovered, 2),
            "deceased": round(self.deceased, 2)
        }
        print(json.dumps(payload), file=sys.stdout, flush=True)

class SEIRDSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, 
                 mortality: float, infectivity_period: float, 
                 incubation_period: float, transmission_rate: float,
                 dt: float, total_population: int, initial_infective: int):
        super().__init__(name)
        self.parent = parent
        
        # Create entity
        self.entity = SEIRDEntity(
            name="seird_entity",
            parent=self,
            mortality=mortality,
            infectivity_period=infectivity_period,
            incubation_period=incubation_period,
            transmission_rate=transmission_rate,
            dt=dt,
            total_population=total_population,
            initial_infective=initial_infective
        )
        self.add_component(self.entity)
        
        # Couplings
        self.add_coupling(self.input["input"], self.entity.input["input"])
        self.add_coupling(self.entity.output["output"], self.output["output"])

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
    
    # Create system
    root = SEIRDSystem(
        name="seird_system",
        parent=None,
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        incubation_period=args.incubation_period,
        transmission_rate=args.transmission_rate,
        dt=args.dt,
        total_population=args.total_population,
        initial_infective=args.initial_infective
    )
    
    # Setup simulation
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)
    
    # Final output
    final_state = root.entity.exit()

if __name__ == "__main__":
    main()