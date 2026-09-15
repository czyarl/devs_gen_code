"""Top-level coupled model for the SEIRD epidemic simulation."""

from xdevs.models import Atomic, Coupled, Port

from .SEIRD_D1_libs.SEIRDModel import SEIRDModel


class SEIRD_D1(Coupled):
    """Top-level coupled model for the SEIRD epidemic simulation. Contains the complete SEIRD process and delegates the actual simulation to its child SEIRDModel."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
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

        # Instantiate the SEIRDModel child
        seird_model = SEIRDModel(
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