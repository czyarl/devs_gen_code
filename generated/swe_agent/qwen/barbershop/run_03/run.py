#!/usr/bin/env python3
"""
Barbershop simulation implementation
"""
import argparse
import sys
import json
import logging
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

# Import modules
from reception import Reception
from checkhair import CheckHair
from cuthair import CutHair

class BarbershopSimulation:
    def __init__(self, simulation_time=1000000.0):
        self.simulation_time = simulation_time
        self.env = simpy.Environment()
        self.reception = Reception(self.env)
        self.checkhair = CheckHair(self.env, self.reception)
        self.cuthair = CutHair(self.env, self.checkhair)
        
        # Connect modules
        self.reception.checkhair = self.checkhair
        self.checkhair.cuthair = self.cuthair
        
    def run(self):
        # Process all input events
        input_lines = []
        events_scheduled = 0
        # Store events to schedule them properly
        scheduled_events = []
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            input_lines.append(line)
            try:
                # Parse time and event
                time_str, event_name = line.split(' ', 1)
                # Convert time string to float (HH:MM:SS:mm format)
                absolute_time = self._parse_time(time_str)
                # Schedule the event
                if event_name == 'newcust':
                    # Schedule at absolute time (relative to simulation start)
                    scheduled_events.append((absolute_time, event_name))
            except Exception as e:
                logging.error(f"Error processing input line: {line} - {e}")
        
        # Debug: Print how many lines we read
        logging.info(f"Read {len(input_lines)} input lines, scheduled {len(scheduled_events)} events")
        
        # Schedule all events
        for absolute_time, event_name in scheduled_events:
            if event_name == 'newcust':
                self.env.process(self._schedule_customer_at_time(absolute_time))
        
        # Run the simulation
        self.env.run(until=self.simulation_time)
        
    def _parse_time(self, time_str):
        """Parse time string HH:MM:SS:mm to float seconds"""
        h, m, s, ms = map(int, time_str.split(':'))
        return h * 3600 + m * 60 + s + ms / 100.0
        
    def _schedule_customer_at_time(self, absolute_time):
        """Schedule a new customer arrival at absolute simulation time"""
        # Wait until the absolute time
        yield self.env.timeout(absolute_time - self.env.now)
        self.reception.arrive_customer()

def main():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds')
    
    args = parser.parse_args()
    
    # Create and run simulation
    simulation = BarbershopSimulation(args.simulation_time)
    simulation.run()

if __name__ == "__main__":
    main()