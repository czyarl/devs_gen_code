#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import simpy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='SEIRD Epidemic Model Simulation')
    
    parser.add_argument(
        '--test_name',
        type=str,
        required=True,
        help='Name of the test case being run'
    )
    parser.add_argument(
        '--mortality',
        type=float,
        default=10.0,
        help='Mortality rate as percentage (0-100)'
    )
    parser.add_argument(
        '--infectivity_period',
        type=float,
        default=14.0,
        help='Average days a person stays infectious'
    )
    parser.add_argument(
        '--dt',
        type=float,
        default=0.1,
        help='Time step for numerical integration in days'
    )
    parser.add_argument(
        '--incubation_period',
        type=float,
        default=5.0,
        help='Average days from exposure to becoming infectious'
    )
    parser.add_argument(
        '--total_population',
        type=int,
        default=1000,
        help='Total population size'
    )
    parser.add_argument(
        '--initial_infective',
        type=int,
        default=10,
        help='Initial number of infected individuals'
    )
    parser.add_argument(
        '--transmission_rate',
        type=float,
        default=2.5,
        help='Transmission rate (β) per day'
    )
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=10.0,
        help='Total simulation time in days'
    )
    
    return parser.parse_args()


class SEIRDModel:
    """SEIRD Epidemic Compartmental Model."""
    
    def __init__(self, args):
        self.beta = args.transmission_rate
        self.mortality = args.mortality
        self.infectivity_period = args.infectivity_period
        self.incubation_period = args.incubation_period
        self.N = float(args.total_population)
        self.dt = args.dt
        self.simulation_time = args.simulation_time
        
        # Initial state
        self.S = self.N - float(args.initial_infective)
        self.E = 0.0
        self.I = float(args.initial_infective)
        self.R = 0.0
        self.D = 0.0
        
        self.time = 0.0
        
        logger.info(f"Initialized SEIRD model with N={self.N}, I0={args.initial_infective}")
        logger.info(f"Parameters: β={self.beta}, mortality={self.mortality}%, "
                   f"incubation={self.incubation_period} days, "
                   f"infectivity={self.infectivity_period} days")
    
    def step(self):
        """Perform one time step of the simulation."""
        # Calculate transitions
        new_exposed = (self.beta * self.S * self.I / self.N) * self.dt
        new_exposed = min(new_exposed, self.S)
        
        new_infective = (self.E / self.incubation_period) * self.dt
        new_infective = min(new_infective, self.E)
        
        new_deceased = (self.I / self.infectivity_period) * (self.mortality / 100) * self.dt
        new_recovered = (self.I / self.infectivity_period) * (1 - self.mortality / 100) * self.dt
        
        # Update compartments
        S_new = self.S - new_exposed
        E_new = self.E + new_exposed - new_infective
        I_new = self.I + new_infective - new_deceased - new_recovered
        R_new = self.R + new_recovered
        D_new = self.D + new_deceased
        
        # Store new values
        self.S = S_new
        self.E = E_new
        self.I = I_new
        self.R = R_new
        self.D = D_new
        
        self.time += self.dt
        
        logger.debug(f"Time={self.time:.2f}: S={self.S:.2f}, E={self.E:.2f}, "
                    f"I={self.I:.2f}, R={self.R:.2f}, D={self.D:.2f}")
    
    def run(self):
        """Run the simulation until the end time."""
        logger.info(f"Starting simulation for {self.simulation_time} days with dt={self.dt}")
        
        steps = int(self.simulation_time / self.dt)
        
        for i in range(steps):
            self.step()
        
        logger.info(f"Simulation completed at time {self.time:.2f}")
        logger.info(f"Final state: S={self.S:.2f}, E={self.E:.2f}, "
                   f"I={self.I:.2f}, R={self.R:.2f}, D={self.D:.2f}")
    
    def get_state(self):
        """Return current state as a dictionary."""
        total = self.S + self.E + self.I + self.R + self.D
        logger.debug(f"Population check: {total:.2f} / {self.N}")
        
        return {
            "time": round(self.time, 2),
            "susceptible": round(self.S, 2),
            "exposed": round(self.E, 2),
            "infective": round(self.I, 2),
            "recovered": round(self.R, 2),
            "deceased": round(self.D, 2)
        }


def main():
    """Main entry point."""
    args = parse_arguments()
    
    logger.info(f"Test case: {args.test_name}")
    
    # Create and run model
    model = SEIRDModel(args)
    model.run()
    
    # Output final state
    result = model.get_state()
    print(json.dumps(result))
    
    logger.info("Simulation finished successfully")


if __name__ == "__main__":
    main()