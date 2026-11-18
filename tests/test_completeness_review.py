"""Reviewer coverage for completeness 1.0.0 (livingproof-evaluator-run#3, #4).

The request path and the CLI routing for a livingproof-evaluator-request had
no test, and nothing pinned the percentage. A trial whose observations are
missing is a missing-observations finding on the request path too (the
contract's examples/integrity/completeness case). A run with no planned
trials is never COMPLETED and never an unhandled exception: it is a
conforming ERROR result, or a clean refusal with no result document.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_completeness as base

from livingproof_evaluator_run import evaluate_evidence
from livingproof_evaluator_run.__main__ import main

EXAMPLE = base.CONTRACT / "examples" / "integrity" / "completeness" / "request.json"


def _findings(document: dict) -> dict[str, str]:
    check = document["integrity"]["checks"][0]
    return {item["trial_id"]: item["category"] for item in check["findings"]}


def _trial_status(document: dict) -> dict[str, str]:
    return {t["id"]: t["test_system_status"] for t in document["integrity"]["trials"]}


def _run_request(tmp_path: Path, request: dict) -> dict:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert main([str(source), "--out", str(out)]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_missing_trial_percentage_is_complete_over_planned(tmp_path):
    out = tmp_path / "result.json"
    evaluate_evidence(base.MISSING, out)
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["integrity"]["run"]["percentage"] == 50
    assert document["integrity"]["checks"][0]["percentage"] == 50


def test_cli_request_flags_the_absent_trial_and_conforms(tmp_path):
    request = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    document = _run_request(tmp_path, request)
    assert base._validate(document) == []
    assert _findings(document).get("trial-absent") == "missing-trial"
    assert _trial_status(document)["trial-absent"] == "ERROR"
    assert document["integrity"]["run"]["conclusion"] == "INCONCLUSIVE"
    assert _trial_status(document)["trial-complete"] == "COMPLETED"


def test_request_trial_without_observations_is_missing_observations(tmp_path):
    request = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    document = _run_request(tmp_path, request)
    assert _findings(document).get("trial-missing-observations") == "missing-observations"
    assert _trial_status(document)["trial-missing-observations"] == "ERROR"


def _no_planned_outcome(run) -> None:
    """No planned trials: a conforming ERROR result, or a clean refusal with no result.

    The v1.1.0 kit requires a non-empty integrity.trials, so refusing (non-zero
    exit or SystemExit, no document) is acceptable. COMPLETED, a non-conforming
    document, or an unhandled exception is not.
    """
    try:
        code, out = run()
    except SystemExit as exc:
        code, out = exc.code or 1, None
    if out is None or not out.exists():
        assert code != 0, "no result document and exit 0"
        return
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["integrity"]["run"]["test_system_status"] == "ERROR"
    assert document["integrity"]["run"]["conclusion"] == "INCONCLUSIVE"
    assert base._validate(document) == []


def test_request_with_no_planned_trials_is_not_completed(tmp_path):
    request = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    request["integrity"]["manifest"]["planned_trials"] = []
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    _no_planned_outcome(lambda: (main([str(source), "--out", str(out)]), out))


def test_evidence_with_zero_planned_trials_is_not_completed(tmp_path):
    manifest = json.loads(base.GOOD.read_text(encoding="utf-8"))
    manifest["plan"]["trials"]["count"] = 0
    manifest["trials"]["count"] = 0
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "result.json"
    _no_planned_outcome(lambda: (main([str(path), "--out", str(out)]), out))
