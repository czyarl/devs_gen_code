from xdevs.models import Atomic, Coupled, Port

from .House_Heating_D1_libs.OutdoorTempSource import OutdoorTempSource
from .House_Heating_D1_libs.RoomModel import RoomModel


class House_Heating_D1(Coupled):
    """Coordinates the simulation of the house heating system by routing outdoor temperature data from the schedule source to the room model."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate OutdoorTempSource
        outdoor_source = OutdoorTempSource(
            name="OutdoorTempSource",
            parent=self,
            simulate_time=simulate_time,
        )

        # Instantiate RoomModel
        # Constants derived from requirements (R013, R017, R024, R026)
        room = RoomModel(
            name="RoomModel",
            parent=self,
            target_temp=24.9,
            heater_gain_rate=0.5,
            heat_loss_rate=0.1,
            initial_room_temp=25.0,
        )

        # Register components
        self.add_component(outdoor_source)
        self.add_component(room)

        # Define internal coupling: OutdoorTempSource.outdoor_temp_out -> RoomModel.outdoor_temp_in
        self.add_coupling(
            outdoor_source.output["outdoor_temp_out"],
            room.input["outdoor_temp_in"],
        )