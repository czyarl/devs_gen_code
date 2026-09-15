"""Requirement-level rules for the O-Train light-rail scenario."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, f1_score, ratio_score


STATIONS = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}
ROUTE = ((0, 1), (0, 2), (0, 3), (0, 4), (1, 5), (1, 4), (1, 3), (1, 2))


def _events(case: EvaluatedCase, event: str, entity: str | None = None) -> list[TraceRecord]:
    return [
        record
        for record in case.trace_records
        if record.event == event and (entity is None or record.entity == entity)
    ]


def _ratio(successes: int, opportunities: int, *, vacuous: float = 0.0) -> QualityScore:
    if opportunities == 0:
        return QualityScore(vacuous)
    return QualityScore(ratio_score(successes, opportunities))


def _station_id(record: TraceRecord) -> int | None:
    value = record.payload.get("station_id")
    if record.payload.get("station_name") != STATIONS.get(value):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    value = record.payload.get("station")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _passenger_identity(record: TraceRecord) -> tuple[object, ...]:
    payload = record.payload
    return (
        payload.get("passenger_id"),
        payload.get("passenger_num"),
        payload.get("origin"),
        payload.get("destination"),
    )


class TrainMovementRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        arrivals = _events(case, "train_arrival", "train")
        correct = sum(
            (record.payload.get("direction"), record.payload.get("station"))
            == ROUTE[index % len(ROUTE)]
            and record.payload.get("station_id") == record.payload.get("station")
            and record.payload.get("station_name") == STATIONS.get(record.payload.get("station_id"))
            for index, record in enumerate(arrivals)
        )
        return _ratio(correct, len(arrivals))


class TrainTimingRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        arrivals = _events(case, "train_arrival", "train")
        if not arrivals:
            return QualityScore(0.0, ("no train arrivals",))
        tolerance = float(self.spec.parameters.get("absolute_time_tolerance_sec", 0.001))
        interval = float(self.spec.parameters.get("travel_interval_sec", 225.0))
        obligations = 1 + max(0, len(arrivals) - 1)
        correct = int(abs(arrivals[0].time) <= tolerance)
        correct += sum(
            abs((right.time - left.time) - interval) <= tolerance
            for left, right in zip(arrivals, arrivals[1:])
        )
        return _ratio(correct, obligations)


class PassengerGenerationRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        generated = _events(case, "passenger_generated", "passenger_generator")
        tolerance = float(self.spec.parameters.get("absolute_time_tolerance_sec", 0.001))
        initial_valid: set[int] = set()
        initial_total = 0
        ordinary_successes = 0
        ordinary_total = 0
        ordinary_ids: list[int] = []
        for record in generated:
            payload = record.payload
            origin = payload.get("origin")
            destination = payload.get("destination")
            station = _station_id(record)
            passenger_id = payload.get("passenger_id")
            passenger_num = payload.get("passenger_num")
            if passenger_id == 0:
                initial_total += 1
                if (
                    passenger_num == 0
                    and origin in STATIONS
                    and station == origin
                    and destination in STATIONS
                    and destination != origin
                    and abs(record.time - 0.5) <= tolerance
                ):
                    initial_valid.add(origin)
                continue
            ordinary_total += 1
            if isinstance(passenger_id, int) and not isinstance(passenger_id, bool):
                ordinary_ids.append(passenger_id)
            valid = (
                isinstance(passenger_num, int)
                and not isinstance(passenger_num, bool)
                and passenger_num >= 1
                and origin in STATIONS
                and destination in STATIONS
                and destination != origin
                and station == origin
                and passenger_id == passenger_num * 100 + origin * 10 + destination
            )
            ordinary_successes += int(valid)
        initial_score = f1_score(len(initial_valid), initial_total, len(STATIONS))
        components = [initial_score]
        if ordinary_total:
            components.append(ordinary_successes / ordinary_total)
            components.append(len(set(ordinary_ids)) / ordinary_total)
        return QualityScore(
            sum(components) / len(components),
            (
                f"valid initialization stations={len(initial_valid)}/5",
                f"valid ordinary passengers={ordinary_successes}/{ordinary_total}",
                f"unique ordinary passenger IDs={len(set(ordinary_ids))}/{ordinary_total}",
            ),
        )


def _normal_cdf(value: float, mean: float, standard_deviation: float) -> float:
    return 0.5 * (1.0 + math.erf((value - mean) / (standard_deviation * math.sqrt(2.0))))


class PassengerIntervalDistributionRule(BehavioralRule):
    """Compare pooled intervals with the specified rounded, clamped normal CDF."""

    def _evaluate_collection(self, cases: Sequence[EvaluatedCase]) -> QualityScore:
        intervals: list[float] = []
        for case in cases:
            by_station: dict[int, list[float]] = defaultdict(list)
            for record in _events(case, "passenger_generated", "passenger_generator"):
                if record.payload.get("passenger_id") != 0:
                    origin = record.payload.get("origin")
                    if origin in STATIONS:
                        by_station[origin].append(record.time)
            for times in by_station.values():
                times.sort()
                intervals.extend(right - left for left, right in zip(times, times[1:]))
        minimum = int(self.spec.parameters.get("minimum_intervals", 100))
        if not intervals:
            return QualityScore(0.0, ("no ordinary passenger intervals",))
        in_range = [value for value in intervals if 59.999 <= value <= 540.001]
        range_score = len(in_range) / len(intervals)
        ordered = sorted(min(540.0, max(60.0, value)) for value in intervals)
        ks_distance = 0.0
        cumulative = 0
        for value, count in sorted(Counter(ordered).items()):
            empirical_before = cumulative / len(ordered)
            cumulative += count
            empirical_after = cumulative / len(ordered)
            if value <= 60.0:
                expected_before = 0.0
                expected_after = _normal_cdf((60.0 + 0.5) / 60.0, 5.0, 5.0)
            elif value >= 540.0:
                expected_before = _normal_cdf((540.0 - 0.5) / 60.0, 5.0, 5.0)
                expected_after = 1.0
            else:
                expected_before = _normal_cdf((value - 0.5) / 60.0, 5.0, 5.0)
                expected_after = _normal_cdf((value + 0.5) / 60.0, 5.0, 5.0)
            ks_distance = max(
                ks_distance,
                abs(empirical_before - expected_before),
                abs(empirical_after - expected_after),
            )
        sample_coverage = min(1.0, len(intervals) / minimum)
        return QualityScore(
            range_score * (1.0 - min(1.0, ks_distance)) * sample_coverage,
            (
                f"intervals={len(intervals)}, range_fraction={range_score:.6f}",
                f"descriptive_KS_distance={ks_distance:.6f}",
                f"sample_coverage={sample_coverage:.6f}",
            ),
        )


class DestinationUniformityRule(BehavioralRule):
    """Score conditional destination balance by total-variation distance, not p-value."""

    def _evaluate_collection(self, cases: Sequence[EvaluatedCase]) -> QualityScore:
        counts: dict[int, dict[int, int]] = {
            origin: {destination: 0 for destination in STATIONS if destination != origin}
            for origin in STATIONS
        }
        for case in cases:
            for record in _events(case, "passenger_generated", "passenger_generator"):
                if record.payload.get("passenger_id") == 0:
                    continue
                origin = record.payload.get("origin")
                destination = record.payload.get("destination")
                if origin in counts and destination in counts[origin]:
                    counts[origin][destination] += 1
        station_scores: list[float] = []
        diagnostics: list[str] = []
        for origin, destinations in counts.items():
            total = sum(destinations.values())
            if total == 0:
                continue
            tv = 0.5 * sum(abs(count / total - 0.25) for count in destinations.values())
            station_scores.append(1.0 - tv)
            diagnostics.append(f"origin {origin}: n={total}, TV={tv:.6f}")
        if not station_scores:
            return QualityScore(0.0, ("no ordinary passenger destinations",))
        return QualityScore(sum(station_scores) / len(station_scores), tuple(diagnostics))


class StationFifoRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        generated: dict[tuple[object, ...], TraceRecord] = {}
        for record in _events(case, "passenger_generated", "passenger_generator"):
            generated[_passenger_identity(record)] = record
        boardings = _events(case, "passenger_boarding", "station_queue")
        successes = 0
        opportunities = 0
        by_station: dict[int, list[tuple[TraceRecord, TraceRecord]]] = defaultdict(list)
        for boarding in boardings:
            opportunities += 1
            source = generated.get(_passenger_identity(boarding))
            station = _station_id(boarding)
            valid = (
                source is not None
                and source.time <= boarding.time
                and source.payload.get("origin") == station
            )
            successes += int(valid)
            if valid:
                by_station[station].append((source, boarding))
        for pairs in by_station.values():
            pairs.sort(key=lambda pair: pair[0].time)
            for left, right in zip(pairs, pairs[1:]):
                opportunities += 1
                successes += int(left[1].time < right[1].time)
        return _ratio(successes, opportunities, vacuous=1.0)


class SerialPassengerTimingRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        delay = float(self.spec.parameters.get("serial_delay_sec", 0.025))
        tolerance = float(self.spec.parameters.get("absolute_time_tolerance_sec", 0.001))
        arrivals: dict[int, list[TraceRecord]] = defaultdict(list)
        for record in _events(case, "train_arrival", "train"):
            station = _station_id(record)
            if station in STATIONS:
                arrivals[station].append(record)
        successes = 0
        opportunities = 0
        for event_name, entity in (
            ("passenger_boarding", "station_queue"),
            ("passenger_exiting", "train_queue"),
        ):
            groups: dict[tuple[int, float], list[TraceRecord]] = defaultdict(list)
            for record in _events(case, event_name, entity):
                station = _station_id(record)
                prior = [arrival for arrival in arrivals.get(station, ()) if arrival.time < record.time]
                opportunities += 1
                if not prior:
                    continue
                groups[(station, prior[-1].time)].append(record)
            for (_, arrival_time), records in groups.items():
                records.sort(key=lambda record: record.time)
                for index, record in enumerate(records, start=1):
                    successes += int(abs(record.time - (arrival_time + index * delay)) <= tolerance)
        return _ratio(successes, opportunities, vacuous=1.0)


class PassengerLifecycleRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        generated: dict[tuple[object, ...], list[TraceRecord]] = defaultdict(list)
        boarded: dict[tuple[object, ...], list[TraceRecord]] = defaultdict(list)
        for record in _events(case, "passenger_generated", "passenger_generator"):
            generated[_passenger_identity(record)].append(record)
        successes = 0
        opportunities = 0
        boarded_once: set[tuple[object, ...]] = set()
        for record in _events(case, "passenger_boarding", "station_queue"):
            identity = _passenger_identity(record)
            source = next((item for item in generated.get(identity, ()) if item.time <= record.time), None)
            opportunities += 1
            valid = (
                source is not None
                and identity not in boarded_once
                and _station_id(record) == record.payload.get("origin")
            )
            successes += int(valid)
            if valid:
                boarded[identity].append(record)
                boarded_once.add(identity)
        exited_once: set[tuple[object, ...]] = set()
        for record in _events(case, "passenger_exiting", "train_queue"):
            identity = _passenger_identity(record)
            source = next((item for item in boarded.get(identity, ()) if item.time < record.time), None)
            opportunities += 1
            successes += int(
                source is not None
                and identity not in exited_once
                and _station_id(record) == record.payload.get("destination")
            )
            if source is not None:
                exited_once.add(identity)
        return _ratio(successes, opportunities, vacuous=1.0)


class ObservableActivityRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        config = case.config.get("checker_config", {})
        if not isinstance(config, dict):
            raise BenchmarkConfigurationError("OTrain checker_config must be a mapping")
        minima = (
            (len(_events(case, "passenger_generated")), int(config.get("min_passengers", 0))),
            (len(_events(case, "train_arrival")), int(config.get("min_train_arrivals", 0))),
        )
        applicable = [(actual, expected) for actual, expected in minima if expected > 0]
        if not applicable:
            return QualityScore(1.0)
        scores = [min(1.0, actual / expected) for actual, expected in applicable]
        return QualityScore(sum(scores) / len(scores))


RULE_TYPES = {
    "otrain.train_movement": TrainMovementRule,
    "otrain.train_timing": TrainTimingRule,
    "otrain.passenger_generation": PassengerGenerationRule,
    "otrain.passenger_interval_distribution": PassengerIntervalDistributionRule,
    "otrain.destination_uniformity": DestinationUniformityRule,
    "otrain.station_fifo": StationFifoRule,
    "otrain.serial_passenger_timing": SerialPassengerTimingRule,
    "otrain.passenger_lifecycle": PassengerLifecycleRule,
    "otrain.observable_activity": ObservableActivityRule,
}


def build_rule_registry(requirements: Iterable[RequirementSpec]) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"OTrain has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
