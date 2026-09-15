"""House_Heating_D1: top-level coupled model wiring schedule source to heating process."""

from xdevs.models import Atomic, Coupled, Port

from .House_Heating_D1_libs.OutdoorTempScheduleSource import OutdoorTempScheduleSource
from .House_Heating_D1_libs.HeatingRoomProcess import HeatingRoomProcess


class House_Heating_D1(Coupled):
    """
    Top-level coupled DEVS model that composes:
      - OutdoorTempScheduleSource: reads stdin schedule and emits per-second outdoor temp
      - HeatingRoomProcess: consumes per-second outdoor temp and prints JSONL observations
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

        # No boundary ports per locked contract.

        outdoor_source = OutdoorTempScheduleSource(
            name="OutdoorTempScheduleSource",
            parent=self,
            simulation_time=simulation_time,
            default_outdoor_temp_c=default_outdoor_temp_c,
        )
        heating_process = HeatingRoomProcess(
            name="HeatingRoomProcess",
            parent=self,
            initial_room_temp_c=initial_room_temp_c,
            initial_control_signal=initial_control_signal,
            heat_loss_factor=heat_loss_factor,
            heater_gain_c=heater_gain_c,
            control_threshold_c=control_threshold_c,
        )

        self.add_component(outdoor_source)
        self.add_component(heating_process)

        # Internal coupling: schedule -> heating dynamics
        self.add_coupling(
            outdoor_source.output["outdoor_temp_c_out"],
            heating_process.input["outdoor_temp_c_in"],
        )