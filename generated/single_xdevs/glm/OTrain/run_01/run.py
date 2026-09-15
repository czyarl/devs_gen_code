```python
import argparse
import sys
import json
import random
import time
import logging

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# --- Constants ---

STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

ROUTE_SEQUENCE = [
    (1, 0), (2, 0), (3, 0), (4, 0),
    (5, 1), (4, 1), (3, 1), (2, 1)
]

TRAVEL_TIME = 225.0
INIT_GEN_TIME = 0.5
GEN_MEAN_MIN = 5.0
GEN_STD_MIN = 5.0
GEN_MIN_MIN = 1.0
GEN_MAX_MIN = 9.0
BOARDING_DELAY = 0.025
ALIGHTING_DELAY = 0.025

# --- Helpers ---

def parse_time_to_seconds(time_str: str) -> float:
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000.0

def get_station_name(sid: int) -> str:
    return STATIONS.get(sid, "Unknown")

def calculate_passenger_id(num: int, origin: int, dest: int) -> int:
    return num * 100 + origin * 10 + dest

# --- Atomic Models ---

class PassengerGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.out_passenger = Port(dict, "out_passenger")
        self.add_out_port(self.out_passenger)
        self.passenger_num = 0
        self.sigma = INIT_GEN_TIME

    def initialize(self):
        self.passenger_num = 0
        self.hold_in("GENERATE", INIT_GEN_TIME)

    def lambdaf(self):
        possible_dests = [s for s in STATIONS.keys() if s != self.station_id]
        dest = random.choice(possible_dests)
        
        if self.passenger_num == 0:
            p_id = 0
            p_num = 0
        else:
            p_id = calculate_passenger_id(self.passenger_num, self.station_id, dest)
            p_num = self.passenger_num
            
        payload = {
            "passenger_id": p_id,
            "passenger_num": p_num,
            "origin": self.station_id,
            "destination": dest
        }
        
        self.out_passenger.add(payload)
        
        print(json.dumps({
            "time": round(self.clock.get_time(), 3),
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": self.station_id,
            "station": get_station_name(self.station_id),
            "payload": payload
        }), file=sys.stdout, flush=True)

    def deltint(self):
        if self.passenger_num == 0:
            self.passenger_num = 1
        else:
            self.passenger_num += 1
            
        interval_min = random.gauss(GEN_MEAN_MIN, GEN_STD_MIN)
        interval_min = max(GEN_MIN_MIN, min(GEN_MAX_MIN, interval_min))
        interval_sec = int(round(interval_min * 60))
        
        self.sigma = float(interval_sec)
        self.hold_in("GENERATE", self.sigma)

    def deltext(self, e):
        self.hold_in("GENERATE", self.sigma - e)

    def exit(self):
        pass


class StationQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        
        self.in_passenger = Port(dict, "in_passenger")
        self.in_train_arrival = Port(dict, "in_train_arrival")
        self.in_boarding_ack = Port(dict, "in_boarding_ack")
        
        self.add_in_port(self.in_passenger)
        self.add_in_port(self.in_train_arrival)
        self.add_in_port(self.in_boarding_ack)
        
        self.out_boarding = Port(dict, "out_boarding")
        self.out_boarding_req = Port(dict, "out_boarding_req")
        self.out_boarding_done = Port(dict, "out_boarding_done")
        
        self.add_out_port(self.out_boarding)
        self.add_out_port(self.out_boarding_req)
        self.add_out_port(self.out_boarding_done)
        
        self.queue = []
        self.phase = "IDLE"
        self.sigma = float('inf')
        self.current_passenger = None

    def initialize(self):
        self.hold_in("IDLE", float('inf'))

    def lambdaf(self):
        if self.phase == "SEND_REQ":
            self.out_boarding_req.add({"station_id": self.station_id})
        elif self.phase == "SEND_PASSENGER":
            if self.current_passenger:
                self.out_boarding.add(self.current_passenger)
                print(json.dumps({
                    "time": round(self.clock.get_time(), 3),
                    "event": "passenger_boarding",
                    "entity_type": "station_queue",
                    "station_id": self.station_id,
                    "station": get_station_name(self.station_id),
                    "payload": self.current_passenger
                }), file=sys.stdout, flush=True)
        elif self.phase == "SEND_DONE":
            self.out_boarding_done.add({"station_id": self.station_id})

    def deltint(self):
        if self.phase == "READY_DELAY":
            self.phase = "SEND_REQ"
            self.sigma = 0.0
        elif self.phase == "SEND_REQ":
            self.phase = "WAIT_PROCEED"
            self.sigma = float('inf')
        elif self.phase == "SEND_PASSENGER":
            if self.queue:
                self.phase = "READY_DELAY"
                self.sigma = BOARDING_DELAY
            else:
                self.phase = "SEND_DONE"
                self.sigma = 0.0
        elif self.phase == "SEND_DONE":
            self.phase = "IDLE"
            self.sigma = float('inf')
            
        self.hold_in(self.phase, self.sigma)

    def deltext(self, e):
        # New Passengers
        if self.in_passenger:
            for p in self.in_passenger.values:
                if p['origin'] == self.station_id:
                    self.queue.append(p)
        
        # Train Arrival
        if self.in_train_arrival:
            if self.queue:
                self.phase = "READY_DELAY"
                self.sigma = BOARDING_DELAY
            else:
                self.phase = "SEND_DONE"
                self.sigma = 0.0
        
        # Boarding ACK
        if self.in_boarding_ack:
            if self.queue:
                self.current_passenger = self.queue.pop(0)
                self.phase = "SEND_PASSENGER"
                self.sigma = 0.0
            else:
                self.phase = "SEND_DONE"
                self.sigma = 0.0
        
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


class Train(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_boarding_req = Port(dict, "in_boarding_req")
        self.in_boarding_done = Port(dict, "in_boarding_done")
        self.in_passenger_data = Port(dict, "in_passenger_data")
        
        self.add_in_port(self.in_boarding_req)
        self.add_in_port(self.in_boarding_done)
        self.add_in_port(self.in_passenger_data)
        
        self.out_arrival = Port(dict, "out_arrival")
        self.out_boarding_ack = Port(dict, "out_boarding_ack")
        
        self.add_out_port(self.out_arrival)
        self.add_out_port(self.out_boarding_ack)
        
        self.route_index = 0
        self.passengers_on_train = []
        self.phase = "MOVING"
        self.sigma = 0.0
        self.alighting_buffer = []
        self.current_station_id = 1
        self.current_direction = 0

    def initialize(self):
        self.hold_in("ARRIVED", 0.0)

    def lambdaf(self):
        if self.phase == "ARRIVED":
            self.out_arrival.add({"station_id": self.current_station_id})
            print(json.dumps({
                "time": round(self.clock.get_time(), 3),
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": self.current_station_id,
                "station": get_station_name(self.current_station_id),
                "payload": {
                    "station": self.current_station_id,
                    "direction": self.current_direction
                }
            }), file=sys.stdout, flush=True)
        elif self.phase == "EXITING":
            if self.alighting_buffer:
                p = self.alighting_buffer.pop(0)
                print(json.dumps({
                    "time": round(self.clock.get_time(), 3),
                    "event": "passenger_exiting",
                    "entity_type": "train_queue",
                    "station_id": self.current_station_id,
                    "station": get_station_name(self.current_station_id),
                    "payload": p
                }), file=sys.stdout, flush=True)
        elif self.phase == "ACK":
            self.out_boarding_ack.add({"station_id": self.current_station_id})

    def deltint(self):
        if self.phase == "ARRIVED":
            self.alighting_buffer = [p for p in self.passengers_on_train if p['destination'] == self.current_station_id]
            self.passengers_on_train = [p for p in self.passengers_on_train if p['destination'] != self.current_station_id]
            
            if self.alighting_buffer:
                self.phase = "EXITING_DELAY"
                self.sigma = ALIGHTING_DELAY
            else:
                self.phase = "WAIT_BOARDING"
                self.sigma = 0.0
                
        elif self.phase == "EXITING_DELAY":
            self.phase = "EXITING"
            self.sigma = 0.0
            
        elif self.phase == "EXITING":
            if self.alighting_buffer:
                self.phase = "EXITING_DELAY"
                self.sigma = ALIGHTING_DELAY
            else:
                self.phase = "WAIT_BOARDING"
                self.sigma = 0.0
                
        elif self.phase == "ACK":
            self.phase = "WAIT_BOARDING"
            self.sigma = 0.0
            
        elif self.phase == "MOVING":
            self.route_index = (self.route_index + 1) % len(ROUTE_SEQUENCE)
            self.current_station_id, self.current_direction = ROUTE_SEQUENCE[self.route_index]
            self.phase = "ARRIVED"
            self.sigma = 0.0
            
        self.hold_in(self.phase, self.sigma)

    def deltext(self, e):
        if self.in_boarding_req:
            for _ in self.in_boarding_req.values:
                if self.phase == "WAIT_BOARDING":
                    self.phase = "ACK"
                    self.sigma = 0.0
                    
        if self.in_boarding_done:
            for _ in self.in_boarding_done.values:
                if self.phase == "WAIT_BOARDING":
                    self.phase = "MOVING"
                    self.sigma = TRAVEL_TIME
                    
        if self.in_passenger_data:
            for p in self.in_passenger_data.values:
                self.passengers_on_train.append(p)
                
        self.hold_in(self.phase, self.sigma)

    def exit(self):
        pass


# --- Coupled Models ---

class Station(Coupled):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        
        self.generator = PassengerGenerator("gen", self, station_id)
        self.queue = StationQueue("queue", self, station_id)
        
        self.add_component(self.generator)
        self.add_component(self.queue)
        
        self.add_coupling(self.generator.out_passenger, self.queue.in_passenger)
        
        self.in_train_arrival = Port(dict, "in_train_arrival")
        self.in_boarding_ack = Port(dict, "in_boarding_ack")
        self.add_in_port(self.in_train_arrival)
        self.add_in_port(self.in_boarding_ack)
        
        self.out_boarding = Port(dict, "out_boarding")
        self.out_boarding_req = Port(dict, "out_boarding_req")