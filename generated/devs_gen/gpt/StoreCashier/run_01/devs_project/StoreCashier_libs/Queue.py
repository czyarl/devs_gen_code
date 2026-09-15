import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


def _format_time_hhmmssmmm(t: float) -> str:
    """Format seconds as HH:MM:SS:mmm (milliseconds, zero-padded)."""
    if t < 0:
        t = 0.0
    total_ms = int(round(t * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "client_in"))
        self.add_in_port(Port(dict, "employee_1_available_in"))
        self.add_in_port(Port(dict, "employee_2_available_in"))

        self.add_out_port(Port(dict, "assign_employee_1_out"))
        self.add_out_port(Port(dict, "assign_employee_2_out"))

        self.waiting_clients: deque[dict] = deque()
        self.employee_available: dict[int, bool] = {1: False, 2: False}

        # Prepared batch of assignments to emit at the next lambdaf() (time t).
        self._prepared_assignments: list[dict] = []

    def initialize(self):
        self.waiting_clients = deque()
        self.employee_available = {1: False, 2: False}
        self._prepared_assignments = []
        self.passivate("WAITING")

    def _has_capacity(self) -> bool:
        return bool(self.waiting_clients) and (self.employee_available[1] or self.employee_available[2])

    def _prepare_pairings_if_possible(self) -> None:
        """Prepare maximal matching at current time t and schedule immediate output if any."""
        if not self._has_capacity():
            self._prepared_assignments = []
            self.passivate("WAITING")
            return

        t = float(get_current_time())
        prepared: list[dict] = []

        while self.waiting_clients and (self.employee_available[1] or self.employee_available[2]):
            client = self.waiting_clients.popleft()

            # Deterministic employee selection: 1 then 2.
            if self.employee_available[1]:
                employee_id = 1
            else:
                employee_id = 2

            self.employee_available[employee_id] = False

            assignment = {
                "client_id": client["client_id"],
                "arrival_time": client["arrival_time"],
                "employee_id": employee_id,
                "paired_time": t,
            }
            prepared.append(assignment)

        self._prepared_assignments = prepared
        if self._prepared_assignments:
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self.passivate("WAITING")

    @staticmethod
    def _valid_client(msg: object) -> bool:
        return isinstance(msg, dict) and ("client_id" in msg) and ("arrival_time" in msg)

    @staticmethod
    def _valid_availability(msg: object, expected_employee_id: int) -> bool:
        return isinstance(msg, dict) and (msg.get("employee_id") == expected_employee_id)

    def deltext(self, e: float):
        # If we're already scheduled to output at this same time, keep it.
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process all inputs received at this simulation time.
        for client in self.input["client_in"].values:
            if self._valid_client(client):
                # Store exactly as received (dict with required keys).
                self.waiting_clients.append(client)

        for notice in self.input["employee_1_available_in"].values:
            if self._valid_availability(notice, 1):
                self.employee_available[1] = True

        for notice in self.input["employee_2_available_in"].values:
            if self._valid_availability(notice, 2):
                self.employee_available[2] = True

        # After processing all inputs at this time, trigger immediate pairing if possible.
        self._prepare_pairings_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        # Emit all prepared pairings at current time t, in prepared order.
        t = float(get_current_time())
        for assignment in self._prepared_assignments:
            employee_id = int(assignment["employee_id"])
            if employee_id == 1:
                self.output["assign_employee_1_out"].add(dict(assignment))
            else:
                self.output["assign_employee_2_out"].add(dict(assignment))

            record = {
                "time": t,
                "time_str": _format_time_hhmmssmmm(t),
                "event": "client_paired",
                "entity_type": "queue",
                "entity": "Queue",
                "payload": {
                    "client_id": int(assignment["client_id"]),
                    "employee_id": employee_id,
                    "paired_time": t,
                },
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        # Clear emitted batch and immediately prepare further pairings at same time if possible.
        self._prepared_assignments = []
        self._prepare_pairings_if_possible()

    def exit(self):
        pass