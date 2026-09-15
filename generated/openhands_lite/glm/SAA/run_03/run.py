#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication - Discrete Event Simulation
"""

import argparse
import json
from typing import List, Dict, Any, Optional
import simpy


class SecureAreaSimulation:
    def __init__(
        self,
        alarm_admin_delay: float = 10.0,
        authentication_delay: float = 2.0,
        display_delay: float = 3.0,
        max_simulation_time: float = 1000.0,
    ):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        self.events: List[Dict[str, Any]] = []
        self.operations: List[Dict[str, Any]] = []
        self.current_state = "Disarmed"
        self.alarm_admin_busy = False
        self.alarm_admin_busy_until = 0.0
        
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Convert HH:MM:SS to seconds."""
        parts = timestamp_str.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    
    def add_event(self, time: float, component: str, message: str, state: Optional[str] = None):
        """Add an event to the events list."""
        event = {"time": time, "component": component, "message": message}
        if state is not None:
            event["state"] = state
        self.events.append(event)
    
    def add_operation(self, input_time: float, action: str, completed: bool, completion_time: Optional[float]):
        """Add an operation record."""
        self.operations.append({
            "input_time": input_time,
            "action": action,
            "completed": completed,
            "completion_time": completion_time
        })
    
    def process_input(self, env: simpy.Environment, input_time: float, port: int, value: int):
        """Process an input request."""
        # Check if AlarmAdmin is busy
        if self.alarm_admin_busy and input_time < self.alarm_admin_busy_until:
            # Request is ignored after input event
            action = "disarm" if value == 0 else "arm"
            self.add_operation(input_time, action, False, None)
            return
        
        # AlarmAdmin accepts the request
        self.alarm_admin_busy = True
        action = "disarm" if value == 0 else "arm"
        
        # Calculate completion time (authentication time)
        completion_time = input_time + self.alarm_admin_delay + self.authentication_delay
        self.alarm_admin_busy_until = completion_time
        
        # Schedule alarmAdmin event
        alarm_admin_time = input_time + self.alarm_admin_delay
        env.process(self.alarm_admin_process(env, input_time, port, value, alarm_admin_time))
    
    def alarm_admin_process(self, env: simpy.Environment, input_time: float, port: int, value: int, alarm_admin_time: float):
        """Process alarmAdmin event and schedule authentication."""
        yield env.timeout(alarm_admin_time - env.now)
        
        # Emit alarmAdmin event
        self.add_event(alarm_admin_time, "alarmAdmin", f"{{{port} {value}}}")
        
        # Schedule authentication event
        auth_time = alarm_admin_time + self.authentication_delay
        env.process(self.authentication_process(env, input_time, port, value, auth_time))
    
    def authentication_process(self, env: simpy.Environment, input_time: float, port: int, value: int, auth_time: float):
        """Process authentication event and schedule display."""
        yield env.timeout(auth_time - env.now)
        
        # Emit authentication event
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        self.add_event(auth_time, "authentication", f"{{{port} {value}}}", state=auth_state)
        
        # Update system state
        if value == 0:
            self.current_state = "Disarmed"
        else:
            self.current_state = "Armed"
        
        # AlarmAdmin stops working at authentication time
        self.alarm_admin_busy = False
        
        # Record operation completion
        action = "disarm" if value == 0 else "arm"
        self.add_operation(input_time, action, True, auth_time)
        
        # Schedule display event
        display_time = auth_time + self.display_delay
        env.process(self.display_process(env, port, value, display_time))
    
    def display_process(self, env: simpy.Environment, port: int, value: int, display_time: float):
        """Process display event."""
        yield env.timeout(display_time - env.now)
        
        # Emit display event
        display_state = "Disarmed" if value == 0 else "Armed"
        self.add_event(display_time, "display", f"{{{port} {value}}}", state=display_state)
    
    def run(self, input_lines: List[str]) -> Dict[str, Any]:
        """Run the simulation."""
        env = simpy.Environment()
        
        # Parse and sort input lines by time
        inputs = []
        for line in input_lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            timestamp_str = parts[0]
            port = int(parts[1])
            value = int(parts[2])
            input_time = self.parse_timestamp(timestamp_str)
            inputs.append((input_time, port, value))
        
        # Sort inputs by time
        inputs.sort(key=lambda x: x[0])
        
        # Schedule input events
        for input_time, port, value in inputs:
            # Emit input_reader event immediately
            self.add_event(input_time, "input_reader", f"{{{port} {value}}}")
            
            # Schedule processing
            env.process(self.process_input(env, input_time, port, value))
        
        # Run simulation
        env.run(until=self.max_simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x["time"])
        
        # Sort operations by input_time
        self.operations.sort(key=lambda x: x["input_time"])
        
        # Determine simulation time
        if self.events:
            simulation_time = max(event["time"] for event in self.events)
        else:
            simulation_time = 0.0
        
        # Build output
        output = {
            "test_name": "",
            "simulation_time": simulation_time,
            "initial_state": "Disarmed",
            "final_state": self.current_state,
            "events": self.events,
            "operations": self.operations
        }
        
        return output


def main():
    parser = argparse.ArgumentParser(description="Secure Area Access Control Simulation")
    parser.add_argument("--test_name", type=str, required=True, help="Test name")
    parser.add_argument("--input_file", type=str, help="Input file path")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Alarm admin delay")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Authentication delay")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Display delay")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Max simulation time")
    
    args = parser.parse_args()
    
    # Read input file
    input_lines = []
    if args.input_file:
        with open(args.input_file, "r") as f:
            input_lines = f.readlines()
    
    # Create and run simulation
    sim = SecureAreaSimulation(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time,
    )
    
    result = sim.run(input_lines)
    result["test_name"] = args.test_name
    
    # Print output to stdout
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
