"""Strict operational gate and canonical JSONL trace parser."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from devs_eval.errors import InfrastructureError
from devs_eval.models import (
    EvaluatedCase,
    ExecutionStatus,
    OperationalCheck,
    OperationalOutcome,
    PayloadFieldSpec,
    RecordAdapterSpec,
    RecordSerialization,
    TraceRecord,
    TraceSchemaSpec,
)


TRACE_DIAGNOSTIC_LIMIT = 100


class _DiagnosticBuffer:
    """Retain representative parser failures without amplifying bad output."""

    def __init__(self, limit: int = TRACE_DIAGNOSTIC_LIMIT) -> None:
        self.limit = limit
        self.items: list[str] = []
        self.omitted = 0

    def append(self, message: str) -> None:
        if len(self.items) < self.limit:
            self.items.append(message)
        else:
            self.omitted += 1

    def extend(self, messages) -> None:
        for message in messages:
            self.append(message)

    def finish(self) -> list[str]:
        if not self.omitted:
            return list(self.items)
        return [
            *self.items,
            f"{self.omitted} additional trace diagnostics omitted "
            f"(limit={self.limit})",
        ]


def _finite_decimal(value: Any) -> Decimal | None:
    """Return a finite numeric value without conflating booleans with 0/1."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _coerce_declared_value(value: Any, expected: str) -> tuple[bool, Any]:
    """Normalize harmless JSON scalar encodings while keeping structure strict.

    Benchmark semantics should not depend on whether a generator wrote ``1``,
    ``1.0``, or ``"1"``.  Booleans and structured values remain strict because
    coercing those can change the meaning of a record rather than its encoding.
    """
    if expected.startswith("nullable_"):
        if value is None:
            return True, None
        return _coerce_declared_value(value, expected.removeprefix("nullable_"))
    if expected == "int":
        number = _finite_decimal(value)
        if number is None or number != number.to_integral_value():
            return False, value
        return True, int(number)
    if expected == "number":
        number = _finite_decimal(value)
        if number is None:
            return False, value
        if isinstance(value, int) and not isinstance(value, bool):
            return True, value
        if isinstance(value, float):
            return True, value
        return True, int(number) if number == number.to_integral_value() else float(number)
    if expected == "scalar":
        if isinstance(value, str):
            return True, value
        number = _finite_decimal(value)
        return (number is not None), value
    if expected == "str":
        if isinstance(value, str):
            return True, value
        number = _finite_decimal(value)
        return (number is not None), str(value)
    if expected == "bool":
        return isinstance(value, bool), value
    if expected == "dict":
        return isinstance(value, dict), value
    if expected == "list":
        return isinstance(value, list), value
    return False, value


def _equivalent_scalar(left: Any, right: Any) -> bool:
    left_number = _finite_decimal(left)
    right_number = _finite_decimal(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return left == right and type(left) is type(right)


def _validate_payload_field(
    payload: dict[str, Any], field: PayloadFieldSpec, line_number: int
) -> str | None:
    if field.name not in payload:
        if field.required:
            return f"line {line_number}: missing payload field {field.name!r}"
        return None
    value = payload[field.name]
    valid, normalized = _coerce_declared_value(value, field.value_type)
    if not valid:
        return (
            f"line {line_number}: payload field {field.name!r} must be "
            f"{field.value_type}, got {type(value).__name__}"
        )
    if field.allowed_values is not None:
        no_match = object()
        matched_allowed = next(
            (
                allowed
                for allowed in field.allowed_values
                if _equivalent_scalar(normalized, allowed)
            ),
            no_match,
        )
        if matched_allowed is no_match:
            return (
                f"line {line_number}: payload field {field.name!r} has unsupported value {value!r}"
            )
        # Preserve the manifest's canonical enum spelling/type for scorers.
        normalized = matched_allowed
    payload[field.name] = normalized
    return None


def _raw_objects(
    stdout: str, schema: TraceSchemaSpec
) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    adapter = schema.record_adapter
    serialization = (
        adapter.serialization if adapter is not None else RecordSerialization.JSONL
    )
    objects: list[tuple[int, dict[str, Any]]] = []
    errors = _DiagnosticBuffer()
    if serialization is RecordSerialization.SINGLE_JSON:
        if not stdout.strip():
            return objects, errors.finish()
        try:
            value = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return objects, [f"document: invalid JSON ({exc.msg})"]
        if not isinstance(value, dict):
            return objects, ["document: output must be one JSON object"]
        return [(1, value)], errors.finish()

    for line_number, raw_line in enumerate(stdout.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(value, dict):
            errors.append(f"line {line_number}: trace record must be a JSON object")
            continue
        objects.append((line_number, value))
    return objects, errors.finish()


def _project_record(
    raw: dict[str, Any], adapter: RecordAdapterSpec, line_number: int
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    raw_field_names = {field.name for field in adapter.raw_fields}
    for field in adapter.raw_fields:
        message = _validate_payload_field(raw, field, line_number)
        if message is not None:
            errors.append(message.replace("payload field", "raw field"))
    if not adapter.allow_extra_raw_fields:
        extra = set(raw) - raw_field_names
        if extra:
            errors.append(f"line {line_number}: unexpected raw fields {sorted(extra)}")
    if errors:
        return None, errors

    time_value = raw[adapter.time_field] if adapter.time_field is not None else adapter.time_constant
    entity = raw[adapter.entity_field] if adapter.entity_field is not None else adapter.entity_constant
    event = raw[adapter.event_field] if adapter.event_field is not None else adapter.event_constant
    if adapter.payload_from_remaining:
        excluded = {
            item
            for item in (adapter.time_field, adapter.entity_field, adapter.event_field)
            if item is not None
        }
        payload = {key: value for key, value in raw.items() if key not in excluded}
    else:
        source_payload = raw[adapter.payload_field]  # validated required by manifest/parser
        if not isinstance(source_payload, dict):
            return None, [f"line {line_number}: projected payload field must be an object"]
        payload = dict(source_payload)
        for field_name in adapter.payload_include_fields:
            if field_name in payload:
                return None, [
                    f"line {line_number}: payload include field {field_name!r} collides with payload"
                ]
            payload[field_name] = raw[field_name]
        for source_name, alias in adapter.payload_include_aliases.items():
            if alias in payload:
                return None, [
                    f"line {line_number}: payload alias {alias!r} collides with payload"
                ]
            payload[alias] = raw[source_name]
    return {
        "time": float(time_value) * adapter.time_scale,
        "entity": entity,
        "event": event,
        "payload": payload,
    }, []


def _project_extension_record(
    raw: dict[str, Any], adapter: RecordAdapterSpec
) -> dict[str, Any]:
    """Project an unscored extension without applying benchmark-specific fields."""
    time_value = (
        raw.get(adapter.time_field)
        if adapter.time_field is not None
        else adapter.time_constant
    )
    entity = (
        raw.get(adapter.entity_field)
        if adapter.entity_field is not None
        else adapter.entity_constant
    )
    event = (
        raw.get(adapter.event_field)
        if adapter.event_field is not None
        else adapter.event_constant
    )
    if adapter.payload_from_remaining:
        excluded = {
            item
            for item in (adapter.time_field, adapter.entity_field, adapter.event_field)
            if item is not None
        }
        payload = {key: value for key, value in raw.items() if key not in excluded}
    else:
        source_payload = raw.get(adapter.payload_field) if adapter.payload_field else {}
        payload = dict(source_payload) if isinstance(source_payload, dict) else source_payload
        if isinstance(payload, dict):
            for field_name in adapter.payload_include_fields:
                if field_name in raw and field_name not in payload:
                    payload[field_name] = raw[field_name]
            for source_name, target_name in adapter.payload_include_aliases.items():
                if source_name in raw and target_name not in payload:
                    payload[target_name] = raw[source_name]
    scaled_time = (
        float(time_value) * adapter.time_scale
        if isinstance(time_value, (int, float)) and not isinstance(time_value, bool)
        else time_value
    )
    return {"time": scaled_time, "entity": entity, "event": event, "payload": payload}


def _parse_trace(stdout: str, schema: TraceSchemaSpec) -> tuple[tuple[TraceRecord, ...], list[str]]:
    records: list[TraceRecord] = []
    errors = _DiagnosticBuffer()
    event_schemas: dict[str, list] = {}
    for item in schema.events:
        event_schemas.setdefault(item.event, []).append(item)
    previous_time: float | None = None
    raw_records, decode_errors = _raw_objects(stdout, schema)
    errors.extend(decode_errors)
    for line_number, raw_value in raw_records:
        # Extension records are outside the benchmark's observable contract.
        # When the manifest permits them, discard an unknown event/entity pair
        # before applying the strict schema for records that are actually scored.
        is_extension = False
        if schema.allow_unknown_events:
            adapter = schema.record_adapter
            if adapter is None:
                raw_event = raw_value.get("event")
                raw_entity = raw_value.get("entity")
            else:
                raw_event = (
                    raw_value.get(adapter.event_field)
                    if adapter.event_field is not None
                    else adapter.event_constant
                )
                raw_entity = (
                    raw_value.get(adapter.entity_field)
                    if adapter.entity_field is not None
                    else adapter.entity_constant
                )
            declared_variants = event_schemas.get(raw_event, [])
            if not any(raw_entity in candidate.entities for candidate in declared_variants):
                is_extension = True
        if schema.record_adapter is not None:
            if is_extension:
                value = _project_extension_record(raw_value, schema.record_adapter)
            else:
                value, projection_errors = _project_record(
                    raw_value, schema.record_adapter, line_number
                )
                errors.extend(projection_errors)
                if value is None:
                    continue
        else:
            value = raw_value
        required_fields = {"time", "entity", "event", "payload"}
        missing = required_fields - set(value)
        extra = set(value) - required_fields
        if missing:
            errors.append(f"line {line_number}: missing envelope fields {sorted(missing)}")
            continue
        if extra:
            errors.append(f"line {line_number}: unexpected envelope fields {sorted(extra)}")
            continue
        time_value = value["time"]
        valid_time, time_value = _coerce_declared_value(time_value, "number")
        if not valid_time or float(time_value) < 0:
            errors.append(f"line {line_number}: time must be a finite nonnegative number")
            continue
        value["time"] = time_value
        entity = value["entity"]
        event = value["event"]
        payload = value["payload"]
        if not isinstance(entity, str) or not entity:
            errors.append(f"line {line_number}: entity must be a non-empty string")
            continue
        if not isinstance(event, str) or not event:
            errors.append(f"line {line_number}: event must be a non-empty string")
            continue
        if not isinstance(payload, dict):
            errors.append(f"line {line_number}: payload must be an object")
            continue
        event_variants = event_schemas.get(event, [])
        if not event_variants and not schema.allow_unknown_events:
            errors.append(f"line {line_number}: unknown event {event!r}")
            continue
        matching_variants = [
            candidate for candidate in event_variants if entity in candidate.entities
        ]
        if event_variants and not matching_variants:
            errors.append(
                f"line {line_number}: entity {entity!r} is invalid for event {event!r}"
            )
            continue
        if matching_variants:
            variant_errors: list[str] = []
            matched = False
            for event_schema in matching_variants:
                candidate_payload = dict(payload)
                candidate_errors = [
                    message
                    for field in event_schema.payload_fields
                    if (
                        message := _validate_payload_field(
                            candidate_payload, field, line_number
                        )
                    )
                    is not None
                ]
                if not event_schema.allow_extra_payload_fields:
                    expected_fields = {field.name for field in event_schema.payload_fields}
                    unexpected = set(payload) - expected_fields
                    if unexpected:
                        candidate_errors.append(
                            f"line {line_number}: unexpected payload fields {sorted(unexpected)}"
                        )
                if not candidate_errors:
                    matched = True
                    payload = candidate_payload
                    break
                variant_errors.append("; ".join(candidate_errors))
            if not matched:
                errors.append(
                    f"line {line_number}: payload matches no schema variant for "
                    f"event {event!r}, entity {entity!r}: {' | '.join(variant_errors)}"
                )
                continue
        normalized_time = float(time_value)
        if (
            schema.require_nondecreasing_time
            and previous_time is not None
            and normalized_time < previous_time
        ):
            errors.append(
                f"line {line_number}: time {normalized_time} precedes prior time {previous_time}"
            )
            continue
        records.append(TraceRecord(normalized_time, entity, event, dict(payload)))
        previous_time = normalized_time
    if not records and not schema.allow_empty_trace:
        errors.append("trace is empty but the scenario schema forbids an empty trace")
    return tuple(records), errors.finish()


def evaluate_operational_output(
    *,
    case_id: str,
    entry_id: str,
    config: dict[str, Any],
    execution: ExecutionStatus,
    stdout: str,
    schema: TraceSchemaSpec,
) -> EvaluatedCase:
    """Apply the strict per-test-case operational gate."""
    if execution.infrastructure_error:
        raise InfrastructureError(execution.infrastructure_error)
    if not isinstance(stdout, str):
        raise InfrastructureError("captured stdout is not text")
    records, trace_errors = _parse_trace(stdout, schema)
    checks = (
        OperationalCheck(
            "completed_before_timeout",
            not execution.timed_out,
            "simulation timed out" if execution.timed_out else "",
        ),
        OperationalCheck(
            "zero_exit_status",
            execution.return_code == 0,
            f"return code was {execution.return_code!r}" if execution.return_code != 0 else "",
        ),
        OperationalCheck(
            "stdout_not_truncated",
            not execution.stdout_truncated,
            "stdout exceeded the capture limit" if execution.stdout_truncated else "",
        ),
        OperationalCheck(
            "workspace_within_limit",
            not execution.workspace_limit_exceeded,
            "simulator workspace exceeded the writable-byte limit"
            if execution.workspace_limit_exceeded
            else "",
        ),
        OperationalCheck(
            "stdout_is_utf8",
            execution.stdout_utf8_valid,
            "stdout contains invalid UTF-8" if not execution.stdout_utf8_valid else "",
        ),
        OperationalCheck(
            "trace_schema_valid",
            not trace_errors,
            "; ".join(trace_errors),
        ),
    )
    passed = all(check.passed for check in checks)
    diagnostics = tuple(check.detail for check in checks if check.detail)
    return EvaluatedCase(
        case_id=case_id,
        entry_id=entry_id,
        config=dict(config),
        execution=execution,
        trace_records=records,
        operational=OperationalOutcome(passed, checks, diagnostics),
    )
