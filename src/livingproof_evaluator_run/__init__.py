"""Run Integrity evaluator: test-system status for a verification run.

Completeness 1.1.0 compares the planned trial count with the observation files present
and trials.results[].sha256, and with media the recordings media.json lists. Pins,
plan-conformance, termination and recording (all 1.1.0) follow; the ones that do not compare
everything list what they left out in not_checked. It never grades the robot.
"""

from livingproof_evaluator_run.evaluate import evaluate, evaluate_evidence

__all__ = ["evaluate", "evaluate_evidence"]
