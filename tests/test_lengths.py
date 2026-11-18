"""Descriptor lengths: clipped to the contract's limits, and guarded before writing.

livingproof-evaluator-run#10, from the recheck of PR 9. The descriptor schema (kit v1.1.0)
allows a finding's ``trial`` 40 characters and its ``text`` 280. Over-limit evidence is clipped
in the descriptor, and a descriptor that is still over a limit is never written.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
import test_completeness as base
from test_pins import _check

from livingproof_evaluator_run.__main__ import main
from livingproof_evaluator_run.plain import DESCRIPTOR_LIMITS, FINDING_LIMITS, MAX_FINDINGS

EXAMPLES = base.CONTRACT / "examples" / "integrity"


def _request(tmp_path: Path, trial_ids: list[str]) -> Path:
    request = json.loads((EXAMPLES / "pins" / "request.json").read_text())
    request["integrity"]["manifest"]["planned_trials"] = [{"id": item} for item in trial_ids]
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    return source


def test_limits_are_the_kits() -> None:
    schema = json.loads((base.CONTRACT / "schema" / "descriptor.schema.json").read_text())
    props = schema["properties"]
    for key, limit in DESCRIPTOR_LIMITS.items():
        assert props[key]["maxLength"] == limit, key
    assert props["findings"]["maxItems"] == MAX_FINDINGS
    finding = schema["$defs"]["finding"]["properties"]
    assert finding["text"]["maxLength"] == FINDING_LIMITS["text"]
    assert finding["severity"]["maxLength"] == FINDING_LIMITS["severity"]
    assert finding["time"]["maxLength"] == FINDING_LIMITS["time"]
    assert finding["reported_by"]["maxLength"] == FINDING_LIMITS["reported_by"]
    assert finding["trial"]["oneOf"][1]["maxLength"] == FINDING_LIMITS["trial"]


@pytest.mark.parametrize("size", [40, 41, 100, 300])
def test_long_trial_ids_are_clipped_in_the_descriptor_only(tmp_path: Path, size: int) -> None:
    trial = "t" * size
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, [trial])), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    items = [item for item in document["descriptor"]["findings"] if "trial" in item]
    assert len(items) == 1
    assert len(items[0]["trial"]) <= 40
    assert all(len(item["text"]) <= 280 for item in document["descriptor"]["findings"])
    assert items[0]["trial"].endswith("\u2026") == (size > 40)
    # The check keeps the full id.
    completeness = _check(document, "completeness")
    assert [f["trial_id"] for f in completeness["findings"]] == [trial]
    assert base._validate(document) == []


def test_a_short_trial_id_and_text_are_not_changed(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, ["trial-99"])), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    (item,) = [i for i in document["descriptor"]["findings"] if "trial" in i]
    assert item["trial"] == "trial-99"
    assert item["text"] == "Planned trial trial-99 has no trial evidence."


def test_over_the_cap_findings_still_conform(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    ids = [f"trial-{index:03d}" for index in range(MAX_FINDINGS + 25)]
    assert main([str(_request(tmp_path, ids)), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert len(document["descriptor"]["findings"]) == MAX_FINDINGS
    assert base._validate(document) == []


@pytest.mark.parametrize("size", [41, 300])
def test_an_over_limit_descriptor_is_never_written(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    size: int,
) -> None:
    # Whatever slips past the clipping, the command must not exit 0 with an invalid result.
    evaluate_module = importlib.import_module("livingproof_evaluator_run.evaluate")
    monkeypatch.setattr(evaluate_module, "_clip", lambda text, limit: text)
    out = tmp_path / "result.json"
    code = main([str(_request(tmp_path, ["t" * size])), "--out", str(out)])
    assert code == 1
    assert not out.exists()
    assert "too long" in capsys.readouterr().err


def test_the_guard_names_an_over_limit_descriptor_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(DESCRIPTOR_LIMITS, "title", 3)
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, ["trial-01"])), "--out", str(out)]) == 1
    assert not out.exists()
    assert "title" in capsys.readouterr().err


@pytest.mark.parametrize(
    "trial,expected",
    [
        ("a" * 35 + "<" + "b" * 20, "a" * 35 + "\u2026"),
        ("a" * 33 + "<" + "b" * 20, "a" * 33 + "\\u003c\u2026"),
        ("<" * 50, "\\u003c" * 6 + "\u2026"),
        ("a" * 36 + "\n" + "b" * 20, "a" * 36 + "\u2026"),
        ("a" * 35 + "\n" + "b" * 20, "a" * 35 + "\\x0a\u2026"),
    ],
)
def test_clipping_never_splits_an_escape_sequence(
    tmp_path: Path, trial: str, expected: str
) -> None:
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, [trial])), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    (item,) = [i for i in document["descriptor"]["findings"] if "trial" in i]
    assert item["trial"] == expected
    assert base._validate(document) == []


def test_text_clipping_never_splits_an_escape_sequence(tmp_path: Path) -> None:
    # "Planned trial " (14) + 260*"a" (260) = 274; \u003c spans [274, 280), straddling cut 279.
    trial = "a" * 260 + "<" + "b" * 30
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, [trial])), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    (item,) = [i for i in document["descriptor"]["findings"] if "trial" in i]
    assert item["text"] == "Planned trial " + "a" * 260 + "\u2026"
    assert base._validate(document) == []


def _clean_request(tmp_path: Path, trial_ids: list[str]) -> Path:
    request = json.loads((EXAMPLES / "clean" / "request.json").read_text())
    request["integrity"]["manifest"]["planned_trials"] = [{"id": item} for item in trial_ids]
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    return source


@pytest.mark.parametrize("count", [49, 50])
def test_at_or_below_the_cap_no_overflow_note_is_added(tmp_path: Path, count: int) -> None:
    out = tmp_path / "result.json"
    ids = [f"trial-{index:03d}" for index in range(count)]
    assert main([str(_clean_request(tmp_path, ids)), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    shown = document["descriptor"]["findings"]
    assert len(shown) == count
    assert all("trial" in item for item in shown)
    assert "more finding" not in document["descriptor"]["details_copy"]
    assert base._validate(document) == []


@pytest.mark.parametrize("count", [51, 75])
def test_past_the_cap_adds_an_and_n_more_note(tmp_path: Path, count: int) -> None:
    out = tmp_path / "result.json"
    ids = [f"trial-{index:03d}" for index in range(count)]
    assert main([str(_clean_request(tmp_path, ids)), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    shown = document["descriptor"]["findings"]
    assert len(shown) == MAX_FINDINGS
    assert [item["trial"] for item in shown[:-1]] == ids[: MAX_FINDINGS - 1]
    dropped = count - (MAX_FINDINGS - 1)
    expected_note = f"And {dropped} more findings (showing {MAX_FINDINGS - 1} of {count})."
    assert shown[-1] == {"text": expected_note}
    assert document["descriptor"]["details_copy"].endswith(expected_note)
    assert len(document["descriptor"]["details_copy"]) <= 1000
    assert base._validate(document) == []


def test_overflow_note_keeps_pins_not_checked_note_within_details_limit(tmp_path: Path) -> None:
    request = json.loads((EXAMPLES / "pins" / "request.json").read_text())
    del request["integrity"]["manifest"]["pins"]["verifier"]
    ids = [f"trial-{index:03d}" for index in range(MAX_FINDINGS)]
    request["integrity"]["manifest"]["planned_trials"] = [{"id": item} for item in ids]
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert main([str(source), "--out", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    # 50 completeness + 5 pins (4 differing; verifier not checked) = 54 findings.
    shown = document["descriptor"]["findings"]
    assert len(shown) == MAX_FINDINGS
    expected_note = "And 5 more findings (showing 49 of 54)."
    assert shown[-1] == {"text": expected_note}
    details = document["descriptor"]["details_copy"]
    assert expected_note in details
    assert "Not checked: verifier." in details
    assert len(details) <= 1000
    assert base._validate(document) == []


@pytest.mark.parametrize("trial_ids", [[""], ["trial-01", ""]])
def test_empty_trial_id_exits_2_with_nothing_written(tmp_path: Path, trial_ids: list[str]) -> None:
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, trial_ids)), "--out", str(out)]) == 2
    assert not out.exists()


@pytest.mark.parametrize("blank", ["   ", "\u200b", "\ufeff"])
def test_blank_trial_id_fails_closed_with_nothing_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], blank: str
) -> None:
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, [blank])), "--out", str(out)]) == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "not plain text" in err and "findings[0].trial" in err


@pytest.mark.parametrize("blank", ["   ", "\u200b"])
def test_present_blank_trial_id_also_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], blank: str
) -> None:
    request = json.loads((EXAMPLES / "clean" / "request.json").read_text())
    request["integrity"]["manifest"]["planned_trials"] = [{"id": blank}]
    trial = dict(request["integrity"]["trials"][0], id=blank)
    request["integrity"]["trials"] = [trial]
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert main([str(source), "--out", str(out)]) == 1
    assert not out.exists()
    assert "not plain text" in capsys.readouterr().err
