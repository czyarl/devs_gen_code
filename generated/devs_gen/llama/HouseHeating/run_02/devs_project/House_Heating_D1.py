"""Complete pattern: a portless coupled root with one internal connection."""

from xdevs.models import Atomic, Coupled, Port
from .House_Heating_D1_libs.OutdoorTempReader import OutdoorTempReader
from .House_Heating_D1_libs.HeatingController import HeatingController


class House_Heating_D1(Coupled):
    """Connect two children without inventing coupled boundary ports."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        outdoor_temp_reader = OutdoorTempReader(
            name="outdoor_temp_reader",
            parent=self,
            simulation_time=simulation_time,
        )
        heating_controller = HeatingController(
            name="heating_controller",
            parent=self,
        )
        self.add_component(outdoor_temp_reader)
        self.add_component(heating_controller)

        self.add_coupling(
            outdoor_temp_reader.output["outdoor_temp"],
            heating_controller.input["outdoor_temp"],
        )