import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_id = 0
        self.add_out_port(Port("pallet", "pallet_generated"))

    def initialize(self):
        self.pallet_id = 0
        self.output["pallet_generated"].add({"pallet_id": self.pallet_id, "expiration_time": self.global_time + self.pallet_expiration_time})
        self.hold_in("generate_pallet", self.pallet_interval)

    def lambdaf(self):
        pass

    def deltint(self):
        self.pallet_id += 1
        self.output["pallet_generated"].add({"pallet_id": self.pallet_id, "expiration_time": self.global_time + self.pallet_expiration_time})
        self.hold_in("generate_pallet", self.pallet_interval)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class LoadingQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_expiration_time = pallet_expiration_time
        self.pallets = []
        self.expired_pallets = 0
        self.add_in_port(Port("pallet", "pallet_arrived"))
        self.add_out_port(Port("pallet", "pallet_expired"))
        self.add_out_port(Port("pallet", "pallet_assigned"))

    def initialize(self):
        self.pallets = []
        self.expired_pallets = 0

    def lambdaf(self):
        pass

    def deltint(self):
        current_time = self.global_time
        self.pallets = [p for p in self.pallets if p['expiration_time'] > current_time]
        if self.pallets:
            self.output["pallet_assigned"].add(self.pallets[0])

    def deltext(self, e):
        for msg in e:
            if msg.port == "pallet_arrived":
                pallet = msg.value
                self.pallets.append({"pallet_id": pallet["pallet_id"], "expiration_time": pallet["expiration_time"]})
                self.output["pallet_queued"].add({"pallet_id": pallet["pallet_id"], "queue_size": len(self.pallets)})

    def exit(self):
        pass

class FleetCoordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        self.aircraft = [f"Aircraft-{i}" for i in range(num_aircraft)]
        self.add_in_port(Port("pallet", "pallet_assigned"))
        self.add_out_port(Port("pallet", "assignment_created"))

    def initialize(self):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for msg in e:
            if msg.port == "pallet_assigned":
                pallet = msg.value
                # Assign pallet to aircraft
                aircraft_id = random.choice(self.aircraft)
                self.output["assignment_created"].add({"aircraft_id": aircraft_id, "pallet_id": pallet["pallet_id"]})

    def exit(self):
        pass

class Aircraft(Atomic):
    def __init__(self, name: str, parent: Coupled | None, flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.add_in_port(Port("pallet", "assignment_created"))
        self.add_out_port(Port("pallet", "depart"))
        self.add_out_port(Port("pallet", "return"))
        self.add_out_port(Port("pallet", "maintenance_start"))
        self.add_out_port(Port("pallet", "maintenance_end"))

    def initialize(self):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for msg in e:
            if msg.port == "assignment_created":
                # Load pallet and depart
                self.output["depart"].add({"aircraft_id": self.name, "pallet_id": msg.value["pallet_id"]})

    def exit(self):
        pass

class Destination(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("pallet", "pallet_delivered"))

    def initialize(self):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        for msg in e:
            if msg.port == "pallet_delivered":
                # Log delivery
                pass

    def exit(self):
        pass

class AirfreightLogistics(Coupled):
    def __init__(self, name: str, parent: Coupled | None, 
                 duration: float, num_aircraft: int, 
                 pallet_interval: float, pallet_expiration_time: float,
                 flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent

        self.facility = Facility(name="facility", parent=self, pallet_interval=pallet_interval, pallet_expiration_time=pallet_expiration_time)
        self.add_component(self.facility)

        self.loading_queue = LoadingQueue(name="loading_queue", parent=self, pallet_expiration_time=pallet_expiration_time)
        self.add_component(self.loading_queue)

        self.fleet_coordinator = FleetCoordinator(name="fleet_coordinator", parent=self, num_aircraft=num_aircraft)
        self.add_component(self.fleet_coordinator)

        self.aircraft = []
        for i in range(num_aircraft):
            aircraft = Aircraft(name=f"aircraft-{i}", parent=self, flight_time=flight_time, unload_time=unload_time, return_time=return_time, maintenance_time=maintenance_time)
            self.add_component(aircraft)
            self.aircraft.append(aircraft)

        self.destination = Destination(name="destination", parent=self)
        self.add_component(self.destination)

        self.add_coupling(self.facility.output["pallet_generated"], self.loading_queue.input["pallet_arrived"])
        self.add_coupling(self.loading_queue.output["pallet_assigned"], self.fleet_coordinator.input["pallet_assigned"])
        self.add_coupling(self.fleet_coordinator.output["assignment_created"], self.aircraft[0].input["assignment_created"])

    def exit(self):
        pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=10000.0)
    parser.add_argument("--num_aircraft", type=int, default=2)
    parser.add_argument("--pallet_interval", type=float, default=25.0)
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0)
    parser.add_argument("--flight_time", type=float, default=30.0)
    parser.add_argument("--unload_time", type=float, default=2.0)
    parser.add_argument("--return_time", type=float, default=30.0)
    parser.add_argument("--maintenance_time", type=float, default=10.0)

    args = parser.parse_args()

    root = AirfreightLogistics(name="airfreight_logistics", parent=None, 
                               duration=args.duration, num_aircraft=args.num_aircraft, 
                               pallet_interval=args.pallet_interval, pallet_expiration_time=args.pallet_expiration_time,
                               flight_time=args.flight_time, unload_time=args.unload_time, return_time=args.return_time, maintenance_time=args.maintenance_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.duration)

if __name__ == "__main__":
    main()