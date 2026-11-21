"""Hand checks from verifying PR 42 (#41), kept as tests.

A present but broken ``media.json`` fails the recording check when a gap limit is declared. These
pin what the crafted-input probe showed: every failing result conforms to the contract (v1.4.0),
the limit embedded in the lock counts as declared, a ``format`` that is a list and a
``media.json`` that is a directory are refused like the other causes, and a failing result with
no ``limits`` is rejected by the contract's schema, which is why the no-limit case cannot be a
result.
"""

from __future__ import annotations

import copy

import pytest
import recordings as rec
import test_completeness as base
from test_recording import _categories, _check, _declare, _evidence, _media, _run

PREFIX = "livingproof-hallway-media/"


def _document(tmp_path, change, **kwargs):
    folder = _evidence(tmp_path, **kwargs)
    media = _media(tmp_path, folder)
    change(folder, media)
    return _run(folder, tmp_path, media)


def _raw(content):
    return lambda _folder, media: (media / "media.json").write_text(content, encoding="utf-8")


def _format(value):
    return lambda _folder, media: rec.edit_media(media, lambda d: d.update(format=value))


def _directory(_folder, media):
    (media / "media.json").unlink()
    (media / "media.json").mkdir()


BROKEN = {
    "unreadable": _raw("not json"),
    "not-an-object": _raw("[]"),
    "format-int": _format(1),
    "format-list": _format([PREFIX + "2.0.0"]),
    "unknown-minor": _format(PREFIX + "2.3.0"),
    "unknown-major": _format(PREFIX + "3.0.0"),
    "other-string": _format("garbage"),
    "a-directory": _directory,
}


@pytest.mark.parametrize("change", BROKEN.values(), ids=BROKEN.keys())
def test_each_failing_result_conforms_to_the_contract(change, tmp_path):
    document = _document(tmp_path, change)
    check = _check(document)
    assert check["applicable"] is True and check["success"] is False
    assert set(_categories(check)) == {"media-file-mismatch"}
    assert base._validate(document) == []


@pytest.mark.parametrize("name", ["unreadable", "format-int", "unknown-major"])
def test_a_limit_declared_in_the_lock_counts_as_declared(name, tmp_path):
    def change(folder, media):
        _declare(folder, gap=None)
        _declare(folder, gap=0.05, where="lock")
        BROKEN[name](folder, media)

    check = _check(_document(tmp_path, change))
    assert check["applicable"] is True and check["success"] is False
    assert check["limits"] == {"max_gap_seconds": 0.05}


@pytest.mark.parametrize("variant", ["no-limits", "not-applicable-failing"])
def test_a_failing_result_without_a_limit_is_rejected_by_the_contract(variant, tmp_path):
    """Cody's contract claim on PR 42: neither shape the no-limit failure could take is valid."""
    document = copy.deepcopy(_document(tmp_path, BROKEN["unknown-major"]))
    check = _check(document)
    check.pop("limits")
    if variant == "not-applicable-failing":
        check.pop("percentage", None)
        check["applicable"] = False
    assert base._validate(document) != []
