import argparse
import sys
import json
import logging

# xdevs imports
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

class SeirdModel(Atomic):
    """
    Atomic DEVS model representing the SEIRD epidemic simulation.
    """
    def __init__(self, name: str, parent: Coupled | None, 
                 total_population: int, 
                 initial_infective: int, 
                 transmission_rate: float, 
                 mortality: float, 
                 infectivity_period: float, 
                 incubation_period: float, 
                 dt: float):
        super().__init__(name)
        self.parent = parent
        
        # Configuration parameters
        self.N = float(total_population)
        self.beta = transmission_rate
        self.mortality_frac = mortality / 100.0  # Convert percentage to fraction
        self.gamma = 1.0 / infectivity_period if infectivity_period > 0 else 0
        self.sigma = 1.0 / incubation_period if incubation_period > 0 else 0
        self.dt = dt
        
        # State variables (S, E, I, R, D)
        self.S = float(self.N - initial_infective)
        self.E = 0.0
        self.I = float(initial_infective)
        self.R = 0.0
        self.D = 0.0
        
        # Output port for state updates
        self.add_out_port(Port(dict, "out_state"))

    def initialize(self):
        # Schedule the first internal transition immediately
        self.hold_in("active", self.dt)

    def lambdaf(self):
        # Output current state to the port
        payload = {
            "time": round(self.time_last, 2),
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2)
        }
        self.output["out_state"].add(payload)

    def deltint(self):
        # Perform the discrete-time update logic based on requirements
        
        S_old = self.S
        E_old = self.E
        I_old = self.I
        R_old = self.R
        D_old = self.D
        
        # 1. Susceptible -> Exposed
        # new_exposed = (beta * S * I / N) * dt
        new_exposed = (self.beta * S_old * I_old / self.N) * self.dt
        new_exposed = min(new_exposed, S_old)
        
        S_new = S_old - new_exposed
        
        # 2. Exposed -> Infective
        # new_infective = (E / incubation_period) * dt
        # Note: incubation_period = 1/sigma, so E / incubation_period = E * sigma
        new_infective = (E_old * self.sigma) * self.dt
        new_infective = min(new_infective, E_old)
        
        E_new = E_old + new_exposed - new_infective
        
        # 3. Infective -> Recovered / Deceased
        # new_deceased = (I / infectivity_period) * (mortality/100) * dt
        # new_recovered = (I / infectivity_period) * (1 - mortality/100) * dt
        # Note: infectivity_period = 1/gamma, so I / infectivity_period = I * gamma
        
        flow_out_I = (I_old * self.gamma) * self.dt
        
        # Ensure we don't remove more than available I (stability safeguard)
        flow_out_I = min(flow_out_I, I_old)
        
        new_deceased = flow_out_I * self.mortality_frac
        new_recovered = flow_out_I * (1.0 - self.mortality_frac)
        
        I_new = I_old + new_infective - new_deceased - new_recovered
        
        # 4. Recovered / Deceased accumulation
        R_new = R_old + new_recovered
        D_new = D_old + new_deceased
        
        # Update state
        self.S = S_new
        self.E = E_new
        self.I = I_new
        self.R = R_new
        self.D = D_new
        
        # Schedule next internal transition
        self.hold_in("active", self.dt)

    def deltext(self, e):
        # No external inputs for this closed system simulation
        # Abstract method implementation required
        self.hold_in("active", self.sigma)

    def exit(self):
        # Output final state to stdout as JSONL
        final_state = {
            "time": round(self.time_last, 2),
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2)
        }
        
        print(json.dumps(final_state), file=sys.stdout, flush=True)
        logger.info(f"Simulation finished. Final time: {self.time_last}")

class SeirdSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, 
                 total_population: int, 
                 initial_infective: int, 
                 transmission_rate: float, 
                 mortality: float, 
                 infectivity_period: float, 
                 incubation_period: float, 
                 dt: float):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate the atomic model
        self.seird_model = SeirdModel(
            name="seird_model",
            parent=self,
            total_population=total_population,
            initial_infective=initial_infective,
            transmission_rate=transmission_rate,
            mortality=mortality,
            infectivity_period=infectivity_period,
            incubation_period=incubation_period,
            dt=dt
        )
        
        # Add component
        self.add_component(self.seird_model)

def main():
    parser = argparse.ArgumentParser(description="SEIRD Epidemic Simulation using xdevs")
    
    # Define arguments
    parser.add_argument("--test_name", type=str, required=True, help="Name of the test case")
    parser.add_argument("--mortality", type=float, default=10.0, help="Mortality rate percentage (0-100)")
    parser.add_argument("--infectivity_period", type=float, default=14.0, help="Average days infectious")
    parser.add_argument("--dt", type=float, default=0.1, help="Time step in days")
    parser.add_argument("--incubation_period", type=float, default=5.0, help="Incubation period in days")
    parser.add_argument("--total_population", type=int, default=1000, help="Total population")
    parser.add_argument("--initial_infective", type=int, default=10, help="Initial infective count")
    parser.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (beta)")
    parser.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")
    
    args = parser.parse_args()
    
    # Validate inputs
    if args.total_population < 0:
        logger.error("Total population must be non-negative")
        sys.exit(1)
    if args.initial_infective > args.total_population:
        logger.error("Initial infective cannot exceed total population")
        sys.exit(1)
    if args.dt <= 0:
        logger.error("dt must be positive")
        sys.exit(1)
        
    logger.info(f"Starting SEIRD simulation: {args.test_name}")
    logger.info(f"Parameters: Pop={args.total_population}, I0={args.initial_infective}, Beta={args.transmission_rate}")
    
    # Build the model
    root = SeirdSystem(
        name="seird_system",
        parent=None,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        mortality=args.mortality,
        infectivity_period=args.infectivity_period,
        incubation_period=args.incubation_period,
        dt=args.dt
    )
    
    # Setup Coordinator
    # SimulationClock(0) starts at time 0
    coord = Coordinator(root, clock=SimulationClock(0))
    
    # Initialize
    coord.initialize()
    
    # Run simulation
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()