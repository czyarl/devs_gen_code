import argparse
import json
import sys
import logging
from typing import List, Dict, Any, Optional

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)

def parse_timestamp(ts_str: str) -> float:
    """
    Converts HH:MM:SS string to seconds since start of day.
    """
    parts = ts_str.strip().split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {ts_str}")
    h, m, s = map(int, parts)
    return h * 3600 + m * 60 + s

def parse_input_file(file_path: str) -> List[Dict[str, Any]]:
    """
    Parses the input file containing requests.
    Returns a list of dictionaries with keys: time, port, value.
    Sorted by time.
    """
    requests = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 3:
                    logger.warning(f"Skipping malformed line: {line}")
                    continue
                
                ts_str, port_str, val_str = parts
                time_sec = parse_timestamp(ts_str)
                port = int(port_str)
                value = int(val_str)
                
                requests.append({
                    "time": time_sec,
                    "port": port,
                    "value": value
                })
    except FileNotFoundError:
        logger.error(f"Input file not found: {file_path}")
        sys.exit(1)
        
    # Sort requests by time just in case
    requests.sort(key=lambda x: x["time"])
    return requests

def run_simulation(
    test_name: str,
    requests: List[Dict[str, Any]],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float
) -> Dict[str, Any]:
    """
    Runs the discrete event simulation.
    """
    
    # Simulation State
    current_state = "Disarmed"
    events: List[Dict[str, Any]] = []
    operations: List[Dict[str, Any]] = []
    
    # Admin status
    # Admin is busy if a request is being processed.
    # The processing completes at the authentication output time.
    admin_busy_until = -1.0
    
    # Helper to add event
    def add_event(time: float, component: str, message: str, state: Optional[str] = None):
        event = {
            "time": time,
            "component": component,
            "message": message
        }
        if state is not None:
            event["state"] = state
        events.append(event)

    # Process requests
    # Since this is a deterministic pipeline with a simple busy-check, 
    # we can calculate times sequentially.
    
    for req in requests:
        req_time = req["time"]
        req_val = req["value"]
        req_port = req["port"]
        
        # 1. Input Reader Event (Always happens)
        msg = f"{{{req_port} {req_val}}}"
        add_event(req_time, "input_reader", msg)
        
        # 2. Check if Admin is busy
        # Admin is busy if req_time < admin_busy_until
        # "If AlarmAdmin is already working on a previous request, the new request is ignored"
        if req_time < admin_busy_until:
            # Request ignored
            operations.append({
                "input_time": req_time,
                "action": "disarm" if req_val == 0 else "arm",
                "completed": False,
                "completion_time": None
            })
            continue
        
        # 3. Admin accepts request
        # Calculate pipeline times
        t_admin = req_time + alarm_admin_delay
        t_auth = t_admin + authentication_delay
        t_display = t_auth + display_delay
        
        # Update admin busy status
        # "The authentication output is also the time when AlarmAdmin stops working"
        admin_busy_until = t_auth
        
        # AlarmAdmin Event
        add_event(t_admin, "alarmAdmin", msg)
        
        # Authentication Event
        auth_state = "DisarmValid" if req_val == 0 else "ArmValid"
        add_event(t_auth, "authentication", msg, state=auth_state)
        
        # Update System State
        # "A redundant accepted request ... still passes through the full pipeline. 
        # It does not add a repeated state transition, but the display still emits the final state for that operation."
        # This implies the state *does* change to the requested value, even if redundant?
        # "does not add a repeated state transition" -> if it's already Armed, and we Arm, it stays Armed.
        # So state = requested state.
        new_state = "Disarmed" if req_val == 0 else "Armed"
        current_state = new_state
        
        # Display Event
        display_state = "Disarmed" if req_val == 0 else "Armed"
        add_event(t_display, "display", msg, state=display_state)
        
        # Record Operation
        operations.append({
            "input_time": req_time,
            "action": "disarm" if req_val == 0 else "arm",
            "completed": True,
            "completion_time": t_auth
        })

    # Determine final simulation time
    last_event_time = 0.0
    if events:
        last_event_time = events[-1]["time"]
    
    # Logic for simulation_time:
    # "normally the time of the last emitted event after all accepted display events are produced, 
    # or max_simulation_time only if the max time is reached before all accepted display events can be produced."
    # This phrasing implies that if the natural end of the simulation (last display event) 
    # occurs *after* the max_simulation_time, we report max_simulation_time.
    # However, if the natural end occurs *before* max_simulation_time, we report the natural end.
    
    if last_event_time > max_simulation_time:
        sim_time = max_simulation_time
    else:
        sim_time = last_event_time

    # Construct Output
    output = {
        "test_name": test_name,
        "simulation_time": sim_time,
        "initial_state": "Disarmed", # As per requirements
        "final_state": current_state,
        "events": events,
        "operations": operations
    }
    
    return output

def main():
    parser = argparse.ArgumentParser(description="Secure Area Access Control Simulation")
    parser.add_argument("--test_name", type=str, required=True, help="Name of the test")
    parser.add_argument("--input_file", type=str, required=False, help="Path to input file")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Delay for AlarmAdmin")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Delay for Authentication")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Delay for Display")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Maximum simulation time")
    
    args = parser.parse_args()
    
    # Parse input
    requests = []
    if args.input_file:
        requests = parse_input_file(args.input_file)
    
    # Run simulation
    result = run_simulation(
        test_name=args.test_name,
        requests=requests,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Output JSON to stdout
    print(json.dumps(result))

if __name__ == "__main__":
    main()