import argparse
import json
import simpy

def parse_time(time_str):
    """Converts HH:MM:SS string to total seconds."""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def main():
    # 1. Parse Command Line Arguments
    parser = argparse.ArgumentParser(description="Secure Area Access Control Simulation")
    parser.add_argument("--test_name", type=str, required=True, help="Name of the test")
    parser.add_argument("--input_file", type=str, help="Path to the input file")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Delay for AlarmAdmin")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Delay for Authentication")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Delay for Display")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Maximum simulation time")
    
    args = parser.parse_args()

    # 2. Read and Parse Input File
    inputs = []
    if args.input_file:
        try:
            with open(args.input_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    
                    time_str = parts[0]
                    port = int(parts[1])
                    value = int(parts[2])
                    
                    t = parse_time(time_str)
                    inputs.append((t, port, value))
        except FileNotFoundError:
            # If file not found, inputs remains empty
            pass

    # Sort inputs by time to ensure operations are listed in chronological order
    inputs.sort(key=lambda x: x[0])

    # 3. Initialize Simulation Environment
    env = simpy.Environment()
    # Resource to model the AlarmAdmin being busy or free
    admin_resource = simpy.Resource(env, capacity=1)
    
    events = []
    operations = []
    
    # Initialize operations list with default values
    for t, p, v in inputs:
        operations.append({
            "input_time": t,
            "action": "disarm" if v == 0 else "arm",
            "completed": False,
            "completion_time": None
        })

    # System state container (using list for mutability within nested function scope)
    current_state = ["Disarmed"]

    # 4. Define Simulation Process
    def request_process(idx, t, port, value):
        # Wait until the input time
        yield env.timeout(t - env.now)

        # Record input_reader event
        events.append({
            "time": env.now,
            "component": "input_reader",
            "message": f"{{{port} {value}}}"
        })

        # Check if AlarmAdmin is busy
        # admin_resource.count is the number of currently active users
        if admin_resource.count < admin_resource.capacity:
            # Request is Accepted
            operations[idx]['completed'] = True
            
            # Acquire AlarmAdmin
            req = admin_resource.request()
            yield req

            # AlarmAdmin Delay
            yield env.timeout(args.alarm_admin_delay)
            events.append({
                "time": env.now,
                "component": "alarmAdmin",
                "message": f"{{{port} {value}}}"
            })

            # Authentication Delay
            yield env.timeout(args.authentication_delay)
            
            # Record Authentication Event
            auth_state = "DisarmValid" if value == 0 else "ArmValid"
            events.append({
                "time": env.now,
                "component": "authentication",
                "message": f"{{{port} {value}}}",
                "state": auth_state
            })

            # Update System State
            current_state[0] = "Disarmed" if value == 0 else "Armed"
            
            # Record completion time
            operations[idx]['completion_time'] = env.now

            # Release AlarmAdmin (Admin stops working at authentication output)
            admin_resource.release(req)

            # Display Delay
            yield env.timeout(args.display_delay)
            
            # Record Display Event
            disp_state = "Disarmed" if value == 0 else "Armed"
            events.append({
                "time": env.now,
                "component": "display",
                "message": f"{{{port} {value}}}",
                "state": disp_state
            })
        else:
            # Request is Ignored
            # operations[idx] already has completed=False and completion_time=None
            pass

    # 5. Schedule Processes
    for i, inp in enumerate(inputs):
        env.process(request_process(i, inp[0], inp[1], inp[2]))

    # 6. Run Simulation
    env.run(until=args.max_simulation_time)

    # 7. Prepare Output
    # Sort events by time (nondecreasing)
    events.sort(key=lambda x: x['time'])

    output = {
        "test_name": args.test_name,
        "simulation_time": env.now,
        "initial_state": "Disarmed",
        "final_state": current_state[0],
        "events": events,
        "operations": operations
    }

    # 8. Print JSON to stdout
    print(json.dumps(output))

if __name__ == "__main__":
    main()