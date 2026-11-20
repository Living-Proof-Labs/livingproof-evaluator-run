"""Adopt livingproof-evaluator v1.2.0 (livingproof-evaluator-run#18).

The contract moved five checks to 1.1.0 (completeness, pins, termination, plan-conformance and
recording), added ``not_checked``, and kept 1.0.0 valid through ``previous_versions``. These tests
pin the adoption against the contract's own registry, examples and reference rules, and the new
behaviour that has no example of its own: the request path of completeness, the listing in
``media.json``, and the rejection of an inconsistent request.
"""

from __future__ import annotations

import importlib
import json
import random
import sys
from pathlib import Path

import pytest
import recordings as rec
import test_completeness as base

from livingproof_evaluator_run import evaluate, evaluate_evidence
from livingproof_evaluator_run.__main__ import main

ROOT = base.ROOT
KIT = base.CONTRACT
EXAMPLES = KIT / "examples" / "integrity"
OURS = ("completeness", "pins", "plan-conformance", "termination", "recording")


def completeness_module():
    return importlib.import_module("livingproof_evaluator_run.completeness")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_request(request: dict, tmp_path: Path) -> dict:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate(source, out) == 0
    return _load(out)


def _check(document: dict, check_id: str) -> dict:
    (found,) = [c for c in document["integrity"]["checks"] if c["id"] == check_id]
    return found


def _ids(check: dict) -> list[tuple[str, str]]:
    return [(item["trial_id"], item["category"]) for item in check["findings"]]


# The contract that is checked out, and the versions we claim.


def test_the_contract_is_pinned_at_v1_4_0() -> None:
    text = (ROOT / "tools" / "fetch_contract.py").read_text(encoding="utf-8")
    assert 'TAG = "v1.4.0"' in text
    assert "v1.1.0" not in text


def test_every_check_is_at_the_version_the_contract_registry_says() -> None:
    from livingproof_evaluator_run import pins, plan_conformance, recording, termination

    registry = _load(KIT / "schema" / "integrity" / "checks" / "registry.json")
    current = {entry["id"]: entry["version"] for entry in registry["checks"]}
    previous = {entry["id"]: entry.get("previous_versions", []) for entry in registry["checks"]}
    ours = {
        "completeness": completeness_module().COMPLETENESS_VERSION,
        "pins": pins.PINS_VERSION,
        "plan-conformance": plan_conformance.PLAN_CONFORMANCE_VERSION,
        "termination": termination.TERMINATION_VERSION,
        "recording": recording.RECORDING_VERSION,
    }
    assert ours == {check: current[check] for check in OURS}
    assert ours["recording"] == "1.2.0"
    assert {v for check, v in ours.items() if check != "recording"} == {"1.1.0"}
    assert previous["recording"] == ["1.0.0", "1.1.0"]
    assert all(previous[check] == ["1.0.0"] for check in OURS if check != "recording")


def test_a_result_reports_every_check_at_its_current_version(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    assert evaluate_evidence(base.GOOD, out) == 0
    checks = _load(out)["integrity"]["checks"]
    assert [(c["id"], c["version"]) for c in checks] == [
        (c, "1.2.0" if c == "recording" else "1.1.0") for c in OURS
    ]


@pytest.mark.parametrize("check", ["completeness", "termination"])
def test_completeness_and_termination_do_not_report_not_checked(check: str, tmp_path: Path) -> None:
    """The envelope rejects ``not_checked`` on the checks that have no skipped subject."""
    out = tmp_path / "result.json"
    assert evaluate_evidence(base.GOOD, out) == 0
    assert "not_checked" not in _check(_load(out), check)


# Every published 1.1.0 example, run through the request path.

PUBLISHED = {
    ("pins-not-checked", "pins"),
    ("pins-none-checked", "pins"),
    ("completeness-preconditions-unmet", "completeness"),
    ("completeness-preconditions-unmet", "plan-conformance"),
    ("completeness-recording-listed-missing", "completeness"),
    ("completeness-recording-listed-missing", "recording"),
    ("plan-conformance/no-lock", "plan-conformance"),
    ("plan-conformance/lock-checked", "plan-conformance"),
    ("recording/not-checked", "recording"),
    ("recording/none-judged", "recording"),
    ("termination/simulation-broken", "termination"),
}


def _examples() -> list[Path]:
    return sorted(path.parent for path in EXAMPLES.rglob("request.json"))


def _comparable(check: dict) -> dict:
    """The check without the summary text, which is the producer's own wording."""
    return {
        **check,
        "findings": [{k: v for k, v in f.items() if k != "summary"} for f in check["findings"]],
    }


def test_every_published_1_1_0_example_gives_the_published_check(tmp_path: Path) -> None:
    covered: set[tuple[str, str]] = set()
    for folder in _examples():
        name = folder.relative_to(EXAMPLES).as_posix()
        expected = _load(folder / "result.json")
        wanted = [c for c in expected["integrity"]["checks"] if c["id"] in OURS]
        if not wanted:
            continue
        request = _load(folder / "request.json")
        if name == "recording/findings":
            continue  # a 1.0.0 request that 1.1.0 rejects; see the malformed-request tests
        (tmp_path / name.replace("/", "_")).mkdir()
        document = _run_request(request, tmp_path / name.replace("/", "_"))
        for want in wanted:
            got = _check(document, want["id"])
            ours = "1.2.0" if want["id"] == "recording" else "1.1.0"
            assert got["version"] == ours, (name, want["id"])
            if want["version"] == "1.1.0":
                assert _comparable({**got, "version": "1.1.0"}) == _comparable(want), (
                    name,
                    want["id"],
                )
                covered.add((name, want["id"]))
        assert base._validate(document) == [], name
    assert PUBLISHED <= covered, PUBLISHED - covered


@pytest.mark.parametrize(
    "name", ["completeness-preconditions-unmet", "completeness-recording-listed-missing"]
)
def test_the_published_1_1_0_examples_give_the_published_run_and_trial_statuses(
    name: str, tmp_path: Path
) -> None:
    request = _load(EXAMPLES / name / "request.json")
    expected = _load(EXAMPLES / name / "result.json")["integrity"]
    document = _run_request(request, tmp_path)
    assert document["integrity"]["trials"] == expected["trials"]
    assert document["integrity"]["run"] == expected["run"]


# completeness on the request path: the recording and observation states a trial reports.


def test_the_published_completeness_example_gives_its_findings(tmp_path: Path) -> None:
    """The contract's 1.0.0 example has a trial for every category. Our check follows its
    findings, one per trial, and reads the recording and observation states it carries."""
    request = _load(EXAMPLES / "completeness" / "request.json")
    expected = _check(_load(EXAMPLES / "completeness" / "result.json"), "completeness")
    got = _check(_run_request(request, tmp_path), "completeness")
    assert got["version"] == "1.1.0"
    assert _ids(got) == _ids(expected)
    assert got["percentage"] == expected["percentage"] == 10
    assert got["success"] is False


@pytest.mark.parametrize(
    "state, category",
    [
        ("missing", "missing-recording"),
        ("truncated", "truncated-recording"),
        ("empty", "empty-recording"),
    ],
)
def test_a_recording_that_is_not_present_is_a_completeness_finding(
    state: str, category: str, tmp_path: Path
) -> None:
    request = _load(EXAMPLES / "completeness-recording-listed-missing" / "request.json")
    recording = request["integrity"]["trials"][2]["recording"]
    recording["state"] = state
    if state == "truncated":
        recording["sha256"] = "d" * 64
    document = _run_request(request, tmp_path)
    assert _ids(_check(document, "completeness")) == [("trial-03", category)]
    assert _check(document, "recording")["not_checked"] == [
        {"trial_id": "trial-03", "reason": "not-present"}
    ]
    assert document["integrity"]["run"]["test_system_status"] == "ERROR"


@pytest.mark.parametrize(
    "state, category",
    [("truncated", "truncated-observations"), ("empty", "empty-observations")],
)
def test_observations_that_are_truncated_or_empty_are_a_completeness_finding(
    state: str, category: str, tmp_path: Path
) -> None:
    request = _load(EXAMPLES / "completeness-recording-listed-missing" / "request.json")
    request["integrity"]["trials"][0]["observations"]["state"] = state
    got = _check(_run_request(request, tmp_path), "completeness")
    assert _ids(got) == [("trial-01", category), ("trial-03", "missing-recording")]


def test_a_trial_with_two_problems_has_both_reported_and_fails_once(tmp_path: Path) -> None:
    request = _load(EXAMPLES / "completeness-recording-listed-missing" / "request.json")
    request["integrity"]["trials"][2]["observations"]["state"] = "missing"
    got = _check(_run_request(request, tmp_path), "completeness")
    assert _ids(got) == [("trial-03", "missing-recording"), ("trial-03", "missing-observations")]
    assert got["percentage"] == pytest.approx(100 * 2 / 3)


def test_a_timeout_has_one_completeness_finding_even_with_no_recording(tmp_path: Path) -> None:
    """The contract: across completeness and termination a trial that timed out has exactly one
    finding. completeness reports the ending and nothing else for that trial."""
    request = _load(EXAMPLES / "completeness-recording-listed-missing" / "request.json")
    trial = request["integrity"]["trials"][2]
    trial["termination"] = "timeout"
    trial.pop("outcome", None)
    got = _check(_run_request(request, tmp_path), "completeness")
    assert _ids(got) == [("trial-03", "ended-by-timeout")]


# completeness applicability (1.1.0), against the contract's reference rule.


def _random_payload(rng: random.Random) -> dict:
    payload: dict = {"trials": [], "manifest": {"planned_trials": [{"id": "a"}]}}
    kind = rng.choice(["none", "met", "unmet", "no-preconditions"])
    if kind != "none":
        evidence: dict = {}
        if kind != "no-preconditions":
            evidence["preconditions"] = {"met": kind == "met"}
        payload["evidence"] = {"plan-conformance": evidence}
    return payload


@pytest.mark.parametrize("version", ["1.1.0", "1.0.0"])
def test_completeness_applicability_equals_the_contract_reference_rule(version: str) -> None:
    sys.path.insert(0, str(KIT / "tests"))
    import integrity_rules

    rng = random.Random(3)
    seen: set[bool] = set()
    for _ in range(200):
        payload = _random_payload(rng)
        expected = integrity_rules.completeness_applicable(payload, version)
        assert completeness_module().applicable_for_request(payload, version) is expected, payload
        seen.add(expected)
    assert seen == ({True, False} if version == "1.1.0" else {True})


def test_the_default_completeness_version_is_the_current_one() -> None:
    sys.path.insert(0, str(KIT / "tests"))
    import integrity_rules

    unmet = {"evidence": {"plan-conformance": {"preconditions": {"met": False}}}}
    assert completeness_module().COMPLETENESS_VERSION == "1.1.0"
    assert completeness_module().applicable_for_request(
        unmet
    ) is integrity_rules.completeness_applicable(unmet)
    assert completeness_module().applicable_for_request(unmet) is False


# A run whose preconditions were unmet, on an evidence manifest.

UNMET = base.FIXTURES.parent / "plan-conformance" / "preconditions-unmet"


def test_a_manifest_whose_preconditions_were_unmet_is_not_a_completeness_error(
    tmp_path: Path,
) -> None:
    out = tmp_path / "result.json"
    assert evaluate_evidence(UNMET / "manifest.json", out) == 0
    document = _load(out)
    assert _check(document, "completeness") == {
        "id": "completeness",
        "version": "1.1.0",
        "applicable": False,
        "success": True,
        "findings": [],
    }
    run = document["integrity"]["run"]
    # Nothing applied to this run (livingproof-evaluator#38, result format 1.2.0): not graded.
    assert run["test_system_status"] == "INCONCLUSIVE" and "percentage" not in run
    assert run["success"] is False and run["conclusion"] == "INCONCLUSIVE"
    assert all(t["test_system_status"] == "COMPLETED" for t in document["integrity"]["trials"])
    assert len(document["integrity"]["trials"]) == 3
    assert base._validate(document) == []


def test_the_same_manifest_with_the_precondition_met_is_judged_as_before(tmp_path: Path) -> None:
    import shutil

    folder = tmp_path / "evidence"
    shutil.copytree(UNMET, folder)
    path = folder / "manifest.json"
    manifest = _load(path)
    manifest["preconditions"][0]["met"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate_evidence(path, out) == 0
    check = _check(_load(out), "completeness")
    assert check["applicable"] is True and check["success"] is False


# completeness reads the recordings media.json lists (an evidence manifest).


def _evidence(tmp_path: Path) -> Path:
    import shutil

    folder = tmp_path / "evidence"
    shutil.copytree(base.FIXTURES.parent / "termination" / "good", folder)
    path = folder / "manifest.json"
    manifest = _load(path)
    manifest.setdefault("plan", {})["recording"] = {"max_gap_seconds": 0.05}
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return folder


def test_one_of_three_listed_recordings_missing_is_not_completed_and_not_100(
    tmp_path: Path,
) -> None:
    """Rivet's question on livingproof-evaluator#34: a run with one of three listed recordings
    missing must not read COMPLETED and 100."""
    folder = _evidence(tmp_path)
    media = tmp_path / "media"
    rec.build_media(media, folder)
    (media / "mcap" / "trial-03.mcap").unlink()
    out = tmp_path / "result.json"
    assert evaluate_evidence(folder / "manifest.json", out, media) == 0
    document = _load(out)
    completeness_check = _check(document, "completeness")
    assert _ids(completeness_check) == [("trial-03", "missing-recording")]
    assert completeness_check["percentage"] == pytest.approx(100 * 2 / 3)
    run = document["integrity"]["run"]
    assert (run["test_system_status"], run["conclusion"]) == ("ERROR", "INCONCLUSIVE")
    assert run["percentage"] == pytest.approx(100 * 2 / 3)
    statuses = {t["id"]: t["test_system_status"] for t in document["integrity"]["trials"]}
    assert statuses == {"trial-01": "COMPLETED", "trial-02": "COMPLETED", "trial-03": "ERROR"}
    assert base._validate(document) == []


def test_without_a_media_directory_completeness_reads_no_recording(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    out = tmp_path / "result.json"
    assert evaluate_evidence(folder / "manifest.json", out) == 0
    document = _load(out)
    assert _check(document, "completeness")["findings"] == []
    assert document["integrity"]["run"]["success"] is True


def test_a_trial_with_no_evidence_is_only_missing_trial(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = tmp_path / "media"
    rec.build_media(media, folder)
    (media / "mcap" / "trial-02.mcap").unlink()
    path = folder / "manifest.json"
    manifest = _load(path)
    del manifest["trials"]["results"][1]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate_evidence(path, out, media) == 0
    assert _ids(_check(_load(out), "completeness")) == [("trial-02", "missing-trial")]


# An inconsistent request is rejected: exit 2, no result.


def _inconsistent() -> dict:
    request = _load(EXAMPLES / "recording" / "clean" / "request.json")
    request["integrity"]["evidence"]["recording"]["trials"][1]["mcap"]["state"] = "incomplete"
    return request


def test_an_inconsistent_request_exits_2_and_writes_no_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(_inconsistent()), encoding="utf-8")
    out = tmp_path / "out" / "result.json"
    assert main([str(source), "--out", str(out)]) == 2
    assert not out.exists() and not out.parent.exists()
    message = capsys.readouterr().err
    assert "malformed request" in message
    assert "recording.state is present" in message


def test_a_rejected_request_leaves_an_earlier_result_alone(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    out.write_text("earlier", encoding="utf-8")
    source = tmp_path / "request.json"
    source.write_text(json.dumps(_inconsistent()), encoding="utf-8")
    assert evaluate(source, out) == 2
    assert out.read_text(encoding="utf-8") == "earlier"


def test_the_error_is_the_contracts_malformed_request_and_a_value_error() -> None:
    from livingproof_evaluator_run import recording

    assert issubclass(recording.MalformedRequest, ValueError)
    with pytest.raises(recording.MalformedRequest, match="classify it as truncated"):
        recording.from_request(_inconsistent()["integrity"])


def test_the_same_request_with_the_state_truncated_is_accepted(tmp_path: Path) -> None:
    request = _inconsistent()
    trial = request["integrity"]["trials"][1]
    trial["recording"]["state"] = "truncated"
    document = _run_request(request, tmp_path)
    assert _ids(_check(document, "completeness")) == [(trial["id"], "truncated-recording")]
    assert _check(document, "recording")["not_checked"] == [
        {"trial_id": trial["id"], "reason": "not-present"}
    ]


def test_an_incomplete_entry_for_a_trial_that_is_not_present_is_not_inconsistent(
    tmp_path: Path,
) -> None:
    request = _inconsistent()
    request["integrity"]["trials"][1]["recording"]["state"] = "missing"
    request["integrity"]["trials"][1]["recording"].pop("sha256", None)
    document = _run_request(request, tmp_path)
    assert document["integrity"]["run"]["test_system_status"] == "ERROR"


def test_the_docs_table_does_not_call_no_media_not_recorded() -> None:
    """No media is not applicable with an empty not_checked list, not a not-recorded trial.
    The docs table must match the code."""
    text = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    start = text.index("| `not-recorded`")
    row = text[start : text.index("\n", start)]
    assert "no media" not in row
    assert "media.json" in row
