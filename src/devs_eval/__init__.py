"""Specification-driven evaluator for the DEVS simulation benchmark."""

from .manifest import load_manifest
from .operational import evaluate_operational_output
from .scoring import evaluate_scenario

__all__ = [
    "evaluate_operational_output",
    "evaluate_scenario",
    "load_manifest",
]

__version__ = "0.2.0"
