import argparse
import json
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class OutdoorTempReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(float, "outdoor_temp"))
        self.outdoor_temps = []
        self.current_time = 0
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("READ", 0)

    def lambdaf(self):
        if self.current_time >= 0:
            # Find the latest outdoor temperature for current_time
            temp = 25.0
            for t, val in self.outdoor_temps:
                if t <= self.current_time:
                    temp = val
                else:
                    break
            self.output["outdoor_temp"].add(temp)
        else:
            self.output["outdoor_temp"].add(25.0)

    def deltint(self):
        self.current_time += 1
        self.hold_in("READ", 1)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class RoomTempController(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(float, "room_temp"))
        self.add_in_port(Port(float, "outdoor_temp"))
        self.add_out_port(Port(int, "control_signal"))
        self.add_out_port(Port(float, "heater_output"))
        
        self.room_temp = 25.0
        self.prev_room_temp = 25.0
        self.prev_control_signal = 0
        self.current_time = 0
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAIT", 1)

    def lambdaf(self):
        self.output["control_signal"].add(self.prev_control_signal)
        self.output["heater_output"].add(0.5 if self.prev_control_signal == 1 else 0.0)

    def deltint(self):
        # Compute heat loss
        outdoor_temp = self.prev_outdoor_temp
        if outdoor_temp > self.prev_room_temp:
            effective_outdoor_temp = self.prev_room_temp
        else:
            effective_outdoor_temp = outdoor_temp
        heat_loss = 0.1 * (self.prev_room_temp - effective_outdoor_temp)
        heat_loss_temp = self.prev_room_temp - heat_loss
        
        # Apply heater output from previous step
        heater_output = 0.5 if self.prev_control_signal == 1 else 0.0
        self.room_temp = heat_loss_temp + heater_output
        
        # Determine next control signal
        if self.room_temp < 24.9:
            next_control_signal = 1
        else:
            next_control_signal = 0
            
        self.prev_room_temp = self.room_temp
        self.prev_control_signal = next_control_signal
        self.prev_outdoor_temp = self.input["outdoor_temp"].values[0] if self.input["outdoor_temp"].values else 25.0
        
        self.current_time += 1
        self.hold_in("WAIT", 1)

    def deltext(self, e):
        if self.input["room_temp"].values:
            self.prev_room_temp = self.input["room_temp"].values[0]
        if self.input["outdoor_temp"].values:
            self.prev_outdoor_temp = self.input["outdoor_temp"].values[0]
        self.hold_in("WAIT", 1)

    def exit(self):
        pass

class HouseHeatingSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, simulate_time: float):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = simulate_time
        
        # Create components
        self.outdoor_reader = OutdoorTempReader(name="outdoor_reader", parent=self)
        self.controller = RoomTempController(name="controller", parent=self)
        
        # Add components
        self.add_component(self.outdoor_reader)
        self.add_component(self.controller)
        
        # Define couplings
        self.add_coupling(self.outdoor_reader.output["outdoor_temp"], self.controller.input["outdoor_temp"])
        
        self.add_coupling(self.controller.output["control_signal"], Port(int, "control_signal"))
        self.add_coupling(self.controller.output["heater_output"], Port(float, "heater_output"))

class SimulationCoordinator:
    def __init__(self, simulate_time: float):
        self.simulate_time = simulate_time
        self.system = HouseHeatingSystem("system", None, simulate_time)
        self.coord = Coordinator(self.system, clock=SimulationClock(0))
        
        self.output_data = []
        self.current_time = 0
        self.prev_room_temp = 25.0
        self.prev_outdoor_temp = 25.0
        self.prev_control_signal = 0
        self.prev_heater_output = 0.0

    def run(self):
        self.coord.initialize()
        
        # Read outdoor temperatures from stdin
        outdoor_temps = []
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                continue
            try:
                h, m, s = map(int, parts[0].split(":"))
                timestamp = h * 3600 + m * 60 + s
                temp = float(parts[1])
                outdoor_temps.append((timestamp, temp))
            except ValueError:
                continue
        self.system.outdoor_reader.outdoor_temps = sorted(outdoor_temps)
        
        # Run simulation
        while self.current_time < self.simulate_time:
            self.coord.simulate_time(1.0)
            self.current_time += 1
            
            # Collect output
            # Get controller outputs
            control_signal = self.prev_control_signal
            heater_output = self.prev_heater_output
            
            # Compute heat loss
            if self.prev_outdoor_temp > self.prev_room_temp:
                effective_outdoor_temp = self.prev_room_temp
            else:
                effective_outdoor_temp = self.prev_outdoor_temp
            heat_loss = 0.1 * (self.prev_room_temp - effective_outdoor_temp)
            heat_loss_temp = self.prev_room_temp - heat_loss
            
            # Apply heater output from previous step
            self.prev_room_temp = heat_loss_temp + heater_output
            
            # Create output record
            record = {
                "time_sec": int(self.current_time),
                "room_temp_c": round(self.prev_room_temp, 2),
                "heat_loss_temp_c": round(heat_loss_temp, 2),
                "control_signal": control_signal,
                "heater_output_c": round(heater_output, 2)
            }
            print(json.dumps(record), file=sys.stdout, flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    args = parser.parse_args()
    
    sim = SimulationCoordinator(args.simulate_time)
    sim.run()

if __name__ == "__main__":
    main()