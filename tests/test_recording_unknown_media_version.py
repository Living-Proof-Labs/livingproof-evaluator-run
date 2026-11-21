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


@pytest.mark.parametrize("content", ["not json", "[]", "7", '{"format": 1}'])
def test_an_unreadable_media_json_stays_not_applicable(content, tmp_path):
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    (media / "media.json").write_text(content, encoding="utf-8")
    check = _check(_run(folder, tmp_path, media))
    assert check["applicable"] is False and check["findings"] == []


def test_with_no_declared_gap_limit_the_check_still_cannot_report_a_finding(tmp_path):
    """An applicable result must carry the limit (the contract's schema), so with none declared
    the unknown version is only named in the not-applicable text. Flagged for Rivet."""
    check, document = _with_format(tmp_path, PREFIX + "3.0.0", gap=None)
    assert check["applicable"] is False
    assert "3.0.0" in document["descriptor"]["success_copy"]
