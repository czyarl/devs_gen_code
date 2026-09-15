import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_id = 0
        self.add_out_port(Port("pallet", "pallet_generated"))

    def initialize(self):
        self.pallet_id = 0
        self.output["pallet_generated"].add({"pallet_id": self.pallet_id, "expiration_time": self.pallet_interval})
        self.hold_in("idle", self.pallet_interval)

    def lambdaf(self):
        pass

    def deltint(self):
        self.pallet_id += 1
        self.output["pallet_generated"].add({"pallet_id": self.pallet_id, "expiration_time": self.global_time + self.pallet_interval})
        self.hold_in("idle", self.pallet_interval)

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
        self.add_in_port(Port("pallet", "pallet_arrived"))
        self.add_out_port(Port("pallet", "pallet_queued"))
        self.add_out_port(Port("pallet", "pallet_expired"))

    def initialize(self):
        self.pallets = []

    def lambdaf(self):
        pass

    def deltint(self):
        current_time = self.global_time
        expired_pallets = [p for p in self.pallets if p['expiration_time'] <= current_time]
        for p in expired_pallets:
            self.pallets.remove(p)
            self.output["pallet_expired"].add({"pallet_id": p['id'], "total_expired": len(expired_pallets)})
        if self.pallets:
            self.output["pallet_queued"].add({"pallet_id": self.pallets[0]['id'], "queue_size": len(self.pallets)})
        self.hold_in("idle", 1)

    def deltext(self, e):
        if e['port'] == 'pallet_arrived':
            self.pallets.append({'id': e['value']['pallet_id'], 'expiration_time': e['value']['expiration_time']})
            self.output["pallet_queued"].add({"pallet_id": e['value']['pallet_id'], "queue_size": len(self.pallets)})
        self.hold_in("idle", 1)

    def exit(self):
        pass

class FleetCoordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        self.aircraft = [f"Aircraft-{i}" for i in range(num_aircraft)]
        self.add_in_port(Port("pallet", "pallet_available"))
        self.add_out_port(Port("assignment", "assignment_created"))

    def initialize(self):
        self.assigned_pallets = {}

    def lambdaf(self):
        pass

    def deltint(self):
        available_aircraft = [a for a in self.aircraft if a not in self.assigned_pallets]
        if available_aircraft and self.input["pallet_available"].values:
            pallet = self.input["pallet_available"].values[0]
            aircraft = available_aircraft[0]
            self.assigned_pallets[aircraft] = pallet['pallet_id']
            self.output["assignment_created"].add({"aircraft_id": aircraft, "pallet_id": pallet['pallet_id']})
        self.hold_in("idle", 1)

    def deltext(self, e):
        if e['port'] == 'pallet_available':
            self.hold_in("idle", 1)

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
        self.add_in_port(Port("assignment", "assignment_received"))
        self.add_out_port(Port("event", "depart"))
        self.add_out_port(Port("event", "return"))
        self.add_out_port(Port("event", "maintenance_start"))
        self.add_out_port(Port("event", "maintenance_end"))

    def initialize(self):
        self.phase = "idle"

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "idle":
            self.hold_in("idle", 1)
        elif self.phase == "loaded":
            self.output["depart"].add({"aircraft_id": self.name, "pallet_id": self.pallet_id})
            self.phase = "flying"
            self.hold_in("flying", self.flight_time)
        elif self.phase == "flying":
            self.phase = "unloading"
            self.hold_in("unloading", self.unload_time)
        elif self.phase == "unloading":
            self.phase = "returning"
            self.hold_in("returning", self.return_time)
        elif self.phase == "returning":
            self.phase = "maintenance"
            self.output["maintenance_start"].add({"aircraft_id": self.name})
            self.hold_in("maintenance", self.maintenance_time)
        elif self.phase == "maintenance":
            self.output["maintenance_end"].add({"aircraft_id": self.name})
            self.phase = "idle"
            self.hold_in("idle", 1)

    def deltext(self, e):
        if e['port'] == 'assignment_received':
            self.pallet_id = e['value']['pallet_id']
            self.phase = "loaded"
            self.hold_in("loaded", 0)

    def exit(self):
        pass

class Destination(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("pallet", "pallet_delivered"))

    def initialize(self):
        self.delivered_pallets = []

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("idle", 1)

    def deltext(self, e):
        if e['port'] == 'pallet_delivered':
            self.delivered_pallets.append(e['value'])
            self.output["pallet_delivered"].add({"pallet_id": e['value']['pallet_id'], "aircraft_id": e['value']['aircraft_id'], "latency": e['value']['latency']})
        self.hold_in("idle", 1)

    def exit(self):
        pass

class AirfreightLogistics(Coupled):
    def __init__(self, name: str, parent: Coupled | None, 
                 duration: float, num_aircraft: int, pallet_interval: float, 
                 pallet_expiration_time: float, flight_time: float, unload_time: float, 
                 return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent

        self.facility = Facility(name="facility", parent=self, pallet_interval=pallet_interval)
        self.add_component(self.facility)

        self.queue = LoadingQueue(name="queue", parent=self, pallet_expiration_time=pallet_expiration_time)
        self.add_component(self.queue)

        self.coordinator = FleetCoordinator(name="coordinator", parent=self, num_aircraft=num_aircraft)
        self.add_component(self.coordinator)

        self.aircraft = []
        for i in range(num_aircraft):
            aircraft = Aircraft(name=f"Aircraft-{i}", parent=self, flight_time=flight_time, unload_time=unload_time, return_time=return_time, maintenance_time=maintenance_time)
            self.add_component(aircraft)
            self.aircraft.append(aircraft)

        self.destination = Destination(name="destination", parent=self)
        self.add_component(self.destination)

        self.add_coupling(self.facility.output["pallet_generated"], self.queue.input["pallet_arrived"])
        self.add_coupling(self.queue.output["pallet_queued"], self.coordinator.input["pallet_available"])
        self.add_coupling(self.coordinator.output["assignment_created"], [a.input["assignment_received"] for a in self.aircraft])
        self.add_coupling([a.output["depart"] for a in self.aircraft], self.destination.input["pallet_delivered"])
        self.add_coupling([a.output["maintenance_start"] for a in self.aircraft], self.coordinator.input["maintenance_completed"])

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
                               flight_time=args.flight_time, unload_time=args.unload_time, 
                               return_time=args.return_time, maintenance_time=args.maintenance_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.duration)

    for event in root.facility.events:
        print(json.dumps({"time": event['time'], "entity": "facility", "event": event['event'], "payload": event['payload']}), file=sys.stdout, flush=True)

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr)
    main()