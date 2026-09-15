"""Deterministic JSON serialization for evaluator artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from devs_eval.errors import InfrastructureError


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def dumps_json(value: Any, *, indent: int = 2) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True, indent=indent)


def write_json(path: str | Path, value: Any) -> None:
    try:
        Path(path).write_text(dumps_json(value) + "\n", encoding="utf-8")
    except OSError as exc:
        raise InfrastructureError(f"cannot write JSON artifact {path}: {exc}") from exc
