"""Complete OTrain coupled model implementation."""

from xdevs.models import Atomic, Coupled, Port
from .OTrain_libs.TrainScheduler import TrainScheduler
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.StationQueue import StationQueue
from .OTrain_libs.TrainQueue import TrainQueue

class OTrain(Coupled):
    """Coordinates the train movement, passenger generation, station queues, and in-train queue behaviors to simulate an O-Train light rail system."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: str,
        initial_time: float,
        travel_interval: float,
        route_sequence: list,
        initial_passenger_time: float,
        mean_interval_minutes: float,
        std_interval_minutes: float,
        min_interval_minutes: float,
        max_interval_minutes: float,
        boarding_delay: float,
        alighting_delay: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Create components
        train_scheduler = TrainScheduler(
            name="train_scheduler",
            parent=self,
            initial_time=initial_time,
            travel_interval=travel_interval,
            route_sequence=route_sequence,
        )
        
        passenger_generator = PassengerGenerator(
            name="passenger_generator",
            parent=self,
            initial_passenger_time=initial_passenger_time,
            mean_interval_minutes=mean_interval_minutes,
            std_interval_minutes=std_interval_minutes,
            min_interval_minutes=min_interval_minutes,
            max_interval_minutes=max_interval_minutes,
        )
        
        # Create station queues
        station_queues = []
        station_names = ["Bayview", "Carling", "Carleton", "Confed", "Greenboro"]
        for i, (station_id, _) in enumerate(route_sequence[:5]):  # First 5 stations
            station_queue = StationQueue(
                name=f"station_queue_{station_id}",
                parent=self,
                station_id=station_id,
                station_name=station_names[station_id - 1],
                boarding_delay=boarding_delay,
            )
            station_queues.append(station_queue)
            self.add_component(station_queue)
        
        # Create train queue
        train_queue = TrainQueue(
            name="train_queue",
            parent=self,
            alighting_delay=alighting_delay,
        )
        self.add_component(train_queue)
        
        # Add components
        self.add_component(train_scheduler)
        self.add_component(passenger_generator)
        
        # Add couplings
        # TrainScheduler -> StationQueue
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            station_queues[0].input["train_arrival"]
        )
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            station_queues[1].input["train_arrival"]
        )
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            station_queues[2].input["train_arrival"]
        )
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            station_queues[3].input["train_arrival"]
        )
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            station_queues[4].input["train_arrival"]
        )
        
        # TrainScheduler -> TrainQueue
        self.add_coupling(
            train_scheduler.output["train_arrival"],
            train_queue.input["train_arrival"]
        )
        
        # PassengerGenerator -> StationQueue
        self.add_coupling(
            passenger_generator.output["passenger_generated"],
            station_queues[0].input["passenger_generated"]
        )
        self.add_coupling(
            passenger_generator.output["passenger_generated"],
            station_queues[1].input["passenger_generated"]
        )
        self.add_coupling(
            passenger_generator.output["passenger_generated"],
            station_queues[2].input["passenger_generated"]
        )
        self.add_coupling(
            passenger_generator.output["passenger_generated"],
            station_queues[3].input["passenger_generated"]
        )
        self.add_coupling(
            passenger_generator.output["passenger_generated"],
            station_queues[4].input["passenger_generated"]
        )
        
        # StationQueue -> TrainQueue
        self.add_coupling(
            station_queues[0].output["passenger_boarding"],
            train_queue.input["passenger_boarding"]
        )
        self.add_coupling(
            station_queues[1].output["passenger_boarding"],
            train_queue.input["passenger_boarding"]
        )
        self.add_coupling(
            station_queues[2].output["passenger_boarding"],
            train_queue.input["passenger_boarding"]
        )
        self.add_coupling(
            station_queues[3].output["passenger_boarding"],
            train_queue.input["passenger_boarding"]
        )
        self.add_coupling(
            station_queues[4].output["passenger_boarding"],
            train_queue.input["passenger_boarding"]
        )