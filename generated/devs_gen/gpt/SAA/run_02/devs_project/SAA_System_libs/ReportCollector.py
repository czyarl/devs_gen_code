import json
import math
import sys
from typing import Any

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ReportCollector(Atomic):
    """
    Passive atomic sink that aggregates structured event/operation facts and
    prints exactly one final JSON report to stdout at simulation end.
    """

    _FLOAT_TOL: float = 1e-9

    def __init__(self, name: str, parent: Coupled | None, test_name: str, max_simulation_time: float):
        super().__init__(name)
        self.parent = parent
        self.test_name = test_name
        self.max_simulation_time = float(max_simulation_time)

        self.add_in_port(Port(dict, "input_event_fact_in"))
        self.add_in_port(Port(dict, "stage_event_fact_in"))
        self.add_in_port(Port(dict, "operation_fact_in"))

        # Initialized in initialize()
        self.initial_state: str
        self.final_state: str
        self.events: list[dict[str, Any]]
        self.operations: list[dict[str, Any]]
        self._event_arrival_counter: int
        self._op_arrival_counter: int
        self.observed_last_event_time: float

    def initialize(self):
        self.initial_state = "Disarmed"
        self.final_state = "Disarmed"
        self.events = []
        self.operations = []
        self._event_arrival_counter = 0
        self._op_arrival_counter = 0
        self.observed_last_event_time = 0.0
        self.passivate("COLLECTING")

    def deltext(self, e: float):
        # No internal events are ever scheduled, but preserve standard DEVS semantics.
        if self.phase != "COLLECTING" and not math.isinf(self.ta()):
            self.hold_in(self.phase, max(0.0, self.ta() - e))

        # 1) input_event_fact_in
        for rec in self.input["input_event_fact_in"].values:
            try:
                d = dict(rec)
            except Exception:
                d = {"_invalid_record": str(rec)}
                print("ReportCollector: received non-dict input_event_fact_in record", file=sys.stderr, flush=True)

            self.events.append(d)
            self._event_arrival_counter += 1

            try:
                t = float(d["time"])
                if t > self.observed_last_event_time:
                    self.observed_last_event_time = t
            except Exception:
                print("ReportCollector: input_reader event missing/invalid 'time'", file=sys.stderr, flush=True)

            # Optional validation of message format; do not modify record.
            try:
                msg = d.get("message", None)
                if not (isinstance(msg, str) and msg.startswith("{") and msg.endswith("}")):
                    print("ReportCollector: input_reader event has invalid message format", file=sys.stderr, flush=True)
            except Exception:
                pass

        # 2) stage_event_fact_in
        for rec in self.input["stage_event_fact_in"].values:
            try:
                d = dict(rec)
            except Exception:
                d = {"_invalid_record": str(rec)}
                print("ReportCollector: received non-dict stage_event_fact_in record", file=sys.stderr, flush=True)

            self.events.append(d)
            self._event_arrival_counter += 1

            try:
                t = float(d["time"])
                if t > self.observed_last_event_time:
                    self.observed_last_event_time = t
            except Exception:
                print("ReportCollector: stage event missing/invalid 'time'", file=sys.stderr, flush=True)

            try:
                msg = d.get("message", None)
                if not (isinstance(msg, str) and msg.startswith("{") and msg.endswith("}")):
                    print("ReportCollector: stage event has invalid message format", file=sys.stderr, flush=True)
            except Exception:
                pass

        # 3) operation_fact_in
        for rec in self.input["operation_fact_in"].values:
            try:
                op = dict(rec)
            except Exception:
                op = {"_invalid_record": str(rec)}
                print("ReportCollector: received non-dict operation_fact_in record", file=sys.stderr, flush=True)

            self.operations.append(op)
            self._op_arrival_counter += 1

            try:
                completed = bool(op["completed"])
                if completed:
                    action = op.get("action", None)
                    if action == "arm":
                        self.final_state = "Armed"
                    elif action == "disarm":
                        self.final_state = "Disarmed"
            except Exception:
                print("ReportCollector: operation record missing/invalid fields", file=sys.stderr, flush=True)

        self.passivate("COLLECTING")

    def lambdaf(self):
        # No DEVS outputs.
        return None

    def deltint(self):
        # No internal transitions; remain passive.
        self.passivate("COLLECTING")

    def exit(self):
        # Stable sort by time/input_time; Python's sort is stable, preserving arrival order for ties.
        try:
            self.events.sort(key=lambda item: float(item["time"]))
        except Exception:
            # Best-effort: keep original order if sorting fails.
            print("ReportCollector: failed to sort events by 'time'", file=sys.stderr, flush=True)

        try:
            self.operations.sort(key=lambda item: float(item["input_time"]))
        except Exception:
            print("ReportCollector: failed to sort operations by 'input_time'", file=sys.stderr, flush=True)

        final_framework_time = float(get_current_time())
        if abs(final_framework_time - self.max_simulation_time) <= self._FLOAT_TOL:
            simulation_time = float(self.max_simulation_time)
        else:
            simulation_time = float(self.observed_last_event_time) if self.events else 0.0

        report = {
            "test_name": self.test_name,
            "simulation_time": simulation_time,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "events": self.events,
            "operations": self.operations,
        }
        print(json.dumps(report), flush=True)