"""Replay of verification-reports-action run 46110994356 (livingproof-evaluator-run#70).

The published Unitree G1 hallway report shows only the stop-reasons note on the
Run Integrity card, because the reporter uses details_copy whenever it is
present. This fixture is the evidence manifest, run-manifest, trial file and media
directory from that run. The test fails if details_copy loses any of the five check
sentences or the stop-reasons line.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_completeness as base

from livingproof_evaluator_run import evaluate_evidence

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "g1-run-46110994356"
MANIFEST = FIXTURE / "evidence" / "manifest.json"
MEDIA = FIXTURE / "media"

# One sentence for each of the five checks, then the stop-reasons note and the
# other notes this run records, joined as they appear in details_copy.
EXPECTED_DETAILS = (
    "Every planned trial has its observation file. "
    "Matched the verification lock: runner, world, configuration. "
    "The plan, the trials and the lock agree on the trial count. "
    "Every trial that ended on its own stopped for a reason the plan allows. "
    "Every recording read is a usable MCAP file that matches media.json, "
    "with no gap over 0.05 s. "
    "Stop reasons: the default allowed list, which excludes simulation-broken "
    "(the plan declares none). "
    "Recording: required channels are the default /base_pose, /joint_states "
    "(the plan declares none). "
    "Not checked: specs, verifier."
)


def test_g1_run_46110994356_details_copy_shows_every_check(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    assert evaluate_evidence(MANIFEST, out, MEDIA) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    details = document["descriptor"]["details_copy"]
    assert details == EXPECTED_DETAILS
    assert len(details) <= 1000
    assert base._validate(document) == []
