#!/usr/bin/env python3
"""
Secure Area Access Control System with PIN Authentication
Discrete Event Simulation Implementation
"""

import argparse
import json
import sys
from typing import List, Dict, Any, Optional
import simpy


class AlarmSystemSimulation:
    """Simulates the secure area alarm system with PIN authentication."""
    
    def __init__(
        self,
        alarm_admin_delay: float = 10.0,
        authentication_delay: float = 2.0,
        display_delay: float = 3.0,
        max_simulation_time: float = 1000.0
    ):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.state = "Disarmed"
        self.initial_state = "Disarmed"
        
        # Event and operation tracking
        self.events: List[Dict[str, Any]] = []
        self.operations: List[Dict[str, Any]] = []
        
        # Track if AlarmAdmin is busy
        self.alarm_admin_busy = False
        
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
        """Add an event to the events list."""
        event = {
            "time": time,
            "component": component,
            "message": message
        }
        if state is not None:
            event["state"] = state
        self.events.append(event)
    
    def add_operation(self, input_time: float, action: str, completed: bool, completion_time: Optional[float]):
        """Add an operation to the operations list."""
        operation = {
            "input_time": input_time,
            "action": action,
            "completed": completed,
            "completion_time": completion_time
        }
        self.operations.append(operation)
    
    def process_request(self, input_time: float, port: int, value: int):
        """Process an input request through the alarm system pipeline."""
        action = "disarm" if value == 0 else "arm"
        message = f"{{{port} {value}}}"
        
        # Record input_reader event
        self.add_event(input_time, "input_reader", message)
        
        # Check if AlarmAdmin is busy
        # Note: If input_time equals the time when alarm_admin_busy becomes False,
        # the request should be accepted (this happens when input arrives at exactly
        # the authentication time)
        if self.alarm_admin_busy:
            # Request is ignored
            self.add_operation(input_time, action, False, None)
            return
        
        # AlarmAdmin accepts the request
        self.alarm_admin_busy = True
        
        # Add operation record (will be updated with completion time later)
        self.add_operation(input_time, action, True, None)
        
        # Schedule alarmAdmin event
        alarm_admin_time = input_time + self.alarm_admin_delay
        self.env.process(self.alarm_admin_process(alarm_admin_time, port, value, input_time))
    
    def alarm_admin_process(self, time: float, port: int, value: int, input_time: float):
        """Simulate AlarmAdmin processing."""
        yield self.env.timeout(time - self.env.now)
        
        action = "disarm" if value == 0 else "arm"
        message = f"{{{port} {value}}}"
        
        # Record alarmAdmin event
        self.add_event(time, "alarmAdmin", message)
        
        # Schedule authentication event
        auth_time = time + self.authentication_delay
        self.env.process(self.authentication_process(auth_time, port, value, input_time))
    
    def authentication_process(self, time: float, port: int, value: int, input_time: float):
        """Simulate authentication processing."""
        yield self.env.timeout(time - self.env.now)
        
        action = "disarm" if value == 0 else "arm"
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        message = f"{{{port} {value}}}"
        
        # Record authentication event
        self.add_event(time, "authentication", message, auth_state)
        
        # Update system state
        self.state = "Disarmed" if value == 0 else "Armed"
        
        # AlarmAdmin is no longer busy
        self.alarm_admin_busy = False
        
        # Update operation record with completion time
        for op in self.operations:
            if op["input_time"] == input_time and op["completion_time"] is None:
                op["completion_time"] = time
                break
        
        # Schedule display event
        display_time = time + self.display_delay
        self.env.process(self.display_process(display_time, port, value))
    
    def display_process(self, time: float, port: int, value: int):
        """Simulate display processing."""
        yield self.env.timeout(time - self.env.now)
        
        display_state = "Disarmed" if value == 0 else "Armed"
        message = f"{{{port} {value}}}"
        
        # Record display event
        self.add_event(time, "display", message, display_state)
    
    def run(self, input_file: Optional[str] = None) -> Dict[str, Any]:
        """Run the simulation."""
        # Parse input file if provided
        input_requests = []
        if input_file:
            with open(input_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    timestamp_str = parts[0]
                    port = int(parts[1])
                    value = int(parts[2])
                    input_time = self.parse_timestamp(timestamp_str)
                    input_requests.append((input_time, port, value))
        
        # Sort input requests by time
        input_requests.sort(key=lambda x: x[0])
        
        # Schedule all input requests
        for input_time, port, value in input_requests:
            # Schedule the request processing
            self.env.process(self._schedule_request(input_time, port, value))
        
        # Run simulation
        self.env.run(until=self.max_simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x["time"])
        
        # Sort operations by input_time
        self.operations.sort(key=lambda x: x["input_time"])
        
        # Determine final simulation time
        if self.events:
            simulation_time = self.events[-1]["time"]
        else:
            simulation_time = 0.0
        
        # Build output
        output = {
            "test_name": "",
            "simulation_time": simulation_time,
            "initial_state": self.initial_state,
            "final_state": self.state,
            "events": self.events,
            "operations": self.operations
        }
        
        return output
    
    def _schedule_request(self, input_time: float, port: int, value: int):
        """Schedule a request at the specified time."""
        # Use a small epsilon to ensure inputs at the same time as
        # authentication are processed after authentication completes
        # This ensures that inputs arriving at exactly the authentication time
        # are accepted (as per specification)
        epsilon = 0.000001
        yield self.env.timeout(input_time - self.env.now + epsilon)
        self.process_request(input_time, port, value)


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description="Secure Area Access Control System Simulation"
    )
    parser.add_argument(
        "--test_name",
        type=str,
        required=True,
        help="Test name for the simulation"
    )
    parser.add_argument(
        "--input_file",
        type=str,
        default=None,
        help="Input file containing operation requests"
    )
    parser.add_argument(
        "--alarm_admin_delay",
        type=float,
        default=10.0,
        help="Delay for AlarmAdmin processing (default: 10.0)"
    )
    parser.add_argument(
        "--authentication_delay",
        type=float,
        default=2.0,
        help="Delay for authentication processing (default: 2.0)"
    )
    parser.add_argument(
        "--display_delay",
        type=float,
        default=3.0,
        help="Delay for display processing (default: 3.0)"
    )
    parser.add_argument(
        "--max_simulation_time",
        type=float,
        default=1000.0,
        help="Maximum simulation time (default: 1000.0)"
    )
    
    args = parser.parse_args()
    
    # Create and run simulation
    sim = AlarmSystemSimulation(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    result = sim.run(input_file=args.input_file)
    result["test_name"] = args.test_name
    
    # Print output to stdout
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
