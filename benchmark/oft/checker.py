"""Requirement-level rules for the Offline File Transfer scenario."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import EvaluatedCase, QualityScore, RequirementSpec, TraceRecord
from devs_eval.rules import BehavioralRule, f1_score


def _events(case: EvaluatedCase, event: str, entity: str | None = None) -> list[TraceRecord]:
    return [
        record
        for record in case.trace_records
        if record.event == event and (entity is None or record.entity == entity)
    ]


def _expected(case: EvaluatedCase, name: str) -> int:
    config = case.config.get("checker_config")
    if not isinstance(config, dict) or name not in config:
        raise BenchmarkConfigurationError(f"OFT case {case.case_id} lacks {name}")
    return int(config[name])


def _parse_timestamp(value: str) -> float:
    fields = value.split(":")
    if len(fields) not in {3, 4}:
        raise BenchmarkConfigurationError(f"invalid OFT input timestamp {value!r}")
    hours, minutes, seconds = (int(item) for item in fields[:3])
    milliseconds = int(fields[3]) if len(fields) == 4 else 0
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def _commands(case: EvaluatedCase) -> list[tuple[float, str, int]]:
    checker_config = case.config.get("checker_config")
    if isinstance(checker_config, dict) and "input_commands" in checker_config:
        commands = checker_config["input_commands"]
        if not isinstance(commands, list):
            raise BenchmarkConfigurationError("OFT input_commands must be a list")
        return [
            (float(item["time"]), str(item["type"]), int(item["value"]))
            for item in commands
        ]
    result: list[tuple[float, str, int]] = []
    for line in case.config.get("sim_stdin", case.config.get("stdin", "")).splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 3 or parts[1] not in {"control", "request"}:
            raise BenchmarkConfigurationError(f"invalid OFT stdin line: {line!r}")
        result.append((_parse_timestamp(parts[0]), parts[1], int(parts[2])))
    return result


def _time_close(left: float, right: float, tolerance: float = 0.001) -> bool:
    return abs(left - right) <= tolerance


def _mean(parts: list[float]) -> float:
    return sum(parts) / len(parts) if parts else 1.0


class CommandSemanticsRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        controls = [(time, value) for time, kind, value in _commands(case) if kind == "control"]
        requests = [(time, bool(value)) for time, kind, value in _commands(case) if kind == "request"]
        logged_controls = _events(case, "control_cmd", "sender")
        logged_requests = _events(case, "download_valve_change", "server_sender")
        acknowledgments = _events(case, "ack_received", "sender")
        cumulative_added = 0
        control_matches = 0
        for record, expected in zip(logged_controls, controls):
            cumulative_added += expected[1]
            completed_before_command = sum(ack.time <= expected[0] for ack in acknowledgments)
            expected_remaining = max(0, cumulative_added - completed_before_command)
            control_matches += int(
                _time_close(record.time, expected[0])
                and record.payload.get("added") == expected[1]
                and record.payload.get("total_remaining") == expected_remaining
            )
        request_matches = sum(
            _time_close(record.time, expected[0])
            and record.payload.get("allowed") is expected[1]
            for record, expected in zip(logged_requests, requests)
        )
        return QualityScore(
            _mean(
                [
                    f1_score(control_matches, len(logged_controls), len(controls)),
                    f1_score(request_matches, len(logged_requests), len(requests)),
                ]
            ),
            (
                f"control echoes={control_matches}/{len(controls)}",
                f"request echoes={request_matches}/{len(requests)}",
            ),
        )


class SenderAbpRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        sent = _events(case, "packet_sent", "sender")
        if not sent:
            return QualityScore(1.0 if _expected(case, "expected_uploads") == 0 else 0.0)
        outstanding: tuple[int, int] | None = None
        successes = 0
        opportunities = 0
        expected_seq = 1
        expected_bit = 0
        ordered = [
            record
            for record in case.trace_records
            if (record.entity, record.event)
            in {
                ("sender", "packet_sent"),
                ("sender", "ack_received"),
                ("sender", "timeout"),
            }
        ]
        timeout_seq: int | None = None
        for record in ordered:
            if record.event == "timeout":
                opportunities += 1
                timeout_seq = record.payload.get("seq")
                successes += int(outstanding is not None and timeout_seq == outstanding[0])
            elif record.event == "packet_sent":
                identity = (record.payload.get("seq"), record.payload.get("bit"))
                retry = record.payload.get("is_retry")
                opportunities += 1
                if retry:
                    valid = (
                        outstanding is not None
                        and identity == outstanding
                        and timeout_seq == identity[0]
                    )
                    successes += int(valid)
                else:
                    valid = outstanding is None and identity == (expected_seq, expected_bit)
                    successes += int(valid)
                    if valid:
                        outstanding = identity
                        timeout_seq = None
            else:
                opportunities += 1
                bit = record.payload.get("bit")
                valid = outstanding is not None and bit == outstanding[1]
                successes += int(valid)
                if valid:
                    outstanding = None
                    expected_seq += 1
                    expected_bit = 1 - expected_bit
                    timeout_seq = None
        return QualityScore(successes / opportunities if opportunities else 0.0)


def _first_unused_after(
    records: list[TraceRecord],
    time: float,
    used: set[int],
    *,
    seq: object | None = None,
    bit: object | None = None,
) -> tuple[int, TraceRecord] | None:
    return next(
        (
            (index, record)
            for index, record in enumerate(records)
            if index not in used
            and record.time >= time
            and (seq is None or record.payload.get("seq") == seq)
            and (bit is None or record.payload.get("bit") == bit)
        ),
        None,
    )


def _first_after(
    records: list[TraceRecord],
    time: float,
    *,
    seq: object | None = None,
    bit: object | None = None,
) -> TraceRecord | None:
    match = _first_unused_after(records, time, set(), seq=seq, bit=bit)
    return match[1] if match is not None else None


class UploadTransportRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = _expected(case, "expected_uploads")
        sent = _events(case, "packet_sent", "sender")
        received = _events(case, "packet_received", "server_receiver")
        server_acks = _events(case, "ack_sent_to_sender", "server_receiver")
        sender_acks = _events(case, "ack_received", "sender")
        if not sent:
            return QualityScore(1.0 if expected == 0 else 0.0)
        successes = 0
        opportunities = 0
        used_received: set[int] = set()
        used_server_acks: set[int] = set()
        used_sender_acks: set[int] = set()
        tolerance = float(self.spec.parameters.get("absolute_time_tolerance_sec", 0.1))
        for packet in sent:
            seq, bit = packet.payload.get("seq"), packet.payload.get("bit")
            arrival_match = _first_unused_after(
                received, packet.time, used_received, seq=seq, bit=bit
            )
            arrival = arrival_match[1] if arrival_match is not None else None
            opportunities += 1
            successes += int(arrival is not None and abs(arrival.time - packet.time - 3.0) <= tolerance)
            if arrival is None:
                continue
            used_received.add(arrival_match[0])
            ack_sent_match = _first_unused_after(
                server_acks, arrival.time, used_server_acks, bit=bit
            )
            ack_sent = ack_sent_match[1] if ack_sent_match is not None else None
            opportunities += 1
            successes += int(ack_sent is not None and abs(ack_sent.time - arrival.time - 3.0) <= tolerance)
            if ack_sent is None:
                continue
            used_server_acks.add(ack_sent_match[0])
            ack_received_match = _first_unused_after(
                sender_acks, ack_sent.time, used_sender_acks, bit=bit
            )
            ack_received = ack_received_match[1] if ack_received_match is not None else None
            opportunities += 1
            successes += int(
                ack_received is not None and abs(ack_received.time - ack_sent.time - 3.0) <= tolerance
            )
            if ack_received_match is not None:
                used_sender_acks.add(ack_received_match[0])
        return QualityScore(successes / opportunities if opportunities else 0.0)


class PreparationTimingRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = _expected(case, "expected_uploads")
        preparations = _events(case, "preparation_started", "sender")
        sends = [
            record for record in _events(case, "packet_sent", "sender")
            if not record.payload.get("is_retry")
        ]
        if not sends:
            return QualityScore(1.0 if expected == 0 else 0.0)
        tolerance = float(self.spec.parameters.get("absolute_time_tolerance_sec", 0.1))
        successes = 0
        used_preparations: set[int] = set()
        for send in sends:
            starts = [
                (index, record)
                for index, record in enumerate(preparations)
                if index not in used_preparations and record.time <= send.time
            ]
            if not starts:
                continue
            index, start = starts[-1]
            used_preparations.add(index)
            successes += int(
                start.payload.get("duration") == 10000
                and abs(send.time - start.time - 10.0) <= tolerance
            )
        return QualityScore(successes / len(sends))


class DownloadValveFifoRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = _expected(case, "expected_downloads")
        received = _events(case, "packet_received", "server_receiver")
        forwarded = _events(case, "packet_forwarded", "server_sender")
        if not forwarded:
            return QualityScore(1.0 if expected == 0 else 0.0)
        request_schedule = [
            (time, bool(value)) for time, kind, value in _commands(case) if kind == "request"
        ]
        stored_order: list[int] = []
        first_received: dict[int, TraceRecord] = {}
        for record in received:
            seq = record.payload.get("seq")
            if isinstance(seq, int) and seq not in stored_order:
                stored_order.append(seq)
                first_received[seq] = record
        forwarded_order: list[int] = []
        successes = 0
        opportunities = 0
        for record in forwarded:
            seq = record.payload.get("seq")
            allowed = False
            for command_time, state in request_schedule:
                if command_time <= record.time:
                    allowed = state
                else:
                    break
            opportunities += 2
            successes += int(allowed)
            successes += int(
                seq in first_received and first_received[seq].time < record.time
            )
            if seq not in forwarded_order:
                forwarded_order.append(seq)
        opportunities += len(forwarded_order)
        successes += sum(left == right for left, right in zip(stored_order, forwarded_order))
        return QualityScore(successes / opportunities if opportunities else 0.0)


class ReceiverDownloadRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected = _expected(case, "expected_downloads")
        forwarded = _events(case, "packet_forwarded", "server_sender")
        starts = _events(case, "processing_started", "receiver")
        receiver_acks = _events(case, "ack_sent", "receiver")
        server_acks = _events(case, "ack_received_from_receiver", "server_sender")
        if not forwarded:
            return QualityScore(1.0 if expected == 0 else 0.0)
        tolerance = float(self.spec.parameters.get("absolute_time_tolerance_sec", 0.1))
        successes = 0
        opportunities = 0
        for packet in forwarded:
            seq, bit = packet.payload.get("seq"), packet.payload.get("bit")
            start = _first_after(starts, packet.time, seq=seq)
            opportunities += 1
            successes += int(start is not None and abs(start.time - packet.time - 3.0) <= tolerance)
            if start is None:
                continue
            ack = _first_after(receiver_acks, start.time, bit=bit)
            opportunities += 1
            successes += int(ack is not None and abs(ack.time - start.time - 10.0) <= tolerance)
            if ack is None:
                continue
            final_ack = _first_after(server_acks, ack.time, bit=bit)
            opportunities += 1
            successes += int(final_ack is not None and abs(final_ack.time - ack.time - 3.0) <= tolerance)
        return QualityScore(successes / opportunities if opportunities else 0.0)


class TransferCompletionRule(BehavioralRule):
    def _evaluate_case(self, case: EvaluatedCase) -> QualityScore:
        expected_uploads = _expected(case, "expected_uploads")
        expected_downloads = _expected(case, "expected_downloads")
        uploads = {
            record.payload.get("seq")
            for record in _events(case, "packet_received", "server_receiver")
        }
        downloads = {
            record.payload.get("seq")
            for record in _events(case, "processing_started", "receiver")
        }
        wanted_uploads = set(range(1, expected_uploads + 1))
        wanted_downloads = set(range(1, expected_downloads + 1))
        upload_score = f1_score(len(uploads & wanted_uploads), len(uploads), len(wanted_uploads))
        download_score = f1_score(
            len(downloads & wanted_downloads), len(downloads), len(wanted_downloads)
        )
        return QualityScore(
            (upload_score + download_score) / 2.0,
            (f"uploads={sorted(uploads)}", f"downloads={sorted(downloads)}"),
        )


RULE_TYPES = {
    "oft.command_semantics": CommandSemanticsRule,
    "oft.sender_abp": SenderAbpRule,
    "oft.preparation_timing": PreparationTimingRule,
    "oft.upload_transport": UploadTransportRule,
    "oft.download_valve_fifo": DownloadValveFifoRule,
    "oft.receiver_download": ReceiverDownloadRule,
    "oft.transfer_completion": TransferCompletionRule,
}


def build_rule_registry(requirements: Iterable[RequirementSpec]) -> dict[str, BehavioralRule]:
    registry: dict[str, BehavioralRule] = {}
    for spec in requirements:
        rule_type = RULE_TYPES.get(spec.requirement_id)
        if rule_type is None:
            raise BenchmarkConfigurationError(
                f"oft has no rule implementation for {spec.requirement_id}"
            )
        registry[spec.requirement_id] = rule_type(spec)
    return registry
