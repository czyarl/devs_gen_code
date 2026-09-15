"""Top-level coupled DEVS model for the secure-area access control scenario.

This coupled model is a pure structural container:
- Instantiates InputRequestSource, AccessPipeline, and ReportCollector.
- Routes request messages and event/operation facts between them.
- Performs no external IO itself and has no boundary ports.
"""

from xdevs.models import Atomic, Coupled, Port

from .SAA_System_libs.InputRequestSource import InputRequestSource
from .SAA_System_libs.AccessPipeline import AccessPipeline
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Top-level coupled model wiring the secure-area access control pipeline."""

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

        # Children
        source = InputRequestSource(
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

        # Couplings (no boundary ports in this root)
        self.add_coupling(
            source.output["request_out"],
            pipeline.input["request_in"],
        )
        self.add_coupling(
            source.output["input_event_fact_out"],
            collector.input["input_event_fact_in"],
        )
        self.add_coupling(
            pipeline.output["stage_event_fact_out"],
            collector.input["stage_event_fact_in"],
        )
        self.add_coupling(
            pipeline.output["operation_fact_out"],
            collector.input["operation_fact_in"],
        )