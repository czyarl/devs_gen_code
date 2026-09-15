"""Strict loading and validation for versioned scenario manifests."""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from devs_eval.errors import BenchmarkConfigurationError
from devs_eval.models import (
    EventSchemaSpec,
    PayloadFieldSpec,
    RecordAdapterSpec,
    RecordSerialization,
    RequirementSpec,
    RuleCategory,
    RuleScope,
    ScenarioManifest,
    ScoreKind,
    TestCaseSpec,
    TraceSchemaSpec,
)

SUPPORTED_PROTOCOL_VERSION = "0.1.0"
BASE_FIELD_TYPES = {"int", "number", "scalar", "str", "bool", "dict", "list"}
SUPPORTED_PAYLOAD_TYPES = BASE_FIELD_TYPES | {f"nullable_{name}" for name in BASE_FIELD_TYPES}
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkConfigurationError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BenchmarkConfigurationError(f"{label} must be a list")
    return value


def _required_text(data: Mapping[str, Any], key: str, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkConfigurationError(f"{label}.{key} must be a non-empty string")
    return value


def _enum(enum_type: type, value: Any, label: str):
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise BenchmarkConfigurationError(f"{label} must be one of: {allowed}") from exc


def _parse_payload_field(data: Mapping[str, Any], label: str) -> PayloadFieldSpec:
    name = _required_text(data, "name", label)
    value_type = _required_text(data, "type", label)
    if value_type not in SUPPORTED_PAYLOAD_TYPES:
        raise BenchmarkConfigurationError(
            f"{label}.type={value_type!r} is unsupported; expected one of "
            f"{sorted(SUPPORTED_PAYLOAD_TYPES)}"
        )
    required = data.get("required", True)
    if not isinstance(required, bool):
        raise BenchmarkConfigurationError(f"{label}.required must be boolean")
    allowed = data.get("allowed_values")
    if allowed is not None:
        allowed = tuple(_require_list(allowed, f"{label}.allowed_values"))
    return PayloadFieldSpec(name, value_type, required, allowed)


def _parse_event(data: Mapping[str, Any], label: str) -> EventSchemaSpec:
    event = _required_text(data, "event", label)
    entities_raw = _require_list(data.get("entities"), f"{label}.entities")
    if not entities_raw or any(not isinstance(item, str) or not item for item in entities_raw):
        raise BenchmarkConfigurationError(f"{label}.entities must contain non-empty strings")
    if len(entities_raw) != len(set(entities_raw)):
        raise BenchmarkConfigurationError(f"{label}.entities contains duplicates")
    fields_raw = _require_list(data.get("payload_fields", []), f"{label}.payload_fields")
    fields = tuple(
        _parse_payload_field(_require_mapping(item, f"{label}.payload_fields[{index}]"),
                             f"{label}.payload_fields[{index}]")
        for index, item in enumerate(fields_raw)
    )
    field_names = [field.name for field in fields]
    if len(field_names) != len(set(field_names)):
        raise BenchmarkConfigurationError(f"{label} contains duplicate payload field names")
    allow_extra = data.get("allow_extra_payload_fields", True)
    if not isinstance(allow_extra, bool):
        raise BenchmarkConfigurationError(f"{label}.allow_extra_payload_fields must be boolean")
    return EventSchemaSpec(event, tuple(entities_raw), fields, allow_extra)


def _parse_trace_schema(data: Mapping[str, Any]) -> TraceSchemaSpec:
    events_raw = _require_list(data.get("events", []), "trace_schema.events")
    events = tuple(
        _parse_event(_require_mapping(item, f"trace_schema.events[{index}]"),
                     f"trace_schema.events[{index}]")
        for index, item in enumerate(events_raw)
    )
    booleans: dict[str, bool] = {}
    for key, default in (
        ("allow_empty_trace", False),
        ("require_nondecreasing_time", True),
        ("allow_unknown_events", False),
    ):
        value = data.get(key, default)
        if not isinstance(value, bool):
            raise BenchmarkConfigurationError(f"trace_schema.{key} must be boolean")
        booleans[key] = value
    time_type = data.get("time_type", "number")
    if time_type not in {"number", "float"}:
        raise BenchmarkConfigurationError("trace_schema.time_type must be 'number' or 'float'")
    adapter_raw = data.get("record_adapter")
    adapter = None
    if adapter_raw is not None:
        adapter = _parse_record_adapter(
            _require_mapping(adapter_raw, "trace_schema.record_adapter")
        )
    return TraceSchemaSpec(
        time_type=time_type, events=events, record_adapter=adapter, **booleans
    )


def _optional_text(data: Mapping[str, Any], key: str, label: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise BenchmarkConfigurationError(f"{label}.{key} must be null or a non-empty string")
    return value


def _parse_record_adapter(data: Mapping[str, Any]) -> RecordAdapterSpec:
    label = "trace_schema.record_adapter"
    serialization = _enum(
        RecordSerialization, data.get("serialization", "jsonl"), f"{label}.serialization"
    )
    time_field = _optional_text(data, "time_field", label)
    time_constant = data.get("time_constant")
    if (time_field is None) == (time_constant is None):
        raise BenchmarkConfigurationError(
            f"{label} must declare exactly one of time_field or time_constant"
        )
    if time_constant is not None and (
        isinstance(time_constant, bool)
        or not isinstance(time_constant, (int, float))
        or not math.isfinite(float(time_constant))
    ):
        raise BenchmarkConfigurationError(f"{label}.time_constant must be finite")
    entity_field = _optional_text(data, "entity_field", label)
    entity_constant = _optional_text(data, "entity_constant", label)
    if (entity_field is None) == (entity_constant is None):
        raise BenchmarkConfigurationError(
            f"{label} must declare exactly one of entity_field or entity_constant"
        )
    event_field = _optional_text(data, "event_field", label)
    event_constant = _optional_text(data, "event_constant", label)
    if (event_field is None) == (event_constant is None):
        raise BenchmarkConfigurationError(
            f"{label} must declare exactly one of event_field or event_constant"
        )
    payload_field = _optional_text(data, "payload_field", label)
    payload_from_remaining = data.get("payload_from_remaining", False)
    if not isinstance(payload_from_remaining, bool):
        raise BenchmarkConfigurationError(f"{label}.payload_from_remaining must be boolean")
    if (payload_field is None) == (not payload_from_remaining):
        raise BenchmarkConfigurationError(
            f"{label} must declare exactly one of payload_field or payload_from_remaining=true"
        )
    includes_raw = _require_list(
        data.get("payload_include_fields", []), f"{label}.payload_include_fields"
    )
    if any(not isinstance(item, str) or not item for item in includes_raw):
        raise BenchmarkConfigurationError(
            f"{label}.payload_include_fields must contain non-empty strings"
        )
    if len(includes_raw) != len(set(includes_raw)):
        raise BenchmarkConfigurationError(f"{label}.payload_include_fields contains duplicates")
    if payload_from_remaining and includes_raw:
        raise BenchmarkConfigurationError(
            f"{label}.payload_include_fields is redundant with payload_from_remaining"
        )
    aliases_raw = data.get("payload_include_aliases", {})
    if not isinstance(aliases_raw, Mapping):
        raise BenchmarkConfigurationError(
            f"{label}.payload_include_aliases must be an object"
        )
    if any(
        not isinstance(source, str)
        or not source
        or not isinstance(alias, str)
        or not alias
        for source, alias in aliases_raw.items()
    ):
        raise BenchmarkConfigurationError(
            f"{label}.payload_include_aliases must map non-empty strings to non-empty strings"
        )
    if len(set(aliases_raw.values())) != len(aliases_raw):
        raise BenchmarkConfigurationError(
            f"{label}.payload_include_aliases contains duplicate destination names"
        )
    if set(includes_raw) & set(aliases_raw.values()):
        raise BenchmarkConfigurationError(
            f"{label} payload include fields and alias destinations collide"
        )
    if payload_from_remaining and aliases_raw:
        raise BenchmarkConfigurationError(
            f"{label}.payload_include_aliases is redundant with payload_from_remaining"
        )
    fields_raw = _require_list(data.get("raw_fields"), f"{label}.raw_fields")
    raw_fields = tuple(
        _parse_payload_field(_require_mapping(item, f"{label}.raw_fields[{index}]"),
                             f"{label}.raw_fields[{index}]")
        for index, item in enumerate(fields_raw)
    )
    raw_names = [field.name for field in raw_fields]
    if not raw_names or len(raw_names) != len(set(raw_names)):
        raise BenchmarkConfigurationError(f"{label}.raw_fields must be non-empty and unique")
    referenced = {
        item
        for item in (
            time_field,
            entity_field,
            event_field,
            payload_field,
            *includes_raw,
            *aliases_raw.keys(),
        )
        if item is not None
    }
    missing = referenced - set(raw_names)
    if missing:
        raise BenchmarkConfigurationError(
            f"{label} projection references fields absent from raw_fields: {sorted(missing)}"
        )
    raw_by_name = {field.name: field for field in raw_fields}
    if time_field is not None and raw_by_name[time_field].value_type not in {"int", "number"}:
        raise BenchmarkConfigurationError(
            f"{label}.time_field must reference an int or number raw field"
        )
    for projection_name, field_name in (
        ("entity_field", entity_field),
        ("event_field", event_field),
    ):
        if field_name is not None and raw_by_name[field_name].value_type != "str":
            raise BenchmarkConfigurationError(
                f"{label}.{projection_name} must reference a str raw field"
            )
    if payload_field is not None and raw_by_name[payload_field].value_type != "dict":
        raise BenchmarkConfigurationError(
            f"{label}.payload_field must reference a dict raw field"
        )
    allow_extra = data.get("allow_extra_raw_fields", False)
    if not isinstance(allow_extra, bool):
        raise BenchmarkConfigurationError(f"{label}.allow_extra_raw_fields must be boolean")
    time_scale = data.get("time_scale", 1.0)
    if (
        isinstance(time_scale, bool)
        or not isinstance(time_scale, (int, float))
        or not math.isfinite(float(time_scale))
        or time_scale <= 0
    ):
        raise BenchmarkConfigurationError(f"{label}.time_scale must be finite and positive")
    return RecordAdapterSpec(
        serialization=serialization,
        time_field=time_field,
        time_constant=float(time_constant) if time_constant is not None else None,
        entity_field=entity_field,
        entity_constant=entity_constant,
        event_field=event_field,
        event_constant=event_constant,
        payload_field=payload_field,
        payload_from_remaining=payload_from_remaining,
        payload_include_fields=tuple(includes_raw),
        payload_include_aliases=dict(aliases_raw),
        raw_fields=raw_fields,
        allow_extra_raw_fields=allow_extra,
        time_scale=float(time_scale),
    )


def _parse_requirement(data: Mapping[str, Any], label: str) -> RequirementSpec:
    applicable = data.get("applicable_case_ids")
    if applicable is not None:
        applicable = tuple(_require_list(applicable, f"{label}.applicable_case_ids"))
        if any(not isinstance(item, str) or not item for item in applicable):
            raise BenchmarkConfigurationError(
                f"{label}.applicable_case_ids must contain non-empty strings"
            )
    minimum = data.get("min_valid_cases", 1)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise BenchmarkConfigurationError(f"{label}.min_valid_cases must be a positive integer")
    parameters = _require_mapping(data.get("parameters", {}), f"{label}.parameters")
    return RequirementSpec(
        requirement_id=_required_text(data, "requirement_id", label),
        name=_required_text(data, "name", label),
        clause=_required_text(data, "clause", label),
        category=_enum(RuleCategory, data.get("category"), f"{label}.category"),
        scope=_enum(RuleScope, data.get("scope"), f"{label}.scope"),
        score_kind=_enum(ScoreKind, data.get("score_kind"), f"{label}.score_kind"),
        applicable_case_ids=applicable,
        min_valid_cases=minimum,
        parameters=dict(parameters),
    )


def _parse_test_case(data: Mapping[str, Any], label: str) -> TestCaseSpec:
    timeout = data.get("timeout_sec", 60.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise BenchmarkConfigurationError(f"{label}.timeout_sec must be positive")
    sim_stdin = data.get("sim_stdin", "")
    if not isinstance(sim_stdin, str):
        raise BenchmarkConfigurationError(f"{label}.sim_stdin must be a string")
    allow_empty_trace = data.get("allow_empty_trace")
    if allow_empty_trace is not None and not isinstance(allow_empty_trace, bool):
        raise BenchmarkConfigurationError(
            f"{label}.allow_empty_trace must be a boolean when provided"
        )
    return TestCaseSpec(
        case_id=_required_text(data, "case_id", label),
        description=_required_text(data, "description", label),
        sim_args=dict(_require_mapping(data.get("sim_args", {}), f"{label}.sim_args")),
        checker_config=dict(
            _require_mapping(data.get("checker_config", {}), f"{label}.checker_config")
        ),
        sim_stdin=sim_stdin,
        timeout_sec=float(timeout),
        allow_empty_trace=allow_empty_trace,
    )


def manifest_from_dict(data: Mapping[str, Any]) -> ScenarioManifest:
    protocol = _required_text(data, "protocol_version", "manifest")
    if protocol != SUPPORTED_PROTOCOL_VERSION:
        raise BenchmarkConfigurationError(
            f"unsupported protocol_version {protocol!r}; expected {SUPPORTED_PROTOCOL_VERSION!r}"
        )
    trace_schema = _parse_trace_schema(
        _require_mapping(data.get("trace_schema"), "trace_schema")
    )
    requirements_raw = _require_list(data.get("requirements"), "requirements")
    cases_raw = _require_list(data.get("test_cases"), "test_cases")
    requirements = tuple(
        _parse_requirement(_require_mapping(item, f"requirements[{index}]"),
                           f"requirements[{index}]")
        for index, item in enumerate(requirements_raw)
    )
    test_cases = tuple(
        _parse_test_case(_require_mapping(item, f"test_cases[{index}]"),
                         f"test_cases[{index}]")
        for index, item in enumerate(cases_raw)
    )
    if not requirements:
        raise BenchmarkConfigurationError("manifest must contain at least one requirement")
    if not test_cases:
        raise BenchmarkConfigurationError("manifest must contain at least one test case")
    requirement_ids = [item.requirement_id for item in requirements]
    case_ids = [item.case_id for item in test_cases]
    scenario_id = _required_text(data, "scenario_id", "manifest")
    for label, identifiers in (
        ("scenario_id", [scenario_id]),
        ("requirement_id", requirement_ids),
        ("case_id", case_ids),
    ):
        invalid = [item for item in identifiers if SAFE_IDENTIFIER.fullmatch(item) is None]
        if invalid:
            raise BenchmarkConfigurationError(
                f"unsafe {label} values; use letters, digits, dot, underscore, or hyphen: {invalid}"
            )
    if len(requirement_ids) != len(set(requirement_ids)):
        raise BenchmarkConfigurationError("manifest contains duplicate requirement IDs")
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkConfigurationError("manifest contains duplicate case IDs")
    known_cases = set(case_ids)
    for requirement in requirements:
        applicable = requirement.applicable_case_ids
        if applicable is not None:
            if len(applicable) != len(set(applicable)):
                raise BenchmarkConfigurationError(
                    f"{requirement.requirement_id} has duplicate applicable case IDs"
                )
            unknown = set(applicable) - known_cases
            if unknown:
                raise BenchmarkConfigurationError(
                    f"{requirement.requirement_id} references unknown cases: {sorted(unknown)}"
                )
        scheduled_count = len(applicable) if applicable is not None else len(test_cases)
        if scheduled_count < requirement.min_valid_cases:
            raise BenchmarkConfigurationError(
                f"{requirement.requirement_id} schedules fewer cases than min_valid_cases"
            )
        if requirement.scope is RuleScope.CASE and requirement.min_valid_cases != 1:
            raise BenchmarkConfigurationError(
                f"case-scoped requirement {requirement.requirement_id} must use min_valid_cases=1"
            )
    return ScenarioManifest(
        protocol_version=protocol,
        benchmark_version=_required_text(data, "benchmark_version", "manifest"),
        scenario_id=scenario_id,
        display_name=_required_text(data, "display_name", "manifest"),
        trace_schema=trace_schema,
        requirements=requirements,
        test_cases=test_cases,
    )


def load_manifest(path: str | Path) -> ScenarioManifest:
    manifest_path = Path(path)
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkConfigurationError(f"cannot load manifest {manifest_path}: {exc}") from exc
    return manifest_from_dict(_require_mapping(raw, "manifest"))


def load_checker(manifest: ScenarioManifest, manifest_path: str | Path):
    """Load the trusted checker colocated with a benchmark manifest."""
    checker_path = Path(manifest_path).resolve().parent / "checker.py"
    if not checker_path.is_file():
        raise BenchmarkConfigurationError(f"benchmark checker not found: {checker_path}")
    spec = importlib.util.spec_from_file_location(
        f"_devs_checker_{manifest.scenario_id}", checker_path
    )
    if spec is None or spec.loader is None:
        raise BenchmarkConfigurationError(f"cannot load benchmark checker: {checker_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(spec.name, None)
        raise BenchmarkConfigurationError(
            f"failed to import benchmark checker {checker_path}: {exc}"
        ) from exc
    builder = getattr(module, "build_rule_registry", None)
    if not callable(builder):
        raise BenchmarkConfigurationError(
            f"benchmark checker lacks build_rule_registry: {checker_path}"
        )
    rules = builder(manifest.requirements)
    expected = {item.requirement_id for item in manifest.requirements}
    if not isinstance(rules, dict) or set(rules) != expected:
        raise BenchmarkConfigurationError(
            f"benchmark checker rule IDs do not match manifest: {checker_path}"
        )
    return rules
