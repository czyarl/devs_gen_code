from xdevs.models import Atomic, Coupled, Port

from .SAA_System_libs.InputReader import InputReader
from .SAA_System_libs.AlarmAdmin import AlarmAdmin
from .SAA_System_libs.Authentication import Authentication
from .SAA_System_libs.Display import Display
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Coordinate the Secure Area Access simulation by routing input requests through the processing pipeline (InputReader, AlarmAdmin, Authentication, Display) and collecting all observable events and operation results into a final report."""

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

        alarm_admin = AlarmAdmin(
            name="AlarmAdmin",
            parent=self,
            alarm_admin_delay=alarm_admin_delay,
        )

        authentication = Authentication(
            name="Authentication",
            parent=self,
            authentication_delay=authentication_delay,
        )

        display = Display(
            name="Display",
            parent=self,
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
        self.add_component(alarm_admin)
        self.add_component(authentication)
        self.add_component(display)
        self.add_component(report_collector)

        # Define couplings
        # Connect InputReader.request_out to AlarmAdmin.request_in.
        self.add_coupling(
            input_reader.output["request_out"],
            alarm_admin.input["request_in"],
        )

        # Connect InputReader.input_event_out to ReportCollector.event_in.
        self.add_coupling(
            input_reader.output["input_event_out"],
            report_collector.input["event_in"],
        )

        # Connect AlarmAdmin.alarm_event_out to ReportCollector.event_in.
        self.add_coupling(
            alarm_admin.output["alarm_event_out"],
            report_collector.input["event_in"],
        )

        # Connect AlarmAdmin.auth_request_out to Authentication.auth_request_in.
        self.add_coupling(
            alarm_admin.output["auth_request_out"],
            authentication.input["auth_request_in"],
        )

        # Connect AlarmAdmin.operation_status_out to ReportCollector.operation_result_in.
        self.add_coupling(
            alarm_admin.output["operation_status_out"],
            report_collector.input["operation_result_in"],
        )

        # Connect Authentication.auth_event_out to ReportCollector.event_in.
        self.add_coupling(
            authentication.output["auth_event_out"],
            report_collector.input["event_in"],
        )

        # Connect Authentication.display_request_out to Display.display_request_in.
        self.add_coupling(
            authentication.output["display_request_out"],
            display.input["display_request_in"],
        )

        # Connect Authentication.auth_complete_out to AlarmAdmin.auth_complete_in.
        self.add_coupling(
            authentication.output["auth_complete_out"],
            alarm_admin.input["auth_complete_in"],
        )

        # Connect Authentication.operation_status_out to ReportCollector.operation_result_in.
        self.add_coupling(
            authentication.output["operation_status_out"],
            report_collector.input["operation_result_in"],
        )

        # Connect Display.display_event_out to ReportCollector.event_in.
        self.add_coupling(
            display.output["display_event_out"],
            report_collector.input["event_in"],
        )