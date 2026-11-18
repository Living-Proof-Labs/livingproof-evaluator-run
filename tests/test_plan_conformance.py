"""plan-conformance 1.0.0 (livingproof-evaluator-run#6).

Fail-first coverage for the third Run Integrity check: the plan, the trials and the lock agree
on the trial count and the command speed, ``trials.results[].index`` is exactly 1 to N, and each
path is ``trials/trial-NN.json`` for its own index. The contract is livingproof-evaluator v1.1.0
(``schema/integrity/checks/plan-conformance.schema.json``, ``docs/run-integrity.md``). Its
reference rules (``tests/integrity_rules.py``) are run against ours, case by case.

Fixtures under ``tests/fixtures/plan-conformance``:

* ``good``: three trials, a plan and a lock that agree. Synthetic, in the shape of the real
  ``tests/fixtures/pins/good`` run (verify run 44253837813), which is also checked here.
* ``findings``: the run the check would have caught. Synthetic, one of every category. It is the
  contract's ``examples/integrity/plan-conformance/findings`` case written as evidence 2.0.0.
* ``preconditions-unmet``: a run that ran no trials, as livingproof-sim-mujoco records it.
"""

from __future__ import annotations

import copy
import json
import random
import shutil
import sys
from pathlib import Path

import pytest
import test_completeness as base

from livingproof_evaluator_run import evaluate, evaluate_evidence
from livingproof_evaluator_run.__main__ import main

FIXTURES = base.FIXTURES.parent / "plan-conformance"
GOOD = FIXTURES / "good"
FINDINGS = FIXTURES / "findings"
UNMET = FIXTURES / "preconditions-unmet"
REAL = base.FIXTURES.parent / "pins" / "good"
EXAMPLES = base.CONTRACT / "examples" / "integrity" / "plan-conformance"
CHECK = "plan-conformance"


def _copy(source: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "evidence"
    shutil.copytree(source, dest)
    return dest


def _edit(folder: Path, change) -> None:
    path = folder / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _run(folder: Path, tmp_path: Path) -> dict:
    out = tmp_path / "result.json"
    assert evaluate_evidence(folder / "manifest.json", out) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def _checks(document: dict) -> list[dict]:
    return document["integrity"]["checks"]


def _check(document: dict) -> dict:
    (found,) = [c for c in _checks(document) if c["id"] == CHECK]
    return found


def _categories(check: dict) -> list[str]:
    return [item["category"] for item in check["findings"]]


def _run_check(source: Path, tmp_path: Path, change=None) -> tuple[dict, dict]:
    folder = _copy(source, tmp_path)
    if change is not None:
        _edit(folder, change)
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


# The doctored cases. Each edits one thing in a copy of the good run (3 trials, speed 0.5, a lock
# block): subjects are 2 counts + the lock's count + the speed + 3 indexes = 7.


def _more_trials_recorded(doc: dict) -> None:
    doc["trials"]["count"] = 4


def _lock_count(doc: dict) -> None:
    doc["lock"]["content"]["plan"]["trials"]["count"] = 4


def _lock_speed(doc: dict) -> None:
    doc["lock"]["content"]["plan"]["command_speed"] = 1.0


def _drop_entry(doc: dict) -> None:
    del doc["trials"]["results"][1]
    doc["trials"]["count"] = 3


def _duplicate_entry(doc: dict) -> None:
    doc["trials"]["results"].append(copy.deepcopy(doc["trials"]["results"][1]))


def _wrong_path(doc: dict) -> None:
    doc["trials"]["results"][2]["path"] = "trials/trial-02.json"


def _noncanonical_path(doc: dict) -> None:
    """The right file under a name that is not trials/trial-NN.json: only this check objects."""
    doc["trials"]["results"][2]["path"] = "./trials/trial-03.json"


def _extra_trial(doc: dict) -> None:
    extra = copy.deepcopy(doc["trials"]["results"][2])
    extra["index"] = 4
    extra["path"] = "trials/trial-04.json"
    doc["trials"]["results"].append(extra)
    doc["trials"]["count"] = 4


def _zero_index(doc: dict) -> None:
    doc["trials"]["results"][0]["index"] = 0


def _plan_count(doc: dict) -> None:
    doc["plan"]["trials"]["count"] = 4


CASES = {
    "plan-count-vs-trials-count": (
        _more_trials_recorded,
        [("trial-count-mismatch", "The plan has 3 trials and trials.count is 4.")],
        100 * 6 / 7,
    ),
    "plan-count-vs-lock": (
        _lock_count,
        [("trial-count-mismatch", "The plan has 3 trials and the lock's plan trial count is 4.")],
        100 * 6 / 7,
    ),
    "command-speed-vs-lock": (
        _lock_speed,
        [("command-speed-mismatch", "The plan's command_speed is 0.5 and the lock's is 1.0.")],
        100 * 6 / 7,
    ),
    "missing-index": (
        _drop_entry,
        [
            (
                "trial-count-mismatch",
                "The plan has 3 trials and the number of trials.results entries is 2.",
            ),
            ("index-missing", "No trials.results entry has index 2."),
        ],
        100 * 5 / 7,
    ),
    "duplicate-index": (
        _duplicate_entry,
        [
            (
                "trial-count-mismatch",
                "The plan has 3 trials and the number of trials.results entries is 4.",
            ),
            ("index-duplicate", "2 trials.results entries have index 2."),
        ],
        100 * 5 / 7,
    ),
    "wrong-path": (
        _wrong_path,
        [
            (
                "path-mismatch",
                "The entry for index 3 has path trials/trial-02.json, not trials/trial-03.json.",
            )
        ],
        100 * 6 / 7,
    ),
    "extra-trial-beyond-the-plan": (
        _extra_trial,
        [
            ("trial-count-mismatch", "The plan has 3 trials and trials.count is 4."),
            (
                "trial-count-mismatch",
                "The plan has 3 trials and the number of trials.results entries is 4.",
            ),
            ("index-out-of-range", "A trials.results entry has index 4, outside 1 to 3."),
        ],
        100 * 5 / 8,
    ),
    "index-zero": (
        _zero_index,
        [
            ("index-missing", "No trials.results entry has index 1."),
            ("index-out-of-range", "A trials.results entry has index 0, outside 1 to 3."),
        ],
        100 * 6 / 8,
    ),
    "plan-count-vs-everything": (
        _plan_count,
        [
            ("trial-count-mismatch", "The plan has 4 trials and trials.count is 3."),
            (
                "trial-count-mismatch",
                "The plan has 4 trials and the number of trials.results entries is 3.",
            ),
            ("trial-count-mismatch", "The plan has 4 trials and the lock's plan trial count is 3."),
            ("index-missing", "No trials.results entry has index 4."),
        ],
        100 * 4 / 8,
    ),
}


def test_good_run_conforms(tmp_path: Path) -> None:
    document, check = _run_check(GOOD, tmp_path)
    assert check == {
        "id": CHECK,
        "version": "1.1.0",
        "applicable": True,
        "success": True,
        "percentage": 100,
        "findings": [],
        "not_checked": [],
    }
    assert document["integrity"]["run"]["test_system_status"] == "COMPLETED"
    assert "conclusion" not in document["integrity"]["run"]
    assert base._validate(document) == []


def test_the_summary_says_whether_the_lock_was_compared(tmp_path: Path) -> None:
    document, _ = _run_check(GOOD, tmp_path / "with", None)
    assert (
        "The plan, the trials and the lock agree on the trial count."
        in (document["descriptor"]["success_copy"])
    )
    assert "lock trial count" not in document["descriptor"]["success_copy"]
    document, _ = _run_check(base.FIXTURES / "good", tmp_path / "without", None)
    copy_ = document["descriptor"]["success_copy"]
    assert "The plan and the trials agree on the trial count." in copy_
    assert "the lock agree" not in copy_
    assert "Not checked: lock trial count, lock command speed." in copy_


def test_real_run_conforms(tmp_path: Path) -> None:
    """The evidence folder of a real run: no command_speed in its plan, a lock that agrees."""
    document, check = _run_check(REAL, tmp_path)
    assert check["applicable"] is True
    assert check["success"] is True
    assert check["percentage"] == 100
    assert check["findings"] == []
    assert base._validate(document) == []


def test_checks_are_reported_in_order(tmp_path: Path) -> None:
    document, _ = _run_check(GOOD, tmp_path)
    assert [c["id"] for c in _checks(document)] == [
        "completeness",
        "pins",
        CHECK,
        "termination",
        "recording",
    ]


def test_completeness_fixture_without_a_lock_block_passes(tmp_path: Path) -> None:
    """tests/fixtures/completeness/good has a plan and no lock block: the lock comparisons are
    skipped, and they are not counted."""
    document, check = _run_check(base.FIXTURES / "good", tmp_path)
    assert check["applicable"] is True
    assert check["success"] is True
    assert check["percentage"] == 100
    assert check["findings"] == []
    assert base._validate(document) == []

    def mismatch(doc: dict) -> None:
        doc["trials"]["count"] = 3

    _, check = _run_check(base.FIXTURES / "good", tmp_path / "again", mismatch)
    # Two counts and two indexes; the missing lock adds no subject and no finding.
    assert _categories(check) == ["trial-count-mismatch"]
    assert check["percentage"] == 75


@pytest.mark.parametrize("name", sorted(CASES))
def test_doctored_run_reports_exactly_what_changed(name: str, tmp_path: Path) -> None:
    change, expected, percentage = CASES[name]
    document, check = _run_check(GOOD, tmp_path, change)
    assert [(i["category"], i["summary"]) for i in check["findings"]] == expected
    assert check["applicable"] is True
    assert check["success"] is False
    assert check["percentage"] == pytest.approx(percentage)
    for item in check["findings"]:
        assert item["classification"] == "test_system"
        # The findings carry no trial id: a missing trial file stays a completeness finding.
        assert set(item) == {"category", "classification", "summary"}
    _conforming_error(document)
    # The run reads the lowest applicable check; completeness may be lower for the same edit.
    applicable = [c["percentage"] for c in _checks(document) if c["applicable"]]
    assert document["integrity"]["run"]["percentage"] == pytest.approx(min(applicable))
    assert document["integrity"]["run"]["percentage"] <= percentage


def test_every_category_has_a_doctored_case() -> None:
    schema = json.loads(
        (base.CONTRACT / "schema/integrity/checks/plan-conformance.schema.json").read_text()
    )
    enum = set(schema["properties"]["findings"]["items"]["properties"]["category"]["enum"])
    covered = {category for _, expected, _ in CASES.values() for category, _ in expected}
    assert (
        covered
        == enum
        == {
            "trial-count-mismatch",
            "command-speed-mismatch",
            "index-missing",
            "index-duplicate",
            "index-out-of-range",
            "path-mismatch",
        }
    )


def test_findings_fixture_is_the_contract_example(tmp_path: Path) -> None:
    """The doctored run with every category reads 20: 2 of its 10 subjects are clean."""
    document = _run(FINDINGS, tmp_path)
    check = _check(document)
    expected = json.loads((EXAMPLES / "findings" / "result.json").read_text())["integrity"][
        "checks"
    ][0]
    assert check == {**expected, "version": "1.1.0", "not_checked": []}
    assert check["percentage"] == 20
    assert sorted(set(_categories(check))) == sorted(
        [
            "trial-count-mismatch",
            "command-speed-mismatch",
            "index-missing",
            "index-duplicate",
            "index-out-of-range",
            "path-mismatch",
        ]
    )
    _conforming_error(document)
    assert document["integrity"]["run"]["percentage"] == 20


def test_a_missing_trial_file_is_not_repeated(tmp_path: Path) -> None:
    """The completeness fixture with a missing trial file is a completeness finding only."""
    document = _run(base.MISSING.parent, tmp_path)
    assert [c["id"] for c in _checks(document) if c["findings"]] == ["completeness"]
    check = _check(document)
    assert check["success"] is True
    assert check["findings"] == []


def test_a_hash_mismatch_is_not_repeated(tmp_path: Path) -> None:
    folder = _copy(GOOD, tmp_path)
    (folder / "trials" / "trial-02.json").write_text("{}\n")
    document = _run(folder, tmp_path)
    assert _check(document)["findings"] == []
    assert [c["id"] for c in _checks(document) if c["findings"]] == ["completeness"]


def test_plan_conformance_findings_do_not_touch_trial_statuses(tmp_path: Path) -> None:
    document, check = _run_check(GOOD, tmp_path, _noncanonical_path)
    assert _categories(check) == ["path-mismatch"]
    assert [t["test_system_status"] for t in document["integrity"]["trials"]] == ["COMPLETED"] * 3
    assert document["integrity"]["run"]["test_system_status"] == "ERROR"


# A run whose preconditions are unmet runs no trials. The check is not applicable.


def test_unmet_preconditions_are_not_applicable(tmp_path: Path) -> None:
    document = _run(UNMET, tmp_path)
    check = _check(document)
    assert check == {
        "id": CHECK,
        "version": "1.1.0",
        "applicable": False,
        "success": True,
        "findings": [],
        "not_checked": [],
    }
    # Not an error: the check itself neither fails the run nor lowers its percentage.
    assert base._validate(document) == []


def test_the_same_manifest_with_the_precondition_met_is_checked(
    tmp_path: Path,
) -> None:
    """With the precondition met the same manifest has empty results and the plan wants 3."""

    def met(doc: dict) -> None:
        doc["preconditions"][0]["met"] = True

    _, check = _run_check(UNMET, tmp_path, met)
    assert check["applicable"] is True
    assert check["success"] is False
    assert _categories(check) == [
        "trial-count-mismatch",
        "index-missing",
        "index-missing",
        "index-missing",
    ]


def test_an_unmet_precondition_that_is_not_required_does_not_stop_the_run(tmp_path: Path) -> None:
    def optional(doc: dict) -> None:
        doc["preconditions"][0]["required"] = False

    _, check = _run_check(UNMET, tmp_path, optional)
    assert check["applicable"] is True


def test_the_unmet_run_stays_not_applicable_with_other_preconditions_met(tmp_path: Path) -> None:
    def many(doc: dict) -> None:
        doc["preconditions"].insert(0, {"name": "fits_width", "met": True, "detail": "ok"})

    _, check = _run_check(UNMET, tmp_path, many)
    assert check["applicable"] is False


# Evidence that is missing or malformed. The check fails closed or says it did not look: it never
# reports a pass nothing earned and never raises.


def test_a_plan_without_a_trial_count_is_not_applicable(tmp_path: Path) -> None:
    def no_plan_count(doc: dict) -> None:
        doc["plan"] = {}

    document, check = _run_check(GOOD, tmp_path, no_plan_count)
    assert check["applicable"] is False
    assert check["findings"] == []
    assert "percentage" not in check
    assert base._validate(document) == []


def test_results_that_are_not_a_list_are_not_applicable(tmp_path: Path) -> None:
    def broken(doc: dict) -> None:
        doc["trials"]["results"] = {"1": "trials/trial-01.json"}

    document, check = _run_check(GOOD, tmp_path, broken)
    assert check["applicable"] is False
    assert base._validate(document) == []


@pytest.mark.parametrize("bad", ["2", 2.0, True, None, [2]])
def test_an_index_that_is_not_an_integer_is_out_of_range(bad: object, tmp_path: Path) -> None:
    def broken(doc: dict) -> None:
        doc["trials"]["results"][1]["index"] = bad

    document, check = _run_check(GOOD, tmp_path, broken)
    assert check["applicable"] is True
    assert "index-out-of-range" in _categories(check)
    assert "index-missing" in _categories(check)
    assert check["success"] is False
    _conforming_error(document)


@pytest.mark.parametrize("bad", [None, "", 3, ["trials/trial-02.json"]])
def test_a_path_that_is_not_text_is_a_path_mismatch(bad: object, tmp_path: Path) -> None:
    def broken(doc: dict) -> None:
        doc["trials"]["results"][1]["path"] = bad

    document, check = _run_check(GOOD, tmp_path, broken)
    assert _categories(check) == ["path-mismatch"]
    _conforming_error(document)


def test_an_entry_that_is_not_an_object_is_out_of_range(tmp_path: Path) -> None:
    def broken(doc: dict) -> None:
        doc["trials"]["results"].append("trials/trial-04.json")
        doc["trials"]["count"] = 4

    document, check = _run_check(GOOD, tmp_path, broken)
    assert "index-out-of-range" in _categories(check)
    _conforming_error(document)


def test_a_lock_block_without_a_plan_count_makes_no_lock_comparison(tmp_path: Path) -> None:
    def no_lock_plan(doc: dict) -> None:
        doc["lock"]["content"]["plan"] = {}

    _, check = _run_check(GOOD, tmp_path, no_lock_plan)
    assert check["success"] is True
    assert check["percentage"] == 100


def test_command_speed_is_compared_only_when_both_sides_record_one(tmp_path: Path) -> None:
    """The contract's rule: both the plan and the lock must carry one."""

    def plan_only(doc: dict) -> None:
        del doc["lock"]["content"]["plan"]["command_speed"]

    def lock_only(doc: dict) -> None:
        del doc["plan"]["command_speed"]

    for change in (plan_only, lock_only):
        _, check = _run_check(GOOD, tmp_path / change.__name__, change)
        assert check["success"] is True
        assert check["percentage"] == 100


@pytest.mark.parametrize("bad", [True, 0, -1, "0.5", [0.5]])
def test_a_command_speed_that_is_not_a_positive_number_is_a_mismatch(
    bad: object, tmp_path: Path
) -> None:
    """Both sides record one, so they are compared; a boolean, zero or text is not a speed."""

    def broken(doc: dict) -> None:
        doc["plan"]["command_speed"] = bad

    document, check = _run_check(GOOD, tmp_path, broken)
    assert _categories(check) == ["command-speed-mismatch"]
    _conforming_error(document)


def test_a_boolean_is_not_equal_to_the_speed_one(tmp_path: Path) -> None:
    def one(doc: dict) -> None:
        doc["plan"]["command_speed"] = True
        doc["lock"]["content"]["plan"]["command_speed"] = 1

    _, check = _run_check(GOOD, tmp_path, one)
    assert _categories(check) == ["command-speed-mismatch"]


def test_a_null_command_speed_is_no_speed(tmp_path: Path) -> None:
    def null(doc: dict) -> None:
        doc["plan"]["command_speed"] = None

    _, check = _run_check(GOOD, tmp_path, null)
    assert check["success"] is True
    assert check["percentage"] == 100


@pytest.mark.parametrize("entry", [{"name": "scenario_supported"}, {"met": None}, {"met": 0}])
def test_only_an_explicit_false_precondition_stops_the_run(entry: dict, tmp_path: Path) -> None:
    def odd(doc: dict) -> None:
        doc["preconditions"] = [entry]

    _, check = _run_check(GOOD, tmp_path, odd)
    assert check["applicable"] is True
    assert check["success"] is True


def test_integer_and_float_speeds_compare_by_value(tmp_path: Path) -> None:
    def same(doc: dict) -> None:
        doc["plan"]["command_speed"] = 1
        doc["lock"]["content"]["plan"]["command_speed"] = 1.0

    _, check = _run_check(GOOD, tmp_path, same)
    assert check["success"] is True


def test_text_copied_from_evidence_is_shown_escaped(tmp_path: Path) -> None:
    def hostile(doc: dict) -> None:
        doc["trials"]["results"][1]["path"] = "<b>trials</b>\n" + "x" * 300

    document, check = _run_check(GOOD, tmp_path, hostile)
    assert _categories(check) == ["path-mismatch"]
    shown = document["descriptor"]["findings"]
    assert all("<" not in item["text"] and "\n" not in item["text"] for item in shown)
    assert len(document["descriptor"]["details_copy"]) <= 1000
    _conforming_error(document)


def test_descriptor_findings_name_no_trial(tmp_path: Path) -> None:
    document, _ = _run_check(GOOD, tmp_path, _noncanonical_path)
    (item,) = document["descriptor"]["findings"]
    assert "trial" not in item
    assert item["severity"] == "Needs attention"
    assert "./trials/trial-03.json" in item["text"]


def test_a_large_plan_keeps_every_finding_and_a_valid_descriptor(tmp_path: Path) -> None:
    def huge(doc: dict) -> None:
        doc["plan"]["trials"]["count"] = 120
        doc["trials"]["count"] = 120

    document, check = _run_check(GOOD, tmp_path, huge)
    assert _categories(check).count("index-missing") == 117
    assert len(document["descriptor"]["findings"]) == 50
    _conforming_error(document)


def test_command_line_reports_plan_conformance(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    assert main([str(FINDINGS / "manifest.json"), "--out", str(out)]) == 0
    check = _check(json.loads(out.read_text(encoding="utf-8")))
    assert check["applicable"] is True
    assert check["percentage"] == 20


def test_the_registry_and_the_enum_name_this_check_and_version() -> None:
    registry = json.loads((base.CONTRACT / "schema/integrity/checks/registry.json").read_text())
    text = json.dumps(registry)
    assert '"plan-conformance"' in text
    from livingproof_evaluator_run import plan_conformance

    assert plan_conformance.PLAN_CONFORMANCE_ID == CHECK
    assert plan_conformance.PLAN_CONFORMANCE_VERSION == "1.1.0"
    schema = json.loads(
        (base.CONTRACT / "schema/integrity/checks/plan-conformance.schema.json").read_text()
    )
    assert plan_conformance.PLAN_CONFORMANCE_VERSION in schema["properties"]["version"]["enum"]
    enum = schema["properties"]["findings"]["items"]["properties"]["category"]["enum"]
    assert sorted(plan_conformance.CATEGORIES) == sorted(enum)


# The request path: evidence['plan-conformance'] on a livingproof-evaluator-request.


def _request(name: str) -> dict:
    return json.loads((EXAMPLES / name / "request.json").read_text(encoding="utf-8"))


def _run_request(request: dict, tmp_path: Path) -> dict:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate(source, out) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def _as_1_1_0(check: dict, request: dict) -> dict:
    """The contract keeps its 1.0.0 examples as published. A 1.0.0 check read as 1.1.0 changes
    its version and gains the ``not_checked`` the reference rule derives from the request."""
    if check["version"] != "1.0.0":
        return check
    sys.path.insert(0, str(base.CONTRACT / "tests"))
    import integrity_rules

    rule = integrity_rules.plan_conformance(request["integrity"], "1.1.0")
    return {**check, "version": "1.1.0", "not_checked": rule["not_checked"]}


@pytest.mark.parametrize(
    "name", ["conformant", "findings", "preconditions-unmet", "no-lock", "lock-checked"]
)
def test_the_contract_examples_give_the_contract_check(name: str, tmp_path: Path) -> None:
    request = _request(name)
    document = _run_request(request, tmp_path)
    expected = json.loads((EXAMPLES / name / "result.json").read_text(encoding="utf-8"))
    want = [c for c in _checks(expected) if c["id"] == CHECK][0]
    assert _check(document) == _as_1_1_0(want, request)
    assert base._validate(document) == []


@pytest.mark.parametrize("name", ["conformant", "findings", "preconditions-unmet"])
def test_version_1_0_0_is_still_selectable_and_gives_the_published_example(name: str) -> None:
    from livingproof_evaluator_run import plan_conformance

    request = _request(name)
    expected = json.loads((EXAMPLES / name / "result.json").read_text(encoding="utf-8"))
    want = [c for c in _checks(expected) if c["id"] == CHECK][0]
    assert want["version"] == "1.0.0"
    outcome = plan_conformance.from_request(request["integrity"], "1.0.0")
    assert outcome.version == "1.0.0"
    assert outcome.applicable is want["applicable"]
    assert outcome.findings == want["findings"]
    assert outcome.not_checked is None
    if want["applicable"]:
        assert outcome.percentage == want["percentage"]


def test_a_lock_with_no_command_speed_lists_that_comparison_alone(tmp_path: Path) -> None:
    request = _request("lock-checked")
    del request["integrity"]["evidence"][CHECK]["lock"]["plan"]["command_speed"]
    check = _check(_run_request(request, tmp_path))
    assert check["not_checked"] == [{"subject": "lock-command-speed", "reason": "not-declared"}]
    assert check["applicable"] is True


def test_the_comparisons_not_made_are_not_in_the_denominator(tmp_path: Path) -> None:
    no_lock = _check(_run_request(_request("no-lock"), tmp_path))
    assert [item["subject"] for item in no_lock["not_checked"]] == [
        "lock-trial-count",
        "lock-command-speed",
    ]
    assert all(item["reason"] == "not-declared" for item in no_lock["not_checked"])


def test_the_descriptor_notes_come_from_not_checked(tmp_path: Path) -> None:
    """One 'Not checked' sentence names every subject any check left out, so a note about the
    lock does not push a sentence off the 400-character card."""
    both = _run_request(_request("no-lock"), tmp_path)["descriptor"]["success_copy"]
    assert "Not checked: lock trial count, lock command speed." in both
    request = _request("lock-checked")
    del request["integrity"]["evidence"][CHECK]["lock"]["plan"]["command_speed"]
    speed = _run_request(request, tmp_path)["descriptor"]["success_copy"]
    assert "Not checked: lock command speed." in speed
    assert "lock trial count" not in speed


def test_a_request_without_plan_conformance_evidence_is_not_applicable(tmp_path: Path) -> None:
    request = _request("conformant")
    del request["integrity"]["evidence"]
    document = _run_request(request, tmp_path)
    check = _check(document)
    assert check["applicable"] is False
    assert check["findings"] == []
    assert base._validate(document) == []


def test_a_request_with_unmet_preconditions_and_disagreeing_counts_is_not_applicable(
    tmp_path: Path,
) -> None:
    request = _request("findings")
    request["integrity"]["evidence"][CHECK]["preconditions"] = {"met": False}
    check = _check(_run_request(request, tmp_path))
    assert check["applicable"] is False
    assert check["findings"] == []


# The reference rules in the contract's tests/integrity_rules.py, against ours.


def _random_evidence(rng: random.Random) -> dict:
    planned = rng.randint(0, 6)

    def pick(value: int) -> int:
        return value if rng.random() < 0.7 else max(0, value + rng.choice([-2, -1, 1, 2]))

    indexes = list(range(1, planned + 1))
    rng.shuffle(indexes)
    indexes = indexes[: max(0, len(indexes) - rng.choice([0, 0, 1, 2]))]
    indexes += [rng.randint(-1, planned + 3) for _ in range(rng.choice([0, 0, 1, 2]))]
    rng.shuffle(indexes)
    results = [
        {
            "index": index,
            "path": f"trials/trial-{index:02d}.json" if rng.random() < 0.8 else "trials/x.json",
        }
        for index in indexes
    ]
    evidence: dict = {
        "plan": {"trial_count": planned},
        "trials": {"count": pick(planned), "results": results},
    }
    if rng.random() < 0.6:
        evidence["plan"]["command_speed"] = rng.choice([0.5, 1.0])
    if rng.random() < 0.7:
        evidence["lock"] = {"plan": {"trial_count": pick(planned)}}
        if rng.random() < 0.7:
            evidence["lock"]["plan"]["command_speed"] = rng.choice([0.5, 1.0])
    if rng.random() < 0.2:
        evidence["preconditions"] = {"met": rng.random() < 0.5}
    return evidence


@pytest.mark.parametrize("version", ["1.1.0", "1.0.0"])
def test_ours_equal_the_contract_reference_rules(version: str) -> None:
    """Each version against the reference rule of that version (the reference defaults to
    1.1.0, so the version is always passed; livingproof-evaluator#34)."""
    sys.path.insert(0, str(base.CONTRACT / "tests"))
    import integrity_rules

    from livingproof_evaluator_run import plan_conformance

    rng = random.Random(1)
    seen: set[str] = set()
    listed: set[str] = set()
    for _ in range(600):
        evidence = _random_evidence(rng)
        payload = {"evidence": {CHECK: evidence}}
        expected = integrity_rules.plan_conformance(payload, version)
        outcome = plan_conformance.from_request(payload, version)
        assert outcome is not None
        assert outcome.version == version
        assert outcome.applicable is expected["applicable"], evidence
        assert outcome.findings == expected["findings"], evidence
        assert outcome.not_checked == expected.get("not_checked"), evidence
        if expected["applicable"]:
            assert outcome.percentage == pytest.approx(expected["percentage"]), evidence
        seen.update(item["category"] for item in expected["findings"])
        listed.update(item["subject"] for item in expected.get("not_checked", []))
    assert seen == set(plan_conformance.CATEGORIES)
    assert listed == ({"lock-trial-count", "lock-command-speed"} if version != "1.0.0" else set())


def test_the_default_version_is_the_current_one_and_is_the_references_default() -> None:
    sys.path.insert(0, str(base.CONTRACT / "tests"))
    import integrity_rules

    from livingproof_evaluator_run import plan_conformance

    rng = random.Random(2)
    assert plan_conformance.PLAN_CONFORMANCE_VERSION == "1.1.0"
    for _ in range(100):
        payload = {"evidence": {CHECK: _random_evidence(rng)}}
        outcome = plan_conformance.from_request(payload)
        expected = integrity_rules.plan_conformance(payload)
        assert outcome.not_checked == expected["not_checked"]
        assert outcome.findings == expected["findings"]
