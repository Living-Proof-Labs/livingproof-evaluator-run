"""An unknown media version fails loudly instead of reporting not applicable (#38).

Rivet's rule: every new ``livingproof-hallway-media`` version needs an explicit, tested addition
here, so a producer that ships a version this check has not learned is a failing finding that
names the version, never a silent skip (that is how 2.1.0 went unread).
"""

from __future__ import annotations

import pytest
import recordings as rec
from test_recording import _check, _categories, _evidence, _media, _run

PREFIX = "livingproof-hallway-media/"


def _with_format(tmp_path, fmt, **kwargs):
    folder = _evidence(tmp_path, **kwargs)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(format=fmt))
    return _check(_run(folder, tmp_path, media)), _run(folder, tmp_path, media)


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


@pytest.mark.parametrize("content", BROKEN)
def test_with_no_declared_gap_limit_a_broken_media_json_is_named_in_the_note(content, tmp_path):
    """The contract lets only an applicable result carry findings (``applicable: false`` requires
    ``success: true`` and no findings), and an applicable result must carry a ``limits`` that
    cannot be invented. So with no declared limit this stays not applicable but names the cause.
    Flagged for Rivet on #41."""
    check, document = _broken(tmp_path, content, gap=None)
    assert check["applicable"] is False and check["findings"] == []
    assert "media.json" in document["descriptor"]["success_copy"]


@pytest.mark.parametrize("version", ["3.0.0", "2.3.0"])
def test_with_no_declared_gap_limit_an_unknown_version_is_named_in_the_note(version, tmp_path):
    check, document = _with_format(tmp_path, PREFIX + version, gap=None)
    assert check["applicable"] is False and check["findings"] == []
    assert version in document["descriptor"]["success_copy"]


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
