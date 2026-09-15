"""Requirement-first rules for secure-area access control (SAA)."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, f1_score, ratio_score


INITIAL_STATE = "Disarmed"
VALID_COMPONENTS = {"input_reader", "alarmAdmin", "authentication", "display"}
STATE_FOR_VALUE = {0: "Disarmed", 1: "Armed"}
AUTH_STATE_FOR_VALUE = {0: "DisarmValid", 1: "ArmValid"}
ACTION_FOR_VALUE = {0: "disarm", 1: "arm"}
MESSAGE_RE = re.compile(r"^\{(\d+) ([01])\}$")

# Versioned copies of benchmark input_data. Keeping the parsed requests here
# prevents evaluation from reading a mutable legacy path at runtime.
REQUESTS: dict[str, tuple[tuple[float, int, int], ...]] = {
    "L0_Empty": (),
    "L1_01_Single_Arm": ((10.0, 0, 1),),
    "L1_02_Single_Disarm": ((10.0, 0, 0),),
    "L1_03_Arm_Then_Disarm": ((10.0, 0, 1), (60.0, 0, 0)),
    "L1_04_Disarm_Then_Arm": ((10.0, 0, 0), (60.0, 0, 1)),
    "L1_05_Duplicate_Arm": ((10.0, 0, 1), (60.0, 0, 1)),
    "L2_01_Rapid_Alternating": (
        (10.0, 0, 1),
        (30.0, 0, 0),
        (50.0, 0, 1),
    ),
    "L2_02_Long_Sequence": (
        (10.0, 0, 1),
        (40.0, 0, 0),
        (70.0, 0, 1),
        (100.0, 0, 0),
    ),
    # The second request arrives one second after authentication at t=22.
    "L2_03_Boundary_Timing": ((10.0, 0, 1), (23.0, 0, 0)),
    # The middle request is busy-time input; the final request is exactly at
    # the first request's authentication completion and must be accepted.
    "L2_04_Busy_And_Exact_Boundary": (
        (10.0, 0, 1),
        (11.0, 0, 0),
        (22.0, 0, 0),
    ),
}


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _same_time(a: object, b: float, tolerance: float) -> bool:
    return _is_number(a) and abs(float(a) - b) <= tolerance


def _message(port: int, value: int) -> str:
    return f"{{{port} {value}}}"


def _sim_args(case: EvaluatedCase) -> dict:
    value = case.config.get("sim_args")
    if not isinstance(value, dict):
        raise BenchmarkConfigurationError(f"case {case.case_id} has no sim_args mapping")
    return value


def _summary_record(case: EvaluatedCase) -> TraceRecord:
    records = [
        item
        for item in case.trace_records
        if item.entity == "system" and item.event == "summary"
    ]
    if len(records) != 1:
        raise BenchmarkConfigurationError(
            f"SAA requires one normalized summary record, got {len(records)}"
        )
    return records[0]


def _summary(case: EvaluatedCase) -> dict:
    return dict(_summary_record(case).payload)


def _events(data: dict) -> list[dict]:
    raw = data.get("events")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _operations(data: dict) -> list[dict]:
    raw = data.get("operations")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _build_expected(case: EvaluatedCase) -> dict:
    try:
        requests = REQUESTS[case.case_id]
    except KeyError as exc:
        raise BenchmarkConfigurationError(
            f"SAA has no versioned input oracle for {case.case_id}"
        ) from exc
    args = _sim_args(case)
    admin_delay = float(args.get("alarm_admin_delay", 10.0))
    auth_delay = float(args.get("authentication_delay", 2.0))
    display_delay = float(args.get("display_delay", 3.0))
    max_time = float(args.get("max_simulation_time", 1000.0))
    events: list[dict] = []
    operations: list[dict] = []
    state = INITIAL_STATE
    state_sequence = [state]
    working_until = -math.inf
    for input_time, port, value in requests:
        msg = _message(port, value)
        events.append(
            {"time": input_time, "component": "input_reader", "message": msg}
        )
        accepted = input_time >= working_until
        completion_time: float | None = None
        if accepted:
            alarm_time = input_time + admin_delay
            auth_time = alarm_time + auth_delay
            display_time = auth_time + display_delay
            completion_time = auth_time
            working_until = auth_time
            state = STATE_FOR_VALUE[value]
            events.extend(
                [
                    {"time": alarm_time, "component": "alarmAdmin", "message": msg},
                    {
                        "time": auth_time,
                        "component": "authentication",
                        "message": msg,
                        "state": AUTH_STATE_FOR_VALUE[value],
                    },
                    {
                        "time": display_time,
                        "component": "display",
                        "message": msg,
                        "state": state,
                    },
                ]
            )
            if state_sequence[-1] != state:
                state_sequence.append(state)
        operations.append(
            {
                "input_time": input_time,
                "action": ACTION_FOR_VALUE[value],
                "completed": accepted,
                "completion_time": completion_time,
            }
        )
    events.sort(key=lambda item: item["time"])
    natural_end = float(events[-1]["time"]) if events else 0.0
    return {
        "events": events,
        "operations": operations,
        "final_state": state,
        "state_sequence": state_sequence,
        "simulation_time": min(natural_end, max_time),
        "max_simulation_time": max_time,
    }


def _event_equal(actual: dict, expected: dict, tolerance: float) -> bool:
    if actual.get("component") != expected["component"]:
        return False
    if actual.get("message") != expected["message"]:
        return False
    if not _same_time(actual.get("time"), float(expected["time"]), tolerance):
        return False
    if "state" in expected:
        return actual.get("state") == expected["state"]
    return "state" not in actual


def _operation_equal(actual: dict, expected: dict, tolerance: float) -> bool:
    if not _same_time(actual.get("input_time"), expected["input_time"], tolerance):
        return False
    if actual.get("action") != expected["action"]:
        return False
    if actual.get("completed") is not expected["completed"]:
        return False
    expected_completion = expected["completion_time"]
    if expected_completion is None:
        return actual.get("completion_time") is None
    return _same_time(actual.get("completion_time"), expected_completion, tolerance)


def _matching_count(actual: list[dict], expected: list[dict], predicate) -> int:
    used: set[int] = set()
    matched = 0
    for wanted in expected:
        index = next(
            (
                index
                for index, candidate in enumerate(actual)
                if index not in used and predicate(candidate, wanted)
            ),
            None,
        )
        if index is not None:
            used.add(index)
            matched += 1
    return matched


class NestedRecordContractRule(BehavioralRule):
    """Score value domains and nested record shapes not covered by raw parsing."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        data = _summary(case)
        args = _sim_args(case)
        checks = [
            data.get("test_name") == args["test_name"],
            data.get("initial_state") == INITIAL_STATE,
            data.get("final_state") in {"Disarmed", "Armed"},
        ]
        diagnostics: list[str] = []
        raw_events = data.get("events", [])
        if isinstance(raw_events, list):
            prior_time: float | None = None
            for index, event in enumerate(raw_events):
                valid = isinstance(event, dict)
                if valid:
                    component = event.get("component")
                    message = event.get("message")
                    message_match = (
                        MESSAGE_RE.fullmatch(message)
                        if isinstance(message, str)
                        else None
                    )
                    valid = (
                        _is_number(event.get("time"))
                        and component in VALID_COMPONENTS
                        and message_match is not None
                        and message_match.group(1) == "0"
                    )
                    if component in {"authentication", "display"}:
                        valid = (
                            valid
                            and {"time", "component", "message", "state"}
                            <= set(event)
                            and isinstance(event.get("state"), str)
                        )
                    else:
                        valid = (
                            valid
                            and {"time", "component", "message"} <= set(event)
                        )
                    if _is_number(event.get("time")):
                        current_time = float(event["time"])
                        valid = valid and (
                            prior_time is None or current_time >= prior_time
                        )
                        prior_time = current_time
                checks.append(valid)
                if not valid:
                    diagnostics.append(f"event {index} violates the nested event contract")
        raw_operations = data.get("operations", [])
        if isinstance(raw_operations, list):
            for index, operation in enumerate(raw_operations):
                valid = isinstance(operation, dict)
                if valid:
                    completed = operation.get("completed")
                    completion = operation.get("completion_time")
                    valid = (
                        {"input_time", "action", "completed", "completion_time"}
                        <= set(operation)
                        and _is_number(operation.get("input_time"))
                        and operation.get("action") in {"arm", "disarm"}
                        and isinstance(completed, bool)
                        and (
                            _is_number(completion)
                            if completed
                            else completion is None
                        )
                    )
                checks.append(valid)
                if not valid:
                    diagnostics.append(
                        f"operation {index} violates the nested operation contract"
                    )
        return QualityScore(ratio_score(sum(checks), len(checks)), tuple(diagnostics))


class InputAccountabilityRule(BehavioralRule):
    """Require one correctly copied input_reader event per input line."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        data = _summary(case)
        expected = [
            item
            for item in _build_expected(case)["events"]
            if item["component"] == "input_reader"
        ]
        actual = [item for item in _events(data) if item.get("component") == "input_reader"]
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        matched = _matching_count(
            actual, expected, lambda a, b: _event_equal(a, b, tolerance)
        )
        return QualityScore(
            f1_score(matched, len(actual), len(expected)),
            (f"matched {matched}/{len(expected)} declared input requests",),
        )


class WorkingPolicyRule(BehavioralRule):
    """Score acceptance, ignoring, and completion-time records."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        data = _summary(case)
        expected = _build_expected(case)["operations"]
        actual = _operations(data)
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        matched = _matching_count(
            actual, expected, lambda a, b: _operation_equal(a, b, tolerance)
        )
        ordered = all(
            float(actual[index]["input_time"]) <= float(actual[index + 1]["input_time"])
            for index in range(len(actual) - 1)
            if _is_number(actual[index].get("input_time"))
            and _is_number(actual[index + 1].get("input_time"))
        )
        match_score = f1_score(matched, len(actual), len(expected))
        return QualityScore(
            (match_score + (1.0 if ordered else 0.0)) / 2.0,
            (
                f"matched {matched}/{len(expected)} operation records",
                f"operations_sorted={ordered}",
            ),
        )


class AuthenticationPipelineRule(BehavioralRule):
    """Score accepted-request component events, delays, messages, and states."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        data = _summary(case)
        expected = [
            item
            for item in _build_expected(case)["events"]
            if item["component"] != "input_reader"
        ]
        actual = [item for item in _events(data) if item.get("component") != "input_reader"]
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        matched = _matching_count(
            actual, expected, lambda a, b: _event_equal(a, b, tolerance)
        )
        return QualityScore(
            f1_score(matched, len(actual), len(expected)),
            (f"matched {matched}/{len(expected)} pipeline events",),
        )


class StateSemanticsRule(BehavioralRule):
    """Score initial/final state and the visible display sequence."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        data = _summary(case)
        expected = _build_expected(case)
        actual_display = [
            item.get("state")
            for item in _events(data)
            if item.get("component") == "display"
        ]
        expected_display = [
            item["state"]
            for item in expected["events"]
            if item["component"] == "display"
        ]
        checks = (
            data.get("initial_state") == INITIAL_STATE,
            data.get("final_state") == expected["final_state"],
            actual_display == expected_display,
        )
        return QualityScore(
            ratio_score(sum(checks), len(checks)),
            (
                f"expected final_state={expected['final_state']!r}",
                f"expected display states={expected_display!r}",
            ),
        )


class SimulationBoundRule(BehavioralRule):
    """Require the declared simulation end to match the final emitted event."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        data = _summary(case)
        expected = _build_expected(case)
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        actual_time = _summary_record(case).time
        events = _events(data)
        checks = [
            actual_time <= expected["max_simulation_time"] + tolerance,
            abs(actual_time - expected["simulation_time"]) <= tolerance,
        ]
        if events:
            event_times = [float(item["time"]) for item in events if _is_number(item.get("time"))]
            checks.append(bool(event_times) and max(event_times) <= actual_time + tolerance)
        else:
            checks.append(not expected["events"] and actual_time <= tolerance)
        return QualityScore(
            ratio_score(sum(checks), len(checks)),
            (
                f"reported simulation_time={actual_time:.6g}",
                f"expected simulation_time={expected['simulation_time']:.6g}",
            ),
        )


RULE_TYPES = {
    "saa.nested_record_contract": NestedRecordContractRule,
    "saa.input_accountability": InputAccountabilityRule,
    "saa.working_policy": WorkingPolicyRule,
    "saa.authentication_pipeline": AuthenticationPipelineRule,
    "saa.state_semantics": StateSemanticsRule,
    "saa.simulation_bound": SimulationBoundRule,
}


def build_rule_registry(
    requirements: Iterable[RequirementSpec],
) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"SAA has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
