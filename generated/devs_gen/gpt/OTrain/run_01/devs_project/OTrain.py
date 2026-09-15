from xdevs.models import Atomic, Coupled, Port

from .OTrain_libs.Train import Train
from .OTrain_libs.PassengerGenerator import PassengerGenerator
from .OTrain_libs.StationQueue import StationQueue


class OTrain(Coupled):
    """
    Top-level coupled DEVS model that assembles:
      - 1 Train
      - 5 PassengerGenerator (one per station)
      - 5 StationQueue (one per station)

    It wires:
      - PassengerGenerator[station_id].passenger_out -> StationQueue[station_id].passenger_in
      - Train.arrival_out -> StationQueue[station_id].train_arrival_in (broadcast)
      - StationQueue[station_id].boarded_out -> Train.boarded_in

    This coupled model is structural only: no ports and no external I/O.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_ids: list,
        station_names: dict,
        travel_time_s: int,
        route_sequence: list,
        initial_train_arrival_time_s: float,
        service_dt_s: float,
        init_passenger_time_s: float,
        gen_mean_min: float,
        gen_std_min: float,
        gen_clamp_min_min: int,
        gen_clamp_max_min: int,
    ):
        super().__init__(name)
        self.parent = parent

        # Child: Train
        train = Train(
            name="train",
            parent=self,
            station_names=station_names,
            travel_time_s=travel_time_s,
            route_sequence=route_sequence,
            initial_arrival_time_s=initial_train_arrival_time_s,
            service_dt_s=service_dt_s,
        )
        self.add_component(train)

        # Children per station
        generators: dict[int, PassengerGenerator] = {}
        queues: dict[int, StationQueue] = {}

        for sid in station_ids:
            gen = PassengerGenerator(
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
            q = StationQueue(
                name=f"station_queue_{sid}",
                parent=self,
                station_id=int(sid),
                station_names=station_names,
                service_dt_s=service_dt_s,
            )

            generators[int(sid)] = gen
            queues[int(sid)] = q

            self.add_component(gen)
            self.add_component(q)

            # Passenger creation -> station FIFO queue
            self.add_coupling(
                gen.output["passenger_out"],
                q.input["passenger_in"],
            )

            # Station boarding -> train
            self.add_coupling(
                q.output["boarded_out"],
                train.input["boarded_in"],
            )

        # Broadcast train arrivals to all station queues
        for sid in station_ids:
            q = queues[int(sid)]
            self.add_coupling(
                train.output["arrival_out"],
                q.input["train_arrival_in"],
            )