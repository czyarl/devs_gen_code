"""Top-level coupled DEVS model for the Ottawa O-Train simulation."""

from xdevs.models import Atomic, Coupled, Port

from .OTrain_libs.Train import Train
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.StationQueue import StationQueue
from .OTrain_libs.TrainQueue import TrainQueue


class OTrain(Coupled):
    """
    Top-level coupled DEVS model that composes the Ottawa O-Train simulation.

    This coupled wrapper only instantiates children and wires DEVS message flows
    so that required JSONL events are written by the responsible atomic models
    in nondecreasing simulation-time order.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_ids: list,
        station_names: dict,
        travel_interval_s: int,
        initial_train_station_id: int,
        initial_train_direction: int,
        route_sequence: list,
        init_passenger_time_s: float,
        gen_mean_min: float,
        gen_std_min: float,
        gen_clamp_min_min: int,
        gen_clamp_max_min: int,
        board_alight_dt_s: float,
    ):
        super().__init__(name)
        self.parent = parent

        # No boundary ports per locked contract.

        # --- Components ---
        train = Train(
            name="train",
            parent=self,
            station_names=station_names,
            travel_interval_s=travel_interval_s,
            initial_train_station_id=initial_train_station_id,
            initial_train_direction=initial_train_direction,
            route_sequence=route_sequence,
        )
        self.add_component(train)

        train_queue = TrainQueue(
            name="train_queue",
            parent=self,
            station_names=station_names,
            alight_dt_s=board_alight_dt_s,
        )
        self.add_component(train_queue)

        passenger_generators: dict[int, PassengerGenerator] = {}
        station_queues: dict[int, StationQueue] = {}

        for sid in station_ids:
            pg = PassengerGenerator(
                name=f"passenger_generator_{sid}",
                parent=self,
                station_id=int(sid),
                station_names=station_names,
                init_passenger_time_s=init_passenger_time_s,
                gen_mean_min=gen_mean_min,
                gen_std_min=gen_std_min,
                gen_clamp_min_min=gen_clamp_min_min,
                gen_clamp_max_min=gen_clamp_max_min,
            )
            sq = StationQueue(
                name=f"station_queue_{sid}",
                parent=self,
                station_id=int(sid),
                station_names=station_names,
                board_dt_s=board_alight_dt_s,
            )

            passenger_generators[int(sid)] = pg
            station_queues[int(sid)] = sq

            self.add_component(pg)
            self.add_component(sq)

        # --- Couplings ---
        # Train arrival broadcast to all station queues.
        for sid, sq in station_queues.items():
            self.add_coupling(
                train.output["arrival_out"],
                sq.input["train_arrival_in"],
            )

        # Train arrival to onboard train queue.
        self.add_coupling(
            train.output["arrival_to_train_queue_out"],
            train_queue.input["train_arrival_in"],
        )

        # Passenger generation to matching station queue (one-to-one).
        for sid in station_ids:
            sid = int(sid)
            self.add_coupling(
                passenger_generators[sid].output["passenger_out"],
                station_queues[sid].input["passenger_in"],
            )

        # Boarded passengers from any station queue to onboard train queue.
        for sid, sq in station_queues.items():
            self.add_coupling(
                sq.output["boarded_out"],
                train_queue.input["boarded_in"],
            )