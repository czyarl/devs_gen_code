"""SEIRD_D1: Coupled wrapper containing a single autonomous SEIRD discrete-time process."""

from xdevs.models import Atomic, Coupled, Port

from .SEIRD_D1_libs.SeirdProcess import SeirdProcess


class SEIRD_D1(Coupled):
    """
    Root coupled wrapper that configures and contains a single autonomous SEIRD
    discrete-time process.

    This coupled model is a pure structural container: it defines no ports and
    performs no external I/O. The contained atomic process is responsible for
    advancing the SEIRD compartments and emitting the final JSONL state to stdout.
    """

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

        process = SeirdProcess(
            name="process",
            parent=self,
            test_name=test_name,
            mortality=mortality,
            infectivity_period=infectivity_period,
            dt=dt,
            incubation_period=incubation_period,
            total_population=total_population,
            initial_infective=initial_infective,
            transmission_rate=transmission_rate,
            simulation_time=simulation_time,
        )
        self.add_component(process)