"""Requirement-level rules for the deterministic House Heating scenario."""

from __future__ import annotations

from collections.abc import Iterable

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, f1_score, linear_tolerance_score, ratio_score


INITIAL_ROOM_TEMP = 25.0
INITIAL_CONTROL_SIGNAL = 0
DEFAULT_OUTDOOR_TEMP = 25.0


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


def _parse_hms(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise BenchmarkConfigurationError(f"invalid HouseHeating timestamp {value!r}")
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError as exc:
        raise BenchmarkConfigurationError(
            f"invalid HouseHeating timestamp {value!r}"
        ) from exc
    if min(hours, minutes, seconds) < 0 or minutes >= 60 or seconds >= 60:
        raise BenchmarkConfigurationError(f"invalid HouseHeating timestamp {value!r}")
    return hours * 3600 + minutes * 60 + seconds


def _schedule(case: EvaluatedCase) -> list[tuple[int, float]]:
    raw = case.config.get("sim_stdin", "")
    if not isinstance(raw, str):
        raise BenchmarkConfigurationError(f"case {case.case_id} has non-text sim_stdin")
    schedule: list[tuple[int, float]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            stamp, temperature = line.split(maxsplit=1)
            schedule.append((_parse_hms(stamp), float(temperature)))
        except (ValueError, TypeError) as exc:
            raise BenchmarkConfigurationError(
                f"case {case.case_id} contains invalid outdoor schedule line {line!r}"
            ) from exc
    schedule.sort()
    return schedule


def _outdoor_at(schedule: list[tuple[int, float]], time_sec: int) -> float:
    current = DEFAULT_OUTDOOR_TEMP
    for stamp, temperature in schedule:
        if stamp > time_sec:
            break
        current = temperature
    return current


def expected_observations(case: EvaluatedCase) -> dict[int, dict[str, float | int]]:
    """Build the independent deterministic oracle stated in the specification."""
    simulate_time = int(float(_sim_args(case)["simulate_time"]))
    if simulate_time < 1:
        raise BenchmarkConfigurationError("HouseHeating simulate_time must be at least one")
    threshold = float(_checker_config(case).get("target_temp", 24.9))
    schedule = _schedule(case)
    expected: dict[int, dict[str, float | int]] = {}
    room_previous = INITIAL_ROOM_TEMP
    control_previous = INITIAL_CONTROL_SIGNAL
    for time_sec in range(1, simulate_time + 1):
        outdoor = min(_outdoor_at(schedule, time_sec - 1), room_previous)
        heat_loss = room_previous - (room_previous - outdoor) * 0.1
        heater_output = 0.5 if control_previous == 1 else 0.0
        room_temperature = heat_loss + heater_output
        control_signal = 1 if room_temperature < threshold else 0
        expected[time_sec] = {
            "room_temp_c": room_temperature,
            "heat_loss_temp_c": heat_loss,
            "control_signal": control_signal,
            "heater_output_c": heater_output,
        }
        room_previous = room_temperature
        control_previous = control_signal
    return expected


def _observed(case: EvaluatedCase) -> tuple[dict[int, TraceRecord], int]:
    values: dict[int, TraceRecord] = {}
    for record in case.trace_records:
        time_sec = int(round(record.time))
        if time_sec >= 1 and abs(record.time - time_sec) <= 1e-6:
            values.setdefault(time_sec, record)
    return values, len(case.trace_records)


class ObservationCoverageRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = expected_observations(case)
        observed, predicted_count = _observed(case)
        true_positives = len(set(expected) & set(observed))
        return QualityScore(
            f1_score(true_positives, predicted_count, len(expected)),
            (f"observed {true_positives}/{len(expected)} required integer seconds",),
        )


class _NumericDynamicsRule(BehavioralRule):
    field: str

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = expected_observations(case)
        observed, _ = _observed(case)
        full_credit = float(self.spec.parameters["full_credit_error_c"])
        zero_credit = float(self.spec.parameters["zero_credit_error_c"])
        scores: list[float] = []
        missing = 0
        for time_sec, wanted in expected.items():
            record = observed.get(time_sec)
            if record is None:
                scores.append(0.0)
                missing += 1
                continue
            error = abs(float(record.payload[self.field]) - float(wanted[self.field]))
            scores.append(
                linear_tolerance_score(
                    error,
                    full_credit_error=full_credit,
                    zero_credit_error=zero_credit,
                )
            )
        return QualityScore(
            sum(scores) / len(scores),
            (f"{self.field}: {missing} missing of {len(expected)} observations",),
        )


class HeatLossRule(_NumericDynamicsRule):
    field = "heat_loss_temp_c"


class HeaterDelayRule(_NumericDynamicsRule):
    field = "heater_output_c"


class RoomTemperatureRule(_NumericDynamicsRule):
    field = "room_temp_c"


class ControlRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = expected_observations(case)
        observed, _ = _observed(case)
        successes = sum(
            observed.get(time_sec) is not None
            and observed[time_sec].payload["control_signal"] == wanted["control_signal"]
            for time_sec, wanted in expected.items()
        )
        return QualityScore(ratio_score(successes, len(expected)))


RULE_TYPES = {
    "house.observation_coverage": ObservationCoverageRule,
    "house.heat_loss": HeatLossRule,
    "house.heater_delay": HeaterDelayRule,
    "house.room_temperature": RoomTemperatureRule,
    "house.control": ControlRule,
}


def build_rule_registry(
    requirements: Iterable[RequirementSpec],
) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"HouseHeating has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
