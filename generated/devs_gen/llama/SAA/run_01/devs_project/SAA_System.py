"""Complete pattern: SAA_System.py"""

from xdevs.models import Atomic, Coupled, Port
import argparse
import json
import sys
from typing import Any
from .SAA_System_libs.InputReader import InputReader
from .SAA_System_libs.AlarmAdmin import AlarmAdmin
from .SAA_System_libs.Authentication import Authentication
from .SAA_System_libs.Display import Display
from .SAA_System_libs.ReportCollector import ReportCollector


class SAA_System(Coupled):
    """Top-level model for a secure area access control system with PIN authentication."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        test_name: str,
        alarm_admin_delay: float = 10.0,
        authentication_delay: float = 2.0,
        display_delay: float = 3.0,
        max_simulation_time: float = 1000.0,
        input_file: str = "",
    ):
        super().__init__(name)
        self.parent = parent

        self.input_reader = InputReader(
            name="input_reader",
            parent=self,
            input_file=input_file,
        )
        self.alarm_admin = AlarmAdmin(
            name="alarm_admin",
            parent=self,
        )
        self.authentication = Authentication(
            name="authentication",
            parent=self,
        )
        self.display = Display(
            name="display",
            parent=self,
        )
        self.report_collector = ReportCollector(
            name="report_collector",
            parent=self,
            test_name=test_name,
        )

        self.add_component(self.input_reader)
        self.add_component(self.alarm_admin)
        self.add_component(self.authentication)
        self.add_component(self.display)
        self.add_component(self.report_collector)

        self.add_coupling(
            self.input_reader.request_out,
            self.alarm_admin.request_in,
        )
        self.add_coupling(
            self.input_reader.input_fact_out,
            self.report_collector.input_fact_in,
        )
        self.add_coupling(
            self.alarm_admin.event_fact_out,
            self.report_collector.event_fact_in,
        )
        self.add_coupling(
            self.alarm_admin.operation_fact_out,
            self.report_collector.operation_fact_in,
        )
        self.add_coupling(
            self.authentication.event_fact_out,
            self.report_collector.event_fact_in,
        )
        self.add_coupling(
            self.authentication.operation_fact_out,
            self.report_collector.operation_fact_in,
        )
        self.add_coupling(
            self.display.event_fact_out,
            self.report_collector.event_fact_in,
        )
        self.add_coupling(
            self.display.operation_fact_out,
            self.report_collector.operation_fact_in,
        )

    def initialize(self) -> None:
        super().initialize()

        if self.parent is None:
            parser = argparse.ArgumentParser()
            parser.add_argument(
                "--test_name",
                type=str,
                required=True,
            )
            parser.add_argument(
                "--input_file",
                type=str,
                default="",
            )
            parser.add_argument(
                "--alarm_admin_delay",
                type=float,
                default=alarm_admin_delay,
            )
            parser.add_argument(
                "--authentication_delay",
                type=float,
                default=authentication_delay,
            )
            parser.add_argument(
                "--display_delay",
                type=float,
                default=display_delay,
            )
            parser.add_argument(
                "--max_simulation_time",
                type=float,
                default=max_simulation_time,
            )
            args: Any = parser.parse_args()

            self.input_reader.initialize(
                input_file=args.input_file,
            )
            self.alarm_admin.initialize()
            self.authentication.initialize()
            self.display.initialize()
            self.report_collector.initialize(
                test_name=args.test_name,
            )

    def exit(self) -> None:
        super().exit()
        print(json.dumps(self.report_collector.final_report), flush=True)