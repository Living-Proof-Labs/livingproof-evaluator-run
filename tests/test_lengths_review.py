"""Reviewer coverage for the descriptor length clipping and guard (PR 11, head 62754f5).

Scripted from Vera's probes. Everything here passes on that head.
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


def _result(tmp_path: Path, trial_ids: list[str]) -> dict:
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, trial_ids)), "--out", str(out)]) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def _trial_findings(document: dict) -> list[dict]:
    return [item for item in document["descriptor"]["findings"] if "trial" in item]


def test_every_length_the_kit_sets_on_the_descriptor_is_guarded() -> None:
    # The reverse of test_limits_are_the_kits: a limit the kit adds later must be noticed here.
    schema = json.loads((base.CONTRACT / "schema" / "descriptor.schema.json").read_text())
    kit_descriptor = {
        key: value["maxLength"]
        for key, value in schema["properties"].items()
        if "maxLength" in value
    }
    kit_descriptor.pop("icon")  # a constant of this evaluator, not evidence-derived
    assert kit_descriptor == DESCRIPTOR_LIMITS
    finding = schema["$defs"]["finding"]["properties"]
    kit_finding = {
        key: value["maxLength"] for key, value in finding.items() if "maxLength" in value
    }
    kit_finding["trial"] = finding["trial"]["oneOf"][1]["maxLength"]
    assert kit_finding == FINDING_LIMITS
    assert schema["properties"]["findings"]["maxItems"] == MAX_FINDINGS


@pytest.mark.parametrize(
    "trial",
    [
        pytest.param("t" * 39, id="39"),
        pytest.param("t" * 40, id="40"),
        pytest.param("t" * 41, id="41"),
        pytest.param("\u00e9" * 41, id="precomposed"),
        pytest.param("e\u0301" * 30, id="combining pairs"),
        pytest.param("\U0001f600" * 41, id="astral"),
        pytest.param("a" * 39 + "\U0001f600\U0001f600", id="astral at the cut"),
        pytest.param("\U0001f468\u200d\U0001f469\u200d\U0001f467\u200d\U0001f466" * 12, id="zwj"),
        pytest.param("a" * 35 + "<" + "b" * 20, id="escape at the cut"),
        pytest.param("<" * 50, id="escape expands past the limit"),
        pytest.param("t" * 38 + " " * 10 + "z", id="spaces at the cut"),
    ],
)
def test_clipping_stays_within_the_limit_and_ends_in_an_ellipsis(
    tmp_path: Path, trial: str
) -> None:
    document = _result(tmp_path, [trial])
    (item,) = _trial_findings(document)
    assert 0 < len(item["trial"]) <= FINDING_LIMITS["trial"]
    assert all(len(f["text"]) <= FINDING_LIMITS["text"] for f in document["descriptor"]["findings"])
    assert base._validate(document) == []
    # The check itself and the per-trial status keep the full id.
    assert [f["trial_id"] for f in _check(document, "completeness")["findings"]] == [trial]
    assert trial in [t["id"] for t in document["integrity"]["trials"]]


def test_a_trial_id_of_exactly_40_is_not_clipped_and_41_is(tmp_path: Path) -> None:
    (exact,) = _trial_findings(_result(tmp_path, ["t" * 40]))
    assert exact["trial"] == "t" * 40
    (over,) = _trial_findings(_result(tmp_path, ["t" * 41]))
    assert over["trial"] == "t" * 39 + "\u2026"


def test_the_long_completeness_text_is_clipped_to_280_with_an_ellipsis(tmp_path: Path) -> None:
    document = _result(tmp_path, ["t" * 300])
    (item,) = _trial_findings(document)
    assert len(item["text"]) == 280
    assert item["text"].endswith("\u2026")
    # The finding in the check keeps the whole sentence, with the full id.
    (finding,) = _check(document, "completeness")["findings"]
    assert "t" * 300 in finding["summary"]


@pytest.mark.parametrize("count", [49, 50, 51, 75])
def test_more_findings_than_the_cap_keep_the_check_whole_and_the_descriptor_at_the_cap(
    tmp_path: Path, count: int
) -> None:
    ids = [f"trial-{index:03d}" for index in range(count)]
    document = _result(tmp_path, ids)
    # The check reports every missing trial; only the descriptor is capped, in order.
    assert [f["trial_id"] for f in _check(document, "completeness")["findings"]] == ids
    shown = document["descriptor"]["findings"]
    assert len(shown) <= MAX_FINDINGS
    assert [item["trial"] for item in shown if "trial" in item] == ids[: len(shown)]
    assert document["integrity"]["run"]["test_system_status"] == "ERROR"
    assert base._validate(document) == []


@pytest.mark.parametrize(
    "limit,size,field",
    [(40, 41, "findings[0].trial"), (280, 300, "findings[0].text")],
)
def test_the_guard_names_the_field_that_is_over(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    limit: int,
    size: int,
    field: str,
) -> None:
    evaluate_module = importlib.import_module("livingproof_evaluator_run.evaluate")
    real = evaluate_module._clip
    # Disable the clipping for one limit only, so the guard has to catch that field.
    monkeypatch.setattr(
        evaluate_module, "_clip", lambda text, bound: text if bound == limit else real(text, bound)
    )
    out = tmp_path / "result.json"
    assert main([str(_request(tmp_path, ["t" * size])), "--out", str(out)]) == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert field in err and "too long" in err
    assert str(limit) in err
