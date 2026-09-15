from xdevs.models import Atomic, Coupled, Port

from .House_Heating_D1_libs.HouseHeatingProcess import HouseHeatingProcess


class House_Heating_D1(Coupled):
    """Root coupled model for the house heating simulation. It contains the HouseHeatingProcess atomic model which manages the simulation logic, reading outdoor temperature schedules and emitting observation records. The root itself does not perform I/O or state transitions."""

    def __init__(self, name: str, parent: Coupled | None, simulate_time: float):
        super().__init__(name)
        self.parent = parent

        process = HouseHeatingProcess(
            name="process",
            parent=self,
            simulate_time=simulate_time,
        )
        self.add_component(process)