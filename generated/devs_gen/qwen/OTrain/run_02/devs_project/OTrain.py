"""Top-level coupled model for the O-Train light rail simulation."""

from xdevs.models import Atomic, Coupled, Port
from .OTrain_libs.TrainScheduler import TrainScheduler
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.StationQueue import StationQueue
from .OTrain_libs.TrainQueue import TrainQueue

class OTrain(Coupled):
    """Top-level coupled model for the O-Train light rail simulation that coordinates train scheduling, passenger generation, station queuing, and in-train passenger management."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: str,
        initial_station_id: int,
        initial_direction: int,
        travel_interval: float,
        route_sequence: list,
        initial_arrival_time: float,
        mean_interval_minutes: float,
        std_interval_minutes: float,
        interval_min_minutes: float,
        interval_max_minutes: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Create TrainScheduler
        train_scheduler = TrainScheduler(
            name="TrainScheduler",
            parent=self,
            initial_station_id=initial_station_id,
            initial_direction=initial_direction,
            travel_interval=travel_interval,
            route_sequence=route_sequence,
        )
        self.add_component(train_scheduler)

        # Create PassengerGenerator
        passenger_generator = PassengerGenerator(
            name="PassengerGenerator",
            parent=self,
            initial_arrival_time=initial_arrival_time,
            mean_interval_minutes=mean_interval_minutes,
            std_interval_minutes=std_interval_minutes,
            interval_min_minutes=interval_min_minutes,
            interval_max_minutes=interval_max_minutes,
        )
        self.add_component(passenger_generator)

        # Create StationQueues for each station
        stations = {
            1: "Bayview",
            2: "Carling",
            3: "Carleton",
            4: "Confed",
            5: "Greenboro"
        }
        station_queues = {}
        for station_id, station_name in stations.items():
            station_queue = StationQueue(
                name=f"StationQueue_{station_id}",
                parent=self,
                station_id=station_id,
                station_name=station_name,
            )
            self.add_component(station_queue)
            station_queues[station_id] = station_queue

        # Create TrainQueue
        train_queue = TrainQueue(
            name="TrainQueue",
            parent=self,
        )
        self.add_component(train_queue)

        # Coupling TrainScheduler.train_arrival to StationQueue.train_arrival
        for station_id, station_queue in station_queues.items():
            self.add_coupling(
                train_scheduler.output["train_arrival"],
                station_queue.input["train_arrival"],
            )

        # Coupling TrainScheduler.train_arrival to TrainQueue.train_arrival
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            train_queue.input["train_arrival"],
        )

        # Coupling PassengerGenerator.passenger_generated to StationQueue.passenger_arrival
        for station_id, station_queue in station_queues.items():
            self.add_coupling(
                passenger_generator.output["passenger_generated"],
                station_queue.input["passenger_arrival"],
            )

        # Coupling StationQueue.passenger_boarding to TrainQueue.passenger_boarding
        for station_id, station_queue in station_queues.items():
            self.add_coupling(
                station_queue.output["passenger_boarding"],
                train_queue.input["passenger_boarding"],
            )

        # Coupling TrainQueue.passenger_exiting to StationQueue.passenger_arrival
        self.add_coupling(
            train_queue.output["passenger_exiting"],
            station_queues[1].input["passenger_arrival"],  # This is a simplification - in a real scenario, we'd need to route to the appropriate station
        )