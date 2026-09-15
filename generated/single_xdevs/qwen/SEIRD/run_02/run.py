import argparse
import sys
import json
import random
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
                 dt: float, 
                 simulation_time: float):
        super().__init__(name)
        self.parent = parent
        self.total_population = total_population
        self.initial_infective = initial_infective
        self.transmission_rate = transmission_rate
        self.incubation_period = incubation_period
        self.infectivity_period = infectivity_period
        self.mortality = mortality / 100.0  # Convert percentage to fraction
        self.dt = dt
        self.simulation_time = simulation_time
        
        # State variables
        self.S = float(total_population - initial_infective)
        self.E = 0.0
        self.I = float(initial_infective)
        self.R = 0.0
        self.D = 0.0
        
        # Time tracking
        self.current_time = 0.0
        self.end_time = simulation_time
        
        # Ports
        self.add_out_port(Port(float, "state_output"))
        
        # Initialize state
        self.hold_in("ACTIVE", dt)

    def initialize(self):
        self.current_time = 0.0
        self.S = float(self.total_population - self.initial_infective)
        self.E = 0.0
        self.I = float(self.initial_infective)
        self.R = 0.0
        self.D = 0.0
        self.hold_in("ACTIVE", self.dt)

    def lambdaf(self):
        # Output current state as JSON object
        output_data = {
            "time": round(self.current_time, 2),
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2)
        }
        self.output["state_output"].add(output_data)

    def deltint(self):
        # Update state based on SEIRD equations
        N = self.total_population
        
        # Calculate new exposures: S -> E
        new_exposed = (self.transmission_rate * self.S * self.I / N) * self.dt
        new_exposed = min(new_exposed, self.S)
        
        # Calculate new infectives: E -> I
        new_infective = (self.E / self.incubation_period) * self.dt
        new_infective = min(new_infective, self.E)
        
        # Calculate new recoveries and deaths: I -> R and I -> D
        new_recovered = (self.I / self.infectivity_period) * (1 - self.mortality) * self.dt
        new_deceased = (self.I / self.infectivity_period) * self.mortality * self.dt
        new_recovered = min(new_recovered, self.I)
        new_deceased = min(new_deceased, self.I)
        
        # Update compartments
        self.S -= new_exposed
        self.E = self.E + new_exposed - new_infective
        self.I = self.I + new_infective - new_recovered - new_deceased
        self.R += new_recovered
        self.D += new_deceased
        
        # Ensure conservation of population (floating point correction)
        total = self.S + self.E + self.I + self.R + self.D
        if abs(total - self.total_population) > 1e-5:
            # Adjust susceptible to maintain conservation
            self.S += self.total_population - total
        
        # Advance time
        self.current_time += self.dt
        
        # Schedule next step or terminate
        if self.current_time < self.end_time:
            self.hold_in("ACTIVE", self.dt)
        else:
            # Final output at end of simulation
            self.hold_in("TERMINATED", float('inf'))

    def deltext(self, e):
        # No external inputs, so just advance time
        self.current_time += e
        if self.current_time < self.end_time:
            self.hold_in("ACTIVE", self.dt)
        else:
            self.hold_in("TERMINATED", float('inf'))

    def exit(self):
        # Output final state as JSONL to stdout
        final_state = {
            "time": round(self.current_time, 2),
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2)
        }
        print(json.dumps(final_state), file=sys.stdout, flush=True)


class SEIRDSimulation(Coupled):
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
        
        # Create the SEIRD model component
        self.seird_model = SEIRDModel(
            name="seird_model",
            parent=self,
            total_population=total_population,
            initial_infective=initial_infective,
            transmission_rate=transmission_rate,
            incubation_period=incubation_period,
            infectivity_period=infectivity_period,
            mortality=mortality,
            dt=dt,
            simulation_time=simulation_time
        )
        
        self.add_component(self.seird_model)
        
        # Connect output to system output
        self.add_coupling(self.seird_model.output["state_output"], self.output["state_output"])


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
    
    # Validate inputs
    if args.total_population < 0:
        print(f"Error: total_population must be >= 0", file=sys.stderr)
        sys.exit(1)
    if args.initial_infective < 0:
        print(f"Error: initial_infective must be >= 0", file=sys.stderr)
        sys.exit(1)
    if args.initial_infective > args.total_population:
        print(f"Error: initial_infective cannot exceed total_population", file=sys.stderr)
        sys.exit(1)
    if args.mortality < 0 or args.mortality > 100:
        print(f"Error: mortality must be between 0 and 100", file=sys.stderr)
        sys.exit(1)
    if args.dt <= 0:
        print(f"Error: dt must be positive", file=sys.stderr)
        sys.exit(1)
    if args.simulation_time < 0:
        print(f"Error: simulation_time must be non-negative", file=sys.stderr)
        sys.exit(1)
    
    # Log configuration to stderr
    print(f"Running test: {args.test_name}", file=sys.stderr)
    print(f"Configuration: population={args.total_population}, initial_infective={args.initial_infective}, "
          f"transmission_rate={args.transmission_rate}, incubation_period={args.incubation_period}, "
          f"infectivity_period={args.infectivity_period}, mortality={args.mortality}, dt={args.dt}, "
          f"simulation_time={args.simulation_time}", file=sys.stderr)
    
    # Create system
    root = SEIRDSimulation(
        name="seird_system",
        parent=None,
        test_name=args.test_name,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality=args.mortality,
        dt=args.dt,
        simulation_time=args.simulation_time
    )
    
    # Initialize and simulate
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)


if __name__ == "__main__":
    main()