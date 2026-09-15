"""Top-level coupled model for the O-Train simulation."""

from xdevs.models import Atomic, Coupled, Port

from .OTrain_libs.Station import Station
from .OTrain_libs.Train import Train


class OTrain(Coupled):
    """Instantiates 5 Station atomic models and 1 Train atomic model.
    
    Connects the Train to all Stations to broadcast arrival events,
    enabling boarding and alighting logic. Propagates configuration
    constants such as station IDs, names, route definitions, and timing
    parameters to children.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_configs: list,
        route_sequence: list,
        travel_interval: float,
        boarding_delay: float,
        alighting_delay: float,
        passenger_gen_mean: float,
        passenger_gen_std: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Extract station IDs and names for child configuration
        all_station_ids = [cfg['id'] for cfg in station_configs]
        station_names_map = {cfg['id']: cfg['name'] for cfg in station_configs}

        # Instantiate Train
        train = Train(
            name="Train",
            parent=self,
            route_sequence=route_sequence,
            travel_interval=travel_interval,
            alighting_delay=alighting_delay,
            station_names=station_names_map,
        )
        self.add_component(train)

        # Instantiate Stations
        stations = []
        for cfg in station_configs:
            station = Station(
                name=f"Station_{cfg['id']}",
                parent=self,
                station_id=cfg['id'],
                station_name=cfg['name'],
                all_station_ids=all_station_ids,
                gen_mean_min=passenger_gen_mean,
                gen_std_min=passenger_gen_std,
                boarding_delay=boarding_delay,
            )
            self.add_component(station)
            stations.append(station)

        # Internal Couplings
        # Connect Train.train_arrival_out to all Station.train_arrival_in
        for station in stations:
            self.add_coupling(
                train.output["train_arrival_out"],
                station.input["train_arrival_in"],
            )

        # Connect all Station.passenger_boarded_out to Train.passenger_boarded_in
        for station in stations:
            self.add_coupling(
                station.output["passenger_boarded_out"],
                train.input["passenger_boarded_in"],
            )