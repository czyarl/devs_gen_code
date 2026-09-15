import argparse
import sys
import json
import random
import logging
from collections import deque

# xdevs imports
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Setup logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AirfreightSim")

# --- Helper Functions for Output ---

def log_event(time, entity, event, payload):
    """Helper to print JSONL to stdout."""
    try:
        output = {
            "time": float(time),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(output), file=sys.stdout, flush=True)
    except Exception as e:
        logger.error(f"Error logging event: {e}")

# --- Constants for Phases ---

PHASE_IDLE = "IDLE"
PHASE_GENERATING = "GENERATING"
PHASE_WAITING = "WAITING"
PHASE_SENDING = "SENDING"
PHASE_FLYING = "FLYING"
PHASE_UNLOADING = "UNLOADING"
PHASE_RETURNING = "RETURNING"
PHASE_MAINTENANCE = "MAINTENANCE"

# --- Data Structures ---

class Pallet:
    def __init__(self, p_id, gen_time, expiration_time):
        self.id = p_id
        self.gen_time = gen_time
        self.expiration_time = expiration_time

# --- Atomic Models ---

class Facility(Atomic):
    def __init__(self, name: str, parent: Coupled | None, interval: float, expiration_time: float):
        super().__init__(name)
        self.parent = parent
        
        # Configuration
        self.interval = interval
        self.expiration_time = expiration_time
        self.next_pallet_id = 1
        
        # Ports
        self.out_pallet = Port(Pallet, "out_pallet")
        self.add_out_port(self.out_pallet)
        
        # State
        self.hold_in(PHASE_IDLE, 0.0)

    def initialize(self):
        # Trigger first generation immediately
        self.hold_in(PHASE_GENERATING, 0.0)

    def lambdaf(self):
        if self.phase == PHASE_GENERATING:
            current_time = self.clock.get_time()
            p_id = self.next_pallet_id
            expiration = current_time + self.expiration_time
            
            # Create Pallet object
            p = Pallet(p_id, current_time, expiration)
            
            self.out_pallet.add(p)
            
            # Log Event
            log_event(current_time, "facility", "pallet_generated", {
                "pallet_id": p_id,
                "expiration_time": expiration
            })
            
            self.next_pallet_id += 1

    def deltint(self):
        if self.phase == PHASE_GENERATING:
            # Schedule next generation
            self.hold_in(PHASE_GENERATING, self.interval)

    def deltext(self, e):
        # Facility doesn't receive inputs
        pass

    def exit(self):
        pass


class LoadingQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.queue = deque()
        self.total_expired = 0
        
        self.in_pallet = Port(Pallet, "in_pallet")
        self.in_req = Port(object, "in_req") 
        
        self.out_pallet = Port(Pallet, "out_pallet")
        self.out_expired = Port(int, "out_expired") 
        
        self.add_in_port(self.in_pallet)
        self.add_in_port(self.in_req)
        self.add_out_port(self.out_pallet)
        self.add_out_port(self.out_expired)
        
        self.hold_in(PHASE_WAITING, float('inf'))

    def initialize(self):
        self.hold_in(PHASE_WAITING, float('inf'))

    def deltint(self):
        # Internal transition happens when a pallet expires.
        if self.phase == PHASE_WAITING:
            if self.queue:
                p = self.queue.popleft()
                self.total_expired += 1
                
                # Log Event
                log_event(self.clock.get_time(), "queue", "pallet_expired", {
                    "pallet_id": p.id,
                    "total_expired": self.total_expired
                })
                
                # Schedule next expiration check
                self.schedule_next_expiration()
            else:
                self.hold_in(PHASE_WAITING, float('inf'))

    def deltext(self, e):
        current_time = self.clock.get_time()
        
        # 1. Process incoming pallets
        if self.in_pallet:
            for p in self.in_pallet.values:
                self.queue.append(p)
                # Log Event
                log_event(current_time, "queue", "pallet_queued", {
                    "pallet_id": p.id,
                    "queue_size": len(self.queue)
                })
        
        # 2. Process requests from Coordinator
        if self.in_req:
            if self.queue:
                # We will output the head pallet
                self.hold_in(PHASE_SENDING, 0.0)
            else:
                self.schedule_next_expiration()

    def lambdaf(self):
        if self.phase == PHASE_SENDING:
            if self.queue:
                p = self.queue.popleft()
                self.out_pallet.add(p)
                self.schedule_next_expiration()

    def schedule_next_expiration(self):
        if not self.queue:
            self.hold_in(PHASE_WAITING, float('inf'))
        else:
            head = self.queue[0]
            time_to_expire = head.expiration_time - self.clock.get_time()
            if time_to_expire < 0:
                time_to_expire = 0
            self.hold_in(PHASE_WAITING, time_to_expire)

    def exit(self):
        pass


class Coordinator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        
        # State
        self.aircraft_status = {} 
        for i in range(num_aircraft):
            self.aircraft_status[i] = "idle"
        
        self.pending_pallet = None 
        
        # Ports
        self.in_pallet = Port(Pallet, "in_pallet") 
        self.in_status = Port(dict, "in_status") 
        
        self.out_req_pallet = Port(object, "out_req_pallet") 
        self.out_assign = Port(dict, "out_assign") 
        
        self.add_in_port(self.in_pallet)
        self.add_in_port(self.in_status)
        self.add_out_port(self.out_req_pallet)
        self.add_out_port(self.out_assign)
        
        self.hold_in("ACTIVE", 0.0)

    def initialize(self):
        self.hold_in("ACTIVE", 0.0)

    def deltint(self):
        if self.phase == "ASSIGNING":
            self.pending_pallet = None
            has_idle = any(s == "idle" for s in self.aircraft_status.values())
            if has_idle and not self.pending_pallet:
                 self.hold_in("REQ_PALLET", 0.0)
            else:
                 self.hold_in("ACTIVE", float('inf'))
                 
        elif self.phase == "REQ_PALLET":
            self.hold_in("WAITING_PALLET", float('inf'))
            
        elif self.phase == "ACTIVE":
            has_idle = any(s == "idle" for s in self.aircraft_status.values())
            
            if self.pending_pallet and has_idle:
                self.hold_in("ASSIGNING", 0.0)
            elif not self.pending_pallet:
                self.hold_in("REQ_PALLET", 0.0)
            else:
                self.hold_in("ACTIVE", float('inf'))

    def deltext(self, e):
        if self.in_status:
            for msg in self.in_status.values:
                self.aircraft_status[msg["aircraft_id"]] = msg["status"]
        
        if self.in_pallet:
            for p in self.in_pallet.values:
                self.pending_pallet = p
        
        self.hold_in("ACTIVE", 0.0)

    def lambdaf(self):
        if self.phase == "REQ_PALLET":
            self.out_req_pallet.add(True)
        elif self.phase == "ASSIGNING":
            if self.pending_pallet:
                for aid, status in self.aircraft_status.items():
                    if status == "idle":
                        self.aircraft_status[aid] = "busy" 
                        
                        payload = {
                            "aircraft_id": aid,
                            "pallet_id": self.pending_pallet.id,
                            "pallet_obj": self.pending_pallet 
                        }
                        self.out_assign.add(payload)
                        
                        log_event(self.clock.get_time(), "coordinator", "assignment_created", {
                            "aircraft_id": aid,
                            "pallet_id": self.pending_pallet.id
                        })
                        break

    def exit(self):
        pass


class Aircraft(Atomic):
    def __init__(self, name: str, parent: Coupled | None, ac_id: int, 
                 flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        super().__init__(name)
        self.parent = parent
        self.id = ac_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        
        self.current_pallet = None
        
        self.in_assign = Port(dict, "in_assign")
        self.out_status = Port(dict, "out_status")
        self.out_delivered = Port(dict, "out_delivered") 
        
        self.add_in_port(self.in_assign)
        self.add_out_port(self.out_status)
        self.add_out_port(self.out_delivered)
        
        self.hold_in(PHASE_IDLE, float('inf'))

    def initialize(self):
        self.out_status.add({"aircraft_id": self.id, "status": "idle"})
        self.hold_in(PHASE_IDLE, float('inf'))

    def deltint(self):
        if self.phase == PHASE_FLYING:
            self.hold_in(PHASE_UNLOADING, self.unload_time)
        elif self.phase == PHASE_UNLOADING:
            self.hold_in(PHASE_RETURNING, self.return_time)
        elif self.phase == PHASE_RETURNING:
            self.hold_in(PHASE_MAINTENANCE, self.maintenance_time)
        elif self.phase == PHASE_MAINTENANCE:
            self.hold_in(PHASE_IDLE, float('inf'))

    def deltext(self, e):
        if self.in_assign:
            for msg in self.in_assign.values:
                if msg["aircraft_id"] == self.id:
                    self.current_pallet = msg["pallet_obj"]
                    log_event(self.clock.get_time(), "aircraft", "depart", {
                        "aircraft_id": self.id,
                        "pallet_id": self.current_pallet.id
                    })
                    self.hold_in(PHASE_FLYING, self.flight_time)

    def lambdaf(self):
        if self.phase == PHASE_IDLE:
            self.out_status.add({"aircraft_id": self.id, "status": "idle"})
        elif self.phase == PHASE_MAINTENANCE:
            self.out_status.add({"aircraft_id": self.id, "status": "idle"})
            log_event(self.clock.get_time(), "aircraft", "maintenance_end", {
                "aircraft_id": self.id
            })
        elif self.phase == PHASE_RETURNING:
            log_event(self.clock.get_time(), "aircraft", "return", {
                "aircraft_id": self.id
            })
            log_event(self.clock.get_time(), "aircraft", "maintenance_start", {
                "aircraft_id": self.id
            })
        elif self.phase == PHASE_UNLOADING:
            if self.current_pallet:
                latency = self.clock.get_time() - self.current_pallet.gen_time
                self.out_delivered.add({
                    "pallet_id": self.current_pallet.id,
                    "aircraft_id": self.id,
                    "latency": latency
                })
                self.current_pallet = None

    def exit(self):
        pass


class Destination(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_delivered = Port(dict, "in_delivered")
        self.add_in_port(self.in_delivered)
        
        self.hold_in("IDLE", float('inf'))

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def deltint(self):
        pass

    def deltext(self, e):
        if self.in_delivered:
            for msg in self.in_delivered.values:
                log_event(self.clock.get_time(), "destination", "pallet_delivered", {
                    "pallet_id": msg["pallet_id"],
                    "aircraft_id": msg["aircraft_id"],
                    "latency": msg["latency"]
                })

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
                                 interval=args.pallet_interval, 
                                 expiration_time=args.pallet_expiration_time)
        self.add_component(self.facility)
        
        self.queue = LoadingQueue(name="loading_queue", parent=self)
        self.add_component(self.queue)
        
        self.coordinator = Coordinator(name="coordinator", parent=self, 
                                       num_aircraft=args.num_aircraft)
        self.add_component(self.coordinator)
        
        self.aircrafts = []
        for i in range(args.num_aircraft):
            ac = Aircraft(name=f"aircraft_{i}", parent=self, 
                          ac_id=i,
                          flight_time=args.flight_time,
                          unload_time=args.unload_time,
                          return_time=args.return_time,
                          maintenance_time=args.maintenance_time)
            self.aircrafts.append(ac)
            self.add_component(ac)
            
        self.destination = Destination(name="destination", parent=self)
        self.add_component(self.destination)
        
        # Couplings
        self.add_coupling(self.facility.out_pallet, self.queue.in_pallet)
        
        self.add_coupling(self.coordinator.out_req_pallet, self.queue.in_req)
        self.add_coupling(self.queue.out_pallet, self.coordinator.in_pallet)
        
        for ac in self.aircrafts:
            self.add_coupling(self.coordinator.out_assign, ac.in_assign)
            self.add_coupling(ac.out_status, self.coordinator.in_status)
            
        for ac in self.aircrafts:
            self.add_coupling(ac.out_delivered, self.destination.in_delivered)


# --- Main Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="Airfreight Logistics Simulation")
    parser.add_argument("--duration", type=float, default=10000.0, help="Total simulation time")
    parser.add_argument("--num_aircraft", type=int, default=2, help="Number of aircraft")
    parser.add_argument("--pallet_interval", type=float, default=25.0, help="Interval between pallets")
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0, help="Pallet expiration time")
    parser.add_argument("--flight_time", type=float, default=30.0, help="Flight time")
    parser.add_argument("--unload_time", type=float, default=2.0, help="Unload time")
    parser.add_argument("--return_time", type=float, default=30.0, help="Return time")
    parser.add_argument("--maintenance_time", type=float, default=10.0, help="Maintenance time")
    
    args = parser.parse_args()
    
    logger.info(f"Starting simulation with duration: {args.duration}")
    
    root = AirfreightSystem(name="airfreight_system", parent=None, args=args)
    
    clock = SimulationClock(max_time=args.duration)
    coord = Coordinator(root, clock=clock)
    
    coord.initialize()
    coord.simulate_time(args.duration)
    
    logger.info("Simulation finished.")

if __name__ == "__main__":
    main()