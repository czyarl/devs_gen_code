"""Requirement-level and native collection rules for the IOBS scenario."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, f1_score


def _events(case: EvaluatedCase, entity: str, event: str) -> list[TraceRecord]:
    return [
        record
        for record in case.trace_records
        if record.entity == entity and record.event == event
    ]


def _config(case: EvaluatedCase) -> dict:
    value = case.config.get("checker_config")
    if not isinstance(value, dict):
        raise BenchmarkConfigurationError(f"IOBS case {case.case_id} lacks checker_config")
    return value


def _requests(case: EvaluatedCase) -> list[tuple[float, int, int]]:
    value = _config(case).get("input_requests")
    if not isinstance(value, list):
        raise BenchmarkConfigurationError(f"IOBS case {case.case_id} lacks input_requests")
    return [
        (float(item["time"]), int(item["valid"]), int(item["invalid"]))
        for item in value
    ]


def _f1_matches(predicted: int, expected: int, matches: int) -> float:
    return f1_score(matches, predicted, expected)


def _time_close(left: float, right: float, tolerance: float = 0.001) -> bool:
    return abs(left - right) <= tolerance


class InputAndAamRoutingRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        requests = _requests(case)
        starts = _events(case, "input_reader1", "start")
        inputs = _events(case, "input_reader1", "input")
        generated = _events(case, "AAM1", "account_generated")
        logouts = _events(case, "AAM1", "logout")
        input_matches = sum(
            _time_close(record.time, expected[0])
            and record.payload.get("valid") == expected[1]
            and record.payload.get("invalid") == expected[2]
            for record, expected in zip(inputs, requests)
        )
        # AAM is a single sequential server. Requests arriving while it is busy
        # complete in FIFO order at successive 10-second boundaries.
        aam_available = 0.0
        routed: list[tuple[float, str]] = []
        for request_time, valid, invalid in requests:
            aam_available = max(request_time, aam_available) + 10.0
            if valid == 1 and invalid == 0:
                routed.append((aam_available, "valid"))
            elif valid == 1 and invalid == 1:
                routed.append((aam_available, "invalid"))
        valid_requests = [time for time, route in routed if route == "valid"]
        invalid_requests = [time for time, route in routed if route == "invalid"]
        valid_matches = sum(
            _time_close(record.time, completion_time)
            for record, completion_time in zip(generated, valid_requests)
        )
        invalid_matches = sum(
            _time_close(record.time, completion_time)
            for record, completion_time in zip(logouts, invalid_requests)
        )
        components = [
            _f1_matches(len(starts), 1, int(len(starts) == 1 and _time_close(starts[0].time, 0.0))),
            _f1_matches(len(inputs), len(requests), input_matches),
            _f1_matches(len(generated), len(valid_requests), valid_matches),
            _f1_matches(len(logouts), len(invalid_requests), invalid_matches),
        ]
        return QualityScore(sum(components) / len(components))


class AnvVerificationRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        generated = _events(case, "AAM1", "account_generated")
        verifications = _events(case, "ANV1", "verification")
        matches = 0
        for source, result in zip(generated, verifications):
            passed = result.payload.get("pass")
            failed = result.payload.get("fail")
            matches += int(
                _time_close(result.time, source.time + 10.0)
                and type(passed) is int
                and type(failed) is int
                and passed in {0, 1}
                and failed in {0, 1}
                and passed + failed == 1
            )
        return QualityScore(_f1_matches(len(verifications), len(generated), matches))


class PasswordRetryRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        passes = [
            record
            for record in _events(case, "ANV1", "verification")
            if record.payload.get("pass") == 1 and record.payload.get("fail") == 0
        ]
        results = _events(case, "PV1", "verification")
        matches = 0
        for source, result in zip(passes, results):
            matches += int(
                _time_close(result.time, source.time + 10.0)
                and result.payload.get("success") == 1
                and type(result.payload.get("attempts")) is int
                and result.payload.get("attempts") >= 1
            )
        return QualityScore(_f1_matches(len(results), len(passes), matches))


class BillGenerationRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        password_results = _events(case, "PV1", "verification")
        bills = _events(case, "BPM1", "bill")
        matches = 0
        for source, bill in zip(password_results, bills):
            amount = bill.payload.get("amount")
            matches += int(
                _time_close(bill.time, source.time + 10.0)
                and type(amount) is int
                and 0 <= amount <= 40
            )
        return QualityScore(_f1_matches(len(bills), len(password_results), matches))


class TransactionStateRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        bills = _events(case, "BPM1", "bill")
        transactions = _events(case, "TPM1", "transaction")
        balance = 3000
        count = 0
        matches = 0
        for bill, transaction in zip(bills, transactions):
            amount = bill.payload.get("amount")
            remaining = transaction.payload.get("remaining")
            declared_count = transaction.payload.get("count")
            valid = (
                type(amount) is int
                and type(remaining) is int
                and type(declared_count) is int
                and amount <= balance
                and remaining == balance - amount
                and remaining >= 0
                and declared_count == count + 1
                and _time_close(transaction.time, bill.time + 10.0)
            )
            matches += int(valid)
            if valid:
                balance = remaining
                count = declared_count
        return QualityScore(_f1_matches(len(transactions), len(bills), matches))


def _conservation_score(left: int, right: int) -> float:
    if left == right == 0:
        return 1.0
    return 1.0 - abs(left - right) / max(left, right)


class FlowConservationRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        config = _config(case)
        inputs = len(_events(case, "input_reader1", "input"))
        generated = len(_events(case, "AAM1", "account_generated"))
        logouts = len(_events(case, "AAM1", "logout"))
        anv = _events(case, "ANV1", "verification")
        anv_pass = sum(record.payload.get("pass") == 1 for record in anv)
        pv = len(_events(case, "PV1", "verification"))
        bills = len(_events(case, "BPM1", "bill"))
        transactions = len(_events(case, "TPM1", "transaction"))
        expected_total = int(config["total_events"])
        expected_valid = int(config["valid_requests"])
        expected_invalid = int(config["invalid_requests"])
        parts = [
            _conservation_score(inputs, expected_total),
            _conservation_score(generated, expected_valid),
            _conservation_score(logouts, expected_invalid),
            _conservation_score(generated, len(anv)),
            _conservation_score(anv_pass, pv),
            _conservation_score(pv, bills),
            _conservation_score(bills, transactions),
        ]
        return QualityScore(sum(parts) / len(parts))


def _grouped_cases(cases: Sequence[EvaluatedCase]) -> dict[str, list[EvaluatedCase]]:
    grouped: dict[str, list[EvaluatedCase]] = defaultdict(list)
    for case in cases:
        group = _config(case).get("case_group")
        if not isinstance(group, str) or not group:
            raise BenchmarkConfigurationError(f"IOBS case {case.case_id} lacks case_group")
        grouped[group].append(case)
    return grouped


def _tolerance_score(rate: float, tolerance: float) -> float:
    if tolerance <= 0:
        raise BenchmarkConfigurationError("IOBS probability_tolerance must be positive")
    return max(0.0, 1.0 - abs(rate - 0.5) / tolerance)


class AnvProbabilityRule(BehavioralRule):
    """Descriptive pass-rate distance; deliberately does not use a p-value."""

    def _evaluate_collection(self, cases: Sequence[EvaluatedCase]) -> QualityScore:
        scores: list[float] = []
        diagnostics: list[str] = []
        for group, members in _grouped_cases(cases).items():
            verifications = [
                record for case in members for record in _events(case, "ANV1", "verification")
            ]
            valid = [
                record
                for record in verifications
                if record.payload.get("pass") in {0, 1}
                and record.payload.get("fail") in {0, 1}
                and record.payload.get("pass") + record.payload.get("fail") == 1
            ]
            if not valid:
                scores.append(0.0)
                diagnostics.append(f"{group}: no valid ANV trials")
                continue
            rate = sum(record.payload["pass"] for record in valid) / len(valid)
            tolerance = float(_config(members[0])["probability_tolerance"])
            scores.append(_tolerance_score(rate, tolerance))
            diagnostics.append(f"{group}: pass_rate={rate:.6f}, n={len(valid)}, tolerance={tolerance}")
        return QualityScore(sum(scores) / len(scores) if scores else 0.0, tuple(diagnostics))


class PasswordProbabilityRule(BehavioralRule):
    """Descriptive success/attempt ratio; deliberately does not use a p-value."""

    def _evaluate_collection(self, cases: Sequence[EvaluatedCase]) -> QualityScore:
        scores: list[float] = []
        diagnostics: list[str] = []
        for group, members in _grouped_cases(cases).items():
            anv_passes = sum(
                record.payload.get("pass") == 1 and record.payload.get("fail") == 0
                for case in members
                for record in _events(case, "ANV1", "verification")
            )
            if anv_passes == 0:
                diagnostics.append(f"{group}: no observed ANV passes; PV probability not applicable")
                continue
            results = [
                record for case in members for record in _events(case, "PV1", "verification")
            ]
            valid = [
                record
                for record in results
                if record.payload.get("success") == 1
                and type(record.payload.get("attempts")) is int
                and record.payload.get("attempts") >= 1
            ]
            attempts = sum(record.payload["attempts"] for record in valid)
            if attempts == 0:
                scores.append(0.0)
                diagnostics.append(f"{group}: no valid PV attempts")
                continue
            rate = len(valid) / attempts
            tolerance = float(_config(members[0])["probability_tolerance"])
            scores.append(_tolerance_score(rate, tolerance))
            diagnostics.append(
                f"{group}: success_per_attempt={rate:.6f}, attempts={attempts}, tolerance={tolerance}"
            )
        return QualityScore(sum(scores) / len(scores) if scores else 0.0, tuple(diagnostics))


RULE_TYPES = {
    "iobs.input_aam_routing": InputAndAamRoutingRule,
    "iobs.anv_verification": AnvVerificationRule,
    "iobs.password_retry": PasswordRetryRule,
    "iobs.bill_generation": BillGenerationRule,
    "iobs.transaction_state": TransactionStateRule,
    "iobs.flow_conservation": FlowConservationRule,
    "iobs.anv_probability": AnvProbabilityRule,
    "iobs.password_probability": PasswordProbabilityRule,
}


def build_rule_registry(requirements: Iterable[RequirementSpec]) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"IOBS has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
