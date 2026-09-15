"""Coupled DEVS model for house heating simulation."""

from xdevs.models import Atomic, Coupled, Port
from .House_Heating_D1_libs.OutdoorTempReader import OutdoorTempReader
from .House_Heating_D1_libs.RoomStateProcessor import RoomStateProcessor


class House_Heating_D1(Coupled):
    """Coupled model for house heating simulation."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Create child components
        outdoor_reader = OutdoorTempReader(
            name="outdoor_reader",
            parent=self,
            simulation_time=simulate_time,
        )
        room_processor = RoomStateProcessor(name="room_processor", parent=self)
        self.add_component(outdoor_reader)
        self.add_component(room_processor)

        # Define couplings
        self.add_coupling(
            outdoor_reader.output["value_out"],
            room_processor.input["value_in"],
        )