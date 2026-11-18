"""Reviewer coverage for the plain-text guard and the not-applicable rule (PR 9, head 80cc8fd).

Scripted from Vera's recheck probes. Every test passed on 80cc8fd except the long trial id on
the request path, which gave an invalid result and exit code 0. It was a strict xfail and is
fixed now: ids and texts are clipped in the descriptor and the guard also checks lengths.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import test_completeness as base
from test_pins import _check, _copy, _edit

from livingproof_evaluator_run.__main__ import main
from livingproof_evaluator_run.plain import VALUE_LIMIT, is_plain, shown

EXAMPLES = base.CONTRACT / "examples" / "integrity"


def _cli(folder: Path, tmp_path: Path) -> dict:
    out = tmp_path / "result.json"
    assert main([str(folder / "manifest.json"), "--out", str(out)]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_is_plain_agrees_with_the_kit_pattern_for_every_code_point() -> None:
    schema = json.loads((base.CONTRACT / "schema" / "descriptor.schema.json").read_text())
    pattern = schema["$defs"]["plain"]["pattern"]
    # Python's ``$`` also matches before a final newline; anchor with \Z so the comparison is exact.
    assert pattern.endswith("*$")
    kit = re.compile(pattern[:-1] + r"\Z")
    wrong = [
        hex(code)
        for code in range(0x110000)
        for text in (chr(code), "a" + chr(code), chr(code) + "a")
        if bool(kit.search(text)) != is_plain(text)
    ]
    assert wrong == []


@pytest.mark.parametrize(
    "value",
    [
        "a\u202eb",  # right-to-left override
        "\u2066x\u2067y\u2068z\u2069",  # bidi isolates
        "x\u200f\u200e",  # direction marks
        "\u200b",  # zero-width space only
        "\ufeffabc",  # byte order mark
        "a\x7fb",  # DEL
        "a\x85\x9fb",  # C1 controls
        "a\u2028\u2029b",  # line and paragraph separators
        "\u2028",
        "a\ud800b",  # lone surrogate
        "a\U0001f600b",  # astral
        "a&amp;\"b'c",  # ampersand and quotes
        "\\u003c\\x0a",  # a literal backslash sequence
    ],
    ids=repr,
)
def test_unusual_recorded_values_give_a_conforming_finding(tmp_path: Path, value: str) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256=value))
    document = _cli(folder, tmp_path)
    assert [f["subject"] for f in _check(document, "pins")["findings"]] == ["world"]
    assert base._validate(document) == []


@pytest.mark.parametrize("size", [99, 100, 101, 5000])
def test_value_bound_is_exactly_100_characters(tmp_path: Path, size: int) -> None:
    value = "a" * size
    assert VALUE_LIMIT == 100
    assert shown(value) == (value if size <= 100 else value[:99] + "\u2026")
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256=value))
    document = _cli(folder, tmp_path)
    summary = _check(document, "pins")["findings"][0]["summary"]
    assert (value in summary) == (size <= 100)
    assert base._validate(document) == []


def test_worst_case_escaping_on_every_subject_still_conforms(tmp_path: Path) -> None:
    folder = _copy(tmp_path)

    def doctor(doc: dict) -> None:
        doc["configuration"]["sha256"] = "<" * 100
        doc["environment"]["runner"]["commit"] = "<" * 100
        doc["environment"]["simulator"]["adapter_commit"] = ">" * 100

    _edit(folder / "manifest.json", doctor)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256="\x00" * 100))
    document = _cli(folder, tmp_path)
    pins = _check(document, "pins")
    assert sorted(f["subject"] for f in pins["findings"]) == ["configuration", "runner", "world"]
    assert base._validate(document) == []


@pytest.mark.parametrize(
    "keep",
    ["world", "configuration", "adapter"],
)
def test_a_single_comparable_subject_still_applies(tmp_path: Path, keep: str) -> None:
    folder = _copy(tmp_path)

    def strip(doc: dict) -> None:
        if keep != "configuration":
            del doc["configuration"]["sha256"]
        del doc["environment"]["runner"]["commit"]
        if keep != "adapter":
            del doc["environment"]["simulator"]["adapter_commit"]

    _edit(folder / "manifest.json", strip)
    if keep != "world":
        (folder / "run-manifest.json").unlink()
    document = _cli(folder, tmp_path)
    pins = _check(document, "pins")
    assert pins["applicable"] is True
    assert pins["success"] is True
    assert pins["percentage"] == 100
    assert document["integrity"]["run"]["test_system_status"] == "COMPLETED"
    assert base._validate(document) == []


def test_a_lock_that_declares_a_subject_the_run_did_not_record_is_not_applicable(
    tmp_path: Path,
) -> None:
    folder = _copy(tmp_path)

    def strip(doc: dict) -> None:
        del doc["configuration"]["sha256"]
        del doc["environment"]["runner"]["commit"]
        del doc["environment"]["simulator"]["adapter_commit"]

    _edit(folder / "manifest.json", strip)
    (folder / "run-manifest.json").unlink()
    pins = _check(_cli(folder, tmp_path), "pins")
    assert pins["applicable"] is False
    assert "percentage" not in pins


@pytest.mark.parametrize("size", [41, 100, 300])
def test_a_long_trial_id_still_gives_a_conforming_result(tmp_path: Path, size: int) -> None:
    request = json.loads((EXAMPLES / "pins" / "request.json").read_text())
    request["integrity"]["manifest"]["planned_trials"] = [{"id": "t" * size}]
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    code = main([str(source), "--out", str(out)])
    # Either refuse (non-zero, nothing written) or write a result the kit accepts.
    assert code != 0 or base._validate(json.loads(out.read_text(encoding="utf-8"))) == []
