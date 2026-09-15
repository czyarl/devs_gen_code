"""Independent workflow oracle and requirement rules for Barbershop."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import heapq
from typing import Any

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, f1_score


TOLERANCE = 0.01


@dataclass(frozen=True)
class ExpectedWorkflow:
    states: tuple[tuple[float, str, str, Any], ...]
    messages: tuple[tuple[float, str, str, str], ...]
    accepted_customers: int


def _parse_input_time(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 4:
        raise BenchmarkConfigurationError(f"invalid Barbershop timestamp {value!r}")
    try:
        hours, minutes, seconds, centiseconds = (int(part) for part in parts)
    except ValueError as exc:
        raise BenchmarkConfigurationError(f"invalid Barbershop timestamp {value!r}") from exc
    if min(hours, minutes, seconds, centiseconds) < 0 or minutes >= 60 or seconds >= 60:
        raise BenchmarkConfigurationError(f"invalid Barbershop timestamp {value!r}")
    return hours * 3600 + minutes * 60 + seconds + centiseconds / 100.0


def _horizon(case: EvaluatedCase) -> float:
    args = case.config.get("sim_args")
    if not isinstance(args, dict):
        raise BenchmarkConfigurationError(f"case {case.case_id} has no sim_args mapping")
    value = args.get("--simulation_time", args.get("simulation_time", 1_000_000.0))
    return float(value)


def _arrivals(case: EvaluatedCase) -> list[float]:
    stdin = case.config.get("sim_stdin", "")
    if not isinstance(stdin, str):
        raise BenchmarkConfigurationError(f"case {case.case_id} has non-text sim_stdin")
    arrivals: list[float] = []
    for line in stdin.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 2 or parts[1] != "newcust":
            raise BenchmarkConfigurationError(
                f"case {case.case_id} has invalid input line {line!r}"
            )
        arrivals.append(_parse_input_time(parts[0]))
    return sorted(arrivals)


def build_expected_workflow(case: EvaluatedCase) -> ExpectedWorkflow:
    """Simulate the specified queue and serial inspection/cutting workflow."""
    horizon = _horizon(case)
    event_heap: list[tuple[float, int, int, str]] = []
    sequence = 0

    def schedule(time: float, priority: int, kind: str) -> None:
        nonlocal sequence
        heapq.heappush(event_heap, (time, priority, sequence, kind))
        sequence += 1

    for arrival in _arrivals(case):
        schedule(arrival, 3, "arrival")

    queue: list[int] = []
    next_customer = 1
    accepted = 0
    reception_status = "idle"
    checkhair_busy = False
    completed = 0
    states: list[tuple[float, str, str, Any]] = []
    messages: list[tuple[float, str, str, str]] = []

    def start_reception(time: float) -> None:
        nonlocal reception_status
        if reception_status == "idle" and queue:
            reception_status = "processing"
            schedule(time + 5.0, 2, "reception_ready")

    def handoff_if_possible(time: float) -> None:
        nonlocal reception_status, checkhair_busy
        if reception_status != "ready" or checkhair_busy or not queue:
            return
        queue.pop(0)
        states.append((time, "reception", "total customers num", len(queue)))
        messages.append((time, "reception", "cust", "newcust"))
        states.append((time, "checkhair", "customer", "newcust"))
        checkhair_busy = True
        reception_status = "idle"
        schedule(time + 7.0, 1, "inspection_done")
        start_reception(time)

    while event_heap:
        time, _, _, kind = heapq.heappop(event_heap)
        if time > horizon + TOLERANCE:
            continue
        if kind == "arrival":
            customer = next_customer
            next_customer += 1
            if len(queue) < 8:
                queue.append(customer)
                accepted += 1
                states.append((time, "reception", "total customers num", len(queue)))
                start_reception(time)
        elif kind == "reception_ready":
            reception_status = "ready"
            handoff_if_possible(time)
        elif kind == "inspection_done":
            messages.append((time, "checkhair", "to_cut", "newcust"))
            schedule(time + 20.0, 0, "service_done")
        elif kind == "service_done":
            completed += 1
            messages.append((time, "cuthair", "out", "done"))
            states.append((time, "cuthair", "total customer done", completed))
            states.append((time, "checkhair", "customer", "done"))
            messages.append((time, "checkhair", "to_reception", "done"))
            checkhair_busy = False
            handoff_if_possible(time)
        else:
            raise BenchmarkConfigurationError(f"unknown oracle event {kind!r}")
    return ExpectedWorkflow(tuple(states), tuple(messages), accepted)


def _canonical_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    if isinstance(value, str):
        try:
            return round(float(value), 6)
        except ValueError:
            return value
    return value


def _state_key(record: TraceRecord) -> tuple[float, str, str, Any]:
    return (
        round(record.time, 6),
        record.entity,
        record.payload["field"],
        _canonical_value(record.payload["value"]),
    )


def _message_key(record: TraceRecord) -> tuple[float, str, str, str]:
    return (
        round(record.time, 6),
        record.entity,
        record.payload["port"],
        record.payload["content"],
    )


def _multiset_f1(predicted: list[tuple], expected: list[tuple]) -> float:
    used: set[int] = set()
    true_positives = 0
    for wanted in expected:
        candidate = next(
            (
                index
                for index, actual in enumerate(predicted)
                if index not in used
                and abs(float(actual[0]) - float(wanted[0])) <= TOLERANCE
                and actual[1:] == wanted[1:]
            ),
            None,
        )
        if candidate is not None:
            used.add(candidate)
            true_positives += 1
    return f1_score(true_positives, len(predicted), len(expected))


def _states(case: EvaluatedCase, entity: str) -> list[tuple]:
    return [
        _state_key(record)
        for record in case.trace_records
        if record.event == "state" and record.entity == entity
    ]


def _messages(case: EvaluatedCase, entity: str) -> list[tuple]:
    return [
        _message_key(record)
        for record in case.trace_records
        if record.event == "message" and record.entity == entity
    ]


class ReceptionWorkflowRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        oracle = build_expected_workflow(case)
        expected_states = [item for item in oracle.states if item[1] == "reception"]
        expected_messages = [item for item in oracle.messages if item[1] == "reception"]
        state_score = _multiset_f1(_states(case, "reception"), expected_states)
        message_score = _multiset_f1(_messages(case, "reception"), expected_messages)
        return QualityScore(
            (state_score + message_score) / 2.0,
            (f"reception states={state_score:.6f}", f"handoffs={message_score:.6f}"),
        )


class InspectionWorkflowRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        oracle = build_expected_workflow(case)
        expected_states = [item for item in oracle.states if item[1] == "checkhair"]
        expected_messages = [item for item in oracle.messages if item[1] == "checkhair"]
        state_score = _multiset_f1(_states(case, "checkhair"), expected_states)
        message_score = _multiset_f1(_messages(case, "checkhair"), expected_messages)
        return QualityScore(
            (state_score + message_score) / 2.0,
            (f"inspection states={state_score:.6f}", f"inspection messages={message_score:.6f}"),
        )


class CuttingWorkflowRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        oracle = build_expected_workflow(case)
        expected_states = [item for item in oracle.states if item[1] == "cuthair"]
        expected_messages = [item for item in oracle.messages if item[1] == "cuthair"]
        state_score = _multiset_f1(_states(case, "cuthair"), expected_states)
        message_score = _multiset_f1(_messages(case, "cuthair"), expected_messages)
        return QualityScore(
            (state_score + message_score) / 2.0,
            (f"cutting counter={state_score:.6f}", f"cutting completions={message_score:.6f}"),
        )


class EndToEndCompletionRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        oracle = build_expected_workflow(case)
        expected = [
            item
            for item in oracle.messages
            if item[1:] == ("checkhair", "to_reception", "done")
        ]
        predicted = [
            _message_key(record)
            for record in case.trace_records
            if record.event == "message"
            and record.entity == "checkhair"
            and record.payload["port"] == "to_reception"
            and record.payload["content"] == "done"
        ]
        return QualityScore(
            _multiset_f1(predicted, expected),
            (f"completed {len(predicted)}/{oracle.accepted_customers} accepted customers",),
        )


RULE_TYPES = {
    "barber.reception_workflow": ReceptionWorkflowRule,
    "barber.inspection_workflow": InspectionWorkflowRule,
    "barber.cutting_workflow": CuttingWorkflowRule,
    "barber.end_to_end_completion": EndToEndCompletionRule,
}


def build_rule_registry(requirements: Iterable[RequirementSpec]) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"barbershop has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
