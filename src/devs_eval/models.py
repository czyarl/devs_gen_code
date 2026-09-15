"""Data contracts shared by manifests, rules, scoring, and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class RuleCategory(str, Enum):
    MICRO = "micro"
    MACRO = "macro"


class RuleScope(str, Enum):
    CASE = "case"
    COLLECTION = "collection"


class ScoreKind(str, Enum):
    BINARY = "binary"
    RATIO = "ratio"
    CONTINUOUS = "continuous"
    COMPOSITE = "composite"


class RecordSerialization(str, Enum):
    JSONL = "jsonl"
    SINGLE_JSON = "single_json"


@dataclass(frozen=True)
class PayloadFieldSpec:
    name: str
    value_type: str
    required: bool = True
    allowed_values: tuple[Any, ...] | None = None


@dataclass(frozen=True)
class EventSchemaSpec:
    event: str
    entities: tuple[str, ...]
    payload_fields: tuple[PayloadFieldSpec, ...] = ()
    allow_extra_payload_fields: bool = True


@dataclass(frozen=True)
class RecordAdapterSpec:
    serialization: RecordSerialization = RecordSerialization.JSONL
    time_field: str | None = "time"
    time_constant: float | None = None
    entity_field: str | None = "entity"
    entity_constant: str | None = None
    event_field: str | None = "event"
    event_constant: str | None = None
    payload_field: str | None = "payload"
    payload_from_remaining: bool = False
    payload_include_fields: tuple[str, ...] = ()
    payload_include_aliases: Mapping[str, str] = field(default_factory=dict)
    raw_fields: tuple[PayloadFieldSpec, ...] = ()
    allow_extra_raw_fields: bool = False
    time_scale: float = 1.0


@dataclass(frozen=True)
class TraceSchemaSpec:
    time_type: str = "number"
    allow_empty_trace: bool = False
    require_nondecreasing_time: bool = True
    allow_unknown_events: bool = False
    events: tuple[EventSchemaSpec, ...] = ()
    record_adapter: RecordAdapterSpec | None = None


@dataclass(frozen=True)
class TraceRecord:
    time: float
    entity: str
    event: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ExecutionStatus:
    return_code: int | None
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    stdout_utf8_valid: bool = True
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    workspace_limit_exceeded: bool = False
    workspace_growth_bytes: int | None = None
    infrastructure_error: str | None = None
    duration_sec: float | None = None


@dataclass(frozen=True)
class OperationalCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class OperationalOutcome:
    passed: bool
    checks: tuple[OperationalCheck, ...]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class TestCaseSpec:
    case_id: str
    description: str
    sim_args: Mapping[str, Any]
    checker_config: Mapping[str, Any]
    sim_stdin: str = ""
    timeout_sec: float = 60.0
    allow_empty_trace: bool | None = None


@dataclass(frozen=True)
class RequirementSpec:
    requirement_id: str
    name: str
    clause: str
    category: RuleCategory
    scope: RuleScope
    score_kind: ScoreKind
    applicable_case_ids: tuple[str, ...] | None = None
    min_valid_cases: int = 1
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScenarioManifest:
    protocol_version: str
    benchmark_version: str
    scenario_id: str
    display_name: str
    trace_schema: TraceSchemaSpec
    requirements: tuple[RequirementSpec, ...]
    test_cases: tuple[TestCaseSpec, ...]


@dataclass(frozen=True)
class EvaluatedCase:
    case_id: str
    entry_id: str
    config: Mapping[str, Any]
    execution: ExecutionStatus
    trace_records: tuple[TraceRecord, ...]
    operational: OperationalOutcome


@dataclass(frozen=True)
class QualityScore:
    score: float
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequirementEvaluation:
    requirement_id: str
    category: RuleCategory
    scope: RuleScope
    quality_score: float
    coverage: float
    score: float
    applicable_case_ids: tuple[str, ...]
    valid_case_ids: tuple[str, ...]
    per_case_scores: Mapping[str, float | None]
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioEvaluation:
    protocol_version: str
    benchmark_version: str
    scenario_id: str
    operational_score: float
    behavioral_score: float
    fully_operational: bool
    category_scores: Mapping[str, float]
    requirement_evaluations: tuple[RequirementEvaluation, ...]
    case_operational: Mapping[str, bool]
    diagnostics: tuple[str, ...] = ()
