"""House_Heating_D1: top-level coupled model for the house-heating simulation.

This coupled model is a pure structural container:
- It instantiates exactly one stdin-driven outdoor-temperature schedule source.
- It instantiates exactly one time-stepped room/heater/controller process.
- It couples the schedule output to the room process input.

All external I/O (stdin reading, stdout JSONL emission, stderr debug) is handled
by the atomic sub-models, not by this coupled model.
"""

from xdevs.models import Atomic, Coupled, Port

from .House_Heating_D1_libs.StdinOutdoorScheduleSource import StdinOutdoorScheduleSource
from .House_Heating_D1_libs.HeatingRoomProcess import HeatingRoomProcess


class House_Heating_D1(Coupled):
    """Top-level coupled model for the house-heating simulation."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        default_outdoor_temp_c: float,
        target_temp_c: float,
        heat_loss_rate: float,
        heater_gain_c: float,
        initial_room_temp_c: float,
        initial_control_signal: int,
        simulate_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # No boundary ports per locked contract.

        # Components
        schedule_source = StdinOutdoorScheduleSource(
            name="outdoor_schedule_source",
            parent=self,
            simulate_time=simulate_time,
            default_outdoor_temp_c=default_outdoor_temp_c,
        )
        room_process = HeatingRoomProcess(
            name="heating_room_process",
            parent=self,
            simulate_time=simulate_time,
            target_temp_c=target_temp_c,
            heat_loss_rate=heat_loss_rate,
            heater_gain_c=heater_gain_c,
            initial_room_temp_c=initial_room_temp_c,
            initial_control_signal=initial_control_signal,
        )

        self.add_component(schedule_source)
        self.add_component(room_process)

        # Internal coupling: schedule -> room process
        self.add_coupling(
            schedule_source.output["scheduled_outdoor_temp_out"],
            room_process.input["scheduled_outdoor_temp_in"],
        )