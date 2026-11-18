"""Reviewer coverage for pins 1.0.0 (livingproof-evaluator-run#5, PR 9).

Scripted from Vera's hand probes at head 4e895df. Two gaps found in review were first recorded
here as strict xfails and are fixed now: (a) a recorded value with a control character or < >
is shown escaped, so the result conforms, and (b) a check that compared nothing is not
applicable. The markers are gone; both tests pass as plain tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_completeness as base
from test_pins import GOOD, ZERO, _check, _copy, _edit, _run, _world

WORLD = json.loads((GOOD / "run-manifest.json").read_text())["world"]["sha256"]


def _result(folder: Path, tmp_path: Path) -> tuple[dict, dict]:
    document = _run(folder, tmp_path)
    return document, _check(document, "pins")


@pytest.mark.parametrize(
    "content",
    ["not json {", "", "[1, 2]", "null", '{"run_id": 7}'],
    ids=["garbage", "empty", "list", "null", "bad-run-id"],
)
def test_unreadable_run_manifest_leaves_world_not_checked(tmp_path: Path, content: str) -> None:
    folder = _copy(tmp_path)
    (folder / "run-manifest.json").write_text(content, encoding="utf-8")
    document, pins = _result(folder, tmp_path)
    assert pins["success"] is True
    assert pins["findings"] == []
    assert "Not checked: specs, verifier, world" in document["descriptor"]["success_copy"]
    assert base._validate(document) == []


def test_run_manifest_world_that_is_not_an_object_is_not_checked(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d.update(world="abc"))
    document, pins = _result(folder, tmp_path)
    assert pins["findings"] == []
    assert "world" in document["descriptor"]["success_copy"].split("Not checked")[1]


def test_missing_run_id_never_pairs_the_run_manifest(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", lambda d: d.pop("run_id"))
    _edit(folder / "run-manifest.json", lambda d: (d.pop("run_id"), _world(d)))
    _, pins = _result(folder, tmp_path)
    # Two documents that both lack a run id are not "the same run".
    assert pins["findings"] == []


@pytest.mark.parametrize("value", [12345, "", None, ["x"]], ids=["int", "empty", "null", "list"])
def test_a_recorded_digest_that_is_not_text_is_not_checked(tmp_path: Path, value) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256=value))
    document, pins = _result(folder, tmp_path)
    assert pins["findings"] == []
    assert "Not checked: specs, verifier, world" in document["descriptor"]["success_copy"]


def test_legacy_lock_world_digest_is_used_when_sources_are_absent(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", lambda d: d["lock"]["content"].pop("sources"))
    _, pins = _result(folder, tmp_path)
    assert pins["success"] is True

    _edit(folder / "manifest.json", lambda d: d["lock"]["content"]["world"].update(sha256=ZERO))
    document, pins = _result(folder, tmp_path)
    assert [f["subject"] for f in pins["findings"]] == ["world"]
    assert base._validate(document) == []


def test_lock_sources_world_wins_over_the_legacy_lock_world(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", lambda d: d["lock"]["content"]["world"].update(sha256=ZERO))
    _, pins = _result(folder, tmp_path)
    # sources.world still matches what the run recorded.
    assert pins["findings"] == []


def test_a_world_digest_in_manifest_json_is_preferred_to_the_sibling(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", lambda d: d["world"].update(sha256=WORLD))
    _edit(folder / "run-manifest.json", _world)
    _, pins = _result(folder, tmp_path)
    assert pins["findings"] == []

    _edit(folder / "manifest.json", lambda d: d["world"].update(sha256=ZERO))
    document, pins = _result(folder, tmp_path)
    (finding,) = pins["findings"]
    assert "manifest world.sha256" in finding["summary"]
    assert base._validate(document) == []


def test_runner_and_adapter_both_differing_is_still_one_finding(tmp_path: Path) -> None:
    folder = _copy(tmp_path)

    def both(doc: dict) -> None:
        doc["environment"]["runner"]["commit"] = "0" * 40
        doc["environment"]["simulator"]["adapter_commit"] = "1" * 40

    _edit(folder / "manifest.json", both)
    document, pins = _result(folder, tmp_path)
    (finding,) = pins["findings"]
    assert finding["subject"] == "runner"
    assert "0" * 40 in finding["summary"] and "1" * 40 in finding["summary"]
    assert base._validate(document) == []


def test_a_recorded_adapter_commit_alone_is_enough_to_check_the_runner(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", lambda d: d["environment"]["runner"].pop("commit"))
    _, pins = _result(folder, tmp_path)
    assert pins["success"] is True

    _edit(
        folder / "manifest.json",
        lambda d: d["environment"]["simulator"].update(adapter_commit="0" * 40),
    )
    _, pins = _result(folder, tmp_path)
    assert [f["subject"] for f in pins["findings"]] == ["runner"]


@pytest.mark.parametrize("bad", ["abc\n", "a\tb", "<b>x</b>", "a\x00b"], ids=repr)
def test_odd_characters_in_a_recorded_value_still_give_a_conforming_result(
    tmp_path: Path, bad: str
) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256=bad))
    document, pins = _result(folder, tmp_path)
    assert [f["subject"] for f in pins["findings"]] == ["world"]
    assert base._validate(document) == []


@pytest.mark.parametrize("case", ["empty-lock", "empty-lock-fields", "nothing-recorded"])
def test_a_check_that_compared_nothing_is_not_a_pass(tmp_path: Path, case: str) -> None:
    folder = _copy(tmp_path)
    if case == "empty-lock":
        _edit(folder / "manifest.json", lambda d: d["lock"].update(content={}))
    elif case == "empty-lock-fields":
        _edit(
            folder / "manifest.json",
            lambda d: d["lock"]["content"].update(
                releases={}, configurations=[], sources={}, world={}
            ),
        )
    else:

        def strip(doc: dict) -> None:
            del doc["configuration"]["sha256"]
            del doc["environment"]["runner"]["commit"]
            del doc["environment"]["simulator"]["adapter_commit"]

        _edit(folder / "manifest.json", strip)
        (folder / "run-manifest.json").unlink()
    document, pins = _result(folder, tmp_path)
    assert pins["applicable"] is False
    assert base._validate(document) == []


def test_a_check_that_compared_nothing_says_what_was_not_checked(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", lambda d: d["lock"].update(content={}))
    document, pins = _result(folder, tmp_path)
    assert pins["applicable"] is False
    assert "percentage" not in pins
    assert pins["findings"] == []
    copy = document["descriptor"]["success_copy"]
    assert "Not checked: specs, runner, verifier, world, configuration" in copy
    assert {i["reason"] for i in pins["not_checked"]} == {"not-declared"}
    assert len(pins["not_checked"]) == 5
    assert document["integrity"]["run"]["percentage"] == 100
    assert base._validate(document) == []
