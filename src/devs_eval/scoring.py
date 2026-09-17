"""Central implementation of operational gating, coverage, and score aggregation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import fmean

from devs_eval.errors import BenchmarkConfigurationError, EvaluatorError
from devs_eval.models import (
    EvaluatedCase,
    QualityScore,
    RequirementEvaluation,
    RuleCategory,
    RuleScope,
    ScenarioEvaluation,
    ScenarioManifest,
)
from devs_eval.rules import BehavioralRule, validate_score


def _validated_quality(result: QualityScore, requirement_id: str) -> QualityScore:
    if not isinstance(result, QualityScore):
        raise EvaluatorError(
            f"rule {requirement_id} returned {type(result).__name__}, expected QualityScore"
        )
    return QualityScore(
        validate_score(result.score, label=f"{requirement_id} quality score"),
        tuple(result.diagnostics),
    )


def _run_case_rule(rule: BehavioralRule, case: EvaluatedCase) -> QualityScore:
    try:
        return _validated_quality(rule.evaluate_case(case), rule.spec.requirement_id)
    except EvaluatorError:
        raise
    except Exception as exc:
        raise EvaluatorError(
            f"rule {rule.spec.requirement_id} failed on case {case.case_id}: {exc}"
        ) from exc


def _run_collection_rule(
    rule: BehavioralRule, cases: Sequence[EvaluatedCase]
) -> QualityScore:
    try:
        return _validated_quality(rule.evaluate_collection(cases), rule.spec.requirement_id)
    except EvaluatorError:
        raise
    except Exception as exc:
        raise EvaluatorError(
            f"collection rule {rule.spec.requirement_id} failed: {exc}"
        ) from exc


def evaluate_scenario(
    manifest: ScenarioManifest,
    cases: Sequence[EvaluatedCase],
    rules: Mapping[str, BehavioralRule],
) -> ScenarioEvaluation:
    """Evaluate one generated simulator against exactly one scenario manifest."""
    manifest_case_ids = tuple(case.case_id for case in manifest.test_cases)
    case_ids = tuple(case.case_id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkConfigurationError("evaluated cases contain duplicate case IDs")
    if set(case_ids) != set(manifest_case_ids):
        missing = sorted(set(manifest_case_ids) - set(case_ids))
        extra = sorted(set(case_ids) - set(manifest_case_ids))
        raise BenchmarkConfigurationError(
            f"evaluated cases do not match manifest; missing={missing}, extra={extra}"
        )
    requirement_ids = {item.requirement_id for item in manifest.requirements}
    if set(rules) != requirement_ids:
        missing = sorted(requirement_ids - set(rules))
        extra = sorted(set(rules) - requirement_ids)
        raise BenchmarkConfigurationError(
            f"rule registry does not match manifest; missing={missing}, extra={extra}"
        )
    manifest_specs = {item.requirement_id: item for item in manifest.requirements}
    for requirement_id, rule in rules.items():
        if rule.spec != manifest_specs[requirement_id]:
            raise BenchmarkConfigurationError(
                f"rule {requirement_id} was constructed from a different requirement spec"
            )

    case_by_id = {case.case_id: case for case in cases}
    manifest_case_by_id = {case.case_id: case for case in manifest.test_cases}
    for case_id, evaluated in case_by_id.items():
        declared = manifest_case_by_id[case_id]
        expected_config = {
            "sim_args": dict(declared.sim_args),
            "sim_stdin": declared.sim_stdin,
            "checker_config": dict(declared.checker_config),
        }
        if dict(evaluated.config) != expected_config:
            raise BenchmarkConfigurationError(
                f"evaluated config for {case_id} does not match the manifest"
            )
    ordered_cases = [case_by_id[case_id] for case_id in manifest_case_ids]
    operational_score = fmean(
        1.0 if case.operational.passed else 0.0 for case in ordered_cases
    )
    evaluations: list[RequirementEvaluation] = []
    category_values: dict[RuleCategory, list[float]] = {
        RuleCategory.MICRO: [],
        RuleCategory.MACRO: [],
    }

    for spec in manifest.requirements:
        rule = rules[spec.requirement_id]
        valid_cases = [case for case in ordered_cases if case.operational.passed]
        coverage = len(valid_cases) / len(ordered_cases)
        diagnostics: list[str] = []
        per_case: dict[str, float | None] = {
            case.case_id: None for case in ordered_cases
        }

        if len(valid_cases) < spec.min_valid_cases:
            quality = 0.0
            final_score = 0.0
            diagnostics.append(
                f"valid case count {len(valid_cases)} is below minimum {spec.min_valid_cases}"
            )
        elif spec.scope is RuleScope.CASE:
            quality_results = []
            for case in valid_cases:
                result = _run_case_rule(rule, case)
                per_case[case.case_id] = result.score
                quality_results.append(result.score)
                diagnostics.extend(f"{case.case_id}: {item}" for item in result.diagnostics)
            quality = fmean(quality_results)
            final_score = coverage * quality
        else:
            result = _run_collection_rule(rule, valid_cases)
            quality = result.score
            final_score = coverage * quality
            diagnostics.extend(result.diagnostics)

        final_score = validate_score(final_score, label=f"{spec.requirement_id} final score")
        category_values[spec.category].append(final_score)
        evaluations.append(
            RequirementEvaluation(
                requirement_id=spec.requirement_id,
                category=spec.category,
                scope=spec.scope,
                quality_score=quality,
                coverage=coverage,
                score=final_score,
                case_ids=manifest_case_ids,
                valid_case_ids=tuple(case.case_id for case in valid_cases),
                per_case_scores=per_case,
                diagnostics=tuple(diagnostics),
            )
        )

    populated_categories = {
        category: fmean(values)
        for category, values in category_values.items()
        if values
    }
    if not populated_categories:
        raise BenchmarkConfigurationError("scenario has no scoreable requirement categories")
    behavioral_score = fmean(populated_categories.values())
    diagnostics = tuple(
        f"{case.case_id}: {'; '.join(case.operational.diagnostics)}"
        for case in ordered_cases
        if not case.operational.passed
    )
    return ScenarioEvaluation(
        protocol_version=manifest.protocol_version,
        benchmark_version=manifest.benchmark_version,
        scenario_id=manifest.scenario_id,
        operational_score=operational_score,
        behavioral_score=behavioral_score,
        fully_operational=all(case.operational.passed for case in ordered_cases),
        category_scores={key.value: value for key, value in populated_categories.items()},
        requirement_evaluations=tuple(evaluations),
        case_operational={case.case_id: case.operational.passed for case in ordered_cases},
        diagnostics=diagnostics,
    )
