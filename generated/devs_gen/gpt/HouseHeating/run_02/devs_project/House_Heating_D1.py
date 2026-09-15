from xdevs.models import Atomic, Coupled, Port

from .House_Heating_D1_libs.OutdoorTempScheduleSource import OutdoorTempScheduleSource
from .House_Heating_D1_libs.HouseHeatingProcess import HouseHeatingProcess


class House_Heating_D1(Coupled):
    """
    Top-level coupled DEVS model that composes:
      - OutdoorTempScheduleSource: reads stdin and emits one driving message per second
      - HouseHeatingProcess: consumes driving messages, advances state, writes JSONL to stdout

    This coupled wrapper is structural only: it owns no ports and performs no OS I/O.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulation_time: float,
        default_outdoor_temp_c: float,
        heat_loss_factor: float,
        heater_gain_c: float,
        control_threshold_c: float,
        initial_room_temp_c: float,
        initial_control_signal: int,
    ):
        super().__init__(name)
        self.parent = parent

        source = OutdoorTempScheduleSource(
            name="outdoor_temp_source",
            parent=self,
            simulation_time=simulation_time,
            default_outdoor_temp_c=default_outdoor_temp_c,
        )
        process = HouseHeatingProcess(
            name="house_heating_process",
            parent=self,
            initial_room_temp_c=initial_room_temp_c,
            initial_control_signal=initial_control_signal,
            heat_loss_factor=heat_loss_factor,
            heater_gain_c=heater_gain_c,
            control_threshold_c=control_threshold_c,
        )

        self.add_component(source)
        self.add_component(process)

        self.add_coupling(
            source.output["outdoor_temp_out"],
            process.input["outdoor_temp_in"],
        )