"""Coupled DEVS model for SAA_System."""

from xdevs.models import Atomic, Coupled, Port

from .SAA_System_libs.InputReader import InputReader
from .SAA_System_libs.AccessPipeline import AccessPipeline
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Route input requests through the secure-area access control pipeline and collect all observable facts into one final report."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        input_path: str,
        test_name: str,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
        max_simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate child components
        input_reader = InputReader(
            name="InputReader",
            parent=self,
            input_path=input_path,
        )
        access_pipeline = AccessPipeline(
            name="AccessPipeline",
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
        self.add_component(access_pipeline)
        self.add_component(report_collector)

        # Define couplings
        self.add_coupling(
            input_reader.output["request_out"],
            access_pipeline.input["request_in"],
        )
        self.add_coupling(
            input_reader.output["input_fact_out"],
            report_collector.input["input_fact_in"],
        )
        self.add_coupling(
            access_pipeline.output["event_fact_out"],
            report_collector.input["event_fact_in"],
        )
        self.add_coupling(
            access_pipeline.output["operation_fact_out"],
            report_collector.input["operation_fact_in"],
        )