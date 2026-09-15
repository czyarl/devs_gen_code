from xdevs.models import Atomic, Coupled, Port

from .SEIRD_D1_libs.SeirdEpidemicModel import SeirdEpidemicModel


class SEIRD_D1(Coupled):
    """Contain the autonomous epidemic simulation process. It receives configuration parameters from the command line and instantiates the atomic model responsible for the SEIRD logic. It does not perform any state transitions or IO operations itself."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        dt: float,
        simulation_time: float,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        incubation_period: float,
        infectivity_period: float,
        mortality: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate the atomic model responsible for the SEIRD logic
        seird_model = SeirdEpidemicModel(
            name="seird_model",
            parent=self,
            dt=dt,
            simulation_time=simulation_time,
            total_population=total_population,
            initial_infective=initial_infective,
            transmission_rate=transmission_rate,
            incubation_period=incubation_period,
            infectivity_period=infectivity_period,
            mortality=mortality,
        )
        self.add_component(seird_model)