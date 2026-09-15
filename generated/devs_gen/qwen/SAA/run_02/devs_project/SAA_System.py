"""SAA_System: Top-level coupled system that orchestrates input processing, alarm system operations, and final report generation."""

from xdevs.models import Atomic, Coupled, Port

from .SAA_System_libs.InputReader import InputReader
from .SAA_System_libs.AlarmSystem import AlarmSystem
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Coupled model orchestrating the Secure Area Access System."""

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
        )
        report_collector = ReportCollector(
            name="ReportCollector",
            parent=self,
            test_name=test_name,
            max_simulation_time=max_simulation_time,
        )

        # Register components
        self.add_component(input_reader)
        self.add_component(alarm_system)
        self.add_component(report_collector)

        # Define couplings
        self.add_coupling(
            input_reader.output["request_out"],
            alarm_system.input["request_in"],
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
        self.add_coupling(
            alarm_system.output["alarm_admin_out"],
            report_collector.input["event_fact_in"],
        )
        self.add_coupling(
            alarm_system.output["authentication_out"],
            report_collector.input["event_fact_in"],
        )
        self.add_coupling(
            alarm_system.output["display_out"],
            report_collector.input["event_fact_in"],
        )