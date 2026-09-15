"""Top-level coupled DEVS model for the Secure Area Access Control scenario.

This coupled model is a pure structural container:
- Instantiates InputFileSource, AccessPipeline, and ReportCollector
- Wires their ports according to the locked contract
- Performs no external I/O and defines no DEVS transition logic
"""

from xdevs.models import Atomic, Coupled, Port

from .SAA_System_libs.InputFileSource import InputFileSource
from .SAA_System_libs.AccessPipeline import AccessPipeline
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Top-level coupled DEVS model for the Secure Area Access Control scenario."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        test_name: str,
        input_file: str,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
        max_simulation_time: float,
    ):
        super().__init__(name)
        self.parent = parent

        # No boundary ports per locked contract.

        source = InputFileSource(
            name="input_source",
            parent=self,
            input_file=input_file,
        )
        pipeline = AccessPipeline(
            name="access_pipeline",
            parent=self,
            alarm_admin_delay=alarm_admin_delay,
            authentication_delay=authentication_delay,
            display_delay=display_delay,
        )
        collector = ReportCollector(
            name="report_collector",
            parent=self,
            test_name=test_name,
            max_simulation_time=max_simulation_time,
        )

        self.add_component(source)
        self.add_component(pipeline)
        self.add_component(collector)

        # Requests drive the pipeline.
        self.add_coupling(
            source.output["request_out"],
            pipeline.input["request_in"],
        )

        # Input reader event facts go directly to the collector.
        self.add_coupling(
            source.output["input_event_fact_out"],
            collector.input["input_event_fact_in"],
        )

        # Pipeline stage events and per-request operation results go to the collector.
        self.add_coupling(
            pipeline.output["stage_event_fact_out"],
            collector.input["stage_event_fact_in"],
        )
        self.add_coupling(
            pipeline.output["operation_fact_out"],
            collector.input["operation_fact_in"],
        )

        # Authentication completion loopback to free AlarmAdmin at auth completion time.
        self.add_coupling(
            pipeline.output["auth_result_out"],
            pipeline.input["auth_result_in"],
        )