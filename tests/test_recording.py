"""recording 1.0.0 (livingproof-evaluator-run#8).

Fail-first coverage for the fifth Run Integrity check: each recording that is present is a usable
MCAP file that agrees with ``media.json`` and with the run evidence. The contract is
livingproof-evaluator v1.1.0 (``schema/integrity/checks/recording.schema.json``,
``docs/run-integrity.md``); its reference rules (``tests/integrity_rules.py``) are run against ours.

Where the evidence comes from (livingproof-sim-mujoco ``media.py``, capability-verifier
``scenario.yml``): the ``media`` job writes ``mcap/trial-NN.mcap`` for every trial and a
``media.json`` (``livingproof-hallway-media/2.0.0``) and uploads them as ``<prefix>mcap-<config>``.
The evidence manifest records neither. The evaluator therefore takes the media directory as
``--media DIR``; without it there is no media and the check is not applicable.

The gap limit is never defaulted in code: it comes from the evidence (``plan.recording.
max_gap_seconds`` on a manifest, ``evidence.recording.max_gap_seconds`` on a request). The limits
used below are test values, not a proposal.

Evidence folders are the synthetic ``tests/fixtures/termination/good`` run; the media is written
by ``tests/recordings.py`` per test, and ``tests/fixtures/recording/real`` is a real recording.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import random
import shutil
import sys
from pathlib import Path

import pytest
import recordings as rec
import test_completeness as base

from livingproof_evaluator_run import evaluate, evaluate_evidence
from livingproof_evaluator_run.__main__ import main

SRC = Path(__file__).resolve().parent.parent / "src" / "livingproof_evaluator_run"
EVIDENCE = base.FIXTURES.parent / "termination" / "good"
REAL = base.FIXTURES.parent / "recording" / "real"
EXAMPLES = base.CONTRACT / "examples" / "integrity" / "recording"
SCHEMA = base.CONTRACT / "schema" / "integrity" / "checks" / "recording.schema.json"
CHECK = "recording"
CATEGORIES = [
    "mcap-incomplete",
    "missing-channel",
    "timestamps-backwards",
    "message-gap-exceeded",
    "media-file-mismatch",
    "observation-link-mismatch",
]
LIMIT = 0.05  # a test value


def module():
    return importlib.import_module("livingproof_evaluator_run.recording")


def _evidence(tmp_path: Path, *, gap: object = LIMIT, channels: object = None) -> Path:
    folder = tmp_path / "evidence"
    shutil.copytree(EVIDENCE, folder)
    _declare(folder, gap=gap, channels=channels)
    return folder


def _declare(folder: Path, *, gap: object = LIMIT, channels: object = None, where="plan") -> None:
    path = folder / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    declaration: dict = {}
    if gap is not None:
        declaration["max_gap_seconds"] = gap
    if channels is not None:
        declaration["required_channels"] = channels
    if where == "plan":
        document.setdefault("plan", {})["recording"] = declaration
    else:
        document["lock"] = {"content": {"plan": {"recording": declaration}}}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _run(folder: Path, tmp_path: Path, media: Path | None) -> dict:
    out = tmp_path / "result.json"
    assert evaluate_evidence(folder / "manifest.json", out, media) == 0
    return json.loads(out.read_text(encoding="utf-8"))


def _checks(document: dict) -> list[dict]:
    return document["integrity"]["checks"]


def _check(document: dict, check_id: str = CHECK) -> dict:
    (found,) = [c for c in _checks(document) if c["id"] == check_id]
    return found


def _categories(check: dict) -> list[str]:
    return [item["category"] for item in check["findings"]]


def _media(tmp_path: Path, folder: Path, **kwargs) -> Path:
    out = tmp_path / "media"
    rec.build_media(out, folder, **kwargs)
    return out


def _doctored(tmp_path: Path, *, gap: object = LIMIT, declared: object = None, **kwargs):
    """A run with media. ``declared`` is the plan's required channels; ``channels`` (in kwargs)
    is what the recordings hold."""
    folder = _evidence(tmp_path, gap=gap, channels=declared)
    media = _media(tmp_path, folder, **kwargs)
    document = _run(folder, tmp_path, media)
    return document, _check(document)


def _conforming_error(document: dict) -> None:
    run = document["integrity"]["run"]
    assert run["test_system_status"] == "ERROR"
    assert run["conclusion"] == "INCONCLUSIVE"
    assert run["success"] is False
    assert "verdict" not in document and "grade" not in document
    assert base._validate(document) == []


def _gap_at(position: int, gap_ns: int) -> dict[int, dict[str, list[int]]]:
    """Trial 2 with a hole of ``gap_ns`` in /base_pose after message ``position``."""
    times = rec.steps(position + 1)
    times += rec.steps(30, start=times[-1] + gap_ns)
    return {2: {rec.POSE: times, rec.JOINTS: rec.steps(position + 31)}}


# A clean run, and no media.


def test_a_clean_run_with_media_passes(tmp_path: Path) -> None:
    document, check = _doctored(tmp_path)
    assert check == {
        "id": "recording",
        "version": "1.0.0",
        "applicable": True,
        "success": True,
        "percentage": 100,
        "limits": {"max_gap_seconds": LIMIT},
        "findings": [],
    }
    assert document["integrity"]["run"]["success"] is True
    assert base._validate(document) == []


def test_no_media_is_not_applicable(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    document = _run(folder, tmp_path, None)
    assert _check(document) == {
        "id": "recording",
        "version": "1.0.0",
        "applicable": False,
        "success": True,
        "findings": [],
    }
    assert document["integrity"]["run"]["percentage"] == 100
    assert "Not checked: recording" in document["descriptor"]["success_copy"]
    assert base._validate(document) == []


def test_not_applicable_never_carries_limits_or_a_percentage(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    check = _check(_run(folder, tmp_path, None))
    assert "limits" not in check and "percentage" not in check


def test_a_run_without_media_is_otherwise_unchanged(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    document = _run(folder, tmp_path, None)
    assert [c["id"] for c in _checks(document)] == [
        "completeness",
        "pins",
        "plan-conformance",
        "termination",
        "recording",
    ]
    assert all(c["success"] for c in _checks(document))


def test_a_nonexistent_media_directory_is_not_applicable(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    document = _run(folder, tmp_path, tmp_path / "nowhere")
    check = _check(document)
    assert check["applicable"] is False and check["findings"] == []
    assert "media.json" in document["descriptor"]["success_copy"]


def test_a_media_directory_without_media_json_is_not_applicable(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = tmp_path / "media"
    rec.write_mcap(media / "mcap" / "trial-01.mcap")
    check = _check(_run(folder, tmp_path, media))
    assert check["applicable"] is False and check["findings"] == []


@pytest.mark.parametrize("content", ["not json", "[]", "7", '{"format": 1}'])
def test_a_media_json_that_is_not_readable_is_not_applicable(content: str, tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    (media / "media.json").write_text(content, encoding="utf-8")
    check = _check(_run(folder, tmp_path, media))
    assert check["applicable"] is False and check["findings"] == []


def test_a_media_json_of_another_format_is_not_applicable(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(format="livingproof-hallway-media/1.0.0"))
    document = _run(folder, tmp_path, media)
    assert _check(document)["applicable"] is False
    assert "livingproof-hallway-media/1.0.0" in document["descriptor"]["success_copy"]


# The gap limit comes from the evidence, with no default.


@pytest.mark.parametrize("limit", [0.05, 0.5, 1, 2.5, 0.0999, 3])
def test_limits_equal_the_evidence_value(limit: object, tmp_path: Path) -> None:
    _, check = _doctored(tmp_path, gap=limit)
    assert check["applicable"] is True
    assert check["limits"] == {"max_gap_seconds": limit}
    assert type(check["limits"]["max_gap_seconds"]) is type(limit)


def test_no_declared_limit_means_not_applicable_even_with_media(tmp_path: Path) -> None:
    folder = _evidence(tmp_path, gap=None)
    media = _media(tmp_path, folder, edit=lambda i, p: rec.truncate(p) if i == 1 else None)
    document = _run(folder, tmp_path, media)
    check = _check(document)
    assert check["applicable"] is False
    assert check["findings"] == [] and "limits" not in check
    text = document["descriptor"]["success_copy"]
    assert "max_gap_seconds" in text and "no default" in text


def test_a_manifest_with_no_recording_declaration_at_all(tmp_path: Path) -> None:
    folder = tmp_path / "evidence"
    shutil.copytree(EVIDENCE, folder)
    media = _media(tmp_path, folder)
    check = _check(_run(folder, tmp_path, media))
    assert check["applicable"] is False


@pytest.mark.parametrize("bad", [0, -1, -0.5, "0.1", True, False, None, [], {}, float("nan")])
def test_an_unusable_limit_is_not_used(bad: object, tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    path = folder / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["plan"]["recording"]["max_gap_seconds"] = bad
    path.write_text(json.dumps(document), encoding="utf-8")
    media = _media(tmp_path, folder)
    check = _check(_run(folder, tmp_path, media))
    assert check["applicable"] is False and "limits" not in check


def test_infinity_is_not_a_limit(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    path = folder / "manifest.json"
    text = path.read_text(encoding="utf-8").replace(f"{LIMIT}", "Infinity")
    path.write_text(text, encoding="utf-8")
    media = _media(tmp_path, folder)
    assert _check(_run(folder, tmp_path, media))["applicable"] is False


def test_the_lock_plan_is_the_fallback_and_the_manifest_plan_wins(tmp_path: Path) -> None:
    folder = _evidence(tmp_path, gap=None)
    _declare(folder, gap=0.4, where="lock")
    media = _media(tmp_path, folder)
    assert _check(_run(folder, tmp_path, media))["limits"] == {"max_gap_seconds": 0.4}
    _declare(folder, gap=0.4, where="lock")
    path = folder / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["plan"] = {**document["plan"], "recording": {"max_gap_seconds": 0.7}}
    path.write_text(json.dumps(document), encoding="utf-8")
    assert _check(_run(folder, tmp_path, media))["limits"] == {"max_gap_seconds": 0.7}


def test_an_unusable_manifest_limit_falls_back_to_the_lock_plan(tmp_path: Path) -> None:
    folder = _evidence(tmp_path, gap=0)
    path = folder / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["lock"] = {"content": {"plan": {"recording": {"max_gap_seconds": 0.4}}}}
    path.write_text(json.dumps(document), encoding="utf-8")
    media = _media(tmp_path, folder)
    assert _check(_run(folder, tmp_path, media))["limits"] == {"max_gap_seconds": 0.4}


def test_the_code_has_no_default_gap_limit() -> None:
    recording = module()
    assert inspect.signature(recording.judge).parameters["max_gap_seconds"].default is (
        inspect.Parameter.empty
    )
    for name in dir(recording):
        value = getattr(recording, name)
        if "GAP" in name.upper() or "LIMIT" in name.upper():
            assert not isinstance(value, (int, float)) or isinstance(value, bool), name
    for path in (SRC / "recording.py", SRC / "mcap_reader.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                assert node.value not in (0.1, 0.02, 0.05, 0.5), (path.name, node.lineno)


def test_the_limit_in_the_result_is_the_evidence_value_on_the_request_path(tmp_path: Path) -> None:
    request = _request("clean")
    request["integrity"]["evidence"]["recording"]["max_gap_seconds"] = 0.37
    check = _run_request(request, tmp_path)
    assert _check(check)["limits"] == {"max_gap_seconds": 0.37}


# Required channels.


def test_required_channels_default_to_the_two_the_runner_records(tmp_path: Path) -> None:
    assert list(module().DEFAULT_REQUIRED_CHANNELS) == ["/base_pose", "/joint_states"]
    only_pose = {i: {rec.POSE: rec.steps(50)} for i in (1, 2, 3)}
    _, check = _doctored(tmp_path, channels=only_pose)
    assert _categories(check) == ["missing-channel"] * 3
    assert "/joint_states" in check["findings"][0]["summary"]


def test_declared_channels_replace_the_default(tmp_path: Path) -> None:
    only_pose = {i: {rec.POSE: rec.steps(50)} for i in (1, 2, 3)}
    folder = _evidence(tmp_path, channels=["/base_pose"])
    media = _media(tmp_path, folder, channels=only_pose)
    check = _check(_run(folder, tmp_path, media))
    assert check["success"] is True and check["findings"] == []


@pytest.mark.parametrize("bad", [[], "/base_pose", ["base_pose"], [1], ["/"], None, {"a": 1}])
def test_an_unusable_channel_declaration_is_not_used(bad: object, tmp_path: Path) -> None:
    only_pose = {i: {rec.POSE: rec.steps(50)} for i in (1, 2, 3)}
    folder = _evidence(tmp_path, channels=bad)
    media = _media(tmp_path, folder, channels=only_pose)
    check = _check(_run(folder, tmp_path, media))
    assert _categories(check) == ["missing-channel"] * 3


def test_the_summary_says_the_default_channels_were_used(tmp_path: Path) -> None:
    document, _ = _doctored(tmp_path)
    text = document["descriptor"]["success_copy"]
    assert "/base_pose" in text and "/joint_states" in text and "default" in text


# Each category.


def test_a_truncated_recording_is_incomplete(tmp_path: Path) -> None:
    document, check = _doctored(tmp_path, edit=lambda i, p: rec.truncate(p) if i == 2 else None)
    assert "mcap-incomplete" in _categories(check)
    first = check["findings"][0]
    assert first["trial_id"] == "trial-02"
    assert first["summary"] == "The recording does not open or has no valid footer and summary."
    assert first["classification"] == "test_system"
    _conforming_error(document)


def test_a_recording_without_a_summary_is_incomplete(tmp_path: Path) -> None:
    _, check = _doctored(tmp_path, edit=lambda i, p: rec.without_summary(p) if i == 3 else None)
    assert _categories(check) == ["mcap-incomplete"]
    assert check["findings"][0]["trial_id"] == "trial-03"


def test_a_recording_that_is_not_an_mcap_is_incomplete(tmp_path: Path) -> None:
    def edit(index: int, path: Path) -> None:
        if index == 1:
            path.write_bytes(b"this is not a recording")

    _, check = _doctored(tmp_path, edit=edit)
    assert _categories(check)[0] == "mcap-incomplete"
    assert {i["trial_id"] for i in check["findings"]} == {"trial-01"}


def test_a_missing_channel_is_a_finding_for_that_trial(tmp_path: Path) -> None:
    _, check = _doctored(tmp_path, channels={2: {rec.POSE: rec.steps(40)}})
    assert [(i["category"], i["trial_id"]) for i in check["findings"]] == [
        ("missing-channel", "trial-02")
    ]
    assert check["findings"][0]["summary"] == (
        "The required channel /joint_states is absent or has no messages."
    )


def test_a_required_channel_with_no_messages_is_missing(tmp_path: Path) -> None:
    def edit(index: int, path: Path) -> None:
        if index == 3:
            rec.write_empty_channel(path, rec.JOINTS, others={rec.POSE: rec.steps(40)})

    _, check = _doctored(tmp_path, edit=edit)
    assert [(i["category"], i["trial_id"]) for i in check["findings"]] == [
        ("missing-channel", "trial-03")
    ]


def test_timestamps_that_go_backwards_are_counted(tmp_path: Path) -> None:
    times = rec.steps(40)
    times[10], times[11], times[25], times[26] = times[11], times[10], times[26], times[25]
    _, check = _doctored(tmp_path, channels={1: {rec.POSE: times, rec.JOINTS: rec.steps(40)}})
    (finding,) = check["findings"]
    assert finding["category"] == "timestamps-backwards"
    assert finding["trial_id"] == "trial-01"
    assert finding["summary"] == "Channel /base_pose has 2 timestamps that go backwards."


def test_a_gap_over_the_limit_is_a_finding(tmp_path: Path) -> None:
    gap_ns = 80_000_000
    _, check = _doctored(tmp_path, channels=_gap_at(10, gap_ns))
    (finding,) = check["findings"]
    assert finding["category"] == "message-gap-exceeded"
    assert finding["trial_id"] == "trial-02"
    assert finding["summary"] == "Channel /base_pose has a gap of 0.08 s, over the limit of 0.05 s."


@pytest.mark.parametrize("limit", [0.05, 0.1, 0.3, 0.07, 1.5, 0.123456789])
def test_a_gap_equal_to_the_limit_is_not_a_finding(limit: float, tmp_path: Path) -> None:
    gap_ns = round(limit * 1e9)
    _, check = _doctored(tmp_path, gap=limit, channels=_gap_at(10, gap_ns))
    assert check["findings"] == []
    assert check["success"] is True and check["percentage"] == 100


@pytest.mark.parametrize("limit", [0.05, 0.1, 0.3, 0.07, 1.5])
def test_a_gap_one_nanosecond_over_the_limit_is_a_finding(limit: float, tmp_path: Path) -> None:
    gap_ns = round(limit * 1e9) + 1
    _, check = _doctored(tmp_path, gap=limit, channels=_gap_at(10, gap_ns))
    assert _categories(check) == ["message-gap-exceeded"]


def test_a_gap_one_nanosecond_under_the_limit_is_not_a_finding(tmp_path: Path) -> None:
    gap_ns = round(0.1 * 1e9) - 1
    _, check = _doctored(tmp_path, gap=0.1, channels=_gap_at(10, gap_ns))
    assert check["findings"] == []


def test_a_recording_that_differs_from_media_json_is_a_file_mismatch(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d["trials"][0]["mcap"].update(sha256="0" * 64))
    check = _check(_run(folder, tmp_path, media))
    (finding,) = check["findings"]
    assert finding["category"] == "media-file-mismatch"
    assert finding["trial_id"] == "trial-01"
    assert finding["summary"] == "The recording's size or sha256 differs from media.json."


def test_a_size_that_differs_from_media_json_is_a_file_mismatch(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d["trials"][1]["mcap"].update(bytes=1))
    check = _check(_run(folder, tmp_path, media))
    assert [(i["category"], i["trial_id"]) for i in check["findings"]] == [
        ("media-file-mismatch", "trial-02")
    ]


def test_a_media_json_without_the_digest_is_a_file_mismatch(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d["trials"][0]["mcap"].pop("sha256"))
    assert _categories(_check(_run(folder, tmp_path, media))) == ["media-file-mismatch"]


def test_an_observation_that_differs_from_the_evidence_is_a_link_mismatch(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d["trials"][2].update(observation_sha256="f" * 64))
    check = _check(_run(folder, tmp_path, media))
    (finding,) = check["findings"]
    assert finding["category"] == "observation-link-mismatch"
    assert finding["trial_id"] == "trial-03"
    assert (
        finding["summary"] == "The observation_sha256 in media.json differs from the run evidence."
    )


def test_a_media_json_without_the_observation_digest_is_a_link_mismatch(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d["trials"][0].pop("observation_sha256"))
    assert _categories(_check(_run(folder, tmp_path, media))) == ["observation-link-mismatch"]


def test_every_category_is_reachable_and_in_the_contract() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    enum = schema["properties"]["findings"]["items"]["properties"]["category"]["enum"]
    assert list(module().CATEGORIES) == CATEGORIES == enum


# Percentage, ordering and what is not recording's business.


def test_percentage_is_the_share_of_judged_recordings_without_a_finding(tmp_path: Path) -> None:
    document, check = _doctored(tmp_path, channels=_gap_at(10, 200_000_000))
    assert check["percentage"] == pytest.approx(100 * 2 / 3)
    assert document["integrity"]["run"]["percentage"] == pytest.approx(100 * 2 / 3)
    _conforming_error(document)


def test_one_trial_with_two_findings_counts_once(tmp_path: Path) -> None:
    times = rec.steps(40)
    times[10], times[11] = times[11], times[10]
    channels = {1: {rec.POSE: times}}
    _, check = _doctored(tmp_path, channels=channels)
    assert sorted(_categories(check)) == ["missing-channel", "timestamps-backwards"]
    assert check["percentage"] == pytest.approx(100 * 2 / 3)


def test_findings_follow_the_trial_order_and_the_contract_order_within_a_trial(
    tmp_path: Path,
) -> None:
    times = rec.steps(40)
    times[10], times[11] = times[11], times[10]
    folder = _evidence(tmp_path)

    def edit(index: int, path: Path) -> None:
        if index == 2:
            rec.write_mcap(path, {rec.POSE: times})

    media = _media(tmp_path, folder, edit=edit)
    rec.edit_media(media, lambda d: d["trials"][1].update(observation_sha256="e" * 64))
    check = _check(_run(folder, tmp_path, media))
    assert _categories(check) == [
        "missing-channel",
        "timestamps-backwards",
        "observation-link-mismatch",
    ]


def test_the_checks_are_reported_in_order(tmp_path: Path) -> None:
    document, _ = _doctored(tmp_path)
    assert [c["id"] for c in _checks(document)] == [
        "completeness",
        "pins",
        "plan-conformance",
        "termination",
        "recording",
    ]


def test_recording_findings_leave_the_trial_statuses_to_completeness(tmp_path: Path) -> None:
    document, check = _doctored(tmp_path, edit=lambda i, p: rec.truncate(p) if i == 1 else None)
    assert check["findings"]
    assert [t["test_system_status"] for t in document["integrity"]["trials"]] == ["COMPLETED"] * 3
    assert _check(document, "completeness")["findings"] == []


def test_a_recording_is_judged_only_when_its_file_is_present(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    (media / "mcap" / "trial-03.mcap").unlink()
    document = _run(folder, tmp_path, media)
    check = _check(document)
    assert check["applicable"] is True and check["findings"] == []
    assert check["percentage"] == 100
    assert "trial-03" in document["descriptor"]["success_copy"]
    assert "Not checked" in document["descriptor"]["success_copy"]


def test_a_missing_recording_is_not_a_recording_finding(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder, edit=lambda i, p: rec.truncate(p) if i == 2 else None)
    (media / "mcap" / "trial-01.mcap").unlink()
    check = _check(_run(folder, tmp_path, media))
    assert {i["trial_id"] for i in check["findings"]} == {"trial-02"}
    assert _categories(check)[0] == "mcap-incomplete"
    assert check["percentage"] == pytest.approx(50)


def test_with_no_recording_present_nothing_is_judged(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    for path in (media / "mcap").iterdir():
        path.unlink()
    document = _run(folder, tmp_path, media)
    check = _check(document)
    assert check["applicable"] is False and check["findings"] == [] and "limits" not in check
    assert document["integrity"]["run"]["percentage"] == 100


def test_a_recording_for_a_trial_the_plan_does_not_have_is_not_judged(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(
        tmp_path,
        folder,
        indexes=(1, 2, 3, 4),
        edit=lambda i, p: (rec.truncate(p) if i == 4 else None),
    )
    check = _check(_run(folder, tmp_path, media))
    assert check["findings"] == [] and check["percentage"] == 100


@pytest.mark.parametrize("path", ["../outside.mcap", "/etc/hostname", "", None, 7, "mcap/"])
def test_a_recording_path_that_leaves_the_media_directory_is_not_read(
    path: object, tmp_path: Path
) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    (tmp_path / "outside.mcap").write_bytes(b"x")
    rec.edit_media(media, lambda d: d["trials"][0]["mcap"].update(path=path))
    document = _run(folder, tmp_path, media)
    check = _check(document)
    assert "trial-01" not in {i["trial_id"] for i in check["findings"]}
    assert check["percentage"] == 100


def test_a_media_json_with_a_malformed_trial_list_is_not_applicable(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(trials="nope"))
    assert _check(_run(folder, tmp_path, media))["applicable"] is False


def test_text_from_evidence_is_shown_escaped(tmp_path: Path) -> None:
    folder = _evidence(tmp_path, channels=["/a<b>\u2028x"])
    media = _media(tmp_path, folder)
    document = _run(folder, tmp_path, media)
    assert base._validate(document) == []
    text = json.dumps({**document["descriptor"], "icon": ""})
    assert "<" not in text and ">" not in text
    assert "\\u003c" in text


def test_the_descriptor_keeps_what_was_not_checked_when_the_summary_is_long(
    tmp_path: Path,
) -> None:
    """The success copy is at most 400 characters. When the checks' sentences do not all fit, the
    sentences that say a check passed give way; a note about what was not checked never does."""
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    (media / "mcap" / "trial-03.mcap").unlink()
    document = _run(folder, tmp_path, media)
    copy = document["descriptor"]["success_copy"]
    assert len(copy) <= 400
    assert "Not checked: recording of trial-03" in copy
    assert copy.startswith("Every planned trial has its observation file.")


def test_the_command_line_takes_the_media_directory(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder, edit=lambda i, p: rec.truncate(p) if i == 1 else None)
    out = tmp_path / "result.json"
    assert main([str(folder / "manifest.json"), "--media", str(media), "--out", str(out)]) == 0
    assert "mcap-incomplete" in _categories(_check(json.loads(out.read_text(encoding="utf-8"))))
    out2 = tmp_path / "result2.json"
    assert main([str(folder / "manifest.json"), "--out", str(out2)]) == 0
    assert _check(json.loads(out2.read_text(encoding="utf-8")))["applicable"] is False


def test_the_media_directory_is_not_an_input_of_a_request(tmp_path: Path) -> None:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(_request("clean")), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate(source, out, tmp_path / "media") == 0
    assert _check(json.loads(out.read_text(encoding="utf-8")))["applicable"] is True


# A real recording.


def _real_media(tmp_path: Path) -> Path:
    """The real media.json, with the three identical Go1 recordings of that run."""
    media = tmp_path / "real-media"
    shutil.copytree(REAL, media)
    document = json.loads((media / "media.json").read_text(encoding="utf-8"))
    source = media / "mcap" / "trial-01.mcap"
    for entry in document["trials"]:
        target = media / entry["mcap"]["path"]
        if not target.exists():
            shutil.copy(source, target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == entry["mcap"]["sha256"]
    return media


def _real_outcome(media: Path, gap: object):
    document = json.loads((media / "media.json").read_text(encoding="utf-8"))
    observation = document["trials"][0]["observation_sha256"]
    results = {i: {"index": i, "sha256": observation} for i in (1, 2, 3)}
    manifest = {"plan": {"recording": {"max_gap_seconds": gap}}}
    return module().from_evidence(manifest, media, 3, results)


def test_the_real_run_media_passes(tmp_path: Path) -> None:
    outcome = _real_outcome(_real_media(tmp_path), 0.05)
    assert outcome.applicable and outcome.findings == []
    assert outcome.judged == 3 and outcome.percentage == 100
    assert outcome.limits == {"max_gap_seconds": 0.05}


def test_the_real_gap_equal_to_the_limit_is_not_a_finding(tmp_path: Path) -> None:
    outcome = _real_outcome(_real_media(tmp_path), 0.02)
    assert outcome.findings == []


def test_the_real_gap_over_a_tighter_limit_is_a_finding(tmp_path: Path) -> None:
    outcome = _real_outcome(_real_media(tmp_path), 0.0199)
    assert {i["category"] for i in outcome.findings} == {"message-gap-exceeded"}
    assert len(outcome.findings) == 6  # three trials, two channels
    assert outcome.findings[0]["summary"] == (
        "Channel /base_pose has a gap of 0.02 s, over the limit of 0.0199 s."
    )


def test_the_real_media_json_names_what_the_check_reads() -> None:
    document = json.loads((REAL / "media.json").read_text(encoding="utf-8"))
    assert document["format"] == "livingproof-hallway-media/2.0.0"
    entry = document["trials"][0]
    assert set(entry) >= {"index", "observation_sha256", "mcap"}
    assert set(entry["mcap"]) == {"path", "bytes", "sha256"}


# The request path: evidence['recording'] and each trial's recording.


def _request(name: str) -> dict:
    return json.loads((EXAMPLES / name / "request.json").read_text(encoding="utf-8"))


def _run_request(request: dict, tmp_path: Path) -> dict:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate(source, out) == 0
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["clean", "findings", "no-media"])
def test_the_contract_examples_give_the_contract_checks(name: str, tmp_path: Path) -> None:
    document = _run_request(_request(name), tmp_path)
    expected = json.loads((EXAMPLES / name / "result.json").read_text(encoding="utf-8"))
    for check in _checks(expected):
        assert _check(document, check["id"]) == check
    assert document["integrity"]["trials"] == expected["integrity"]["trials"]
    assert document["integrity"]["run"] == expected["integrity"]["run"]
    assert base._validate(document) == []


def test_only_recordings_completeness_reports_as_present_are_judged(tmp_path: Path) -> None:
    request = _request("findings")
    document = _run_request(request, tmp_path)
    judged = {i["trial_id"] for i in _check(document)["findings"]}
    assert "trial-absent-file" not in judged
    present = [
        t["id"] for t in request["integrity"]["trials"] if t["recording"]["state"] == "present"
    ]
    assert len(present) == 7
    assert _check(document)["percentage"] == pytest.approx(100 * 1 / 7)


def test_a_missing_recording_with_findings_in_the_evidence_is_still_not_judged(
    tmp_path: Path,
) -> None:
    request = _request("clean")
    request["integrity"]["trials"][0]["recording"] = {"state": "missing"}
    evidence = request["integrity"]["evidence"]["recording"]["trials"][0]
    evidence["mcap"]["state"] = "incomplete"
    check = _check(_run_request(request, tmp_path))
    assert check["findings"] == [] and check["percentage"] == 100


def test_a_request_without_recording_evidence_is_not_applicable(tmp_path: Path) -> None:
    request = _request("clean")
    del request["integrity"]["evidence"]["recording"]
    check = _check(_run_request(request, tmp_path))
    assert check == {
        "id": "recording",
        "version": "1.0.0",
        "applicable": False,
        "success": True,
        "findings": [],
    }


@pytest.mark.parametrize("key", ["max_gap_seconds", "required_channels"])
def test_a_request_that_omits_what_the_contract_requires_is_not_applicable(
    key: str, tmp_path: Path
) -> None:
    request = _request("clean")
    del request["integrity"]["evidence"]["recording"][key]
    check = _check(_run_request(request, tmp_path))
    assert check["applicable"] is False and "limits" not in check and check["findings"] == []


def test_a_request_with_no_trial_in_the_evidence_is_not_applicable(tmp_path: Path) -> None:
    request = _request("clean")
    request["integrity"]["evidence"]["recording"]["trials"] = []
    assert _check(_run_request(request, tmp_path))["applicable"] is False


# The contract's reference rules, against ours.


def _random_request(rng: random.Random) -> dict:
    n = rng.randint(0, 6)
    limit = rng.choice([0.05, 0.1, 0.5, 1, 2.5])
    required = rng.sample(["/base_pose", "/joint_states", "/contacts"], rng.randint(1, 3))
    topics = ["/base_pose", "/joint_states", "/contacts", "/extra"]
    sha = lambda: rng.choice(["a" * 64, "b" * 64])  # noqa: E731
    trials, entries = [], []
    for i in range(n):
        trial_id = f"t{i}"
        state = rng.choice(["present"] * 4 + ["missing"])
        trials.append({"id": trial_id, "recording": {"state": state}})
        if rng.random() < 0.1:
            continue
        mcap_sha, mcap_bytes = sha(), rng.choice([100, 200])
        channels = []
        for topic in rng.sample(topics, rng.randint(0, 4)):
            channels.append(
                {
                    "topic": topic,
                    "message_count": rng.choice([0, 5, 500]),
                    "backward_steps": rng.choice([0, 0, 0, 1, 3]),
                    "max_gap_seconds": rng.choice([0.02, 0.05, 0.1, 0.1, 0.5, 1, 2.5, 3]),
                }
            )
        link = sha()
        entries.append(
            {
                "id": trial_id,
                "mcap": {
                    "state": rng.choice(["complete"] * 4 + ["incomplete"]),
                    "bytes": mcap_bytes,
                    "sha256": mcap_sha,
                    "channels": channels,
                },
                "media": {
                    "mcap_bytes": rng.choice([mcap_bytes] * 4 + [mcap_bytes + 1]),
                    "mcap_sha256": rng.choice([mcap_sha] * 4 + [sha()]),
                    "observation_sha256": link,
                },
                "evidence_observation_sha256": rng.choice([link] * 4 + [sha()]),
            }
        )
    evidence: dict = {"media_available": rng.random() < 0.9}
    if evidence["media_available"]:
        evidence.update(required_channels=required, max_gap_seconds=limit, trials=entries)
    else:
        evidence["trials"] = []
    return {"trials": trials, "evidence": {"recording": evidence}}


def test_ours_equal_the_contract_reference_rules() -> None:
    sys.path.insert(0, str(base.CONTRACT / "tests"))
    import integrity_rules

    recording = module()
    rng = random.Random(8)
    seen: set[str] = set()
    not_applicable = 0
    for _ in range(600):
        request = _random_request(rng)
        expected = integrity_rules.recording(request)
        outcome = recording.from_request(request)
        assert outcome.applicable is expected["applicable"], request
        assert outcome.findings == expected["findings"], request
        if expected["applicable"]:
            assert outcome.percentage == pytest.approx(expected["percentage"]), request
            assert outcome.limits == expected["limits"], request
        else:
            assert outcome.limits is None
            not_applicable += 1
        seen.update(item["category"] for item in expected["findings"])
    assert seen == set(CATEGORIES)
    assert not_applicable > 20


# Cases the first pass left open (found by mutating the code).


def test_a_recording_that_is_a_link_out_of_the_media_directory_is_not_read(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    outside = tmp_path / "outside.mcap"
    rec.write_mcap(outside)
    target = media / "mcap" / "trial-01.mcap"
    target.unlink()
    target.symlink_to(outside)
    document = _run(folder, tmp_path, media)
    assert "trial-01" not in {i["trial_id"] for i in _check(document)["findings"]}
    assert "trial-01 (no file to read)" in document["descriptor"]["success_copy"]


@pytest.mark.parametrize("bad", [0, -1, -0.5, "0.1", True, None, float("nan"), float("inf")])
def test_a_request_with_an_unusable_limit_is_not_applicable(bad: object, tmp_path: Path) -> None:
    request = _request("clean")
    request["integrity"]["evidence"]["recording"]["max_gap_seconds"] = bad
    check = _check(_run_request(request, tmp_path))
    assert check["applicable"] is False and "limits" not in check and check["findings"] == []


@pytest.mark.parametrize("flag", [1, "true", "yes", None, [True]])
def test_media_available_must_be_true_itself(flag: object, tmp_path: Path) -> None:
    request = _request("clean")
    request["integrity"]["evidence"]["recording"]["media_available"] = flag
    assert _check(_run_request(request, tmp_path))["applicable"] is False


def test_a_recording_for_a_trial_with_no_result_row_is_not_judged(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    path = folder / "manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    del document["trials"]["results"][1]
    path.write_text(json.dumps(document), encoding="utf-8")
    result = _run(folder, tmp_path, media)
    check = _check(result)
    assert check["applicable"] is True and check["findings"] == []
    assert check["percentage"] == 100
    assert [i["category"] for i in _check(result, "completeness")["findings"]] == ["missing-trial"]
