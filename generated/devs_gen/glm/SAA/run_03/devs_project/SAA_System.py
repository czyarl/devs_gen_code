from xdevs.models import Atomic, Coupled, Port

from .SAA_System_libs.RequestSource import RequestSource
from .SAA_System_libs.AccessPipeline import AccessPipeline
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Orchestrate the Secure Area Access simulation by routing parsed requests from the source through the processing pipeline and aggregating all observable events and operations into a final report. The root model itself performs no file IO or state transitions."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        input_file: str,
        test_name: str,
        alarm_admin_delay: float = 10.0,
        authentication_delay: float = 2.0,
        display_delay: float = 3.0,
        max_simulation_time: float = 1000.0,
    ):
        super().__init__(name)
        self.parent = parent

        # Instantiate components
        request_source = RequestSource(
            name="RequestSource",
            parent=self,
            input_file=input_file,
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
        self.add_component(request_source)
        self.add_component(access_pipeline)
        self.add_component(report_collector)

        # Define couplings
        # Connect RequestSource.request_out to AccessPipeline.request_in
        self.add_coupling(
            request_source.output["request_out"],
            access_pipeline.input["request_in"],
        )

        # Connect RequestSource.input_event_out to ReportCollector.event_in
        self.add_coupling(
            request_source.output["input_event_out"],
            report_collector.input["event_in"],
        )

        # Connect AccessPipeline.event_out to ReportCollector.event_in
        self.add_coupling(
            access_pipeline.output["event_out"],
            report_collector.input["event_in"],
        )

        # Connect AccessPipeline.operation_out to ReportCollector.operation_in
        self.add_coupling(
            access_pipeline.output["operation_out"],
            report_collector.input["operation_in"],
        )