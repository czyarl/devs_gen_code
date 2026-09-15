"""Complete pattern: a coupled root model containing and configuring the SEIRD model."""

from xdevs.models import Coupled, Port
from .SEIRD_D1_libs.SEIRD_Model import SEIRD_Model


class SEIRD_D1(Coupled):
    """Root model for the SEIRD simulation, containing and configuring the SEIRD model."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        test_name: str,
        mortality: float,
        infectivity_period: float,
        dt: float,
        incubation_period: float,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        seird_model = SEIRD_Model(
            name="seird_model",
            parent=self,
            mortality=mortality,
            infectivity_period=infectivity_period,
            dt=dt,
            incubation_period=incubation_period,
            total_population=total_population,
            initial_infective=initial_infective,
            transmission_rate=transmission_rate,
            simulation_time=simulation_time,
        )
        self.add_component(seird_model)