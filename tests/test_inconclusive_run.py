"""A run where no check applies is INCONCLUSIVE at result format 1.2.0 (#28).

livingproof-evaluator v1.4.0 (issue #38): when every reported check is not applicable the run is
``INCONCLUSIVE`` (status and conclusion), ``success`` false, with no ``percentage``. A run with
any applicable check reads as before: COMPLETED, or ERROR with conclusion INCONCLUSIVE. Every
document is validated against the v1.4.0 schema and checks, and against the kit's example.
"""

from __future__ import annotations

import json
from pathlib import Path

import test_completeness as base

from livingproof_evaluator_run import evaluate

KIT = base.CONTRACT
EXAMPLES = KIT / "examples" / "integrity"
FORMAT = "livingproof-evaluator-result/1.2.0"
SKIP = {"recording/findings"}  # a 1.0.0 request that this evaluator rejects as malformed


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(name: str, tmp_path: Path) -> dict:
    out = tmp_path / (name.replace("/", "_") + ".json")
    assert evaluate(EXAMPLES / name / "request.json", out) == 0
    return _load(out)


def _no_pins_to_compare(name: str) -> dict:
    """The published request with the lock declaring no pins, so pins has nothing to compare."""
    request = _load(EXAMPLES / name / "request.json")
    request["integrity"]["lock"]["pins"] = {}
    return request


def _run_request(request: dict, tmp_path: Path) -> dict:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate(source, out) == 0
    return _load(out)


def _names() -> list[str]:
    return sorted(
        path.parent.relative_to(EXAMPLES).as_posix()
        for path in EXAMPLES.rglob("request.json")
        if path.parent.relative_to(EXAMPLES).as_posix() not in SKIP
    )


def test_the_contract_is_pinned_at_v1_4_0() -> None:
    text = (base.ROOT / "tools" / "fetch_contract.py").read_text(encoding="utf-8")
    assert 'TAG = "v1.4.0"' in text
    described = (KIT / "schema" / "evaluator-result.schema.json").read_text(encoding="utf-8")
    assert "livingproof-evaluator-result/1.2.0" in described


def test_nothing_applicable_gives_the_published_inconclusive_run(tmp_path: Path) -> None:
    document = _run_request(_no_pins_to_compare("all-not-applicable"), tmp_path)
    expected = _load(EXAMPLES / "all-not-applicable" / "result.json")["integrity"]
    assert document["format"] == FORMAT
    run = document["integrity"]["run"]
    assert run == expected["run"]
    assert run["test_system_status"] == "INCONCLUSIVE"
    assert run["conclusion"] == "INCONCLUSIVE"
    assert run["success"] is False
    assert "percentage" not in run
    assert not any(check["applicable"] for check in document["integrity"]["checks"])
    assert document["integrity"]["trials"] == expected["trials"]
    assert document["descriptor"]["findings"] == []
    assert "not graded" in document["descriptor"]["details_copy"]
    assert base._validate(document) == []


def test_the_published_request_with_pins_to_compare_is_not_inconclusive(tmp_path: Path) -> None:
    """Our five checks include pins, which compares here, so the run is judged."""
    document = _run("all-not-applicable", tmp_path)
    applicable = [c["id"] for c in document["integrity"]["checks"] if c["applicable"]]
    assert applicable == ["pins"]
    run = document["integrity"]["run"]
    assert run["test_system_status"] == "COMPLETED"
    assert run["success"] is True
    assert run["percentage"] == 100
    assert base._validate(document) == []


def test_every_example_request_gives_a_valid_1_2_0_run_by_the_rule(tmp_path: Path) -> None:
    seen = {"INCONCLUSIVE": 0, "COMPLETED": 0, "ERROR": 0}
    for name in _names():
        document = _run(name, tmp_path)
        assert document["format"] == FORMAT, name
        assert base._validate(document) == [], name
        checks = document["integrity"]["checks"]
        run = document["integrity"]["run"]
        applicable = [check for check in checks if check["applicable"]]
        status = run["test_system_status"]
        seen[status] += 1
        if not applicable:
            assert status == "INCONCLUSIVE" and "percentage" not in run, name
            assert run["success"] is False and run["conclusion"] == "INCONCLUSIVE", name
        elif all(check["success"] for check in checks):
            assert status == "COMPLETED" and run["success"] is True, name
            assert run["percentage"] == min(check["percentage"] for check in applicable), name
            assert "conclusion" not in run, name
        else:
            assert status == "ERROR" and run["success"] is False, name
            assert run["conclusion"] == "INCONCLUSIVE" and "percentage" in run, name
    assert seen["COMPLETED"] and seen["ERROR"], seen


def test_a_mixed_run_is_not_inconclusive(tmp_path: Path) -> None:
    mixed = []
    for name in _names():
        document = _run(name, tmp_path)
        checks = document["integrity"]["checks"]
        flags = {check["applicable"] for check in checks}
        if flags == {True, False}:
            mixed.append(document)
            run = document["integrity"]["run"]
            assert run["test_system_status"] in ("COMPLETED", "ERROR")
            assert "percentage" in run
            assert base._validate(document) == []
    assert mixed, "no example has both an applicable and a not applicable check"


def test_a_failed_run_keeps_the_error_path(tmp_path: Path) -> None:
    document = _run("completeness", tmp_path)
    run = document["integrity"]["run"]
    assert run["test_system_status"] == "ERROR"
    assert run["conclusion"] == "INCONCLUSIVE"
    assert run["success"] is False
    assert "percentage" in run
    assert base._validate(document) == []


def test_an_evidence_manifest_run_declares_1_2_0(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    assert base._evaluate(base.GOOD, out) == 0
    document = _load(out)
    assert document["format"] == FORMAT
    assert document["integrity"]["run"]["test_system_status"] == "COMPLETED"
    assert base._validate(document) == []
