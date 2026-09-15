from xdevs.models import Atomic, Coupled, Port

from .House_Heating_D1_libs.OutdoorSource import OutdoorSource
from .House_Heating_D1_libs.RoomModel import RoomModel


class House_Heating_D1(Coupled):
    """Coordinate the simulation by managing the outdoor temperature source and the room physics model."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: float,
        default_outdoor_temp: float,
        initial_room_temp: float,
        target_temp: float,
        heater_gain: float,
        loss_rate: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate OutdoorSource
        outdoor_source = OutdoorSource(
            name="OutdoorSource",
            parent=self,
            simulate_time=simulate_time,
            default_outdoor_temp=default_outdoor_temp,
        )
        self.add_component(outdoor_source)

        # Instantiate RoomModel
        room_model = RoomModel(
            name="RoomModel",
            parent=self,
            initial_room_temp=initial_room_temp,
            target_temp=target_temp,
            heater_gain=heater_gain,
            loss_rate=loss_rate,
        )
        self.add_component(room_model)

        # Connect OutdoorSource.outdoor_temp_out to RoomModel.outdoor_temp_in
        self.add_coupling(
            outdoor_source.output["outdoor_temp_out"],
            room_model.input["outdoor_temp_in"],
        )