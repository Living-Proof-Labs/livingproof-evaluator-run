"""Run Integrity evaluator: test-system status for a verification run.

The first slice is completeness 1.0.0: planned trial count versus observation
files present, and trials.results[].sha256 matching. It never grades the robot.
"""

from livingproof_evaluator_run.evaluate import evaluate, evaluate_evidence

__all__ = ["evaluate", "evaluate_evidence"]
