"""Complete pattern: a portless coupled root with one internal connection."""

from xdevs.models import Atomic, Coupled, Port

from .OTrain_libs.TrainScheduler import TrainScheduler
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.StationQueue import StationQueue
from .OTrain_libs.TrainQueue import TrainQueue

import sys
import json
import time
import random


class OTrain(Coupled):
    """Orchestrate the O-Train light rail simulation including train movement, passenger generation, and station/train queue operations."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: str,
    ):
        super().__init__(name)
        self.parent = parent

        # Parse simulate_time
        h, m, s, ms = map(int, simulate_time.split(":"))
        self.simulate_time = h * 3600 + m * 60 + s + ms / 1000.0

        # Station IDs and names
        self.stations = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}

        # Train route configuration
        self.route_stations = [
            (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
            (4, 1), (3, 1), (2, 1), (1, 0)
        ]
        self.travel_interval = 225  # seconds between stations

        # Passenger generation configuration
        self.initial_passenger_time = 0.5
        self.mean_interval_minutes = 5.0
        self.std_interval_minutes = 5.0
        self.min_interval_minutes = 1.0
        self.max_interval_minutes = 9.0

        # Boarding/alighting delays
        self.boarding_delay_seconds = 0.025
        self.alighting_delay_seconds = 0.025

        # Create components
        train_scheduler = TrainScheduler(
            name="TrainScheduler",
            parent=self,
            initial_arrival_time=0.0,
            travel_interval=self.travel_interval,
            route_stations=self.route_stations,
        )

        passenger_generator = PassengerGenerator(
            name="PassengerGenerator",
            parent=self,
            initial_passenger_time=self.initial_passenger_time,
            mean_interval_minutes=self.mean_interval_minutes,
            std_interval_minutes=self.std_interval_minutes,
            min_interval_minutes=self.min_interval_minutes,
            max_interval_minutes=self.max_interval_minutes,
        )

        station_queues = []
        train_queues = []
        for i in range(1, 6):
            station_queue = StationQueue(
                name=f"StationQueue_{i}",
                parent=self,
                boarding_delay_seconds=self.boarding_delay_seconds,
            )
            train_queue = TrainQueue(
                name=f"TrainQueue_{i}",
                parent=self,
                alighting_delay_seconds=self.alighting_delay_seconds,
            )
            station_queues.append(station_queue)
            train_queues.append(train_queue)

        # Add components to the coupled model
        self.add_component(train_scheduler)
        self.add_component(passenger_generator)
        for sq in station_queues:
            self.add_component(sq)
        for tq in train_queues:
            self.add_component(tq)

        # Coupling: TrainScheduler.train_arrival -> StationQueue.train_arrival
        # Coupling: TrainScheduler.train_arrival -> TrainQueue.train_arrival
        for i, sq in enumerate(station_queues):
            self.add_coupling(
                train_scheduler.output["train_arrival"],
                sq.input["train_arrival"],
            )
        for i, tq in enumerate(train_queues):
            self.add_coupling(
                train_scheduler.output["train_arrival"],
                tq.input["train_arrival"],
            )

        # Coupling: PassengerGenerator.passenger_generated -> StationQueue.passenger_generated
        for i, sq in enumerate(station_queues):
            self.add_coupling(
                passenger_generator.output["passenger_generated"],
                sq.input["passenger_generated"],
            )

        # Coupling: StationQueue.passenger_boarding -> TrainQueue.passenger_boarding
        for i, tq in enumerate(train_queues):
            self.add_coupling(
                station_queues[i].output["passenger_boarding"],
                tq.input["passenger_boarding"],
            )