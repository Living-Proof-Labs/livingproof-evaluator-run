"""Hand checks from verifying PR 44 (#43), kept as tests.

With no usable gap limit a present but broken ``media.json`` is refused: exit 2, the cause on
stderr, no result. These pin what the crafted-input probe showed: a limit the check cannot use
(0, negative, text, a boolean) counts as no limit, a ``media.json`` that is a directory is
refused, a limit declared only in the lock is not refused, and a refusal leaves nothing new in
the output directory, through the command line as capability-verifier calls it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import recordings as rec
from test_recording import _check, _declare, _evidence, _media, _run

PREFIX = "livingproof-hallway-media/"
SRC = Path(__file__).resolve().parents[1] / "src"


def _cli(folder, media, out):
    command = [sys.executable, "-m", "livingproof_evaluator_run", str(folder / "manifest.json")]
    command += ["--media", str(media), "--out", str(out)]
    env = {"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin"}
    return subprocess.run(command, capture_output=True, text=True, env=env, check=False)


@pytest.mark.parametrize("gap", [0, -1, "5", True], ids=["zero", "negative", "text", "bool"])
def test_an_unusable_limit_is_no_limit_so_an_unknown_version_is_refused(gap, tmp_path):
    folder = _evidence(tmp_path, gap=gap)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(format=PREFIX + "3.0.0"))
    done = _cli(folder, media, tmp_path / "out" / "result.json")
    assert done.returncode == 2 and "declares no gap limit" in done.stderr
    assert not (tmp_path / "out").exists()


def test_a_media_json_that_is_a_directory_is_refused(tmp_path):
    folder = _evidence(tmp_path, gap=None)
    media = _media(tmp_path, folder)
    (media / "media.json").unlink()
    (media / "media.json").mkdir()
    done = _cli(folder, media, tmp_path / "out" / "result.json")
    assert done.returncode == 2 and "not readable" in done.stderr


def test_a_limit_declared_only_in_the_lock_is_not_refused(tmp_path):
    folder = _evidence(tmp_path, gap=None)
    _declare(folder, gap=0.05, where="lock")
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(format=PREFIX + "3.0.0"))
    check = _check(_run(folder, tmp_path, media))
    assert check["applicable"] is True and check["success"] is False


def test_a_refusal_adds_nothing_to_the_output_directory(tmp_path):
    folder = _evidence(tmp_path, gap=None)
    media = _media(tmp_path, folder)
    (media / "media.json").write_text("not json", encoding="utf-8")
    target = tmp_path / "evaluator-results"
    target.mkdir()
    (target / "specs-files.json").write_text("{}\n", encoding="utf-8")  # as cv copies it first
    done = _cli(folder, media, target / "result.json")
    assert done.returncode == 2 and done.stdout == ""
    assert sorted(p.name for p in target.iterdir()) == ["specs-files.json"]


def test_a_refusal_leaves_an_existing_out_file_as_it_was(tmp_path):
    """Characterises today's behaviour, the same as every other exit-1/exit-2 path: a file
    already at ``--out`` is neither written nor removed. Flagged for Rivet on PR 44; change this
    test if a refusal should remove it."""
    folder = _evidence(tmp_path, gap=None)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(format=PREFIX + "2.3.0"))
    out = tmp_path / "result.json"
    out.write_text('{"stale": true}\n', encoding="utf-8")
    assert _cli(folder, media, out).returncode == 2
    assert out.read_text(encoding="utf-8") == '{"stale": true}\n'
