from xdevs.models import Atomic, Coupled, Port

from .OTrain_libs.Train import Train
from .OTrain_libs.Station import Station


class OTrain(Coupled):
    """Root coupled model for the O-Train simulation."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Instantiate Train
        train = Train(name="Train", parent=self)
        self.add_component(train)

        # Instantiate 5 Stations with IDs 1-5
        station_names = {
            1: "Bayview",
            2: "Carling",
            3: "Carleton",
            4: "Confed",
            5: "Greenboro",
        }

        stations = {}
        for sid, sname in station_names.items():
            station = Station(
                name=f"Station_{sname}",
                parent=self,
                station_id=sid,
                station_name=sname,
            )
            self.add_component(station)
            stations[sid] = station

        # Coupling: Train.arrival_out -> every Station.train_arrival_in
        for station in stations.values():
            self.add_coupling(
                train.output["arrival_out"],
                station.input["train_arrival_in"],
            )

        # Coupling: every Station.boarding_out -> Train.boarding_in
        for station in stations.values():
            self.add_coupling(
                station.output["boarding_out"],
                train.input["boarding_in"],
            )