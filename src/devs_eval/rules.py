"""Behavioral-rule interface and shared score primitives."""

from __future__ import annotations

import math
from abc import ABC
from collections.abc import Sequence

from devs_eval.errors import BenchmarkConfigurationError, ScoreValidationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, RuleScope


class BehavioralRule(ABC):
    """One implementation per top-level natural-language requirement."""

    def __init__(self, spec: RequirementSpec) -> None:
        self.spec = spec

    def evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        if self.spec.scope is not RuleScope.CASE:
            raise BenchmarkConfigurationError(
                f"{self.spec.requirement_id} is not a case-scoped requirement"
            )
        return self._evaluate_case(case)

    def evaluate_collection(self, cases: Sequence[EvaluatedCase]) -> QualityScore:
        if self.spec.scope is not RuleScope.COLLECTION:
            raise BenchmarkConfigurationError(
                f"{self.spec.requirement_id} is not a collection-scoped requirement"
            )
        return self._evaluate_collection(cases)

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        raise NotImplementedError

    def _evaluate_collection(self, cases: Sequence[EvaluatedCase]) -> QualityScore:
        raise NotImplementedError


def validate_score(score: float, *, label: str = "score") -> float:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ScoreValidationError(f"{label} must be numeric, got {type(score).__name__}")
    value = float(score)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ScoreValidationError(f"{label} must be finite and within [0, 1], got {score!r}")
    return value


def ratio_score(successes: int | float, total: int | float) -> float:
    if isinstance(successes, bool) or isinstance(total, bool):
        raise BenchmarkConfigurationError("ratio inputs cannot be booleans")
    if not math.isfinite(float(successes)) or not math.isfinite(float(total)):
        raise BenchmarkConfigurationError("ratio inputs must be finite")
    if total <= 0:
        raise BenchmarkConfigurationError("ratio denominator must be positive")
    if successes < 0 or successes > total:
        raise BenchmarkConfigurationError("ratio numerator must lie within [0, total]")
    return float(successes) / float(total)


def f1_score(true_positives: int, predicted: int, expected: int) -> float:
    if min(true_positives, predicted, expected) < 0:
        raise BenchmarkConfigurationError("F1 counts cannot be negative")
    if true_positives > predicted or true_positives > expected:
        raise BenchmarkConfigurationError("true positives exceed predicted or expected count")
    if predicted == 0 and expected == 0:
        return 1.0
    if predicted + expected == 0:
        raise BenchmarkConfigurationError("unreachable zero F1 denominator")
    return (2.0 * true_positives) / float(predicted + expected)


def linear_tolerance_score(
    absolute_error: float,
    *,
    full_credit_error: float,
    zero_credit_error: float,
) -> float:
    """Give full credit up to one boundary, then decrease linearly to zero."""
    values = (absolute_error, full_credit_error, zero_credit_error)
    if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
        raise BenchmarkConfigurationError("tolerance parameters must be finite numbers")
    if absolute_error < 0 or full_credit_error < 0:
        raise BenchmarkConfigurationError("errors cannot be negative")
    if zero_credit_error <= full_credit_error:
        raise BenchmarkConfigurationError("zero-credit error must exceed full-credit error")
    if absolute_error <= full_credit_error:
        return 1.0
    if absolute_error >= zero_credit_error:
        return 0.0
    return 1.0 - (
        (float(absolute_error) - float(full_credit_error))
        / (float(zero_credit_error) - float(full_credit_error))
    )
