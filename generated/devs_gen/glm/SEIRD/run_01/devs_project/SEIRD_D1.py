from xdevs.models import Atomic, Coupled, Port

from .SEIRD_D1_libs.SeirdProcess import SeirdProcess


class SEIRD_D1(Coupled):
    """Root coupled model that encapsulates the SEIRD simulation. It passes configuration parameters from the runner to the child process and contains the single atomic component responsible for the simulation logic and output generation."""

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

        process = SeirdProcess(
            name="SeirdProcess",
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
        self.add_component(process)