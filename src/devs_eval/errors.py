"""Typed failures used to keep model, infrastructure, and evaluator failures separate."""


class DevsEvalError(Exception):
    """Base class for evaluator errors."""


class BenchmarkConfigurationError(DevsEvalError):
    """The benchmark manifest or rule registry is internally inconsistent."""


class InfrastructureError(DevsEvalError):
    """The evaluation environment failed before a model output could be assessed."""


class EvaluatorError(DevsEvalError):
    """A checker failed or returned an invalid result."""


class ScoreValidationError(EvaluatorError):
    """A rule returned a non-finite score or a score outside [0, 1]."""
