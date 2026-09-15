import argparse
import sys
import json
import logging
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SeirdAtomic(Atomic):
    """
    Atomic model representing the SEIRD epidemic compartmental model.
    It performs discrete-time integration steps at fixed intervals (dt).
    """
    def __init__(self, name: str, parent: Coupled | None, config: dict):
        super().__init__(name)
        self.parent = parent
        self.config = config
        
        # Parameters
        self.N = config['total_population']
        self.beta = config['transmission_rate']
        self.mortality = config['mortality']
        self.infectivity_period = config['infectivity_period']
        self.incubation_period = config['incubation_period']
        self.dt = config['dt']
        self.simulation_time = config['simulation_time']
        
        # State Variables
        self.S = float(self.N - config['initial_infective'])
        self.E = 0.0
        self.I = float(config['initial_infective'])
        self.R = 0.0
        self.D = 0.0
        
        # Current simulation time
        self.current_time = 0.0

        # Ports
        self.add_in_port(Port(object, "in"))
        self.add_out_port(Port(dict, "out"))

    def initialize(self):
        """Initialize the model and schedule the first internal transition."""
        logger.info(f"Initializing SEIRD Model: S={self.S}, E={self.E}, I={self.I}, R={self.R}, D={self.D}")
        # Schedule first event immediately
        self.hold_in("active", self.dt)

    def lambdaf(self):
        """Output the current state to the output port."""
        # Prepare the state payload
        state_payload = {
            "time": round(self.current_time, 2),
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2)
        }
        self.output["out"].add(state_payload)

    def deltint(self):
        """Internal transition: Perform the SEIRD calculation for the next time step."""
        # Update time
        self.current_time += self.dt
        
        # 1. Calculate flows
        # S -> E
        new_exposed_raw = (self.beta * self.S * self.I / self.N) * self.dt
        new_exposed = min(new_exposed_raw, self.S)
        
        # E -> I
        new_infective_raw = (self.E / self.incubation_period) * self.dt
        new_infective = min(new_infective_raw, self.E)
        
        # I -> R and I -> D
        # Total leaving I
        flow_out_I = (self.I / self.infectivity_period) * self.dt
        # Split based on mortality
        new_deceased = flow_out_I * (self.mortality / 100.0)
        new_recovered = flow_out_I * (1.0 - self.mortality / 100.0)
        
        # 2. Update Stocks
        self.S = self.S - new_exposed
        self.E = self.E + new_exposed - new_infective
        self.I = self.I + new_infective - new_recovered - new_deceased
        self.R = self.R + new_recovered
        self.D = self.D + new_deceased
        
        # 3. Schedule next event
        if self.current_time < self.simulation_time:
            self.hold_in("active", self.dt)
        else:
            self.passivate()

    def deltext(self, e):
        """External transition: Not used in this autonomous model."""
        pass

    def exit(self):
        """Cleanup and final output."""
        logger.info("Simulation finished. Writing final state to stdout.")
        
        final_state = {
            "time": round(self.current_time, 2),
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2)
        }
        print(json.dumps(final_state), file=sys.stdout, flush=True)

class SeirdSystem(Coupled):
    """
    Coupled model representing the top-level system.
    """
    def __init__(self, name: str, parent: Coupled | None, config: dict):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate the Atomic model
        self.seird_model = SeirdAtomic(name="seird_process", parent=self, config=config)
        self.add_component(self.seird_model)
        
        # Define ports for the Coupled model
        self.add_in_port(Port(object, "in"))
        self.add_out_port(Port(dict, "out"))
        
        # Couplings
        self.add_coupling(self.seird_model.output["out"], self.output["out"])

def main():
    parser = argparse.ArgumentParser(description="SEIRD Epidemic Model Simulation using xdevs")
    
    # Required Arguments
    parser.add_argument("--test_name", type=str, required=True, help="Name of the test case being run")
    
    # Optional Arguments with Defaults
    parser.add_argument("--mortality", type=float, default=10.0, help="Mortality rate as percentage (0-100)")
    parser.add_argument("--infectivity_period", type=float, default=14.0, help="Average days a person stays infectious")
    parser.add_argument("--dt", type=float, default=0.1, help="Time step for numerical integration in days")
    parser.add_argument("--incubation_period", type=float, default=5.0, help="Average days from exposure to becoming infectious")
    parser.add_argument("--total_population", type=int, default=1000, help="Total population size")
    parser.add_argument("--initial_infective", type=int, default=10, help="Initial number of infected individuals")
    parser.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (β) per day")
    parser.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")
    
    args = parser.parse_args()
    
    # Log configuration
    logger.info(f"Starting simulation: {args.test_name}")
    logger.info(f"Parameters: N={args.total_population}, I0={args.initial_infective}, Beta={args.transmission_rate}, Time={args.simulation_time}")

    # Prepare configuration dictionary
    config = {
        'total_population': args.total_population,
        'initial_infective': args.initial_infective,
        'transmission_rate': args.transmission_rate,
        'mortality': args.mortality,
        'infectivity_period': args.infectivity_period,
        'incubation_period': args.incubation_period,
        'dt': args.dt,
        'simulation_time': args.simulation_time
    }
    
    # Build the model
    root = SeirdSystem(name="seird_system", parent=None, config=config)
    
    # Setup Coordinator
    coord = Coordinator(root, clock=SimulationClock(0))
    
    # Run simulation
    try:
        coord.initialize()
        coord.simulate_time(args.simulation_time)
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()