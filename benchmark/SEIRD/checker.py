"""Requirement-first rules for the SEIRD final-state benchmark."""

from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import fmean

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, ratio_score


COMPARTMENTS = ("susceptible", "exposed", "infective", "recovered", "deceased")


def expected_final_state(case: EvaluatedCase) -> dict[str, float]:
    """Replay the specified old-state recurrence using this case's arguments."""
    args = _sim_args(case)
    total = float(args["total_population"])
    infective = float(args["initial_infective"])
    susceptible = total - infective
    exposed = recovered = deceased = 0.0
    dt = float(args["dt"])
    simulation_time = float(args["simulation_time"])
    incubation = float(args["incubation_period"])
    infectivity = float(args["infectivity_period"])
    mortality = float(args["mortality"]) / 100.0
    beta = float(args["transmission_rate"])
    if dt <= 0 or simulation_time < 0 or incubation <= 0 or infectivity <= 0:
        raise BenchmarkConfigurationError("SEIRD time steps and periods must be positive")
    steps = max(0, math.ceil(simulation_time / dt - 1e-12) - 1)
    for _ in range(steps):
        new_exposed = (
            0.0
            if total <= 0
            else min(susceptible, beta * susceptible * infective / total * dt)
        )
        new_infective = min(exposed, exposed / incubation * dt)
        new_deceased = infective / infectivity * mortality * dt
        new_recovered = infective / infectivity * (1.0 - mortality) * dt
        susceptible, exposed, infective, recovered, deceased = (
            susceptible - new_exposed,
            exposed + new_exposed - new_infective,
            infective + new_infective - new_deceased - new_recovered,
            recovered + new_recovered,
            deceased + new_deceased,
        )
    return dict(zip(COMPARTMENTS, (susceptible, exposed, infective, recovered, deceased)))


def _sim_args(case: EvaluatedCase) -> dict:
    value = case.config.get("sim_args")
    if not isinstance(value, dict):
        raise BenchmarkConfigurationError(f"case {case.case_id} has no sim_args mapping")
    return value


def _final_state(case: EvaluatedCase) -> TraceRecord:
    states = [
        record
        for record in case.trace_records
        if record.entity == "system" and record.event == "state"
    ]
    if not states:
        raise BenchmarkConfigurationError(
            "operationally valid SEIRD output contains no normalized state record"
        )
    return states[-1]


def _bounded_accuracy(actual: float, expected: float, scale: float) -> float:
    """Natural-scale absolute accuracy without an arbitrary pass threshold."""
    if scale <= 0:
        raise BenchmarkConfigurationError("accuracy scale must be positive")
    return 1.0 - min(abs(float(actual) - float(expected)) / scale, 1.0)


class FinalTimeRule(BehavioralRule):
    """Require the reported final state to correspond to simulation_time."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = float(_sim_args(case)["simulation_time"])
        actual = _final_state(case).time
        tolerance = float(self.spec.parameters["absolute_tolerance_days"])
        score = 1.0 if abs(actual - expected) <= tolerance else 0.0
        return QualityScore(score, (f"reported time={actual}, requested time={expected}",))


class FinalCompartmentStateRule(BehavioralRule):
    """Compare all five final compartments with the versioned case oracle."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        payload = _final_state(case).payload
        expected = expected_final_state(case)
        scores: list[float] = []
        diagnostics: list[str] = []
        for field in COMPARTMENTS:
            actual_value = float(payload[field])
            expected_value = float(expected[field])
            # Relative to the compartment itself, with one person as the
            # denominator floor for zero and near-zero states.
            scale = max(abs(expected_value), 1.0)
            score = _bounded_accuracy(actual_value, expected_value, scale)
            scores.append(score)
            diagnostics.append(
                f"{field}: actual={actual_value:.6g}, oracle={expected_value:.6g}, "
                f"normalized_accuracy={score:.6f}"
            )
        return QualityScore(fmean(scores), tuple(diagnostics))


class PopulationConservationRule(BehavioralRule):
    """Score conservation on the declared total-population scale."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        payload = _final_state(case).payload
        total = float(_sim_args(case)["total_population"])
        observed = sum(float(payload[field]) for field in COMPARTMENTS)
        score = _bounded_accuracy(observed, total, max(abs(total), 1.0))
        return QualityScore(
            score,
            (f"compartment sum={observed:.6g}, total_population={total:.6g}",),
        )


class CompartmentBoundsRule(BehavioralRule):
    """Require every compartment to remain within the closed population."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        payload = _final_state(case).payload
        total = float(_sim_args(case)["total_population"])
        valid = [0.0 <= float(payload[field]) <= total for field in COMPARTMENTS]
        return QualityScore(
            ratio_score(sum(valid), len(valid)),
            tuple(
                f"{field}={float(payload[field]):.6g} is outside [0,{total:.6g}]"
                for field, ok in zip(COMPARTMENTS, valid)
                if not ok
            ),
        )


class MortalityPartitionRule(BehavioralRule):
    """Score the recovered/deceased split against the configured mortality."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        payload = _final_state(case).payload
        recovered = float(payload["recovered"])
        deceased = float(payload["deceased"])
        resolved = recovered + deceased
        expected_state = expected_final_state(case)
        expected_resolved = expected_state["recovered"] + expected_state["deceased"]
        zero_tolerance = float(self.spec.parameters["zero_resolved_tolerance_people"])
        if expected_resolved <= zero_tolerance:
            within_tolerance = (
                abs(recovered) <= zero_tolerance and abs(deceased) <= zero_tolerance
            )
            return QualityScore(
                1.0 if within_tolerance else 0.0,
                (
                    "expected no resolved population; "
                    f"reported R={recovered:.6g}, D={deceased:.6g}",
                ),
            )
        if resolved <= 0:
            return QualityScore(
                0.0,
                ("expected resolved infective outflow but none was reported",),
            )
        actual = deceased / resolved
        expected = float(_sim_args(case)["mortality"]) / 100.0
        # Both quantities are proportions, so one is their natural maximum
        # absolute-error scale.
        score = _bounded_accuracy(actual, expected, 1.0)
        return QualityScore(
            score,
            (f"D/(R+D)={actual:.6f}, configured mortality={expected:.6f}",),
        )


class TransmissionRegimeRule(BehavioralRule):
    """Check the qualitative consequence of zero versus positive transmission."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        args = _sim_args(case)
        payload = _final_state(case).payload
        total = float(args["total_population"])
        initial_i = float(args["initial_infective"])
        initial_s = total - initial_i
        beta = float(args["transmission_rate"])
        if beta == 0.0:
            susceptible = _bounded_accuracy(
                float(payload["susceptible"]), initial_s, max(abs(initial_s), 1.0)
            )
            exposed = _bounded_accuracy(float(payload["exposed"]), 0.0, 1.0)
            resolved = (
                float(payload["infective"])
                + float(payload["recovered"])
                + float(payload["deceased"])
            )
            ird = _bounded_accuracy(resolved, initial_i, max(abs(initial_i), 1.0))
            return QualityScore(
                fmean((susceptible, exposed, ird)),
                (
                    f"zero-transmission S accuracy={susceptible:.6f}",
                    f"zero-transmission E accuracy={exposed:.6f}",
                    f"zero-transmission I+R+D accuracy={ird:.6f}",
                ),
            )
        if total <= 0 or initial_i <= 0 or initial_s <= 0:
            return QualityScore(
                1.0,
                ("positive-transmission spread is inapplicable without S and I",),
            )
        spread = float(payload["susceptible"]) < initial_s
        return QualityScore(
            1.0 if spread else 0.0,
            (f"final S={float(payload['susceptible']):.6g}, initial S={initial_s:.6g}",),
        )


RULE_TYPES = {
    "seird.final_time": FinalTimeRule,
    "seird.final_compartment_state": FinalCompartmentStateRule,
    "seird.population_conservation": PopulationConservationRule,
    "seird.compartment_bounds": CompartmentBoundsRule,
    "seird.mortality_partition": MortalityPartitionRule,
    "seird.transmission_regime": TransmissionRegimeRule,
}


def build_rule_registry(
    requirements: Iterable[RequirementSpec],
) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"SEIRD has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
