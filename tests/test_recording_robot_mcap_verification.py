"""Checks made by hand while verifying livingproof-evaluator-run#35, kept as tests.

The fixtures under ``tests/fixtures/recording/sim-*`` are real output of livingproof-sim-mujoco
(v3.9.0 writes media 2.2.0 with a robot MCAP, v3.8.1 writes 2.1.0) from the toy hallway of its own
tests: ``sim-3.9.0-pub`` with an adapter that publishes ``/estimated_pose``, ``sim-3.9.0-toy`` with
one that publishes nothing (a valid MCAP with no message), ``sim-3.8.1-toy`` media 2.1.0. Trial 1
only. The run evidence is the synthetic ``termination/good`` one with trial 1's digest replaced by
the media's ``observation_sha256``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import recordings as rec
from test_recording import EVIDENCE, LIMIT, _categories, _check, _declare, _run

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recording"
ESTIMATED = "/estimated_pose"


def _real(tmp_path: Path, name: str) -> tuple[Path, Path]:
    media = tmp_path / "media"
    shutil.copytree(FIXTURES / name, media)
    folder = tmp_path / "evidence"
    shutil.copytree(EVIDENCE, folder)
    _declare(folder, gap=LIMIT)
    path = folder / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    observed = json.loads((media / "media.json").read_text(encoding="utf-8"))["trials"][0]
    manifest["trials"]["results"][0]["sha256"] = observed["observation_sha256"]
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return folder, media


def _relist(media: Path, key: str = "robot_mcap") -> None:
    """Make media.json agree with the file as it now is."""

    def change(document):
        entry = document["trials"][0][key]
        file = media / entry["path"]
        entry["bytes"], entry["sha256"] = file.stat().st_size, rec.sha256(file)

    rec.edit_media(media, change)


def _verdict(tmp_path, folder, media):
    return _check(_run(folder, tmp_path, media))


@pytest.mark.parametrize("name", ["sim-3.9.0-pub", "sim-3.9.0-toy"])
def test_real_sim_3_9_0_output_passes_with_or_without_robot_messages(name, tmp_path):
    folder, media = _real(tmp_path, name)
    check = _verdict(tmp_path, folder, media)
    assert check["applicable"] is True and check["findings"] == []
    assert check["percentage"] == 100
    document = json.loads((media / "media.json").read_text(encoding="utf-8"))
    assert document["format"] == "livingproof-hallway-media/2.2.0"
    assert (media / document["trials"][0]["robot_mcap"]["path"]).stat().st_size > 0


def test_real_sim_3_8_1_media_2_1_0_is_judged_not_skipped(tmp_path):
    folder, media = _real(tmp_path, "sim-3.8.1-toy")
    check = _verdict(tmp_path, folder, media)
    assert check["applicable"] is True and check["findings"] == []
    assert check["percentage"] == 100


@pytest.mark.parametrize("damage", ["empty", "garbage", "truncated"])
def test_a_real_robot_file_that_is_empty_garbage_or_cut_short_is_media_file_mismatch(
    damage, tmp_path
):
    folder, media = _real(tmp_path, "sim-3.9.0-pub")
    path = media / "mcap" / "trial-01.robot.mcap"
    if damage == "empty":
        path.write_bytes(b"")
    elif damage == "garbage":
        path.write_bytes(b"not an mcap")
    else:
        rec.truncate(path, 0.5)
    _relist(media)  # media.json agrees with the damaged file, so only the content is wrong
    check = _verdict(tmp_path, folder, media)
    assert _categories(check) == ["media-file-mismatch"]
    assert check["findings"][0]["trial_id"] == "trial-01"


def test_a_real_robot_file_with_a_changed_size_or_digest_is_media_file_mismatch(tmp_path):
    folder, media = _real(tmp_path, "sim-3.9.0-pub")
    rec.edit_media(media, lambda d: d["trials"][0]["robot_mcap"].update(bytes=1))
    assert _categories(_verdict(tmp_path, folder, media)) == ["media-file-mismatch"]
    folder, media = _real(tmp_path / "again", "sim-3.9.0-pub")
    rec.edit_media(media, lambda d: d["trials"][0]["robot_mcap"].update(sha256="0" * 64))
    assert _categories(_verdict(tmp_path / "again", folder, media)) == ["media-file-mismatch"]


@pytest.mark.parametrize("listing", ["junk", None, {"path": "../../etc/hostname"}, {"bytes": 1}])
def test_an_unusable_robot_listing_is_media_file_mismatch(listing, tmp_path):
    folder, media = _real(tmp_path, "sim-3.9.0-toy")

    def change(document):
        if listing is None:
            document["trials"][0].pop("robot_mcap")
        else:
            document["trials"][0]["robot_mcap"] = listing

    rec.edit_media(media, change)
    assert _categories(_verdict(tmp_path, folder, media)) == ["media-file-mismatch"]


def test_a_robot_gap_equal_to_the_limit_passes_and_one_step_over_does_not(tmp_path):
    step = rec.steps(10)[-1]
    equal = rec.steps(10) + rec.steps(10, start=step + round(LIMIT * 1e9))
    over = rec.steps(10) + rec.steps(10, start=step + round(LIMIT * 1e9) + 10_000_000)
    for index, (times, expected) in enumerate(((equal, []), (over, ["message-gap-exceeded"]))):
        base = tmp_path / str(index)
        folder, media = _real(base, "sim-3.9.0-pub")
        rec.write_mcap(media / "mcap" / "trial-01.robot.mcap", {ESTIMATED: times})
        _relist(media)
        assert _categories(_verdict(base, folder, media)) == expected


def test_a_trial_whose_sim_file_is_missing_is_left_to_completeness(tmp_path):
    """The robot file is judged only for a trial whose sim file was judged."""
    folder, media = _real(tmp_path, "sim-3.9.0-pub")
    (media / "mcap" / "trial-01.mcap").unlink()
    (media / "mcap" / "trial-01.robot.mcap").write_bytes(b"garbage")
    check = _verdict(tmp_path, folder, media)
    assert check["findings"] == []


@pytest.mark.parametrize("version", ["2.3.0", "3.0.0"])
def test_a_media_format_this_check_does_not_read_fails_and_names_it(version, tmp_path):
    """Refused, not skipped (#38): a failing finding that names the format."""
    folder, media = _real(tmp_path, "sim-3.9.0-pub")
    rec.edit_media(media, lambda d: d.update(format=f"livingproof-hallway-media/{version}"))
    document = _run(folder, tmp_path, media)
    check = _check(document)
    assert check["applicable"] is True and check["success"] is False
    assert {f["category"] for f in check["findings"]} == {"media-file-mismatch"}
    assert f"livingproof-hallway-media/{version}" in json.dumps(check["findings"])
