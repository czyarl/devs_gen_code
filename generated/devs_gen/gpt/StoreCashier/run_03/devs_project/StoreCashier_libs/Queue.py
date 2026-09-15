import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


def _time_to_hhmmssmmm(t: float) -> str:
    """Format simulation time seconds as HH:MM:SS:mmm (milliseconds)."""
    if t < 0:
        t = 0.0
    total_ms = int(round(t * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_min = total_s // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


class Queue(Atomic):
    """
    Atomic FIFO queue + dispatcher.

    - Receives clients and employee availability notices.
    - Maintains FIFO waiting clients and a set of available employees.
    - Performs instantaneous pairing(s) at current simulation time whenever possible.
    - Emits assignment_out DEVS messages and writes client_paired JSONL to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "client_in"))
        self.add_in_port(Port(dict, "employee_available_in"))
        self.add_out_port(Port(dict, "assignment_out"))

        self.waiting: deque[dict] = deque()
        self.available_employees: set[int] = set()

        # Prepared batch for the next zero-delay output.
        self._prepared_assignments: list[dict] = []
        self._prepared_logs: list[dict] = []

        # Optional monotonicity guard (not used to reorder; only for sanity).
        self._last_emitted_time: float | None = None

    def initialize(self):
        self.waiting = deque()
        self.available_employees = set()
        self._prepared_assignments = []
        self._prepared_logs = []
        self._last_emitted_time = None
        self.passivate("WAITING")

    def _valid_client(self, msg: object) -> dict | None:
        if not isinstance(msg, dict):
            return None
        if "client_id" not in msg or "arrival_time" not in msg:
            return None
        try:
            client_id = int(msg["client_id"])
            arrival_time = float(msg["arrival_time"])
        except (TypeError, ValueError):
            return None
        return {"client_id": client_id, "arrival_time": arrival_time}

    def _valid_employee_notice(self, msg: object) -> int | None:
        if not isinstance(msg, dict):
            return None
        if "employee_id" not in msg:
            return None
        try:
            employee_id = int(msg["employee_id"])
        except (TypeError, ValueError):
            return None
        return employee_id

    def _prepare_pairings_if_possible(self) -> None:
        """
        Prepare maximal set of pairings at current simulation time.
        Schedules OUTPUT_READY at sigma=0 if at least one pairing exists,
        otherwise passivates.
        """
        t = float(get_current_time())

        self._prepared_assignments = []
        self._prepared_logs = []

        while self.waiting and self.available_employees:
            client = self.waiting.popleft()
            employee_id = min(self.available_employees)
            self.available_employees.remove(employee_id)

            assignment = {
                "client_id": int(client["client_id"]),
                "employee_id": int(employee_id),
                "arrival_time": float(client["arrival_time"]),
                "paired_time": t,
            }
            self._prepared_assignments.append(assignment)

            log_record = {
                "time": t,
                "time_str": _time_to_hhmmssmmm(t),
                "event": "client_paired",
                "entity_type": "queue",
                "entity": "Queue",
                "payload": {
                    "client_id": int(client["client_id"]),
                    "employee_id": int(employee_id),
                    "paired_time": t,
                },
            }
            self._prepared_logs.append(log_record)

        if self._prepared_assignments:
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self.passivate("WAITING")

    def deltext(self, e: float):
        # If an output is already scheduled, do not modify prepared batch.
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        for msg in self.input["client_in"].values:
            client = self._valid_client(msg)
            if client is not None:
                self.waiting.append(client)

        for msg in self.input["employee_available_in"].values:
            employee_id = self._valid_employee_notice(msg)
            if employee_id is not None:
                self.available_employees.add(employee_id)

        self._prepare_pairings_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        t = float(get_current_time())

        # Enforce nondecreasing emission order if simulator behaves unexpectedly.
        # Do not reorder; simply suppress if time goes backwards.
        if self._last_emitted_time is not None and t < self._last_emitted_time:
            return

        for assignment, log_record in zip(self._prepared_assignments, self._prepared_logs):
            self.output["assignment_out"].add(dict(assignment))
            print(json.dumps(log_record), flush=True)

        self._last_emitted_time = t

    def deltint(self):
        self._prepared_assignments = []
        self._prepared_logs = []
        # Continue pairing at the same simulation time if still possible.
        self._prepare_pairings_if_possible()

    def exit(self):
        pass