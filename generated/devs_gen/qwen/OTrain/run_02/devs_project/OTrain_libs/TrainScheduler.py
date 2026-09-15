from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TrainScheduler(Atomic):
    """Manages the train's movement along the predefined route and generates train_arrival events at each station."""

    def __init__(self, name: str, parent: Coupled | None, initial_station_id: int, initial_direction: int, travel_interval: float, route_sequence: list):
        super().__init__(name)
        self.parent = parent
        self.initial_station_id = initial_station_id
        self.initial_direction = initial_direction
        self.travel_interval = travel_interval
        self.route_sequence = route_sequence
        
        self.add_out_port(Port(dict, "train_arrival"))
        
        # Internal state
        self.current_station_id = initial_station_id
        self.current_direction = initial_direction
        self.next_arrival_time = 0.0
        self.route_index = 0

    def initialize(self):
        # Set initial state
        self.current_station_id = self.initial_station_id
        self.current_direction = self.initial_direction
        self.next_arrival_time = 0.0
        # Find the initial index in the route
        for i, (station, direction) in enumerate(self.route_sequence):
            if station == self.current_station_id and direction == self.current_direction:
                self.route_index = i
                break
        
        # Emit initial train_arrival event at t=0.0
        self.hold_in("OUTPUT_READY", 0.0)

    def deltext(self, e):
        # This model has no input ports.
        pass

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            # Emit the train_arrival event
            arrival_event = {
                "station_id": self.current_station_id,
                "direction": self.current_direction
            }
            self.output["train_arrival"].add(arrival_event)

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            # Move to next station in the route
            self.route_index = (self.route_index + 1) % len(self.route_sequence)
            self.current_station_id, self.current_direction = self.route_sequence[self.route_index]
            
            # Schedule next arrival
            self.next_arrival_time += self.travel_interval
            self.hold_in("OUTPUT_READY", self.travel_interval)
        else:
            self.passivate()

    def exit(self):
        pass