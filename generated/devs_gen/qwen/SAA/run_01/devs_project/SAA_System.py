"""SAA_System: Top-level coupled model that routes input requests through the alarm system and collects all observable facts into one final report."""

from xdevs.models import Atomic, Coupled, Port
from .SAA_System_libs.InputReader import InputReader
from .SAA_System_libs.AlarmSystem import AlarmSystem
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Coupled model for the Secure Area Access System."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        input_file: str,
        test_name: str,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
        max_simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        input_reader = InputReader(
            name="InputReader",
            parent=self,
            input_file=input_file,
        )
        alarm_system = AlarmSystem(
            name="AlarmSystem",
            parent=self,
            alarm_admin_delay=alarm_admin_delay,
            authentication_delay=authentication_delay,
            display_delay=display_delay,
            max_simulation_time=max_simulation_time,
        )
        report_collector = ReportCollector(
            name="ReportCollector",
            parent=self,
            test_name=test_name,
            initial_state="Disarmed",
        )

        # Register components
        self.add_component(input_reader)
        self.add_component(alarm_system)
        self.add_component(report_collector)

        # Define couplings
        self.add_coupling(
            input_reader.output["input_event_out"],
            alarm_system.input["input_event_in"],
        )
        self.add_coupling(
            input_reader.output["input_fact_out"],
            report_collector.input["input_fact_in"],
        )
        self.add_coupling(
            alarm_system.output["event_fact_out"],
            report_collector.input["event_fact_in"],
        )
        self.add_coupling(
            alarm_system.output["operation_fact_out"],
            report_collector.input["operation_fact_in"],
        )