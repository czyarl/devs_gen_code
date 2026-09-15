"""Requirement-first rules for the Strategic Airlift (SA) benchmark."""

from __future__ import annotations

import math
import heapq
from collections.abc import Iterable
from statistics import fmean

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, f1_score, ratio_score


def _sim_args(case: EvaluatedCase) -> dict:
    value = case.config.get("sim_args")
    if not isinstance(value, dict):
        raise BenchmarkConfigurationError(f"case {case.case_id} has no sim_args mapping")
    return value


def _arg(case: EvaluatedCase, name: str, default: float) -> float:
    return float(_sim_args(case).get(name, default))


def _events(
    case: EvaluatedCase, event: str, entity: str | None = None
) -> list[TraceRecord]:
    return [
        record
        for record in case.trace_records
        if record.event == event and (entity is None or record.entity == entity)
    ]


def _same_time(a: float, b: float, tolerance: float) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def _expected_generation_times(case: EvaluatedCase) -> list[float]:
    duration = _arg(case, "duration", 10000.0)
    interval = _arg(case, "pallet_interval", 25.0)
    if interval <= 0 or duration < 0:
        raise BenchmarkConfigurationError(
            "SA duration must be nonnegative and pallet_interval positive"
        )
    result: list[float] = []
    index = 0
    # The run interval is [0,duration): the specification says the simulation
    # stops when duration is reached, but does not define event priority at the
    # right endpoint. This convention is explicit in the requirement map.
    while index * interval < duration - 1e-12:
        result.append(index * interval)
        index += 1
    return result


def _match_times(
    actual: list[TraceRecord], expected: list[float], tolerance: float
) -> tuple[int, dict[int, TraceRecord]]:
    used: set[int] = set()
    mapping: dict[int, TraceRecord] = {}
    for expected_index, wanted in enumerate(expected):
        candidate = next(
            (
                index
                for index, record in enumerate(actual)
                if index not in used and _same_time(record.time, wanted, tolerance)
            ),
            None,
        )
        if candidate is not None:
            used.add(candidate)
            mapping[expected_index] = actual[candidate]
    return len(mapping), mapping


def _expected_assignment_times(case: EvaluatedCase) -> dict[int, float]:
    """Reference FIFO/resource schedule, indexed by generation position."""
    generation_times = _expected_generation_times(case)
    aircraft_count = int(_sim_args(case).get("num_aircraft", 2))
    if aircraft_count < 1:
        raise BenchmarkConfigurationError("SA num_aircraft must be positive")
    expiration = _arg(case, "pallet_expiration_time", 150.0)
    cycle = (
        _arg(case, "flight_time", 30.0)
        + _arg(case, "unload_time", 2.0)
        + _arg(case, "return_time", 30.0)
        + _arg(case, "maintenance_time", 10.0)
    )
    duration = _arg(case, "duration", 10000.0)
    available = [0.0 for _ in range(aircraft_count)]
    heapq.heapify(available)
    queue: list[int] = []
    next_generation = 0
    expected: dict[int, float] = {}
    while next_generation < len(generation_times) or queue:
        if not queue:
            current = generation_times[next_generation]
        else:
            next_time = (
                generation_times[next_generation]
                if next_generation < len(generation_times)
                else math.inf
            )
            current = min(next_time, available[0])
        if current >= duration - 1e-12:
            break
        while (
            next_generation < len(generation_times)
            and generation_times[next_generation] <= current + 1e-12
        ):
            queue.append(next_generation)
            next_generation += 1
        queue = [
            index
            for index in queue
            if generation_times[index] + expiration > current + 1e-12
        ]
        while queue and available and available[0] <= current + 1e-12:
            heapq.heappop(available)
            pallet_index = queue.pop(0)
            expected[pallet_index] = current
            heapq.heappush(available, current + cycle)
    return expected


def _find(
    records: list[TraceRecord],
    *,
    time: float | None = None,
    tolerance: float = 0.0,
    **payload: object,
) -> TraceRecord | None:
    for record in records:
        if time is not None and not _same_time(record.time, time, tolerance):
            continue
        if all(record.payload.get(key) == value for key, value in payload.items()):
            return record
    return None


class PalletGenerationRule(BehavioralRule):
    """Score the t=0 periodic generation schedule and unique pallet IDs."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = _expected_generation_times(case)
        actual = _events(case, "pallet_generated", "facility")
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        matched, _ = _match_times(actual, expected, tolerance)
        schedule_score = f1_score(matched, len(actual), len(expected))
        identifiers = [record.payload["pallet_id"] for record in actual]
        unique_score = (
            len(set(identifiers)) / len(identifiers) if identifiers else (1.0 if not expected else 0.0)
        )
        return QualityScore(
            fmean((schedule_score, unique_score)),
            (
                f"matched {matched}/{len(expected)} scheduled generation times",
                f"unique pallet IDs={len(set(identifiers))}/{len(identifiers)}",
            ),
        )


class QueueLifecycleRule(BehavioralRule):
    """Score immediate queueing, deadline calculation, FIFO queue size, and expiry."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        duration = _arg(case, "duration", 10000.0)
        expiration = _arg(case, "pallet_expiration_time", 150.0)
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        expected_times = _expected_generation_times(case)
        generated = _events(case, "pallet_generated", "facility")
        queued = _events(case, "pallet_queued", "queue")
        assignments = _events(case, "assignment_created", "coordinator")
        expired = _events(case, "pallet_expired", "queue")
        _, generation_map = _match_times(generated, expected_times, tolerance)
        checks: list[bool] = []
        diagnostics: list[str] = []
        for index, generation_time in enumerate(expected_times):
            record = generation_map.get(index)
            exists = record is not None
            checks.append(exists)
            if record is None:
                diagnostics.append(f"missing generated pallet at t={generation_time:g}")
                # The remaining three obligations cannot be satisfied without
                # the generated identity; retain them in the denominator.
                checks.extend((False, False, False))
                continue
            pallet_id = record.payload["pallet_id"]
            deadline = generation_time + expiration
            deadline_ok = _same_time(
                float(record.payload["expiration_time"]), deadline, tolerance
            )
            queued_record = _find(
                queued,
                time=generation_time,
                tolerance=tolerance,
                pallet_id=pallet_id,
            )
            checks.extend((deadline_ok, queued_record is not None))
            assigned = _find(assignments, pallet_id=pallet_id)
            expiry = _find(expired, pallet_id=pallet_id)
            if assigned is not None:
                terminal_ok = assigned.time < deadline and expiry is None
            elif deadline < duration - tolerance:
                terminal_ok = expiry is not None and _same_time(
                    expiry.time, deadline, tolerance
                )
            else:
                terminal_ok = expiry is None or _same_time(expiry.time, deadline, tolerance)
            checks.append(terminal_ok)
        # Replay logged queue_size. Same-time records are consumed in trace
        # order, which is the only observable ordering at equal timestamps.
        queue_ids: list[int] = []
        expired_count = 0
        for record in case.trace_records:
            if record.event == "pallet_queued":
                queue_ids.append(int(record.payload["pallet_id"]))
                checks.append(record.payload["queue_size"] == len(queue_ids))
            elif record.event in {"assignment_created", "pallet_expired"}:
                pallet_id = int(record.payload["pallet_id"])
                if pallet_id in queue_ids:
                    queue_ids.remove(pallet_id)
                if record.event == "pallet_expired":
                    expired_count += 1
                    checks.append(record.payload["total_expired"] == expired_count)
        return QualityScore(
            ratio_score(sum(checks), len(checks)) if checks else 1.0,
            tuple(diagnostics),
        )


class CoordinatorRule(BehavioralRule):
    """Score FIFO assignment, zero-time loading, and aircraft capacity."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        aircraft_count = int(_sim_args(case).get("num_aircraft", 2))
        flight = _arg(case, "flight_time", 30.0)
        unload = _arg(case, "unload_time", 2.0)
        returning = _arg(case, "return_time", 30.0)
        maintenance = _arg(case, "maintenance_time", 10.0)
        expected_times = _expected_generation_times(case)
        generated = _events(case, "pallet_generated", "facility")
        _, generation_map = _match_times(generated, expected_times, tolerance)
        expected_assignments = _expected_assignment_times(case)
        actual_assignments = _events(case, "assignment_created", "coordinator")
        used: set[int] = set()
        matched = 0
        checks: list[bool] = []
        departures = _events(case, "depart", "aircraft")
        for generation_index, expected_time in expected_assignments.items():
            generation = generation_map.get(generation_index)
            if generation is None:
                continue
            pallet_id = generation.payload["pallet_id"]
            candidate = next(
                (
                    index
                    for index, record in enumerate(actual_assignments)
                    if index not in used
                    and record.payload["pallet_id"] == pallet_id
                    and _same_time(record.time, expected_time, tolerance)
                ),
                None,
            )
            if candidate is not None:
                used.add(candidate)
                matched += 1
        assignment_score = f1_score(
            matched, len(actual_assignments), len(expected_assignments)
        )
        for record in actual_assignments:
            pallet_id = int(record.payload["pallet_id"])
            aircraft_id = int(record.payload["aircraft_id"])
            checks.append(1 <= aircraft_id <= aircraft_count)
            depart = _find(
                departures,
                time=record.time,
                tolerance=tolerance,
                pallet_id=pallet_id,
                aircraft_id=aircraft_id,
            )
            checks.append(depart is not None)
        cycle_length = flight + unload + returning + maintenance
        by_aircraft: dict[int, list[TraceRecord]] = {}
        for depart in departures:
            by_aircraft.setdefault(int(depart.payload["aircraft_id"]), []).append(depart)
        for records in by_aircraft.values():
            records.sort(key=lambda item: item.time)
            for previous, current in zip(records, records[1:]):
                checks.append(current.time + tolerance >= previous.time + cycle_length)
        validity_score = (
            ratio_score(sum(checks), len(checks))
            if checks
            else (1.0 if not expected_assignments else 0.0)
        )
        return QualityScore(
            fmean((assignment_score, validity_score)),
            (
                f"matched {matched}/{len(expected_assignments)} reference FIFO assignments",
                f"assignment validity={validity_score:.6f}",
            ),
        )


class AircraftCycleRule(BehavioralRule):
    """Score each observable transport, return, and maintenance timer."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        duration = _arg(case, "duration", 10000.0)
        flight = _arg(case, "flight_time", 30.0)
        unload = _arg(case, "unload_time", 2.0)
        returning = _arg(case, "return_time", 30.0)
        maintenance = _arg(case, "maintenance_time", 10.0)
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        deliveries = _events(case, "pallet_delivered", "destination")
        returns = _events(case, "return", "aircraft")
        starts = _events(case, "maintenance_start", "aircraft")
        ends = _events(case, "maintenance_end", "aircraft")
        checks: list[bool] = []
        expected_counts = {"delivery": 0, "return": 0, "start": 0, "end": 0}
        for depart in _events(case, "depart", "aircraft"):
            aircraft_id = depart.payload["aircraft_id"]
            pallet_id = depart.payload["pallet_id"]
            delivery_time = depart.time + flight + unload
            return_time = delivery_time + returning
            maintenance_end = return_time + maintenance
            if delivery_time < duration - tolerance:
                expected_counts["delivery"] += 1
                checks.append(
                    _find(
                        deliveries,
                        time=delivery_time,
                        tolerance=tolerance,
                        aircraft_id=aircraft_id,
                        pallet_id=pallet_id,
                    )
                    is not None
                )
            if return_time < duration - tolerance:
                expected_counts["return"] += 1
                expected_counts["start"] += 1
                checks.append(
                    _find(
                        returns,
                        time=return_time,
                        tolerance=tolerance,
                        aircraft_id=aircraft_id,
                    )
                    is not None
                )
                checks.append(
                    _find(
                        starts,
                        time=return_time,
                        tolerance=tolerance,
                        aircraft_id=aircraft_id,
                    )
                    is not None
                )
            if maintenance_end < duration - tolerance:
                expected_counts["end"] += 1
                checks.append(
                    _find(
                        ends,
                        time=maintenance_end,
                        tolerance=tolerance,
                        aircraft_id=aircraft_id,
                    )
                    is not None
                )
        checks.extend(
            (
                len(deliveries) == expected_counts["delivery"],
                len(returns) == expected_counts["return"],
                len(starts) == expected_counts["start"],
                len(ends) == expected_counts["end"],
            )
        )
        return QualityScore(
            ratio_score(sum(checks), len(checks)),
            (f"checked {len(checks)} in-horizon aircraft-cycle obligations",),
        )


class DeliveryLatencyRule(BehavioralRule):
    """Score delivery identity, unload completion time, and latency arithmetic."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        flight = _arg(case, "flight_time", 30.0)
        unload = _arg(case, "unload_time", 2.0)
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        generated = {
            record.payload["pallet_id"]: record
            for record in _events(case, "pallet_generated", "facility")
        }
        departures = _events(case, "depart", "aircraft")
        checks: list[bool] = []
        for delivery in _events(case, "pallet_delivered", "destination"):
            pallet_id = delivery.payload["pallet_id"]
            aircraft_id = delivery.payload["aircraft_id"]
            generation = generated.get(pallet_id)
            depart = _find(
                departures, pallet_id=pallet_id, aircraft_id=aircraft_id
            )
            checks.append(generation is not None and depart is not None)
            if generation is None or depart is None:
                checks.extend((False, False))
                continue
            checks.append(
                _same_time(delivery.time, depart.time + flight + unload, tolerance)
            )
            checks.append(
                _same_time(
                    float(delivery.payload["latency"]),
                    delivery.time - generation.time,
                    tolerance,
                )
            )
        if not checks:
            due_deliveries = [
                depart
                for depart in departures
                if depart.time + flight + unload
                < _arg(case, "duration", 10000.0) - tolerance
            ]
            return QualityScore(1.0 if not due_deliveries else 0.0)
        return QualityScore(ratio_score(sum(checks), len(checks)))


class InHorizonResolutionRule(BehavioralRule):
    """Account for every scheduled pallet whose outcome is due within the run."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        duration = _arg(case, "duration", 10000.0)
        expiration = _arg(case, "pallet_expiration_time", 150.0)
        flight = _arg(case, "flight_time", 30.0)
        unload = _arg(case, "unload_time", 2.0)
        tolerance = float(self.spec.parameters["absolute_time_tolerance_seconds"])
        expected_times = _expected_generation_times(case)
        generated = _events(case, "pallet_generated", "facility")
        assignments = _events(case, "assignment_created", "coordinator")
        deliveries = _events(case, "pallet_delivered", "destination")
        expiries = _events(case, "pallet_expired", "queue")
        _, generation_map = _match_times(generated, expected_times, tolerance)
        checks: list[bool] = []
        for index, generation_time in enumerate(expected_times):
            generation = generation_map.get(index)
            if generation is None:
                checks.append(False)
                continue
            pallet_id = generation.payload["pallet_id"]
            assignment = _find(assignments, pallet_id=pallet_id)
            if assignment is not None:
                if assignment.time >= generation_time + expiration:
                    checks.append(False)
                elif assignment.time + flight + unload < duration - tolerance:
                    checks.append(_find(deliveries, pallet_id=pallet_id) is not None)
                else:
                    checks.append(True)
            elif generation_time + expiration < duration - tolerance:
                expiry = _find(expiries, pallet_id=pallet_id)
                checks.append(
                    expiry is not None
                    and _same_time(
                        expiry.time, generation_time + expiration, tolerance
                    )
                )
            else:
                checks.append(True)
        return QualityScore(
            ratio_score(sum(checks), len(checks)) if checks else 1.0,
            (f"resolved {sum(checks)}/{len(checks)} scheduled pallet obligations",),
        )


RULE_TYPES = {
    "sa.pallet_generation": PalletGenerationRule,
    "sa.queue_lifecycle": QueueLifecycleRule,
    "sa.coordinator_fifo_capacity": CoordinatorRule,
    "sa.aircraft_cycle": AircraftCycleRule,
    "sa.delivery_latency": DeliveryLatencyRule,
    "sa.in_horizon_resolution": InHorizonResolutionRule,
}


def build_rule_registry(
    requirements: Iterable[RequirementSpec],
) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"SA has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
