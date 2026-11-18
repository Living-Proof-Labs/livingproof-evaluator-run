"""termination 1.0.0 (livingproof-evaluator-run#7).

Fail-first coverage for the fourth Run Integrity check: every trial that ended on its own
records a stop reason, and the plan allows it. The contract is livingproof-evaluator v1.1.0
(``schema/integrity/checks/termination.schema.json``, ``docs/run-integrity.md``). Its reference
rules (``tests/integrity_rules.py``) are run against ours, case by case.

Where the evidence comes from, per ``livingproof-hallway-evidence/2.0.0`` as livingproof-sim-mujoco
writes it:

* the trial's stop reason is the ``end`` in its observation file (``trials/trial-NN.json``);
* the manifest copies it as ``trials.results[].outcome``;
* the runner's words map to the contract's: ``crossed_exit`` is ``mission-done``,
  ``left_hallway`` is ``left-world``, ``time_limit`` is ``time-limit``, ``non_finite_state`` is
  ``simulation-broken``;
* the plan's allowed list is ``plan.allowed_stop_reasons`` in the manifest, else the lock's plan,
  else a default that leaves out ``simulation-broken``.

Fixtures under ``tests/fixtures/termination``: ``good`` is three trials, one per clean runner
ending. It is synthetic, in the shape of the real ``tests/fixtures/pins/good`` run. Every doctored
run is a copy of it with one change, and is synthetic too.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import sys
from pathlib import Path

import pytest
import test_completeness as base

from livingproof_evaluator_run import evaluate, evaluate_evidence
from livingproof_evaluator_run.__main__ import main

FIXTURES = base.FIXTURES.parent / "termination"
GOOD = FIXTURES / "good"
REAL = base.FIXTURES.parent / "pins" / "good"
EXAMPLES = base.CONTRACT / "examples" / "integrity" / "termination"
CHECK = "termination"
SCHEMA = base.CONTRACT / "schema" / "integrity" / "checks" / "termination.schema.json"
VOCABULARY = {
    "time-limit",
    "mission-done",
    "left-world",
    "simulation-broken",
    "adapter-or-scenario-done",
}
DEFAULT_ALLOWED = ["time-limit", "mission-done", "left-world", "adapter-or-scenario-done"]


def _copy(source: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "evidence"
    shutil.copytree(source, dest)
    return dest


def _manifest(folder: Path, change) -> None:
    path = folder / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _set_end(folder: Path, index: int, end: object, *, outcome: object = "same") -> None:
    """Write ``end`` into trial ``index`` and keep its digest (and outcome) in the manifest, so
    completeness stays clean and only this check can object."""
    path = folder / "trials" / f"trial-{index:02d}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if end is None:
        document.pop("end", None)
    else:
        document["end"] = end
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def change(doc: dict) -> None:
        row = doc["trials"]["results"][index - 1]
        row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if outcome == "same":
            row["outcome"] = end
        elif outcome is None:
            row.pop("outcome", None)
        else:
            row["outcome"] = outcome

    _manifest(folder, change)


def _run(folder: Path, tmp_path: Path) -> dict:
    out = tmp_path / "result.json"
    assert evaluate_evidence(folder / "manifest.json", out) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def _checks(document: dict) -> list[dict]:
    return document["integrity"]["checks"]


def _check(document: dict, check_id: str = CHECK) -> dict:
    (found,) = [c for c in _checks(document) if c["id"] == check_id]
    return found


def _categories(check: dict) -> list[str]:
    return [item["category"] for item in check["findings"]]


def _doctored(tmp_path: Path, change, source: Path = GOOD) -> tuple[dict, dict]:
    folder = _copy(source, tmp_path)
    change(folder)
    document = _run(folder, tmp_path)
    return document, _check(document)


def _conforming_error(document: dict) -> None:
    run = document["integrity"]["run"]
    assert run["test_system_status"] == "ERROR"
    assert run["conclusion"] == "INCONCLUSIVE"
    assert run["success"] is False
    assert "verdict" not in document
    assert "grade" not in document
    assert base._validate(document) == []


# The good run and the contract's vocabulary.


def test_good_run_ends_cleanly(tmp_path: Path) -> None:
    document, check = _doctored(tmp_path, lambda folder: None)
    assert check == {
        "id": CHECK,
        "version": "1.0.0",
        "applicable": True,
        "success": True,
        "percentage": 100,
        "findings": [],
        "referrals": [],
    }
    assert document["integrity"]["run"]["test_system_status"] == "COMPLETED"
    assert "conclusion" not in document["integrity"]["run"]
    assert base._validate(document) == []


def test_real_run_ends_cleanly(tmp_path: Path) -> None:
    """The evidence folder of a real run: ``end`` is crossed_exit in the file and the manifest."""
    document, check = _doctored(tmp_path, lambda folder: None, REAL)
    assert check["applicable"] is True
    assert check["success"] is True
    assert check["percentage"] == 100
    assert base._validate(document) == []


def test_checks_are_reported_in_order(tmp_path: Path) -> None:
    document, _ = _doctored(tmp_path, lambda folder: None)
    assert [c["id"] for c in _checks(document)] == [
        "completeness",
        "pins",
        "plan-conformance",
        CHECK,
        "recording",
    ]


@pytest.mark.parametrize(
    ("end", "stop_reason"),
    [
        ("crossed_exit", "mission-done"),
        ("left_hallway", "left-world"),
        ("time_limit", "time-limit"),
        ("adapter_done", "adapter-or-scenario-done"),
    ],
)
def test_every_clean_runner_ending_is_allowed_by_default(
    end: str, stop_reason: str, tmp_path: Path
) -> None:
    document, check = _doctored(tmp_path, lambda folder: _set_end(folder, 1, end))
    assert check["success"] is True
    assert check["findings"] == []
    from livingproof_evaluator_run import termination

    assert termination.END_TO_STOP_REASON[end] == stop_reason
    assert stop_reason in termination.DEFAULT_ALLOWED_STOP_REASONS


def test_the_runner_words_map_to_the_contract_vocabulary() -> None:
    from livingproof_evaluator_run import termination

    assert termination.END_TO_STOP_REASON == {
        "crossed_exit": "mission-done",
        "left_hallway": "left-world",
        "left_world": "left-world",
        "time_limit": "time-limit",
        "non_finite_state": "simulation-broken",
        "adapter_done": "adapter-or-scenario-done",
    }
    assert set(termination.END_TO_STOP_REASON.values()) <= VOCABULARY


def test_the_vocabulary_and_categories_are_the_contracts() -> None:
    from livingproof_evaluator_run import termination

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["$defs"]["stop_reason"]["enum"]) == VOCABULARY
    assert set(termination.STOP_REASONS) == VOCABULARY
    enum = schema["properties"]["findings"]["items"]["properties"]["category"]["enum"]
    assert sorted(termination.CATEGORIES) == sorted(enum)
    assert schema["properties"]["version"]["const"] == termination.TERMINATION_VERSION
    assert termination.TERMINATION_ID == CHECK
    assert '"termination"' in (base.CONTRACT / "schema/integrity/checks/registry.json").read_text()


# Where the plan's allowed list comes from, and the default.


def test_the_default_allowed_list_excludes_simulation_broken() -> None:
    from livingproof_evaluator_run import termination

    assert "simulation-broken" not in termination.DEFAULT_ALLOWED_STOP_REASONS
    assert sorted(termination.DEFAULT_ALLOWED_STOP_REASONS) == sorted(DEFAULT_ALLOWED)
    assert set(termination.DEFAULT_ALLOWED_STOP_REASONS) < VOCABULARY


def test_a_broken_simulation_is_a_finding_under_the_default(tmp_path: Path) -> None:
    """non_finite_state is simulation-broken, and the default plan does not allow it."""
    document, check = _doctored(tmp_path, lambda f: _set_end(f, 2, "non_finite_state"))
    assert [(i["category"], i["trial_id"], i["summary"]) for i in check["findings"]] == [
        (
            "disallowed-stop-reason",
            "trial-02",
            "The stop reason simulation-broken is not one the plan allows.",
        )
    ]
    assert check["success"] is False
    assert check["percentage"] == pytest.approx(100 * 2 / 3)
    _conforming_error(document)


def test_the_summary_says_the_default_list_was_used(tmp_path: Path) -> None:
    document, _ = _doctored(tmp_path, lambda folder: None)
    copy_ = document["descriptor"]["success_copy"]
    assert "default" in copy_
    assert "simulation-broken" in copy_


def _declare(reasons: object, where: str = "plan"):
    def change(folder: Path) -> None:
        def edit(doc: dict) -> None:
            if where == "plan":
                doc["plan"]["allowed_stop_reasons"] = reasons
            else:
                doc.setdefault("lock", {}).setdefault("content", {}).setdefault("plan", {})[
                    "allowed_stop_reasons"
                ] = reasons

        _manifest(folder, edit)

    return change


def test_a_plan_that_allows_simulation_broken_makes_it_clean(tmp_path: Path) -> None:
    def change(folder: Path) -> None:
        _set_end(folder, 2, "non_finite_state")
        _declare(DEFAULT_ALLOWED + ["simulation-broken"])(folder)

    document, check = _doctored(tmp_path, change)
    assert check["success"] is True
    assert check["findings"] == []
    assert base._validate(document) == []


def test_a_plan_list_replaces_the_default(tmp_path: Path) -> None:
    """The plan allows only mission-done, so a clean left_hallway is no longer allowed."""

    def change(folder: Path) -> None:
        _declare(["mission-done"])(folder)

    _, check = _doctored(tmp_path, change)
    assert [(i["trial_id"], i["category"]) for i in check["findings"]] == [
        ("trial-02", "disallowed-stop-reason"),
        ("trial-03", "disallowed-stop-reason"),
    ]
    assert check["percentage"] == pytest.approx(100 / 3)


def test_the_lock_plan_is_the_fallback_and_the_manifest_plan_wins(tmp_path: Path) -> None:
    def from_lock(folder: Path) -> None:
        _set_end(folder, 2, "non_finite_state")
        _declare(DEFAULT_ALLOWED + ["simulation-broken"], "lock")(folder)

    _, check = _doctored(tmp_path / "lock", from_lock)
    assert check["success"] is True

    def both(folder: Path) -> None:
        from_lock(folder)
        _declare(DEFAULT_ALLOWED)(folder)

    _, check = _doctored(tmp_path / "both", both)
    assert _categories(check) == ["disallowed-stop-reason"]


@pytest.mark.parametrize("bad", [[], "mission-done", ["bogus"], [1, None], {"a": 1}, 5])
def test_a_declaration_that_names_no_known_reason_falls_back_to_the_default(
    bad: object, tmp_path: Path
) -> None:
    """Never wider than the default: an unusable declaration cannot allow a broken simulation."""

    def change(folder: Path) -> None:
        _set_end(folder, 2, "non_finite_state")
        _declare(bad)(folder)

    document, check = _doctored(tmp_path, change)
    assert _categories(check) == ["disallowed-stop-reason"]
    assert "default" in document["descriptor"]["details_copy"]
    _conforming_error(document)


def test_unknown_names_in_a_declaration_are_ignored(tmp_path: Path) -> None:
    def change(folder: Path) -> None:
        _set_end(folder, 2, "non_finite_state")
        _declare(["mission-done", "left-world", "time-limit", "bogus", "simulation-broken"])(folder)

    _, check = _doctored(tmp_path, change)
    assert check["success"] is True


# The finding categories.


def test_an_end_outside_the_vocabulary_is_unknown(tmp_path: Path) -> None:
    document, check = _doctored(tmp_path, lambda f: _set_end(f, 3, "exploded"))
    assert [(i["category"], i["trial_id"], i["summary"]) for i in check["findings"]] == [
        (
            "unknown-stop-reason",
            "trial-03",
            "The stop reason exploded is not in the stop reason vocabulary.",
        )
    ]
    _conforming_error(document)


def test_a_missing_end_is_a_missing_stop_reason(tmp_path: Path) -> None:
    document, check = _doctored(tmp_path, lambda f: _set_end(f, 1, None, outcome=None))
    assert [(i["category"], i["trial_id"], i["summary"]) for i in check["findings"]] == [
        ("missing-stop-reason", "trial-01", "The trial records no stop reason.")
    ]
    _conforming_error(document)


def test_a_manifest_outcome_that_differs_is_a_mismatch(tmp_path: Path) -> None:
    document, check = _doctored(
        tmp_path, lambda f: _set_end(f, 1, "crossed_exit", outcome="time_limit")
    )
    assert [(i["category"], i["trial_id"], i["summary"]) for i in check["findings"]] == [
        (
            "stop-reason-mismatch",
            "trial-01",
            "The trial records mission-done and the manifest records time-limit.",
        )
    ]
    _conforming_error(document)


def test_a_manifest_without_an_outcome_is_not_a_mismatch(tmp_path: Path) -> None:
    _, check = _doctored(tmp_path, lambda f: _set_end(f, 1, "crossed_exit", outcome=None))
    assert check["findings"] == []


def test_a_missing_end_with_an_outcome_is_only_missing(tmp_path: Path) -> None:
    _, check = _doctored(tmp_path, lambda f: _set_end(f, 1, None, outcome="crossed_exit"))
    assert _categories(check) == ["missing-stop-reason"]


def test_one_trial_can_be_unknown_and_mismatched_and_counts_once(tmp_path: Path) -> None:
    _, check = _doctored(tmp_path, lambda f: _set_end(f, 1, "weird", outcome="crossed_exit"))
    assert _categories(check) == ["unknown-stop-reason", "stop-reason-mismatch"]
    assert check["percentage"] == pytest.approx(100 * 2 / 3)


@pytest.mark.parametrize("bad", [5, True, 1.5, ["crossed_exit"], {"a": 1}, ""])
def test_an_end_that_is_not_text_is_not_a_clean_ending(bad: object, tmp_path: Path) -> None:
    document, check = _doctored(tmp_path, lambda f: _set_end(f, 1, bad, outcome=None))
    assert check["success"] is False
    assert _categories(check) == (["missing-stop-reason"] if bad == "" else ["unknown-stop-reason"])
    _conforming_error(document)


@pytest.mark.parametrize("content", ["not json", "[]", "5", "null"])
def test_a_trial_file_that_is_not_an_observation_has_no_stop_reason(
    content: str, tmp_path: Path
) -> None:
    def change(folder: Path) -> None:
        path = folder / "trials" / "trial-01.json"
        path.write_text(content, encoding="utf-8")

        def edit(doc: dict) -> None:
            doc["trials"]["results"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

        _manifest(folder, edit)

    document, check = _doctored(tmp_path, change)
    assert _categories(check) == ["missing-stop-reason"]
    _conforming_error(document)


def test_findings_name_the_trial_and_never_a_verdict(tmp_path: Path) -> None:
    def change(folder: Path) -> None:
        _set_end(folder, 1, "non_finite_state")
        _set_end(folder, 2, "exploded")
        _set_end(folder, 3, None, outcome=None)

    document, check = _doctored(tmp_path, change)
    assert _categories(check) == [
        "disallowed-stop-reason",
        "unknown-stop-reason",
        "missing-stop-reason",
    ]
    assert check["percentage"] == 0
    for item in check["findings"]:
        assert set(item) == {"category", "classification", "summary", "trial_id"}
        assert item["classification"] == "test_system"
    shown = document["descriptor"]["findings"]
    assert [item["trial"] for item in shown if "trial" in item][:3] == [
        "trial-01",
        "trial-02",
        "trial-03",
    ]
    _conforming_error(document)


def test_findings_leave_the_trial_statuses_to_completeness(tmp_path: Path) -> None:
    """As the contract's termination findings example: its trials stay COMPLETED."""
    document, _ = _doctored(tmp_path, lambda f: _set_end(f, 2, "non_finite_state"))
    assert [t["test_system_status"] for t in document["integrity"]["trials"]] == ["COMPLETED"] * 3
    assert document["integrity"]["run"]["test_system_status"] == "ERROR"
    assert document["integrity"]["run"]["percentage"] == pytest.approx(100 * 2 / 3)


# Completeness keeps a trial it already reports. This check judges only trials it can read.


def test_a_missing_trial_file_stays_a_completeness_finding(tmp_path: Path) -> None:
    def change(folder: Path) -> None:
        (folder / "trials" / "trial-02.json").unlink()

    document, check = _doctored(tmp_path, change)
    assert check["findings"] == []
    assert check["percentage"] == 100
    assert [c["id"] for c in _checks(document) if c["findings"]] == ["completeness"]


def test_a_hash_mismatch_stays_a_completeness_finding(tmp_path: Path) -> None:
    def change(folder: Path) -> None:
        (folder / "trials" / "trial-02.json").write_text('{"end": "exploded"}\n')

    document, check = _doctored(tmp_path, change)
    assert check["findings"] == []
    assert [c["id"] for c in _checks(document) if c["findings"]] == ["completeness"]


def test_a_trial_never_has_findings_from_both_checks(tmp_path: Path) -> None:
    def change(folder: Path) -> None:
        (folder / "trials" / "trial-01.json").unlink()
        _set_end(folder, 2, "non_finite_state")
        (folder / "trials" / "trial-03.json").write_text("{}\n")

    document, check = _doctored(tmp_path, change)
    mine = {i["trial_id"] for i in check["findings"]}
    theirs = {i["trial_id"] for i in _check(document, "completeness")["findings"]}
    assert mine == {"trial-02"}
    assert theirs == {"trial-01", "trial-03"}
    assert mine.isdisjoint(theirs)


def test_no_readable_trial_means_not_applicable(tmp_path: Path) -> None:
    def change(folder: Path) -> None:
        for index in (1, 2, 3):
            (folder / "trials" / f"trial-{index:02d}.json").unlink()

    document, check = _doctored(tmp_path, change)
    assert check == {
        "id": CHECK,
        "version": "1.0.0",
        "applicable": False,
        "success": True,
        "findings": [],
        "referrals": [],
    }
    assert "Not checked: termination" in document["descriptor"]["details_copy"]
    assert base._validate(document) == []


def test_a_run_with_nothing_judged_does_not_lower_the_run_percentage(tmp_path: Path) -> None:
    def change(folder: Path) -> None:
        for index in (2, 3):
            (folder / "trials" / f"trial-{index:02d}.json").unlink()

    document, check = _doctored(tmp_path, change)
    assert check["percentage"] == 100
    assert document["integrity"]["run"]["percentage"] == pytest.approx(100 / 3)


def test_the_evidence_path_has_no_referrals(tmp_path: Path) -> None:
    """The manifest records no timeout or crash, so there is nothing to refer."""
    _, check = _doctored(tmp_path, lambda f: _set_end(f, 2, "non_finite_state"))
    assert check["referrals"] == []


def test_text_copied_from_evidence_is_shown_escaped(tmp_path: Path) -> None:
    hostile = "<b>end</b>\n" + "x" * 300
    document, check = _doctored(tmp_path, lambda f: _set_end(f, 1, hostile, outcome=None))
    assert _categories(check) == ["unknown-stop-reason"]
    assert "<" not in check["findings"][0]["summary"]
    assert "\n" not in check["findings"][0]["summary"]
    assert all(
        "<" not in i["text"] and "\n" not in i["text"] for i in document["descriptor"]["findings"]
    )
    _conforming_error(document)


def test_command_line_reports_termination(tmp_path: Path) -> None:
    folder = _copy(GOOD, tmp_path)
    _set_end(folder, 1, "non_finite_state")
    out = tmp_path / "result.json"
    assert main([str(folder / "manifest.json"), "--out", str(out)]) == 0
    check = _check(json.loads(out.read_text(encoding="utf-8")))
    assert _categories(check) == ["disallowed-stop-reason"]


# The request path: evidence['termination'] and each trial's termination.


def _request(name: str) -> dict:
    return json.loads((EXAMPLES / name / "request.json").read_text(encoding="utf-8"))


def _run_request(request: dict, tmp_path: Path) -> dict:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate(source, out) == 0
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["clean", "findings", "timeout-single-report"])
def test_the_contract_examples_give_the_contract_checks(name: str, tmp_path: Path) -> None:
    document = _run_request(_request(name), tmp_path)
    expected = json.loads((EXAMPLES / name / "result.json").read_text(encoding="utf-8"))
    for check in _checks(expected):
        assert _check(document, check["id"]) == check
    assert document["integrity"]["trials"] == expected["integrity"]["trials"]
    assert base._validate(document) == []


def test_a_timeout_and_a_crash_are_reported_once_by_completeness(tmp_path: Path) -> None:
    document = _run_request(_request("timeout-single-report"), tmp_path)
    completeness = _check(document, "completeness")
    termination = _check(document)
    assert [(i["trial_id"], i["category"]) for i in completeness["findings"]] == [
        ("trial-timeout", "ended-by-timeout"),
        ("trial-crash", "ended-by-crash"),
    ]
    assert termination["findings"] == []
    assert termination["success"] is True
    assert termination["percentage"] == 100
    assert termination["referrals"] == [
        {"trial_id": "trial-timeout", "check": "completeness", "category": "ended-by-timeout"},
        {"trial_id": "trial-crash", "check": "completeness", "category": "ended-by-crash"},
    ]
    # One finding per ending: no trial has a finding from both checks.
    assert {i["trial_id"] for i in completeness["findings"]}.isdisjoint(
        {i["trial_id"] for i in termination["findings"]}
    )
    run = document["integrity"]["run"]
    assert run["test_system_status"] == "ERROR"
    assert run["percentage"] == pytest.approx(100 / 3)


def test_referrals_change_neither_success_nor_percentage(tmp_path: Path) -> None:
    """The same request with and without the two endings: termination reads the same."""
    plain = _request("timeout-single-report")
    plain["integrity"]["trials"] = [
        trial for trial in plain["integrity"]["trials"] if trial["termination"] == "completed"
    ]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_referrals = _run_request(_request("timeout-single-report"), tmp_path / "a")
    without = _run_request(plain, tmp_path / "b")
    one, two = _check(with_referrals), _check(without)
    assert (one["success"], one["percentage"], one["findings"]) == (
        two["success"],
        two["percentage"],
        two["findings"],
    )
    assert len(one["referrals"]) == 2
    assert two["referrals"] == []


def test_a_timeout_with_a_bad_stop_reason_still_has_one_finding(tmp_path: Path) -> None:
    request = _request("timeout-single-report")
    request["integrity"]["evidence"]["termination"]["trials"].append(
        {"id": "trial-timeout", "stop_reason": "exploded"}
    )
    document = _run_request(request, tmp_path)
    assert _check(document)["findings"] == []
    mine = [
        item
        for check in _checks(document)
        for item in check["findings"]
        if item["trial_id"] == "trial-timeout"
    ]
    assert [item["category"] for item in mine] == ["ended-by-timeout"]


def test_a_request_without_termination_evidence_is_not_applicable(tmp_path: Path) -> None:
    request = _request("clean")
    del request["integrity"]["evidence"]
    document = _run_request(request, tmp_path)
    check = _check(document)
    assert check["applicable"] is False
    assert check["referrals"] == []
    assert base._validate(document) == []


def test_a_request_without_an_allowed_list_uses_the_default(tmp_path: Path) -> None:
    request = _request("findings")
    del request["integrity"]["evidence"]["termination"]["allowed_stop_reasons"]
    check = _check(_run_request(request, tmp_path))
    assert "disallowed-stop-reason" in _categories(check)
    assert "unknown-stop-reason" in _categories(check)


def test_the_request_path_does_not_map_runner_words(tmp_path: Path) -> None:
    """Stop reasons in a request are already the contract's: non_finite_state is unknown there,
    as in the contract's findings example."""
    check = _check(_run_request(_request("findings"), tmp_path))
    assert ("unknown-stop-reason", "trial-unknown") in [
        (i["category"], i["trial_id"]) for i in check["findings"]
    ]


# The contract's reference rules, against ours.


def _random_request(rng: random.Random) -> dict:
    n = rng.randint(0, 6)
    names = sorted(VOCABULARY)
    trials = [
        {"id": f"t{i}", "termination": rng.choice(["completed"] * 4 + ["timeout", "crash"])}
        for i in range(n)
    ]
    evidence_trials = []
    for trial in trials:
        if rng.random() < 0.15:
            continue
        entry: dict = {"id": trial["id"]}
        if rng.random() < 0.85:
            entry["stop_reason"] = rng.choice(names + ["bogus", "non_finite_state"])
        if rng.random() < 0.4:
            entry["manifest_stop_reason"] = rng.choice(names)
        evidence_trials.append(entry)
    allowed = rng.sample(names, rng.randint(1, len(names)))
    return {
        "trials": trials,
        "evidence": {"termination": {"allowed_stop_reasons": allowed, "trials": evidence_trials}},
    }


def test_ours_equal_the_contract_reference_rules() -> None:
    sys.path.insert(0, str(base.CONTRACT / "tests"))
    import integrity_rules

    from livingproof_evaluator_run import termination

    rng = random.Random(7)
    seen: set[str] = set()
    referred = judged_none = 0
    for _ in range(600):
        request = _random_request(rng)
        expected = integrity_rules.termination(request, VOCABULARY)
        outcome = termination.from_request(request)
        assert outcome.applicable is expected["applicable"], request
        assert outcome.findings == expected["findings"], request
        assert outcome.referrals == expected["referrals"], request
        if expected["applicable"]:
            assert outcome.percentage == pytest.approx(expected["percentage"]), request
        else:
            judged_none += 1
        referred += bool(expected["referrals"])
        seen.update(item["category"] for item in expected["findings"])
    assert seen == set(termination.CATEGORIES)
    assert referred > 50
    assert judged_none > 5


def test_left_world_from_a_route_observation_maps_to_the_contracts_left_world(
    tmp_path: Path,
) -> None:
    """Current sim-mujoco observe_route writes end='left_world' (test_walk_corner).

    That is the contract's left-world, which the default allows. An unmapped
    left_world would be reported as unknown-stop-reason, even on a clean leave.
    """
    document, check = _doctored(tmp_path, lambda folder: _set_end(folder, 1, "left_world"), REAL)
    assert check["success"] is True
    assert check["findings"] == []
    from livingproof_evaluator_run import termination

    assert termination.END_TO_STOP_REASON["left_world"] == "left-world"
    assert "left-world" in termination.DEFAULT_ALLOWED_STOP_REASONS
    assert base._validate(document) == []
