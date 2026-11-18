"""pins 1.0.0 (livingproof-evaluator-run#5).

The good fixture is the evidence folder of a real run (livingproof-verification
verify run 44253837813, Go1 playground corner-left): ``manifest.json``, the
``run-manifest.json`` beside it, and the trial file. Each doctored case changes one
recorded value (or the value the embedded lock declares) in a copy of it. The
doctored runs are synthetic: the run itself was not wrong.

Results must conform to the livingproof-evaluator v1.0.8 conformance kit, name the
declared and the recorded value, and never carry a robot verdict.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import test_completeness as base

from livingproof_evaluator_run import evaluate_evidence
from livingproof_evaluator_run.__main__ import main

GOOD = base.FIXTURES.parent / "pins" / "good"
ZERO = "0" * 64
ZERO_COMMIT = "0" * 40


def _copy(tmp_path: Path) -> Path:
    dest = tmp_path / "evidence"
    shutil.copytree(GOOD, dest)
    return dest


def _edit(path: Path, change) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _run(folder: Path, tmp_path: Path) -> dict:
    out = tmp_path / "result.json"
    assert evaluate_evidence(folder / "manifest.json", out) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def _check(document: dict, check_id: str) -> dict:
    (found,) = [c for c in document["integrity"]["checks"] if c["id"] == check_id]
    return found


def _conforming_error(document: dict) -> None:
    run = document["integrity"]["run"]
    assert run["test_system_status"] == "ERROR"
    assert run["conclusion"] == "INCONCLUSIVE"
    assert run["success"] is False
    assert "verdict" not in document
    assert "grade" not in document
    assert "verdict" not in document["integrity"]
    assert base._validate(document) == []


def test_good_run_matches_its_lock_and_lists_what_was_not_checked(tmp_path: Path) -> None:
    document = _run(GOOD, tmp_path)
    pins = _check(document, "pins")
    assert pins["version"] == "1.0.0"
    assert pins["applicable"] is True
    assert pins["success"] is True
    assert pins["percentage"] == 100
    assert pins["findings"] == []
    assert document["integrity"]["run"]["test_system_status"] == "COMPLETED"
    assert "conclusion" not in document["integrity"]["run"]
    # Today's evidence records no spec file digests and no verifier image digest.
    copy = document["descriptor"]["success_copy"]
    assert "Not checked: specs, verifier" in copy
    assert "world" in copy.split("Not checked")[0]
    assert "configuration" in copy.split("Not checked")[0]
    assert "runner" in copy.split("Not checked")[0]
    assert base._validate(document) == []


def test_completeness_is_still_reported_first(tmp_path: Path) -> None:
    document = _run(GOOD, tmp_path)
    assert [c["id"] for c in document["integrity"]["checks"]] == ["completeness", "pins"]


def _world(doc: dict) -> None:
    doc["world"]["sha256"] = ZERO


def _configuration(doc: dict) -> None:
    doc["configuration"]["sha256"] = ZERO


def _runner(doc: dict) -> None:
    doc["environment"]["runner"]["commit"] = ZERO_COMMIT


def _adapter(doc: dict) -> None:
    doc["environment"]["simulator"]["adapter_commit"] = ZERO_COMMIT


def _lock_runner(doc: dict) -> None:
    doc["lock"]["content"]["releases"]["runner"]["commit"] = ZERO_COMMIT


def _lock_world(doc: dict) -> None:
    doc["lock"]["content"]["sources"]["world"]["sha256"] = ZERO


def _lock_configuration(doc: dict) -> None:
    doc["lock"]["content"]["configurations"][0]["sha256"] = ZERO


CASES = [
    # (file, change, subject, the value the doctored side records)
    ("run-manifest.json", _world, "world", ZERO),
    ("manifest.json", _configuration, "configuration", ZERO),
    ("manifest.json", _runner, "runner", ZERO_COMMIT),
    ("manifest.json", _adapter, "runner", ZERO_COMMIT),
    ("manifest.json", _lock_runner, "runner", ZERO_COMMIT),
    ("manifest.json", _lock_world, "world", ZERO),
    ("manifest.json", _lock_configuration, "configuration", ZERO),
]


@pytest.mark.parametrize("name,change,subject,value", CASES)
def test_doctored_value_is_one_hash_mismatch_on_its_subject(
    tmp_path: Path, name: str, change, subject: str, value: str
) -> None:
    folder = _copy(tmp_path)
    _edit(folder / name, change)
    document = _run(folder, tmp_path)
    pins = _check(document, "pins")
    assert pins["success"] is False
    assert [f["subject"] for f in pins["findings"]] == [subject]
    (finding,) = pins["findings"]
    assert finding["category"] == "hash-mismatch"
    assert finding["classification"] == "test_system"
    assert "trial_id" not in finding
    assert value in finding["summary"]
    # Two of the three checkable subjects still match, of five: 2/5.
    assert pins["percentage"] == 40
    assert document["integrity"]["run"]["percentage"] == 40
    _conforming_error(document)
    # The completeness check is untouched.
    assert _check(document, "completeness")["success"] is True


def test_finding_names_the_declared_and_the_recorded_value(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", _runner)
    document = _run(folder, tmp_path)
    (finding,) = _check(document, "pins")["findings"]
    declared = json.loads((GOOD / "manifest.json").read_text())["lock"]["content"]["releases"][
        "runner"
    ]["commit"]
    assert declared in finding["summary"]
    assert ZERO_COMMIT in finding["summary"]
    assert "lock" in finding["summary"]


def test_several_differing_subjects_give_one_finding_each(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", lambda d: (_configuration(d), _runner(d), _adapter(d)))
    _edit(folder / "run-manifest.json", _world)
    document = _run(folder, tmp_path)
    pins = _check(document, "pins")
    assert sorted(f["subject"] for f in pins["findings"]) == [
        "configuration",
        "runner",
        "world",
    ]
    # No subject matches, so nothing counts toward the share.
    assert pins["percentage"] == 0
    _conforming_error(document)
    shown = document["descriptor"]["findings"]
    assert len(shown) == 3
    assert all(item["text"] for item in shown)


def test_world_without_a_recorded_digest_is_not_checked(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    (folder / "run-manifest.json").unlink()
    document = _run(folder, tmp_path)
    pins = _check(document, "pins")
    assert pins["success"] is True
    assert pins["findings"] == []
    assert "Not checked: specs, verifier, world" in document["descriptor"]["success_copy"]
    assert base._validate(document) == []


def test_run_manifest_of_another_run_is_not_used(tmp_path: Path) -> None:
    folder = _copy(tmp_path)

    def other(doc: dict) -> None:
        doc["run_id"] = "another-run"
        doc["world"]["sha256"] = ZERO

    _edit(folder / "run-manifest.json", other)
    document = _run(folder, tmp_path)
    pins = _check(document, "pins")
    assert pins["findings"] == []
    assert "Not checked: specs, verifier, world" in document["descriptor"]["success_copy"]


def test_unrecorded_configuration_and_runner_are_not_checked(tmp_path: Path) -> None:
    folder = _copy(tmp_path)

    def strip(doc: dict) -> None:
        del doc["configuration"]["sha256"]
        del doc["environment"]["runner"]["commit"]
        del doc["environment"]["simulator"]["adapter_commit"]

    _edit(folder / "manifest.json", strip)
    document = _run(folder, tmp_path)
    pins = _check(document, "pins")
    assert pins["findings"] == []
    copy = document["descriptor"]["success_copy"]
    assert copy.endswith("Not checked: specs, runner, verifier, configuration.") or (
        "Not checked: specs, runner, verifier, configuration" in copy
    )


def test_a_lock_that_declares_nothing_for_a_subject_is_not_checked(tmp_path: Path) -> None:
    folder = _copy(tmp_path)

    def strip(doc: dict) -> None:
        content = doc["lock"]["content"]
        content["world"].pop("sha256")
        del content["sources"]

    _edit(folder / "manifest.json", strip)
    document = _run(folder, tmp_path)
    assert _check(document, "pins")["findings"] == []
    assert "world" in document["descriptor"]["success_copy"].split("Not checked")[1]


def test_manifest_without_an_embedded_lock_has_nothing_to_compare(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    assert evaluate_evidence(base.GOOD, out) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    pins = _check(document, "pins")
    assert pins["applicable"] is False
    assert pins["success"] is True
    assert "percentage" not in pins
    assert pins["findings"] == []
    # An inapplicable check does not lower the run percentage.
    assert document["integrity"]["run"]["percentage"] == 100
    assert base._validate(document) == []


def test_run_percentage_is_the_minimum_over_the_applicable_checks(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", _runner)
    (folder / "trials" / "trial-01.json").write_text("{}\n")  # completeness: digest mismatch
    document = _run(folder, tmp_path)
    assert _check(document, "completeness")["percentage"] == 0
    assert _check(document, "pins")["percentage"] == 40
    assert document["integrity"]["run"]["percentage"] == 0
    _conforming_error(document)
    assert len(document["descriptor"]["findings"]) == 2


def test_cli_reports_a_doctored_run(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", _configuration)
    out = tmp_path / "result.json"
    assert main([str(folder / "manifest.json"), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert [f["subject"] for f in _check(document, "pins")["findings"]] == ["configuration"]
    _conforming_error(document)


def test_descriptor_text_stays_within_the_contract_limits(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "manifest.json", lambda d: (_configuration(d), _runner(d), _adapter(d)))
    _edit(folder / "run-manifest.json", _world)
    descriptor = _run(folder, tmp_path)["descriptor"]
    assert len(descriptor["details_copy"]) <= 1000
    assert all(len(item["text"]) <= 280 for item in descriptor["findings"])


# The contract's own examples carry manifest and lock pins as sha256 values.
EXAMPLES = base.CONTRACT / "examples" / "integrity"


def _example(name: str, tmp_path: Path) -> dict:
    source = tmp_path / "request.json"
    source.write_text((EXAMPLES / name / "request.json").read_text(), encoding="utf-8")
    out = tmp_path / "result.json"
    assert main([str(source), "--out", str(out)]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["pins", "pins-partial"])
def test_contract_pins_examples_give_the_example_findings(tmp_path: Path, name: str) -> None:
    expected = json.loads((EXAMPLES / name / "result.json").read_text())
    want = [c for c in expected["integrity"]["checks"] if c["id"] == "pins"][0]
    document = _example(name, tmp_path)
    got = _check(document, "pins")
    assert got["success"] is False
    assert got["percentage"] == want["percentage"]
    assert [f["subject"] for f in got["findings"]] == [f["subject"] for f in want["findings"]]
    assert all(f["category"] == "hash-mismatch" for f in got["findings"])
    _conforming_error(document)


def test_contract_clean_example_has_matching_pins(tmp_path: Path) -> None:
    document = _example("clean", tmp_path)
    got = _check(document, "pins")
    assert got["success"] is True
    assert got["percentage"] == 100
    assert document["integrity"]["run"]["test_system_status"] == "COMPLETED"
    assert base._validate(document) == []


def test_request_without_pins_has_nothing_to_compare(tmp_path: Path) -> None:
    request = json.loads((EXAMPLES / "clean" / "request.json").read_text())
    del request["integrity"]["manifest"]["pins"]
    del request["integrity"]["lock"]["pins"]
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert main([str(source), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert _check(document, "pins")["applicable"] is False
    assert base._validate(document) == []


def test_request_with_one_side_of_a_pin_missing_is_not_checked(tmp_path: Path) -> None:
    request = json.loads((EXAMPLES / "clean" / "request.json").read_text())
    del request["integrity"]["manifest"]["pins"]["verifier"]
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert main([str(source), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    pins = _check(document, "pins")
    assert pins["success"] is True
    assert "Not checked: verifier" in document["descriptor"]["success_copy"]
