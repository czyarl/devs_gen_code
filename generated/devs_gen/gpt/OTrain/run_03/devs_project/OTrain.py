"""Top-level coupled DEVS model for the Ottawa O-Train scenario.

This coupled model is a pure structural container:
- Instantiates TrainScheduler, 5 PassengerGenerator(s), 5 StationQueue(s), and TrainQueue.
- Wires internal couplings so that:
  * TrainScheduler broadcasts arrivals to all StationQueue(s) and to TrainQueue.
  * Each PassengerGenerator feeds its co-located StationQueue.
  * Each StationQueue forwards boarded passengers to TrainQueue.

Per the locked contract, this coupled model:
- Has no boundary ports.
- Performs no OS I/O.
- Implements only __init__ (no DEVS transition logic).
"""

from xdevs.models import Atomic, Coupled, Port

from .OTrain_libs.TrainScheduler import TrainScheduler
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.StationQueue import StationQueue
from .OTrain_libs.TrainQueue import TrainQueue


class OTrain(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_ids: list,
        station_names: dict,
        train_travel_interval_s: float,
        train_route_sequence: list,
        passenger_init_time_s: float,
        passenger_interarrival_mean_min: float,
        passenger_interarrival_std_min: float,
        passenger_interarrival_clamp_min_min: float,
        passenger_interarrival_clamp_max_min: float,
        boarding_alighting_step_s: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Core components
        scheduler = TrainScheduler(
            name="train_scheduler",
            parent=self,
            station_names=station_names,
            travel_interval_s=train_travel_interval_s,
            route_sequence=train_route_sequence,
        )
        train_queue = TrainQueue(
            name="train_queue",
            parent=self,
            station_names=station_names,
            step_s=boarding_alighting_step_s,
        )

        self.add_component(scheduler)
        self.add_component(train_queue)

        # Per-station components
        passenger_generators: dict[int, PassengerGenerator] = {}
        station_queues: dict[int, StationQueue] = {}

        for station_id in station_ids:
            pg = PassengerGenerator(
                name=f"passenger_generator_{station_id}",
                parent=self,
                station_id=station_id,
                station_ids=station_ids,
                station_names=station_names,
                init_time_s=passenger_init_time_s,
                interarrival_mean_min=passenger_interarrival_mean_min,
                interarrival_std_min=passenger_interarrival_std_min,
                clamp_min_min=passenger_interarrival_clamp_min_min,
                clamp_max_min=passenger_interarrival_clamp_max_min,
            )
            sq = StationQueue(
                name=f"station_queue_{station_id}",
                parent=self,
                station_id=station_id,
                station_names=station_names,
                step_s=boarding_alighting_step_s,
            )

            passenger_generators[station_id] = pg
            station_queues[station_id] = sq

            self.add_component(pg)
            self.add_component(sq)

            # Passenger generation -> station queue
            self.add_coupling(
                pg.output["passenger_out"],
                sq.input["passenger_in"],
            )

            # Station queue boarding -> train queue
            self.add_coupling(
                sq.output["boarded_passenger_out"],
                train_queue.input["boarded_passenger_in"],
            )

            # Broadcast train arrivals -> each station queue (queues ignore non-matching station_id)
            self.add_coupling(
                scheduler.output["train_arrival_out"],
                sq.input["train_arrival_in"],
            )

        # Train arrivals -> train queue (for alighting)
        self.add_coupling(
            scheduler.output["train_arrival_out"],
            train_queue.input["train_arrival_in"],
        )