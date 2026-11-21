"""An unknown media version fails loudly instead of reporting not applicable (#38).

Rivet's rule: every new ``livingproof-hallway-media`` version needs an explicit, tested addition
here, so a producer that ships a version this check has not learned is a failing finding that
names the version, never a silent skip (that is how 2.1.0 went unread).
"""

from __future__ import annotations

import json

import pytest
import recordings as rec
from livingproof_evaluator_run.__main__ import main
from livingproof_evaluator_run import recording
from livingproof_evaluator_run.evaluate import _planned_count, _results_by_index, evaluate_evidence
from test_recording import _check, _categories, _evidence, _media, _run

PREFIX = "livingproof-hallway-media/"


def _with_format(tmp_path, fmt, **kwargs):
    folder = _evidence(tmp_path, **kwargs)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(format=fmt))
    document = _run(folder, tmp_path, media)
    return _check(document), document


@pytest.mark.parametrize("version", ["2.3.0", "2.10.0"], ids=["minor", "double-digit-minor"])
def test_an_unknown_minor_version_fails_and_names_it(version, tmp_path):
    check, _ = _with_format(tmp_path, PREFIX + version)
    assert check["applicable"] is True and check["success"] is False
    assert _categories(check) == ["media-file-mismatch"] * 3
    assert all(version in f["summary"] for f in check["findings"])
    assert {f["trial_id"] for f in check["findings"]} == {"trial-01", "trial-02", "trial-03"}
    assert check["percentage"] == 0


@pytest.mark.parametrize("version", ["3.0.0", "1.0.0", "10.0.0"], ids=["major", "older", "far"])
def test_an_unknown_major_version_fails_and_names_it(version, tmp_path):
    check, document = _with_format(tmp_path, PREFIX + version)
    assert check["success"] is False and version in check["findings"][0]["summary"]
    assert document["integrity"]["run"]["success"] is False


def test_the_failure_says_which_versions_are_known(tmp_path):
    check, _ = _with_format(tmp_path, PREFIX + "2.3.0")
    summary = check["findings"][0]["summary"]
    for known in ("2.0.0", "2.1.0", "2.2.0"):
        assert known in summary


def test_a_format_string_of_another_kind_also_fails(tmp_path):
    check, _ = _with_format(tmp_path, "something-else/1")
    assert check["success"] is False and "something-else/1" in check["findings"][0]["summary"]


# 2.2.0 needs its robot files; test_recording_robot_mcap.py covers it.
@pytest.mark.parametrize("version", ["2.0.0", "2.1.0"])
def test_known_versions_behave_as_before(version, tmp_path):
    check, _ = _with_format(tmp_path, PREFIX + version)
    assert check["applicable"] is True and check["success"] is True and check["findings"] == []


def _broken(tmp_path, content, **kwargs):
    folder = _evidence(tmp_path, **kwargs)
    media = _media(tmp_path, folder)
    (media / "media.json").write_text(content, encoding="utf-8")
    document = _run(folder, tmp_path, media)
    return _check(document), document


# #41: a media.json that is present but broken is an integrity failure, not an opt-out.
BROKEN = ["not json", "", "[]", "7", '{"format": 1}', '{"format": null}', '{"trials": []}']


@pytest.mark.parametrize("content", BROKEN)
def test_a_broken_media_json_fails_with_a_declared_gap_limit(content, tmp_path):
    check, document = _broken(tmp_path, content)
    assert check["applicable"] is True and check["success"] is False
    assert _categories(check) == ["media-file-mismatch"] * 3
    assert "limits" in check and check["percentage"] == 0
    assert document["integrity"]["run"]["success"] is False


def _refused(tmp_path, capsys, content=None, fmt=None):
    """Run with no declared gap limit; returns (exit status, stderr, result path)."""
    folder = _evidence(tmp_path, gap=None)
    media = _media(tmp_path, folder)
    if content is not None:
        (media / "media.json").write_text(content, encoding="utf-8")
    if fmt is not None:
        rec.edit_media(media, lambda d: d.update(format=fmt))
    out = tmp_path / "result.json"
    capsys.readouterr()
    status = evaluate_evidence(folder / "manifest.json", out, media)
    return status, capsys.readouterr().err, out


# #43: with no gap limit a broken media.json cannot be an applicable finding (no limits to carry),
# so the evaluator refuses: exit 2, a message on stderr naming the cause, and no result.
@pytest.mark.parametrize(
    ("content", "cause"),
    [
        ("not json", "not readable"),
        ("", "not readable"),
        ("[]", "not readable"),
        ('{"format": 1}', "no format that is text"),
        ('{"format": null}', "no format that is text"),
        ('{"trials": []}', "no format that is text"),
    ],
)
def test_with_no_gap_limit_a_broken_media_json_is_refused_with_exit_2(
    content, cause, tmp_path, capsys
):
    status, err, out = _refused(tmp_path, capsys, content=content)
    assert status == 2 and not out.exists()
    assert cause in err and "declares no gap limit" in err and "no result written" in err


@pytest.mark.parametrize("version", ["3.0.0", "2.3.0"])
def test_with_no_gap_limit_an_unknown_version_is_refused_naming_it(version, tmp_path, capsys):
    status, err, out = _refused(tmp_path, capsys, fmt=PREFIX + version)
    assert status == 2 and not out.exists()
    assert PREFIX + version in err and PREFIX + "2.2.0" in err


def test_the_command_line_exits_2_and_writes_no_result(tmp_path, capsys):
    folder = _evidence(tmp_path, gap=None)
    media = _media(tmp_path, folder)
    (media / "media.json").write_text("not json", encoding="utf-8")
    out = tmp_path / "result.json"
    argv = [str(folder / "manifest.json"), "--out", str(out), "--media", str(media)]
    assert main(argv) == 2 and not out.exists()


def test_the_summary_says_what_is_wrong_with_media_json(tmp_path):
    unreadable, _ = _broken(tmp_path / "a", "not json")
    not_text, _ = _broken(tmp_path / "b", '{"format": 1}')
    assert "readable" in unreadable["findings"][0]["summary"]
    assert "text" in not_text["findings"][0]["summary"]


@pytest.mark.parametrize("version", ["2.0.0", "2.1.0"])
def test_a_known_version_with_no_declared_gap_limit_stays_not_applicable(version, tmp_path):
    check, _ = _with_format(tmp_path, PREFIX + version, gap=None)
    assert check["applicable"] is False and check["findings"] == []


def test_a_media_directory_with_no_media_json_stays_not_applicable(tmp_path):
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    (media / "media.json").unlink()
    check = _check(_run(folder, tmp_path, media))
    assert check["applicable"] is False and check["findings"] == []


# A known version with a broken body is refused like any other broken media.json: the docs say a
# media.json that cannot be judged is an integrity failure, not an opt-out.
KNOWN = ["2.0.0", "2.1.0", "2.2.0"]


def _without_trials(tmp_path, version, how, **kwargs):
    folder = _evidence(tmp_path, **kwargs)
    media = _media(tmp_path, folder)

    def edit(doc):
        doc["format"] = PREFIX + version
        if how == "missing":
            doc.pop("trials", None)
        else:
            doc["trials"] = how

    rec.edit_media(media, edit)
    return folder, media


BODIES = ["missing", "text", None, 7, {"index": 1}]


@pytest.mark.parametrize("how", BODIES, ids=["missing", "text", "null", "number", "object"])
@pytest.mark.parametrize("version", KNOWN)
def test_a_known_version_with_no_trials_list_fails_with_a_declared_gap_limit(
    version, how, tmp_path
):
    folder, media = _without_trials(tmp_path, version, how)
    document = _run(folder, tmp_path, media)
    check = _check(document)
    assert check["applicable"] is True and check["success"] is False
    assert _categories(check) == ["media-file-mismatch"] * 3
    assert "trials" in check["findings"][0]["summary"]
    assert document["integrity"]["run"]["success"] is False


@pytest.mark.parametrize("how", BODIES, ids=["missing", "text", "null", "number", "object"])
@pytest.mark.parametrize("version", KNOWN)
def test_a_known_version_with_no_trials_list_is_refused_with_no_gap_limit(
    version, how, tmp_path, capsys
):
    folder, media = _without_trials(tmp_path, version, how, gap=None)
    out = tmp_path / "result.json"
    capsys.readouterr()
    assert evaluate_evidence(folder / "manifest.json", out, media) == 2
    assert not out.exists() and "trials" in capsys.readouterr().err


def test_an_empty_trials_list_is_still_nothing_recorded_not_a_refusal(tmp_path):
    folder, media = _without_trials(tmp_path, "2.0.0", [])
    check = _check(_run(folder, tmp_path, media))
    assert check["findings"] == [] and check["applicable"] is False


# The guard #40 had and #42 dropped (without saying so): at the selectable recording 1.0.0 a broken
# media.json stays not applicable, as it was before any of this.
@pytest.mark.parametrize("fmt", [PREFIX + "3.0.0", None, 7])
def test_recording_1_0_0_does_not_turn_a_broken_media_json_into_findings(fmt, tmp_path):
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(format=fmt))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    results = _results_by_index(manifest)
    outcome = recording.from_evidence(manifest, media, _planned_count(manifest), results, "1.0.0")
    assert outcome.applicable is False and outcome.findings == []
    assert outcome.version == "1.0.0" and outcome.not_checked is None
