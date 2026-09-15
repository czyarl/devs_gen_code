import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


def _format_time_str(t: float) -> str:
    # HH:MM:SS:mmm from simulation seconds (float). Milliseconds are truncated.
    if t < 0:
        t = 0.0
    total_ms = int(t * 1000.0)
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_min = total_s // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


class Queue(Atomic):
    """
    Atomic FIFO dispatcher:
    - Buffers unpaired clients in strict FIFO order.
    - Tracks currently idle employees (no duplicates).
    - Forms instantaneous pairings whenever possible and emits:
      (1) pairing_out DEVS messages and (2) JSONL stdout records.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "client_in"))
        self.add_in_port(Port(dict, "employee_available_in"))
        self.add_out_port(Port(dict, "pairing_out"))

        self.waiting_clients: deque[dict] = deque()
        self.available_employees: set[int] = set()
        self.pending_pairings: list[dict] = []

    def initialize(self):
        self.waiting_clients = deque()
        self.available_employees = set()
        self.pending_pairings = []
        self.passivate("WAITING")

    def _compute_pairings(self, t: float) -> None:
        # Compute as many pairings as possible at time t.
        while self.waiting_clients and self.available_employees:
            client = self.waiting_clients.popleft()
            employee_id = min(self.available_employees)  # deterministic policy
            self.available_employees.remove(employee_id)

            assignment = {
                "client_id": int(client["client_id"]),
                "arrival_time": float(client["arrival_time"]),
                "employee_id": int(employee_id),
                "paired_time": float(t),
            }
            self.pending_pairings.append(assignment)

        if self.pending_pairings:
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self.passivate("WAITING")

    def deltext(self, e: float):
        # If an internal output is already scheduled at the same time,
        # do not change state here; let the imminent internal transition run.
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process all external inputs at current simulation time.
        t = float(get_current_time())

        for m in self.input["client_in"].values:
            client_id = int(m["client_id"])
            arrival_time = float(m["arrival_time"])
            self.waiting_clients.append({"client_id": client_id, "arrival_time": arrival_time})

        for m in self.input["employee_available_in"].values:
            employee_id = int(m["employee_id"])
            # Ignore duplicates
            if employee_id not in self.available_employees:
                self.available_employees.add(employee_id)

        self._compute_pairings(t)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        t = float(get_current_time())
        time_str = _format_time_str(t)

        for assignment in self.pending_pairings:
            # DEVS output
            self.output["pairing_out"].add(dict(assignment))

            # External IO: JSONL stdout
            record = {
                "time": t,
                "time_str": time_str,
                "event": "client_paired",
                "entity_type": "queue",
                "entity": "Queue",
                "payload": {
                    "client_id": int(assignment["client_id"]),
                    "employee_id": int(assignment["employee_id"]),
                    "paired_time": t,
                },
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        # Clear emitted pairings and immediately see if more can be formed
        # (e.g., if there were more waiting clients and available employees).
        self.pending_pairings = []
        t = float(get_current_time())
        self._compute_pairings(t)

    def exit(self):
        pass