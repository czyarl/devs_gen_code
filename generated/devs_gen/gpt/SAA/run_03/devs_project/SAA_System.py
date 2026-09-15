"""Top-level coupled DEVS model for the Secure Area Access Control simulation.

This coupled wrapper is a pure structural container:
- Instantiates InputFileSource, AlarmAdmin, Authentication, Display, ReportCollector
- Couples their ports to form the required pipeline and reporting fan-in
- Contains no boundary ports and performs no OS I/O
"""

from xdevs.models import Atomic, Coupled, Port

from .SAA_System_libs.InputFileSource import InputFileSource
from .SAA_System_libs.AlarmAdmin import AlarmAdmin
from .SAA_System_libs.Authentication import Authentication
from .SAA_System_libs.Display import Display
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Top-level coupled model wiring the Secure Area Access Control system."""

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

        # Children
        source = InputFileSource(
            name="input_source",
            parent=self,
            input_file=input_file,
        )
        alarm_admin = AlarmAdmin(
            name="alarm_admin",
            parent=self,
            alarm_admin_delay=alarm_admin_delay,
        )
        auth = Authentication(
            name="authentication",
            parent=self,
            authentication_delay=authentication_delay,
        )
        display = Display(
            name="display",
            parent=self,
            display_delay=display_delay,
            initial_state="Disarmed",
        )
        report = ReportCollector(
            name="report_collector",
            parent=self,
            test_name=test_name,
            max_simulation_time=max_simulation_time,
            initial_state="Disarmed",
        )

        self.add_component(source)
        self.add_component(alarm_admin)
        self.add_component(auth)
        self.add_component(display)
        self.add_component(report)

        # Couplings (IC only)
        self.add_coupling(source.output["request_out"], alarm_admin.input["request_in"])
        self.add_coupling(source.output["input_event_out"], report.input["input_event_in"])

        self.add_coupling(alarm_admin.output["to_auth_out"], auth.input["request_in"])
        self.add_coupling(alarm_admin.output["alarmadmin_event_out"], report.input["alarmadmin_event_in"])

        self.add_coupling(auth.output["complete_to_admin_out"], alarm_admin.input["auth_complete_in"])
        self.add_coupling(auth.output["validation_to_display_out"], display.input["validation_in"])
        self.add_coupling(auth.output["authentication_event_out"], report.input["authentication_event_in"])

        self.add_coupling(display.output["display_event_out"], report.input["display_event_in"])
        self.add_coupling(display.output["state_update_out"], report.input["state_update_in"])

        self.add_coupling(alarm_admin.output["operation_fact_out"], report.input["operation_fact_in"])
        self.add_coupling(alarm_admin.output["operation_update_out"], report.input["operation_update_in"])