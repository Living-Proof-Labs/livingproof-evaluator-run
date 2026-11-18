"""The descriptor's 400-character copy after recording 1.0.0 (livingproof-evaluator-run#8, PR 16)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import test_completeness as base

from livingproof_evaluator_run import evaluate_evidence

PINS_GOOD = base.FIXTURES.parent / "pins" / "good"
TERMINATION_SENTENCE = "Every trial that ended on its own stopped for a reason the plan allows."


def test_a_real_lock_run_without_media_keeps_the_termination_sentence(tmp_path: Path) -> None:
    """A run that matches its lock and has no media is the usual run today. The sentence saying
    that termination passed was on its card before recording 1.0.0 and must stay there: the new
    'Not checked: recording' note must not push it out of the 400 characters."""
    folder = tmp_path / "evidence"
    shutil.copytree(PINS_GOOD, folder)
    out = tmp_path / "result.json"
    assert evaluate_evidence(folder / "manifest.json", out, None) == 0
    copy = json.loads(out.read_text(encoding="utf-8"))["descriptor"]["success_copy"]
    assert len(copy) <= 400
    assert "Matched the verification lock" in copy
    assert TERMINATION_SENTENCE in copy


REAL_MEDIA = base.FIXTURES.parent / "recording" / "real"
PINS_SENTENCE = "Matched the verification lock"
PLAN_SENTENCE = "agree on the trial count"


def test_a_real_lock_run_with_media_but_no_gap_limit_keeps_the_pass_sentences(
    tmp_path: Path,
) -> None:
    """Once the Run Integrity job is given --media (capability-verifier#156) and before a plan
    declares max_gap_seconds (nothing does today), recording is not applicable. The new notes
    that list each trial as not-recorded must not push the pins, plan-conformance or termination
    pass sentences off the 400-character card. This is the same class of regression as PR 16."""
    folder = tmp_path / "evidence"
    shutil.copytree(PINS_GOOD, folder)
    media = tmp_path / "media"
    shutil.copytree(REAL_MEDIA, media)
    out = tmp_path / "result.json"
    assert evaluate_evidence(folder / "manifest.json", out, media) == 0
    copy = json.loads(out.read_text(encoding="utf-8"))["descriptor"]["success_copy"]
    assert len(copy) <= 400
    assert PINS_SENTENCE in copy
    assert PLAN_SENTENCE in copy
    assert TERMINATION_SENTENCE in copy
