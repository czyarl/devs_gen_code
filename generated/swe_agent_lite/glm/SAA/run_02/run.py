#!/usr/bin/env python3
"""
Secure Area Access Control System with PIN Authentication
Discrete Event Simulation using simpy
"""

import argparse
import json
import sys
from typing import List, Dict, Any, Optional
import simpy


class AlarmSystemSimulation:
    """Simulates the secure area alarm system with DES."""
    
    def __init__(
        self,
        test_name: str,
        alarm_admin_delay: float = 10.0,
        authentication_delay: float = 2.0,
        display_delay: float = 3.0,
        max_simulation_time: float = 1000.0
    ):
        self.test_name = test_name
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.current_state = "Disarmed"
        self.initial_state = "Disarmed"
        
        # Event records
        self.events: List[Dict[str, Any]] = []
        
        # Operation records
        self.operations: List[Dict[str, Any]] = []
        
        # AlarmAdmin busy flag
        self.alarm_admin_busy = False
        self.alarm_admin_busy_until = 0.0
        
        # Simulation environment
        self.env = simpy.Environment()
        
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Convert HH:MM:SS timestamp to seconds."""
        parts = timestamp_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    
    def add_event(self, time: float, component: str, message: str, state: Optional[str] = None):
        """Add an event record."""
        event = {
            "time": time,
            "component": component,
            "message": message
        }
        if state is not None:
            event["state"] = state
        self.events.append(event)
    
    def add_operation(
        self,
        input_time: float,
        action: str,
        completed: bool,
        completion_time: Optional[float] = None
    ):
        """Add an operation record."""
        operation = {
            "input_time": input_time,
            "action": action,
            "completed": completed,
            "completion_time": completion_time
        }
        self.operations.append(operation)
    
    def process_input_request(self, timestamp_str: str, port: int, value: int):
        """Process a single input request."""
        input_time = self.parse_timestamp(timestamp_str)
        
        # Determine action
        action = "disarm" if value == 0 else "arm"
        
        # Create message for events
        message = f"{{{port} {value}}}"
        
        # Record input_reader event
        self.add_event(input_time, "input_reader", message)
        
        # Check if AlarmAdmin is busy
        if self.alarm_admin_busy and input_time < self.alarm_admin_busy_until:
            # Request is ignored
            self.add_operation(input_time, action, False, None)
            return
        
        # Request is accepted
        # Schedule the pipeline events
        alarm_admin_time = input_time + self.alarm_admin_delay
        authentication_time = alarm_admin_time + self.authentication_delay
        display_time = authentication_time + self.display_delay
        
        # Mark AlarmAdmin as busy until authentication completes
        self.alarm_admin_busy = True
        self.alarm_admin_busy_until = authentication_time
        
        # Schedule alarmAdmin event
        self.env.process(self.alarm_admin_event(alarm_admin_time, message))
        
        # Schedule authentication event
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        self.env.process(self.authentication_event(authentication_time, message, auth_state))
        
        # Schedule display event and update state
        new_state = "Disarmed" if value == 0 else "Armed"
        self.env.process(self.display_event(display_time, message, new_state))
        
        # Record operation
        self.add_operation(input_time, action, True, authentication_time)
    
    def alarm_admin_event(self, time: float, message: str):
        """Simulate alarmAdmin event."""
        yield self.env.timeout(time - self.env.now)
        self.add_event(time, "alarmAdmin", message)
    
    def authentication_event(self, time: float, message: str, state: str):
        """Simulate authentication event."""
        yield self.env.timeout(time - self.env.now)
        self.add_event(time, "authentication", message, state)
    
    def display_event(self, time: float, message: str, new_state: str):
        """Simulate display event and update system state."""
        yield self.env.timeout(time - self.env.now)
        self.add_event(time, "display", message, new_state)
        self.current_state = new_state
    
    def read_input_file(self, input_file: str):
        """Read and parse input file."""
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                timestamp_str = parts[0]
                port = int(parts[1])
                value = int(parts[2])
                self.process_input_request(timestamp_str, port, value)
    
    def run(self):
        """Run the simulation."""
        # Sort events by time to ensure proper scheduling
        # We need to process all input events first, then run the simulation
        # The simpy environment will handle the timing
        
        # Find the maximum time we need to simulate
        if self.events:
            max_event_time = max(event["time"] for event in self.events)
            simulation_end_time = min(max_event_time, self.max_simulation_time)
        else:
            simulation_end_time = 0.0
        
        # Run the simulation
        self.env.run(until=simulation_end_time)
        
        # Determine final simulation time
        if self.events:
            self.simulation_time = max(event["time"] for event in self.events)
        else:
            self.simulation_time = 0.0
        
        # Cap at max_simulation_time
        self.simulation_time = min(self.simulation_time, self.max_simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda e: e["time"])
        
        # Sort operations by input_time
        self.operations.sort(key=lambda o: o["input_time"])
    
    def get_output(self) -> Dict[str, Any]:
        """Generate the output JSON."""
        return {
            "test_name": self.test_name,
            "simulation_time": self.simulation_time,
            "initial_state": self.initial_state,
            "final_state": self.current_state,
            "events": self.events,
            "operations": self.operations
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Secure Area Access Control System Simulation"
    )
    parser.add_argument(
        "--test_name",
        type=str,
        required=True,
        help="Test name copied into output JSON"
    )
    parser.add_argument(
        "--input_file",
        type=str,
        help="Input request file path"
    )
    parser.add_argument(
        "--alarm_admin_delay",
        type=float,
        default=10.0,
        help="Alarm admin delay in seconds (default: 10.0)"
    )
    parser.add_argument(
        "--authentication_delay",
        type=float,
        default=2.0,
        help="Authentication delay in seconds (default: 2.0)"
    )
    parser.add_argument(
        "--display_delay",
        type=float,
        default=3.0,
        help="Display delay in seconds (default: 3.0)"
    )
    parser.add_argument(
        "--max_simulation_time",
        type=float,
        default=1000.0,
        help="Maximum simulation time in seconds (default: 1000.0)"
    )
    
    args = parser.parse_args()
    
    # Create simulation
    sim = AlarmSystemSimulation(
        test_name=args.test_name,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Read input file if provided
    if args.input_file:
        sim.read_input_file(args.input_file)
    
    # Run simulation
    sim.run()
    
    # Output JSON to stdout
    output = sim.get_output()
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
