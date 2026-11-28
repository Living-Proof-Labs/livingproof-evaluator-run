"""Vera (verification) checks for livingproof-evaluator-run#70 (PR 73).

Every case replays the real evidence of verification-reports-action run 46110994356
(tests/fixtures/g1-run-46110994356) through ``evaluate_evidence`` and reads the card text the
Run Integrity descriptor carries. They turn what was checked by hand into tests: one sentence
for each of the five checks in ``details_copy``, wording that follows what each check did, no
literal counts or limits, the 1000-character bound on a passing run with many notes, and a
failing run and ``success_copy`` that are unchanged.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import test_completeness as base

from livingproof_evaluator_run import evaluate_evidence

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "g1-run-46110994356"

CHECK_ORDER = ["completeness", "pins", "plan-conformance", "termination", "recording"]
# What each check's own sentence looks like, so a reworded or dropped one is found.
SENTENCE = {
    "completeness": re.compile(r"Every planned trial has its observation file\."),
    "pins": re.compile(r"Matched the verification lock: [a-z, ]+\."),
    "plan-conformance": re.compile(
        r"The plan(?:, the trials and the lock| and the trials) agree on the trial count\."
    ),
    "termination": re.compile(
        r"Every trial that ended on its own stopped for a reason the plan allows\."
    ),
    "recording": re.compile(
        r"Every recording read is a usable MCAP file that matches media\.json, "
        r"with no gap over [0-9.]+ s\."
    ),
}


def _run(tmp_path: Path, mutate=None, *, media: bool = True) -> dict:
    work = tmp_path / "run"
    shutil.copytree(FIXTURE, work)
    manifest_path = work / "evidence" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutate:
        mutate(work, manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    out = tmp_path / "result.json"
    args = (manifest_path, out, work / "media") if media else (manifest_path, out)
    assert evaluate_evidence(*args) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert base._validate(document) == []
    return document


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=\.)\s+", text) if part]


def test_a_passing_run_has_exactly_five_checks_and_a_sentence_for_each(tmp_path: Path) -> None:
    document = _run(tmp_path)
    assert [c["id"] for c in document["integrity"]["checks"]] == CHECK_ORDER
    assert all(c["applicable"] and c["success"] for c in document["integrity"]["checks"])
    details = document["descriptor"]["details_copy"]
    positions = []
    for check in CHECK_ORDER:
        assert len(SENTENCE[check].findall(details)) == 1, (check, details)
        positions.append(SENTENCE[check].search(details).start())
    assert positions == sorted(positions), "the sentences follow the check order"
    assert details.startswith("Every planned trial has its observation file.")


def test_the_gap_in_the_recording_sentence_is_the_plans_limit(tmp_path: Path) -> None:
    def mutate(work: Path, manifest: dict) -> None:
        manifest["plan"]["recording"]["max_gap_seconds"] = 0.07

    details = _run(tmp_path, mutate)["descriptor"]["details_copy"]
    assert "with no gap over 0.07 s." in details
    assert "0.05" not in details


def test_stop_reasons_is_one_line_and_only_when_the_plan_has_no_usable_list(
    tmp_path: Path,
) -> None:
    details = _run(tmp_path)["descriptor"]["details_copy"]
    assert details.count("Stop reasons:") == 1
    assert "(the plan declares none)." in details

    def unknown(work: Path, manifest: dict) -> None:
        manifest["plan"]["allowed_stop_reasons"] = ["bogus"]

    details = _run(tmp_path / "unknown", unknown)["descriptor"]["details_copy"]
    assert details.count("Stop reasons:") == 1
    assert "(the plan's list names no known stop reason)." in details

    def declared(work: Path, manifest: dict) -> None:
        manifest["plan"]["allowed_stop_reasons"] = ["time-limit", "mission-done", "left-world"]

    details = _run(tmp_path / "declared", declared)["descriptor"]["details_copy"]
    assert "Stop reasons:" not in details
    assert SENTENCE["termination"].search(details)


def test_without_a_lock_the_card_claims_no_match_and_says_what_was_not_checked(
    tmp_path: Path,
) -> None:
    def mutate(work: Path, manifest: dict) -> None:
        manifest.pop("lock")

    document = _run(tmp_path, mutate)
    pins = next(c for c in document["integrity"]["checks"] if c["id"] == "pins")
    assert pins["applicable"] is False
    details = document["descriptor"]["details_copy"]
    assert "Matched the verification lock" not in details
    assert "The plan and the trials agree on the trial count." in details
    assert "the lock agree" not in details
    assert "Not checked: lock trial count, lock command speed." in details
    for check in ("completeness", "plan-conformance", "termination", "recording"):
        assert SENTENCE[check].search(details), check


def test_a_check_that_was_not_applicable_gets_no_pass_sentence(tmp_path: Path) -> None:
    """Without media the recording check does not apply, so the card must not say it passed."""
    document = _run(tmp_path, media=False)
    checks = {c["id"]: c for c in document["integrity"]["checks"]}
    assert checks["recording"]["applicable"] is False
    details = document["descriptor"]["details_copy"]
    assert "MCAP" not in details
    for check in ("completeness", "pins", "plan-conformance", "termination"):
        assert SENTENCE[check].search(details), check


def test_details_carry_every_sentence_of_the_400_character_summary(tmp_path: Path) -> None:
    descriptor = _run(tmp_path)["descriptor"]
    summary, details = descriptor["success_copy"], descriptor["details_copy"]
    assert len(summary) <= 400 and len(details) <= 1000
    for sentence in _sentences(summary):
        if sentence != "More notes.":
            assert sentence in details, sentence
    # The summary drops the recording sentence on this real run; the details keep it.
    assert SENTENCE["recording"].search(details)
    assert not SENTENCE["recording"].search(summary)


def test_notes_are_not_cut_off_a_passing_card_with_many_unrecorded_trials(
    tmp_path: Path,
) -> None:
    def mutate(work: Path, manifest: dict) -> None:
        template = work / "evidence" / "trials" / "trial-01.json"
        rows = [manifest["trials"]["results"][0]]
        for index in range(2, 31):
            shutil.copy(template, work / "evidence" / "trials" / f"trial-{index:02d}.json")
            row = copy.deepcopy(rows[0])
            row.update(index=index, path=f"trials/trial-{index:02d}.json")
            rows.append(row)
        manifest["trials"].update(results=rows, count=30)
        manifest["plan"]["trials"]["count"] = 30
        manifest["lock"]["content"]["plan"]["trials"]["count"] = 30

    details = _run(tmp_path, mutate)["descriptor"]["details_copy"]
    assert len(details) <= 1000 and not details.endswith("\u2026")
    assert "Not checked: recording of trial-02, trial-03, trial-04, trial-05, trial-06 and 24" in (
        details
    )
    assert details.endswith("Not checked: specs, verifier.")
    for check in CHECK_ORDER:
        assert SENTENCE[check].search(details), check


def test_a_failing_run_keeps_its_findings_card_and_has_no_summary(tmp_path: Path) -> None:
    def mutate(work: Path, manifest: dict) -> None:
        manifest["lock"]["content"]["plan"]["trials"]["count"] = 2

    document = _run(tmp_path, mutate)
    descriptor = document["descriptor"]
    assert document["integrity"]["run"]["test_system_status"] == "ERROR"
    assert "success_copy" not in descriptor
    details = descriptor["details_copy"]
    assert details.startswith("The plan has 1 trials and the lock's plan trial count is 2.")
    for check in CHECK_ORDER:
        assert not SENTENCE[check].search(details), check


def test_success_copy_on_the_real_run_is_what_the_published_card_carried(tmp_path: Path) -> None:
    """The summary consumers still read does not change (live bundle, evaluator 1.9.0)."""
    expected = (
        "Every planned trial has its observation file. Matched the verification lock: "
        "runner, world, configuration. The plan, the trials and the lock agree on the trial "
        "count. Every trial that ended on its own stopped for a reason the plan allows. "
        "Recording: required channels are the default /base_pose, /joint_states (the plan "
        "declares none). Not checked: specs, verifier. More notes."
    )
    assert _run(tmp_path)["descriptor"]["success_copy"] == expected


def _passing_report(check_id: str, sentence: str, notes: list[str] | None = None):
    from livingproof_evaluator_run.evaluate import Report

    check = {
        "id": check_id,
        "version": "1.0.0",
        "applicable": True,
        "success": True,
        "percentage": 100,
        "findings": [],
    }
    return Report(check, success_copy=sentence, notes=notes or [])


def test_details_of_a_passing_run_are_cut_to_the_contract_length_not_refused(
    tmp_path: Path,
) -> None:
    """Notes past 1000 characters are cut with an ellipsis. Without the cut the contract
    refuses the descriptor, no result is written and a passing run exits 1."""
    from livingproof_evaluator_run.evaluate import _write_result

    long_note = "Recording: " + "x" * 900 + "."
    reports = [
        _passing_report(
            check, f"Sentence for {check}.", [long_note] if check == "recording" else []
        )
        for check in CHECK_ORDER
    ]
    out = tmp_path / "result.json"
    assert _write_result(out, run_id="r", inputs=[], trials=[], reports=reports) == 0
    details = json.loads(out.read_text(encoding="utf-8"))["descriptor"]["details_copy"]
    assert len(details) == 1000 and details.endswith("\u2026")
    assert details.startswith("Sentence for completeness. Sentence for pins.")


def test_a_passing_details_copy_clips_later_notes_first(tmp_path: Path) -> None:
    """A passing details_copy is the joined check sentences plus notes, then cut
    from the end to 1000 characters. A later note is dropped first. A check
    sentence at the start, and an earlier note such as the stop-reasons line,
    stay intact. This is not the 400-character success_copy packing, which
    drops stop-reasons first and then last-check-first.
    """
    from livingproof_evaluator_run.evaluate import _write_result

    late = "Late note: " + "y" * 900 + "."
    reports = [
        _passing_report(
            check,
            f"Sentence for {check}.",
            ["Stop reasons: the default allowed list.", late] if check == "termination" else [],
        )
        for check in CHECK_ORDER
    ]
    out = tmp_path / "result.json"
    assert _write_result(out, run_id="r", inputs=[], trials=[], reports=reports) == 0
    details = json.loads(out.read_text(encoding="utf-8"))["descriptor"]["details_copy"]
    assert len(details) == 1000 and details.endswith("…")
    for check in CHECK_ORDER:
        assert f"Sentence for {check}." in details
    assert "Stop reasons: the default allowed list." in details
    assert late not in details
    assert "Late note:" in details
