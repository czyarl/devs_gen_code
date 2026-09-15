import json
import sys
from typing import Any

from xdevs.models import Atomic, Coupled, Port


class ReportCollector(Atomic):
    """
    Atomic DEVS model: ReportCollector

    Collects event facts and operation facts during the simulation and emits
    exactly one final JSON report to stdout from exit().
    """

    def __init__(self, name: str, parent: Coupled | None, test_name: str, max_simulation_time: float):
        super().__init__(name)
        self.parent = parent

        self.test_name = test_name
        self.max_simulation_time = float(max_simulation_time)

        # Input ports
        self.add_in_port(Port(dict, "input_event_fact_in"))
        self.add_in_port(Port(dict, "stage_event_fact_in"))
        self.add_in_port(Port(dict, "operation_fact_in"))

        # Retained state
        self._arrival_counter: int = 0
        self._events_raw: list[dict[str, Any]] = []
        self._operations_raw: list[dict[str, Any]] = []

        self._any_display_event: bool = False
        self._last_display_state: str | None = None

        self._any_auth_event: bool = False
        self._last_auth_state_mapped: str | None = None  # fallback: Disarmed/Armed derived from auth state

    def initialize(self):
        self._arrival_counter = 0
        self._events_raw = []
        self._operations_raw = []
        self._any_display_event = False
        self._last_display_state = None
        self._any_auth_event = False
        self._last_auth_state_mapped = None
        self.passivate("COLLECTING")

    def _next_arrival_index(self) -> int:
        self._arrival_counter += 1
        return self._arrival_counter

    @staticmethod
    def _drop_state_if_not_allowed(event: dict[str, Any]) -> dict[str, Any]:
        """
        Enforce output constraint: only authentication and display may include 'state'.
        If upstream sends 'state' for other components, drop it.
        """
        if not isinstance(event, dict):
            return event  # type: ignore[return-value]

        component = event.get("component", None)
        if "state" in event and component not in {"authentication", "display"}:
            cleaned = dict(event)
            cleaned.pop("state", None)
            return cleaned
        return event

    @staticmethod
    def _map_auth_state_to_final_state(auth_state: Any) -> str | None:
        if auth_state == "DisarmValid":
            return "Disarmed"
        if auth_state == "ArmValid":
            return "Armed"
        return None

    def deltext(self, e: float):
        # This model is passive; it only collects incoming facts.
        # Preserve quiescence (no internal events).
        # We still accept inputs regardless of elapsed time e.
        for record in self.input["input_event_fact_in"].values:
            if not isinstance(record, dict):
                continue
            # Minimal validation: must contain keys {'time','component','message'}
            if not {"time", "component", "message"}.issubset(record.keys()):
                continue
            # Store as-is except enforce 'state' absence for input_reader/alarmAdmin by dropping if present.
            stored = self._drop_state_if_not_allowed(record)
            self._events_raw.append(
                {"__arrival_index": self._next_arrival_index(), "__kind": "event", **stored}
            )

        for record in self.input["stage_event_fact_in"].values:
            if not isinstance(record, dict):
                continue
            stored = self._drop_state_if_not_allowed(record)
            self._events_raw.append(
                {"__arrival_index": self._next_arrival_index(), "__kind": "event", **stored}
            )

            component = stored.get("component", None)
            if component == "display" and "state" in stored:
                self._any_display_event = True
                self._last_display_state = stored.get("state")
            elif component == "authentication" and "state" in stored:
                self._any_auth_event = True
                mapped = self._map_auth_state_to_final_state(stored.get("state"))
                if mapped is not None:
                    self._last_auth_state_mapped = mapped

        for record in self.input["operation_fact_in"].values:
            if not isinstance(record, dict):
                continue
            # Store as-is
            self._operations_raw.append(
                {"__arrival_index": self._next_arrival_index(), "__kind": "op", **record}
            )

        self.passivate("COLLECTING")

    def lambdaf(self):
        # No DEVS outputs.
        return None

    def deltint(self):
        # No internal events are scheduled; remain passive.
        self.passivate("COLLECTING")

    def _sorted_events_for_output(self) -> list[dict[str, Any]]:
        # Stable sort by time, preserving arrival order for ties.
        # Python sort is stable; include arrival index as a secondary key only if needed.
        # We can sort by time alone; stability preserves insertion order for equal keys.
        events = [dict(item) for item in self._events_raw]
        events.sort(key=lambda d: float(d.get("time", 0.0)))
        # Remove internal keys and ensure state constraint again.
        out: list[dict[str, Any]] = []
        for ev in events:
            ev.pop("__arrival_index", None)
            ev.pop("__kind", None)
            ev = self._drop_state_if_not_allowed(ev)
            out.append(ev)
        return out

    def _sorted_operations_for_output(self) -> list[dict[str, Any]]:
        ops = [dict(item) for item in self._operations_raw]
        ops.sort(key=lambda d: float(d.get("input_time", 0.0)))
        out: list[dict[str, Any]] = []
        for op in ops:
            op.pop("__arrival_index", None)
            op.pop("__kind", None)
            out.append(op)
        return out

    def _compute_final_state(self, sorted_events: list[dict[str, Any]], sorted_ops: list[dict[str, Any]]) -> str:
        # If at least one display event was received, final_state is state of chronologically last display event
        if any(ev.get("component") == "display" and "state" in ev for ev in sorted_events):
            last_state: str | None = None
            for ev in sorted_events:
                if ev.get("component") == "display" and "state" in ev:
                    last_state = ev.get("state")
            if last_state is not None:
                return str(last_state)

        # Else, if no display events but at least one accepted operation exists, use last authentication state mapping if available
        any_accepted = any(bool(op.get("completed")) for op in sorted_ops)
        if any_accepted:
            # Find chronologically last authentication event with state, map it
            last_mapped: str | None = None
            for ev in sorted_events:
                if ev.get("component") == "authentication" and "state" in ev:
                    last_mapped = self._map_auth_state_to_final_state(ev.get("state"))
            if last_mapped is not None:
                return last_mapped
            if self._last_auth_state_mapped is not None:
                return self._last_auth_state_mapped

        # Else: Disarmed
        return "Disarmed"

    def _compute_simulation_time(self, sorted_events: list[dict[str, Any]], sorted_ops: list[dict[str, Any]]) -> float:
        max_event_time = 0.0
        for ev in sorted_events:
            try:
                t = float(ev.get("time", 0.0))
            except (TypeError, ValueError):
                continue
            if t > max_event_time:
                max_event_time = t

        # Conservative horizon-capping inference.
        # If there is at least one accepted operation, and we have evidence that display emissions are missing
        # while the latest observed event time is strictly less than max_simulation_time, cap to max_simulation_time.
        any_accepted = any(bool(op.get("completed")) for op in sorted_ops)
        if any_accepted and max_event_time < self.max_simulation_time:
            # Evidence heuristic:
            # - At least one authentication event exists at time <= max_simulation_time
            # - and either no display events exist at all, or the latest display time is < latest auth time (indicating pending display)
            latest_auth_time: float | None = None
            latest_display_time: float | None = None
            any_auth = False
            any_display = False

            for ev in sorted_events:
                comp = ev.get("component")
                if comp == "authentication":
                    any_auth = True
                    try:
                        t = float(ev.get("time"))
                    except (TypeError, ValueError):
                        continue
                    if t <= self.max_simulation_time:
                        if latest_auth_time is None or t > latest_auth_time:
                            latest_auth_time = t
                elif comp == "display":
                    any_display = True
                    try:
                        t = float(ev.get("time"))
                    except (TypeError, ValueError):
                        continue
                    if latest_display_time is None or t > latest_display_time:
                        latest_display_time = t

            missing_display_evidence = False
            if any_auth and latest_auth_time is not None:
                if (not any_display) or (latest_display_time is None) or (latest_display_time < latest_auth_time):
                    missing_display_evidence = True

            if missing_display_evidence:
                return float(self.max_simulation_time)

        return float(max_event_time)

    def exit(self):
        events_out = self._sorted_events_for_output()
        ops_out = self._sorted_operations_for_output()

        record = {
            "test_name": self.test_name,
            "simulation_time": self._compute_simulation_time(events_out, ops_out),
            "initial_state": "Disarmed",
            "final_state": self._compute_final_state(events_out, ops_out),
            "events": events_out,
            "operations": ops_out,
        }

        # Write exactly one JSON object to stdout, newline allowed, nothing else to stdout.
        print(json.dumps(record), flush=True)

        # Optional debug to stderr (none by default). Keep hook for future troubleshooting.
        # print(f"[ReportCollector] wrote final report for test_name={self.test_name}", file=sys.stderr, flush=True)