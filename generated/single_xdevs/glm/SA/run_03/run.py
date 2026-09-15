import argparse
import sys
import json
import logging

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("xdevs_simulation")

# --- Helper for Output ---
def log_event(time: float, entity: str, event: str, payload: dict):
    """Prints a JSONL event to stdout."""
    print(json.dumps({
        "time": time,
        "entity": entity,
        "event": event,
        "payload": payload
    }), file=sys.stdout, flush=True)

# --- Atomic Models ---

class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled | None, pallet_interval: float, pallet_expiration_time: float):
        super().__init__(name)
        self.parent = parent
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        
        self.pallet_counter = 0
        self.current_pallet = None
        
        self.out_pallet = Port(object, "out_pallet")
        self.add_out_port(self.out_pallet)
        
    def initialize(self):
        # Generate first pallet immediately at t=0
        self.pallet_counter += 1
        self.current_pallet = {
            "pallet_id": self.pallet_counter,
            "generation_time": 0.0, 
            "expiration_deadline": self.pallet_expiration_time 
        }
        self.hold_in("active", self.pallet_interval)

    def deltint(self):
        self.hold_in("active", self.pallet_interval)
        
    def deltext(self, e):
        pass

    def lambdaf(self):
        gen_time = self.clock.get_time()
        self.current_pallet["generation_time"] = gen_time
        self.current_pallet["expiration_deadline"] = gen_time + self.pallet_expiration_time
        
        log_event(
            time=gen_time,
            entity="facility",
            event="pallet_generated",
            payload={
                "pallet_id": self.current_pallet["pallet_id"],
                "expiration_time": self.current_pallet["expiration_deadline"]
            }
        )
        
        self.out_pallet.add(self.current_pallet)
        
        self.pallet_counter += 1
        self.current_pallet = {
            "pallet_id": self.pallet_counter,
            "generation_time": 0.0, 
            "expiration_deadline": 0.0
        }

    def exit(self):
        pass

class LoadingQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.queue = []
        self.total_expired = 0
        self.next_expiration = float('inf')
        
        self.in_pallet = Port(object, "in_pallet")
        self.add_in_port(self.in_pallet)
        
        self.in_request = Port(object, "in_request")
        self.add_in_port(self.in_request)
        
        self.out_pallet_data = Port(object, "out_pallet_data")
        self.add_out_port(self.out_pallet_data)
        
        self.out_notify = Port(object, "out_notify")
        self.add_out_port(self.out_notify)
        
        self.out_expired = Port(object, "out_expired")
        self.add_out_port(self.out_expired)

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def deltint(self):
        current_time = self.clock.get_time()
        
        to_remove = []
        for p in self.queue:
            if p["expiration_deadline"] <= current_time:
                to_remove.append(p)
        
        for p in to_remove:
            self.queue.remove(p)
            self.total_expired += 1
            log_event(
                time=current_time,
                entity="queue",
                event="pallet_expired",
                payload={
                    "pallet_id": p["pallet_id"],
                    "total_expired": self.total_expired
                }
            )
            self.out_expired.add(p)

        if self.queue:
            min_deadline = min(p["expiration_deadline"] for p in self.queue)
            self.next_expiration = min_deadline
            self.hold_in("has_items", max(0.0, min_deadline - current_time))
        else:
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        current_time = self.clock.get_time()
        
        for p in self.in_pallet.values:
            self.queue.append(p)
            log_event(
                time=current_time,
                entity="queue",
                event="pallet_queued",
                payload={
                    "pallet_id": p["pallet_id"],
                    "queue_size": len(self.queue)
                }
            )
        
        has_request = len(self.in_request.values) > 0
        
        if self.queue:
            min_deadline = min(p["expiration_deadline"] for p in self.queue)
            self.next_expiration = min_deadline
            time_to_expire = max(0.0, min_deadline - current_time)
            
            if has_request:
                self.hold_in("responding", 0.0)
            else:
                self.hold_in("has_items", time_to_expire)
        else:
            self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "responding":
            if self.queue:
                p = self.queue.pop(0)
                self.out_pallet_data.add(p)
                if self.queue:
                    self.out_notify.add("available")

    def exit(self):
        pass

class FleetCoordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        
        self.idle_aircraft = list(range(1, num_aircraft + 1))
        
        self.request_to_send = False
        self.assign_to_send = None
        
        self.in_pallet_data = Port(object, "in_pallet_data")
        self.add_in_port(self.in_pallet_data)
        self.in_notify = Port(object, "in_notify")
        self.add_in_port(self.in_notify)
        self.in_aircraft_status = Port(object, "in_aircraft_status")
        self.add_in_port(self.in_aircraft_status)
        
        self.out_request = Port(object, "out_request")
        self.add_out_port(self.out_request)
        self.out_assign = Port(object, "out_assign")
        self.add_out_port(self.out_assign)

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def deltint(self):
        self.hold_in("idle", float('inf'))

    def deltext(self, e):
        current_time = self.clock.get_time()
        
        for msg in self.in_aircraft_status.values:
            if msg["state"] == "idle":
                if msg["aircraft_id"] not in self.idle_aircraft:
                    self.idle_aircraft.append(msg["aircraft_id"])
        
        received_pallets = list(self.in_pallet_data.values)
        has_notify = len(self.in_notify.values) > 0
        
        if received_pallets:
            p = received_pallets[0]
            if self.idle_aircraft:
                ac_id = self.idle_aircraft.pop(0)
                log_event(
                    time=current_time,
                    entity="coordinator",
                    event="assignment_created",
                    payload={"aircraft_id": ac_id, "pallet_id": p["pallet_id"]}
                )
                self.assign_to_send = {"aircraft_id": ac_id, "pallet": p}
                self.hold_in("outputting", 0.0)
            else:
                pass
        
        elif has_notify and self.idle_aircraft:
            self.request_to_send = True
            self.hold_in("outputting", 0.0)
        else:
            self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "outputting":
            if self.request_to_send:
                self.out_request.add("request")
                self.request_to_send = False
            if self.assign_to_send:
                self.out_assign.add(self.assign_to_send)
                self.assign_to_send = None

    def exit(self):
        pass

class Aircraft(Atomic):
    def __init__(self, name: str, parent: Coupled | None, aircraft_id: int, 
                 flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        
        self.current_pallet = None
        
        self.in_assign = Port(object, "in_assign")
        self.add_in_port(self.in_assign)
        self.out_status = Port(object, "out_status")
        self.add_out_port(self.out_status)
        self.out_delivery = Port(object, "out_delivery")
        self.add_out_port(self.out_delivery)

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def deltint(self):
        if self.phase == "loading": self.hold_in("flying", self.flight_time)
        elif self.phase == "flying": self.hold_in("unloading", self.unload_time)
        elif self.phase == "unloading": self.hold_in("returning", self.return_time)
        elif self.phase == "returning": self.hold_in("evt_return", 0.0)
        elif self.phase == "evt_return": self.hold_in("doing_maint", self.maintenance_time)
        elif self.phase == "doing_maint": self.hold_in("evt_maint_end", 0.0)
        elif self.phase == "evt_maint_end": self.hold_in("enter_idle", 0.0)
        elif self.phase == "enter_idle": self.hold_in("idle", float('inf'))
        elif self.phase == "idle": self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            for msg in self.in_assign.values:
                if msg["aircraft_id"] == self.aircraft_id:
                    self.current_pallet = msg["pallet"]
                    self.hold_in("loading", 0.0)

    def lambdaf(self):
        t = self.clock.get_time()
        if self.phase == "loading":
            log_event(t, "aircraft", "depart", {"aircraft_id": self.aircraft_id, "pallet_id": self.current_pallet["pallet_id"]})
        elif self.phase == "unloading":
            if self.current_pallet:
                lat = t - self.current_pallet["generation_time"]
                self.out_delivery.add({"pallet": self.current_pallet, "aircraft_id": self.aircraft_id})
                self.current_pallet = None
        elif self.phase == "evt_return":
            log_event(t, "aircraft", "return", {"aircraft_id": self.aircraft_id})
            log_event(t, "aircraft", "maintenance_start", {"aircraft_id": self.aircraft_id})
        elif self.phase == "evt_maint_end":
            log_event(t, "aircraft", "maintenance_end", {"aircraft_id": self.aircraft_id})
        elif self.phase == "enter_idle":
            self.out_status.add({"aircraft_id": self.aircraft_id, "state": "idle"})

    def exit(self):
        pass

class Destination(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.in_delivery = Port(object, "in_delivery")
        self.add_in_port(self.in_delivery)

    def initialize(self):
        self.hold_in("passive", float('inf'))

    def deltint(self):
        self.hold_in("passive", float('inf'))

    def deltext(self, e):
        t = self.clock.get_time()
        for msg in self.in_delivery.values:
            p = msg["pallet"]
            ac_id = msg["aircraft_id"]
            latency = t - p["generation_time"]
            log_event(
                time=t,
                entity="destination",
                event="pallet_delivered",
                payload={
                    "pallet_id": p["pallet_id"],
                    "aircraft_id": ac_id,
                    "latency": latency
                }
            )

    def lambdaf(self):
        pass

    def exit(self):
        pass

# --- Coupled Model ---

class AirfreightSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, args):
        super().__init__(name)
        self.parent = parent
        self.args = args
        
        self.facility = Facility(name="facility", parent=self, 
                                 pallet_interval=args.pallet_interval, 
                                 pallet_expiration_time=args.pallet_expiration_time)
        self.add_component(self.facility)
        
        self.queue = LoadingQueue(name="loading_queue", parent=self)
        self.add_component(self.queue)
        
        self.coordinator = FleetCoordinator(name="coordinator", parent=self, 
                                             num_aircraft=args.num_aircraft)
        self.add_component(self.coordinator)
        
        self.aircrafts = []
        for i in range(args.num_aircraft):
            ac = Aircraft(name=f"aircraft_{i+1}", parent=self, aircraft_id=i+1,
                          flight_time=args.flight_time, unload_time=args.unload_time,
                          return_time=args.return_time, maintenance_time=args.maintenance_time)
            self.aircrafts.append(ac)
            self.add_component(ac)
            
        self.destination = Destination(name="destination", parent=self)
        self.add_component(self.destination)
        
        self.add_coupling(self.facility.out_pallet, self.queue.in_pallet)
        self.add_coupling(self.queue.out_notify, self.coordinator.in_notify)
        self.add_coupling(self.coordinator.out_request, self.queue.in_request)
        self.add_coupling(self.queue.out_pallet_data, self.coordinator.in_pallet_data)
        
        for ac in self.aircrafts:
            self.add_coupling(self.coordinator.out_assign, ac.in_assign)
            self.add_coupling(ac.out_status, self.coordinator.in_aircraft_status)
            self.add_coupling(ac.out_delivery, self.destination.in_delivery)

# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Airfreight Logistics Simulation")
    parser.add_argument("--duration", type=float, default=10000.0, help="Total simulation time")
    parser.add_argument("--num_aircraft", type=int, default=2, help="Number of aircraft")
    parser.add_argument("--pallet_interval", type=float, default=25.0, help="Pallet generation interval")
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0, help="Pallet expiration time")
    parser.add_argument("--flight_time", type=float, default=30.0, help="Flight duration")
    parser.add_argument("--unload_time", type=float, default=2.0, help="Unload duration")
    parser.add_argument("--return_time", type=float, default=30.0, help="Return duration")
    parser.add_argument("--maintenance_time", type=float, default=10.0, help="Maintenance duration")
    
    args = parser.parse_args()
    
    system = AirfreightSystem(name="airfreight_system", parent=None, args=args)
    
    clock = SimulationClock(max_time=args.duration)
    coord = Coordinator(system, clock=clock)
    
    coord.initialize()
    coord.simulate()

if __name__ == "__main__":
    main()