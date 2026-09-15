"""Requirement-level rules for the two-employee StoreCashier scenario."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, ratio_score


TOLERANCE = 0.05
REQUIRED_EVENTS = {
    "employee_available",
    "client_generated",
    "client_paired",
    "client_served",
}
TIME_STRING_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}):(\d{3})$")


def _sim_args(case: EvaluatedCase) -> dict:
    value = case.config.get("sim_args")
    if not isinstance(value, dict):
        raise BenchmarkConfigurationError(f"case {case.case_id} has no sim_args mapping")
    return value


def _checker_config(case: EvaluatedCase) -> dict:
    value = case.config.get("checker_config")
    if not isinstance(value, dict):
        raise BenchmarkConfigurationError(
            f"case {case.case_id} has no checker_config mapping"
        )
    return value


def _events(case: EvaluatedCase, event: str) -> list[TraceRecord]:
    return [record for record in case.trace_records if record.event == event]


def _close(left: float, right: float) -> bool:
    return abs(float(left) - float(right)) <= TOLERANCE


def _parse_time_string(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    match = TIME_STRING_RE.fullmatch(value)
    if match is None:
        return None
    hours, minutes, seconds, milliseconds = (int(item) for item in match.groups())
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


class TraceMetadataRule(BehavioralRule):
    """Check raw time labels and employee/entity identity after projection."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        successes = 0
        opportunities = 0
        for record in case.trace_records:
            parsed_time = _parse_time_string(record.payload.get("time_str"))
            opportunities += 1
            successes += int(
                parsed_time is not None and abs(parsed_time - record.time) <= 0.0005 + 1e-12
            )
            if record.event in {"employee_available", "client_served"}:
                opportunities += 1
                successes += int(
                    record.entity == f"Employee_{record.payload.get('employee_id')}"
                )
        return QualityScore(
            ratio_score(successes, opportunities),
            (f"metadata obligations={successes}/{opportunities}",),
        )


def _horizon(case: EvaluatedCase) -> float:
    value = str(_sim_args(case).get("simulation_time", "00:05:00:000"))
    parts = value.split(":")
    if len(parts) != 4:
        raise BenchmarkConfigurationError(f"invalid simulation_time {value!r}")
    try:
        hours, minutes, seconds, milliseconds = (int(item) for item in parts)
    except ValueError as exc:
        raise BenchmarkConfigurationError(f"invalid simulation_time {value!r}") from exc
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def _generation_map(case: EvaluatedCase) -> dict[int, float]:
    return {
        record.payload["client_id"]: record.time
        for record in _events(case, "client_generated")
    }


def _pair_map(case: EvaluatedCase) -> dict[int, TraceRecord]:
    values: dict[int, TraceRecord] = {}
    for record in _events(case, "client_paired"):
        values.setdefault(record.payload["client_id"], record)
    return values


def _service_bounds(case: EvaluatedCase, employee_id: int) -> tuple[float, float]:
    config = _checker_config(case)
    mean = float(
        config.get(
            f"employee_{employee_id}_service_time",
            config.get(f"employee_{employee_id}_mean", 20.0 if employee_id == 1 else 30.0),
        )
    )
    stddev = float(config.get(f"employee_{employee_id}_stddev", 0.0 if employee_id == 1 else 4.0))
    if stddev == 0:
        return mean - TOLERANCE, mean + TOLERANCE
    return mean - 3 * stddev - TOLERANCE, mean + 3 * stddev + TOLERANCE


class ClientGenerationRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        records = _events(case, "client_generated")
        if not records:
            return QualityScore(0.0, ("no generated clients",))
        mean = float(self.spec.parameters["client_mean"])
        stddev = float(self.spec.parameters["client_stddev"])
        successes = 0
        opportunities = 0
        for index, record in enumerate(records, start=1):
            opportunities += 2
            successes += int(record.payload["client_id"] == index)
            successes += int(_close(record.payload["arrival_time"], record.time))
        opportunities += 1
        successes += int(_close(records[0].time, 0.0))
        for previous, current in zip(records, records[1:]):
            interval = current.time - previous.time
            opportunities += 1
            successes += int(-TOLERANCE <= interval <= mean + 5 * stddev + TOLERANCE)
        return QualityScore(ratio_score(successes, opportunities))


class FifoImmediatePairingRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        waiting: deque[int] = deque()
        arrivals: dict[int, float] = {}
        available_since: dict[int, float] = {}
        paired: set[int] = set()
        successes = 0
        opportunities = 0
        indexed = list(enumerate(case.trace_records))
        indexed.sort(key=lambda item: (item[1].time, item[0]))
        for _, record in indexed:
            if record.event == "client_generated":
                client_id = record.payload["client_id"]
                waiting.append(client_id)
                arrivals[client_id] = record.time
            elif record.event == "employee_available":
                available_since[record.payload["employee_id"]] = record.time
            elif record.event == "client_paired":
                client_id = record.payload["client_id"]
                employee_id = record.payload["employee_id"]
                opportunities += 5
                successes += int(_close(record.payload["paired_time"], record.time))
                successes += int(client_id in arrivals and client_id not in paired)
                successes += int(bool(waiting) and waiting[0] == client_id)
                successes += int(employee_id in available_since)
                if waiting and available_since:
                    ready_time = max(arrivals[waiting[0]], min(available_since.values()))
                    successes += int(_close(record.time, ready_time))
                if client_id in waiting:
                    waiting.remove(client_id)
                paired.add(client_id)
                available_since.pop(employee_id, None)
        if opportunities == 0:
            return QualityScore(0.0, ("no client_paired events",))
        return QualityScore(ratio_score(successes, opportunities))


class EmployeeExclusivityRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        available: set[int] = set()
        active: dict[int, int] = {}
        successes = 0
        opportunities = 0
        initial = {
            record.payload["employee_id"]
            for record in _events(case, "employee_available")
            if _close(record.time, 0.0)
        }
        for employee_id in (1, 2):
            opportunities += 1
            successes += int(employee_id in initial)
        indexed = list(enumerate(case.trace_records))
        priority = {"client_served": 0, "employee_available": 1, "client_generated": 2, "client_paired": 3}
        indexed.sort(key=lambda item: (item[1].time, priority.get(item[1].event, 9), item[0]))
        for _, record in indexed:
            employee_id = record.payload.get("employee_id")
            if record.event == "employee_available":
                opportunities += 1
                successes += int(employee_id not in active and employee_id not in available)
                available.add(employee_id)
            elif record.event == "client_paired":
                opportunities += 1
                successes += int(employee_id in available and employee_id not in active)
                available.discard(employee_id)
                active[employee_id] = record.payload["client_id"]
            elif record.event == "client_served":
                opportunities += 2
                successes += int(active.get(employee_id) == record.payload["client_id"])
                has_release = any(
                    item.event == "employee_available"
                    and item.payload["employee_id"] == employee_id
                    and _close(item.time, record.time)
                    for item in case.trace_records
                )
                successes += int(has_release)
                active.pop(employee_id, None)
        return QualityScore(ratio_score(successes, opportunities))


def _due_pairs(case: EvaluatedCase) -> dict[int, TraceRecord]:
    horizon = _horizon(case)
    due: dict[int, TraceRecord] = {}
    for client_id, pair in _pair_map(case).items():
        _, upper = _service_bounds(case, pair.payload["employee_id"])
        if pair.time + upper <= horizon + TOLERANCE:
            due[client_id] = pair
    return due


class ServiceDurationRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        due = _due_pairs(case)
        all_pairs = _pair_map(case)
        served = _events(case, "client_served")
        valid = 0
        matched: set[int] = set()
        for record in served:
            client_id = record.payload["client_id"]
            pair = all_pairs.get(client_id)
            if pair is None or pair.payload["employee_id"] != record.payload["employee_id"]:
                continue
            lower, upper = _service_bounds(case, record.payload["employee_id"])
            if client_id not in matched and lower <= record.time - pair.time <= upper:
                valid += 1
                matched.add(client_id)
        observed_validity = (
            valid / len(served) if served else (1.0 if not due else 0.0)
        )
        due_coverage = len(set(due) & matched) / len(due) if due else 1.0
        return QualityScore(
            (observed_validity + due_coverage) / 2.0,
            (
                f"observed duration validity={observed_validity:.6f}",
                f"guaranteed-due completion coverage={due_coverage:.6f}",
            ),
        )


class ServedFieldsRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        due = _due_pairs(case)
        all_pairs = _pair_map(case)
        arrivals = _generation_map(case)
        served = _events(case, "client_served")
        successes = 0
        observed_ids = {record.payload["client_id"] for record in served}
        missing_guaranteed = set(due) - observed_ids
        opportunities = (len(served) + len(missing_guaranteed)) * 4
        if opportunities == 0:
            return QualityScore(1.0, ("no service completion was due before the horizon",))
        consumed: set[int] = set()
        for record in served:
            client_id = record.payload["client_id"]
            pair = all_pairs.get(client_id)
            if pair is None or client_id in consumed:
                continue
            consumed.add(client_id)
            successes += int(pair.payload["employee_id"] == record.payload["employee_id"])
            successes += int(_close(record.payload["arrived"], arrivals.get(client_id, float("inf"))))
            successes += int(_close(record.payload["dispatched"], record.time))
            successes += int(
                _close(
                    record.payload["delay"],
                    float(record.payload["dispatched"]) - float(record.payload["arrived"]),
                )
            )
        return QualityScore(ratio_score(successes, opportunities))


class RequiredWorkflowRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        observed = {record.event for record in case.trace_records}
        event_coverage = len(observed & REQUIRED_EVENTS) / len(REQUIRED_EVENTS)
        due = _due_pairs(case)
        served_ids = {record.payload["client_id"] for record in _events(case, "client_served")}
        completion = (
            len(set(due) & served_ids) / len(due)
            if due
            else 1.0
        )
        return QualityScore(
            (event_coverage + completion) / 2.0,
            (f"event coverage={event_coverage:.6f}", f"due completion={completion:.6f}"),
        )


class HorizonRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        if not case.trace_records:
            return QualityScore(1.0, ("no records to place beyond the horizon",))
        horizon = _horizon(case)
        successes = sum(record.time <= horizon + TOLERANCE for record in case.trace_records)
        return QualityScore(ratio_score(successes, len(case.trace_records)))


RULE_TYPES = {
    "store.trace_metadata": TraceMetadataRule,
    "store.client_generation": ClientGenerationRule,
    "store.fifo_immediate_pairing": FifoImmediatePairingRule,
    "store.employee_exclusivity": EmployeeExclusivityRule,
    "store.service_duration": ServiceDurationRule,
    "store.served_fields": ServedFieldsRule,
    "store.required_workflow": RequiredWorkflowRule,
    "store.horizon": HorizonRule,
}


def build_rule_registry(requirements: Iterable[RequirementSpec]) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"StoreCashier has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
