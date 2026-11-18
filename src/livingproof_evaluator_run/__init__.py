"""Run Integrity evaluator: test-system status for a verification run.

Completeness 1.0.0 compares the planned trial count with the observation files present
and trials.results[].sha256. Pins 1.0.0 and plan-conformance 1.0.0 follow. It never
grades the robot.
"""

from livingproof_evaluator_run.evaluate import evaluate, evaluate_evidence

__all__ = ["evaluate", "evaluate_evidence"]
