"""Descriptor text is plain text, and the CLI never exits 0 with a result the contract rejects.

livingproof-evaluator-run#5, review of PR 9 (gap a). The descriptor plain-text pattern refuses
``<``, ``>``, control characters and the line separators. Values copied out of evidence are
shown escaped; a final check on the descriptor stops anything else from being written.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
import test_completeness as base
from test_pins import GOOD, ZERO, _check, _copy, _edit

from livingproof_evaluator_run import pins
from livingproof_evaluator_run.__main__ import main
from livingproof_evaluator_run.plain import VALUE_LIMIT, escape, is_plain, shown

ODD = ["abc\n", "a\tb", "<b>x</b>", "a\x00b", "a\x7fb", "a\x85b", "a\u2028b", "a\u2029b", "\r\n"]


def _cli(folder: Path, tmp_path: Path) -> tuple[int, Path]:
    out = tmp_path / "result.json"
    return main([str(folder / "manifest.json"), "--out", str(out)]), out


@pytest.mark.parametrize("bad", ODD, ids=repr)
def test_recorded_value_is_shown_escaped_and_still_a_finding(tmp_path: Path, bad: str) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256=bad))
    code, out = _cli(folder, tmp_path)
    assert code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    (finding,) = _check(document, "pins")["findings"]
    assert finding["subject"] == "world"
    assert is_plain(finding["summary"])
    assert all(is_plain(item["text"]) for item in document["descriptor"]["findings"])
    assert is_plain(document["descriptor"]["details_copy"])
    # The reader sees what was recorded, not a blank.
    assert escape(bad) in finding["summary"]
    assert base._validate(document) == []


@pytest.mark.parametrize("bad", ODD, ids=repr)
def test_declared_value_in_the_lock_is_escaped_too(tmp_path: Path, bad: str) -> None:
    folder = _copy(tmp_path)
    _edit(
        folder / "manifest.json",
        lambda d: d["lock"]["content"]["sources"]["world"].update(sha256=bad),
    )
    code, out = _cli(folder, tmp_path)
    assert code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert [f["subject"] for f in _check(document, "pins")["findings"]] == ["world"]
    assert base._validate(document) == []


def test_a_very_long_recorded_value_is_bounded(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256="ab" * 5000))
    code, out = _cli(folder, tmp_path)
    assert code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    (finding,) = _check(document, "pins")["findings"]
    assert len(finding["summary"]) < 400
    assert base._validate(document) == []


def test_ordinary_values_are_shown_unchanged(tmp_path: Path) -> None:
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256=ZERO))
    code, out = _cli(folder, tmp_path)
    assert code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    (finding,) = _check(document, "pins")["findings"]
    assert ZERO in finding["summary"]
    assert shown(ZERO) == ZERO


def test_escape_is_exact() -> None:
    assert escape("a<b>\n\x00\x85\u2028") == "a\\u003cb\\u003e\\x0a\\x00\\u0085\\u2028"
    assert escape("sha256:AbC") == "sha256:AbC"
    assert len(shown("x" * 500)) == VALUE_LIMIT


def test_is_plain_matches_the_contract_pattern() -> None:
    assert is_plain("Matched the verification lock: world.")
    for refused in ["a<b", "a>b", "a\nb", "a\x7fb", "a\u2028b", "", "   ", "\u200b", None, 3]:
        assert not is_plain(refused)


def test_a_descriptor_the_contract_would_refuse_is_never_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Whatever slips past the escaping, the command must not exit 0 with an invalid result.
    evaluate_module = importlib.import_module("livingproof_evaluator_run.evaluate")
    monkeypatch.setattr(evaluate_module, "plain", lambda text: text)
    monkeypatch.setattr(pins, "shown", lambda text: text)
    folder = _copy(tmp_path)
    _edit(folder / "run-manifest.json", lambda d: d["world"].update(sha256="<b>"))
    code, out = _cli(folder, tmp_path)
    assert code == 1
    assert not out.exists()
    assert "not plain text" in capsys.readouterr().err


def test_request_with_a_markup_trial_id_still_conforms(tmp_path: Path) -> None:
    request = json.loads(
        (base.CONTRACT / "examples" / "integrity" / "clean" / "request.json").read_text()
    )
    trials = request["integrity"]["manifest"]["planned_trials"]
    request["integrity"]["manifest"]["planned_trials"] = [*trials, {"id": "trial-<x>\n"}]
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert main([str(source), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert all(is_plain(item["text"]) for item in document["descriptor"]["findings"])
    assert base._validate(document) == []


def test_good_fixture_is_unchanged_by_the_guard(tmp_path: Path) -> None:
    code, out = _cli(GOOD, tmp_path)
    assert code == 0
    assert base._validate(json.loads(out.read_text(encoding="utf-8"))) == []
