"""Coupled DEVS model for house heating simulation."""

from xdevs.models import Atomic, Coupled, Port
from .House_Heating_D1_libs.OutdoorTempReader import OutdoorTempReader
from .House_Heating_D1_libs.HeatingController import HeatingController


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
        heating_controller = HeatingController(
            name="heating_controller",
            parent=self,
            target_temp_c=24.9,
            heater_gain=0.5,
            heat_loss_rate=0.1,
            initial_room_temp=25.0,
            initial_control_signal=0,
            initial_heater_output=0.0,
        )

        # Register components
        self.add_component(outdoor_reader)
        self.add_component(heating_controller)

        # Define couplings
        self.add_coupling(
            outdoor_reader.output["value_out"],
            heating_controller.input["value_in"],
        )