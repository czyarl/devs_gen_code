"""Requirement-first rules for the Alternating Bit Protocol scenario."""

from __future__ import annotations

from collections.abc import Iterable

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, f1_score, ratio_score


def _sim_args(case: EvaluatedCase) -> dict:
    value = case.config.get("sim_args")
    if not isinstance(value, dict):
        raise BenchmarkConfigurationError(f"case {case.case_id} has no sim_args mapping")
    return value


def _events(case: EvaluatedCase, event: str, entity: str | None = None) -> list[TraceRecord]:
    return [
        record
        for record in case.trace_records
        if record.event == event and (entity is None or record.entity == entity)
    ]


def _ratio_or_zero(successes: int, opportunities: int, message: str) -> QualityScore:
    if opportunities == 0:
        return QualityScore(0.0, (message,))
    return QualityScore(ratio_score(successes, opportunities))


def _ordered_protocol_events(case: EvaluatedCase) -> list[TraceRecord]:
    indexed = [
        (index, record)
        for index, record in enumerate(case.trace_records)
        if record.event in {"packet_sent", "ack_received"}
    ]
    # The specification gives a matching ACK priority over a timeout that
    # expires at the same simulation time.  A retry printed immediately before
    # that ACK must therefore not gain credit merely because of log order.
    priority = {"ack_received": 0, "packet_sent": 1}
    indexed.sort(key=lambda item: (item[1].time, priority[item[1].event], item[0]))
    return [record for _, record in indexed]


class PacketIdentityRule(BehavioralRule):
    """Score the declared sequence numbers and alternating bits of new packets."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        total = int(_sim_args(case)["total_packets"])
        predicted = [
            (record.payload["seq_num"], record.payload["bit"])
            for record in _events(case, "packet_sent", "sender")
            if not record.payload["is_retry"]
        ]
        expected = [(index, (index - 1) % 2) for index in range(1, total + 1)]
        true_positives = sum(
            actual == wanted for actual, wanted in zip(predicted, expected)
        )
        return QualityScore(
            f1_score(true_positives, len(predicted), len(expected)),
            (f"matched {true_positives}/{len(expected)} expected packet positions",),
        )


class StopAndWaitRule(BehavioralRule):
    """Replay observable sender state and score every send/ACK obligation."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        outstanding: tuple[int, int] | None = None
        successes = 0
        opportunities = 0
        for record in _ordered_protocol_events(case):
            if record.event == "packet_sent":
                identity = (record.payload["seq_num"], record.payload["bit"])
                opportunities += 1
                if record.payload["is_retry"]:
                    correct = outstanding is not None and identity == outstanding
                    successes += int(correct)
                else:
                    correct = outstanding is None
                    successes += int(correct)
                    if outstanding is None:
                        outstanding = identity
            else:
                opportunities += 1
                expected_valid = (
                    outstanding is not None and record.payload["ack_bit"] == outstanding[1]
                )
                declared_valid = record.payload["is_valid"]
                successes += int(declared_valid == expected_valid)
                if declared_valid and expected_valid:
                    outstanding = None
        return _ratio_or_zero(
            successes,
            opportunities,
            "no packet or ACK events were available for stop-and-wait replay",
        )


class NoiseModelRule(BehavioralRule):
    """Score independent per-channel LCG state and the declared pass/drop fate."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        seed = int(_sim_args(case)["seed"])
        state = {"forward": seed, "backward": seed}
        successes = 0
        events = _events(case, "packet_get", "subnet")
        for record in events:
            channel = record.payload["channel"]
            state[channel] = (17 * state[channel] + 11) % 100
            expected_noise = state[channel]
            expected_behavior = "drop" if expected_noise < 10 else "pass"
            successes += int(
                record.payload["noise_value"] == expected_noise
                and record.payload["behavior"] == expected_behavior
            )
        return _ratio_or_zero(
            successes, len(events), "no packet_get events were available for LCG replay"
        )


def _pair_obligations(
    left: list[TraceRecord],
    right: list[TraceRecord],
    predicate,
) -> tuple[int, int]:
    opportunities = max(len(left), len(right))
    successes = sum(predicate(a, b) for a, b in zip(left, right))
    return successes, opportunities


class ComponentDelayRule(BehavioralRule):
    """Score declared component delay values and their elapsed-time effects."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        args = _sim_args(case)
        all_starts = _events(case, "delay_start")
        sender_starts = [
            record
            for record in _events(case, "delay_start", "sender")
            if record.payload["type"] == "preparation"
        ]
        receiver_starts = [
            record
            for record in _events(case, "delay_start", "receiver")
            if record.payload["type"] == "processing"
        ]
        sends = _events(case, "packet_sent", "sender")
        receipts = _events(case, "packet_received", "receiver")
        declaration_successes = sum(
            (
                record.entity == "sender"
                and record.payload["type"] == "preparation"
                and record.payload["duration"] == args["sender_delay"]
            )
            or (
                record.entity == "receiver"
                and record.payload["type"] == "processing"
                and record.payload["duration"] == args["receiver_delay"]
            )
            for record in all_starts
        )

        def completion_fraction(starts, completions, duration):
            used: set[int] = set()
            matched = 0
            for completion in completions:
                candidate = next(
                    (
                        index
                        for index, start in enumerate(starts)
                        if index not in used
                        and abs(completion.time - (start.time + float(duration))) <= 0.01
                    ),
                    None,
                )
                if candidate is not None:
                    used.add(candidate)
                    matched += 1
            return matched / len(completions) if completions else 0.0

        declaration_score = (
            declaration_successes / len(all_starts) if all_starts else 0.0
        )
        sender_timing = completion_fraction(sender_starts, sends, args["sender_delay"])
        receiver_timing = completion_fraction(
            receiver_starts, receipts, args["receiver_delay"]
        )
        return QualityScore(
            (declaration_score + sender_timing + receiver_timing) / 3.0,
            (
                f"delay declarations={declaration_score:.6f}",
                f"sender completion timing={sender_timing:.6f}",
                f"receiver completion timing={receiver_timing:.6f}",
            ),
        )


class ChannelTimingRule(BehavioralRule):
    """Score immediate fate decisions and latency of transmitted packets/ACKs."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        channel_delay = float(_sim_args(case)["channel_delay"])
        sends = _events(case, "packet_sent", "sender")
        forward = [
            record
            for record in _events(case, "packet_get", "subnet")
            if record.payload["channel"] == "forward"
        ]
        receipts = _events(case, "packet_received", "receiver")
        backward = [
            record
            for record in _events(case, "packet_get", "subnet")
            if record.payload["channel"] == "backward"
        ]
        receiver_starts = _events(case, "delay_start", "receiver")
        acks = _events(case, "ack_received", "sender")
        successes = 0
        opportunities = 0
        comparisons = (
            (sends, forward, lambda a, b: abs(a.time - b.time) <= 0.01),
            (receipts, backward, lambda a, b: abs(a.time - b.time) <= 0.01),
            (
                [record for record in forward if record.payload["behavior"] == "pass"],
                receiver_starts,
                lambda a, b: abs(b.time - (a.time + channel_delay)) <= 0.01,
            ),
            (
                [record for record in backward if record.payload["behavior"] == "pass"],
                acks,
                lambda a, b: abs(b.time - (a.time + channel_delay)) <= 0.01,
            ),
        )
        for left, right, predicate in comparisons:
            matched, pairs = _pair_obligations(left, right, predicate)
            successes += matched
            opportunities += pairs
        return _ratio_or_zero(
            successes, opportunities, "no channel-timing obligations were observable"
        )


class RequiredEventCoverageRule(BehavioralRule):
    """Measure coverage of the event vocabulary required by the output contract."""

    REQUIRED_EVENTS = {
        "delay_start",
        "packet_sent",
        "packet_get",
        "packet_received",
        "ack_received",
    }

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        observed = {record.event for record in case.trace_records}
        covered = len(self.REQUIRED_EVENTS & observed)
        return QualityScore(ratio_score(covered, len(self.REQUIRED_EVENTS)))


class ReliableCompletionRule(BehavioralRule):
    """Score receiver delivery and valid sender completion for the requested session."""

    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        total = int(_sim_args(case)["total_packets"])
        if total <= 0:
            raise BenchmarkConfigurationError("ABP total_packets must be positive")
        expected = set(range(1, total + 1))
        received = {
            record.payload["seq_num"]
            for record in _events(case, "packet_received", "receiver")
            if record.payload["seq_num"] in expected
            and record.payload["bit"] == (record.payload["seq_num"] - 1) % 2
        }
        valid_acks = 0
        outstanding: tuple[int, int] | None = None
        for record in _ordered_protocol_events(case):
            if record.event == "packet_sent":
                identity = (record.payload["seq_num"], record.payload["bit"])
                if outstanding is None and not record.payload["is_retry"]:
                    outstanding = identity
            elif (
                outstanding is not None
                and record.payload["is_valid"]
                and record.payload["ack_bit"] == outstanding[1]
            ):
                valid_acks += 1
                outstanding = None
        delivery = len(received) / total
        completion = min(valid_acks, total) / total
        return QualityScore(
            (delivery + completion) / 2.0,
            (
                f"received {len(received)}/{total} expected sequence numbers",
                f"observed {min(valid_acks, total)}/{total} valid acknowledgments",
            ),
        )


RULE_TYPES = {
    "abp.packet_identity": PacketIdentityRule,
    "abp.stop_and_wait": StopAndWaitRule,
    "abp.noise_model": NoiseModelRule,
    "abp.component_delays": ComponentDelayRule,
    "abp.channel_timing": ChannelTimingRule,
    "abp.required_event_coverage": RequiredEventCoverageRule,
    "abp.reliable_completion": ReliableCompletionRule,
}


def build_rule_registry(
    requirements: Iterable[RequirementSpec],
) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"ABP has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
