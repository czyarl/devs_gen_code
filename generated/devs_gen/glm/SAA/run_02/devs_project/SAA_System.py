from xdevs.models import Atomic, Coupled, Port

from .SAA_System_libs.InputSource import InputSource
from .SAA_System_libs.AlarmPipeline import AlarmPipeline
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Route input requests through the processing pipeline and route observable facts to the final report collector."""

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

        # Instantiate components
        input_source = InputSource(
            name="InputSource",
            parent=self,
            input_path=input_path,
        )
        alarm_pipeline = AlarmPipeline(
            name="AlarmPipeline",
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
        self.add_component(input_source)
        self.add_component(alarm_pipeline)
        self.add_component(report_collector)

        # Define couplings
        # Connect InputSource.request_out to AlarmPipeline.request_in
        self.add_coupling(
            input_source.output["request_out"],
            alarm_pipeline.input["request_in"],
        )

        # Connect InputSource.input_fact_out to ReportCollector.input_fact_in
        self.add_coupling(
            input_source.output["input_fact_out"],
            report_collector.input["input_fact_in"],
        )

        # Connect AlarmPipeline.event_fact_out to ReportCollector.event_fact_in
        self.add_coupling(
            alarm_pipeline.output["event_fact_out"],
            report_collector.input["event_fact_in"],
        )

        # Connect AlarmPipeline.operation_fact_out to ReportCollector.operation_fact_in
        self.add_coupling(
            alarm_pipeline.output["operation_fact_out"],
            report_collector.input["operation_fact_in"],
        )