from xdevs.models import Atomic, Coupled, Port
from .SEIRD_D1_libs.SEIRD_Model import SEIRD_Model


class SEIRD_D1(Coupled):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
    ):
        super().__init__(name)
        self.parent = parent

        self.SEIRD_Model = SEIRD_Model(
            name="SEIRD_Model",
            parent=self,
            mortality=10.0,
            infectivity_period=14.0,
            dt=0.1,
            incubation_period=5.0,
            total_population=1000,
            initial_infective=10,
            transmission_rate=2.5,
            simulation_time=10.0,
        )
        self.add_component(self.SEIRD_Model)