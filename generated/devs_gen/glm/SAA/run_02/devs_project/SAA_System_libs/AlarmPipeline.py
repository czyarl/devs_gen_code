from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class AlarmPipeline(Atomic):
    """Manage the AlarmAdmin busy state, apply the ordered delays for accepted requests, and send alarmAdmin, authentication, and display event records along with operation facts to ReportCollector."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        alarm_admin_delay: float,
        authentication_delay: float,
        display_delay: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay

        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "event_fact_out"))
        self.add_out_port(Port(dict, "operation_fact_out"))

        self.current_request = None
        self.rejection_queue = []
        self.saved_phase = "IDLE"
        self.saved_sigma = float('inf')

    def initialize(self):
        self.current_request = None
        self.rejection_queue = []
        self.saved_phase = "IDLE"
        self.saved_sigma = float('inf')
        self.passivate("IDLE")

    def deltext(self, e: float):
        was_busy = self.phase != "IDLE"
        remaining = max(0.0, self.ta() - e) if was_busy else 0.0

        has_input = False
        for request in self.input["request_in"].values:
            has_input = True
            if not was_busy:
                # Accept the request
                self.current_request = dict(request)
                self.hold_in("ALARM_ADMIN", self.alarm_admin_delay)
                break
            else:
                # Busy: Queue for rejection
                self.rejection_queue.append(dict(request))

        if has_input:
            if not was_busy:
                # Already handled above
                pass
            else:
                # We are busy. If we have rejections to emit, interrupt to emit them.
                if self.rejection_queue:
                    self.saved_phase = self.phase
                    self.saved_sigma = remaining
                    self.hold_in("EMIT_REJECTION", 0.0)
                else:
                    # Continue current phase
                    self.hold_in(self.phase, remaining)
        else:
            # No input, just update time if busy
            if was_busy:
                self.hold_in(self.phase, remaining)

    def lambdaf(self):
        now = get_current_time()

        if self.phase == "EMIT_REJECTION":
            if self.rejection_queue:
                req = self.rejection_queue.pop(0)
                action = "disarm" if req["value"] == 0 else "arm"
                self.output["operation_fact_out"].add({
                    "input_time": req["input_time"],
                    "action": action,
                    "completed": False,
                    "completion_time": None
                })
        elif self.phase == "ALARM_ADMIN":
            msg = f"{{{self.current_request['port']} {self.current_request['value']}}}"
            self.output["event_fact_out"].add({
                "time": now,
                "component": "alarmAdmin",
                "message": msg
            })
        elif self.phase == "AUTHENTICATION":
            state_str = "DisarmValid" if self.current_request["value"] == 0 else "ArmValid"
            msg = f"{{{self.current_request['port']} {self.current_request['value']}}}"
            self.output["event_fact_out"].add({
                "time": now,
                "component": "authentication",
                "message": msg,
                "state": state_str
            })
            action = "disarm" if self.current_request["value"] == 0 else "arm"
            self.output["operation_fact_out"].add({
                "input_time": self.current_request["input_time"],
                "action": action,
                "completed": True,
                "completion_time": now
            })
        elif self.phase == "DISPLAY":
            state_str = "Disarmed" if self.current_request["value"] == 0 else "Armed"
            msg = f"{{{self.current_request['port']} {self.current_request['value']}}}"
            self.output["event_fact_out"].add({
                "time": now,
                "component": "display",
                "message": msg,
                "state": state_str
            })

    def deltint(self):
        if self.phase == "EMIT_REJECTION":
            if self.rejection_queue:
                self.hold_in("EMIT_REJECTION", 0.0)
            else:
                self.hold_in(self.saved_phase, self.saved_sigma)
        elif self.phase == "ALARM_ADMIN":
            self.hold_in("AUTHENTICATION", self.authentication_delay)
        elif self.phase == "AUTHENTICATION":
            self.hold_in("DISPLAY", self.display_delay)
        elif self.phase == "DISPLAY":
            self.current_request = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass