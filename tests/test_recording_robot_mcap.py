"""The recording check reads the robot MCAP as well as the sim MCAP (livingproof-evaluator-run#35).

livingproof-sim-mujoco #172 writes ``mcap/trial-NN.mcap`` (simulator ground truth) and
``mcap/trial-NN.robot.mcap`` (what the adapter published) per trial, and names both in
``media.json`` (``livingproof-hallway-media/2.2.0``: ``mcap`` plus ``robot_mcap``). The choices
made here, for review:

* the sim file is judged exactly as before, including the required channels;
* the robot file is judged for structure, timestamps, the gap limit, and size and sha256 against
  ``media.json``, but no channel is required of it (empty is fine until adapters publish);
* a trial fails when either file has a finding, and is still one judged trial;
* the findings are the contract's existing categories; a robot file that is missing, unlisted at
  2.2.0 or not a usable MCAP is ``media-file-mismatch``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import recordings as rec
from test_recording import _check, _categories, _doctored, _evidence, _media, _run

ESTIMATED = "/estimated_pose"


def _robot(tmp_path: Path, channels=None, *, fmt="livingproof-hallway-media/2.2.0", keep=True):
    """A run whose media is 2.2.0, with a robot file per trial holding ``channels``."""
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    entries = json.loads((media / "media.json").read_text())["trials"]
    for entry in entries:
        index = entry["index"]
        path = media / "mcap" / f"trial-{index:02d}.robot.mcap"
        rec.write_mcap(path, (channels or {}).get(index, {}))
        if keep:
            entry["robot_mcap"] = {
                "path": f"mcap/trial-{index:02d}.robot.mcap",
                "bytes": path.stat().st_size,
                "sha256": rec.sha256(path),
            }

    def change(document):
        document["format"] = fmt
        document["trials"] = entries

    rec.edit_media(media, change)
    return folder, media


def _check_of(tmp_path, folder, media):
    return _check(_run(folder, tmp_path, media))


@pytest.mark.parametrize(
    "fmt", ["livingproof-hallway-media/2.0.0", "livingproof-hallway-media/2.1.0"]
)
def test_earlier_media_formats_are_still_read(fmt, tmp_path):
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(media, lambda d: d.update(format=fmt))
    check = _check_of(tmp_path, folder, media)
    assert check["applicable"] and check["findings"] == []
    assert check["percentage"] == 100


def test_empty_robot_files_pass(tmp_path):
    folder, media = _robot(tmp_path)
    check = _check_of(tmp_path, folder, media)
    assert check["applicable"] is True and check["findings"] == []
    assert check["percentage"] == 100


def test_a_robot_file_with_estimated_pose_passes(tmp_path):
    folder, media = _robot(tmp_path, {i: {ESTIMATED: rec.steps(100)} for i in (1, 2, 3)})
    check = _check_of(tmp_path, folder, media)
    assert check["findings"] == [] and check["percentage"] == 100


def test_the_sim_file_still_needs_its_required_channels(tmp_path):
    """/base_pose in the robot file does not stand in for a sim file that lacks it."""
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder, channels={2: {rec.JOINTS: rec.steps(100)}})
    entries = json.loads((media / "media.json").read_text())["trials"]
    for entry in entries:
        path = media / "mcap" / f"trial-{entry['index']:02d}.robot.mcap"
        rec.write_mcap(path, {rec.POSE: rec.steps(100)} if entry["index"] == 2 else {})
        entry["robot_mcap"] = {
            "path": f"mcap/{path.name}",
            "bytes": path.stat().st_size,
            "sha256": rec.sha256(path),
        }
    rec.edit_media(
        media, lambda d: d.update(format="livingproof-hallway-media/2.2.0", trials=entries)
    )
    check = _check_of(tmp_path, folder, media)
    assert _categories(check) == ["missing-channel"]
    assert check["findings"][0]["trial_id"] == "trial-02"


def test_a_robot_file_whose_digest_differs_from_media_json_fails_that_trial(tmp_path):
    folder, media = _robot(tmp_path)
    path = media / "mcap" / "trial-02.robot.mcap"
    rec.write_mcap(path, {ESTIMATED: rec.steps(7)})  # not what media.json recorded
    check = _check_of(tmp_path, folder, media)
    assert _categories(check) == ["media-file-mismatch"]
    (finding,) = check["findings"]
    assert finding["trial_id"] == "trial-02" and "robot" in finding["summary"].lower()
    assert round(check["percentage"], 1) == round(100 * 2 / 3, 1)


def test_a_robot_file_with_timestamps_going_backwards_is_a_finding(tmp_path):
    times = rec.steps(50) + rec.steps(50, start=0)
    folder, media = _robot(tmp_path, {1: {ESTIMATED: times}})
    check = _check_of(tmp_path, folder, media)
    assert "timestamps-backwards" in _categories(check)
    assert {f["trial_id"] for f in check["findings"]} == {"trial-01"}


def test_a_robot_gap_over_the_limit_is_a_finding_but_a_short_one_is_not(tmp_path):
    long = rec.steps(10) + rec.steps(10, start=rec.steps(10)[-1] + 200_000_000)
    folder, media = _robot(tmp_path, {3: {ESTIMATED: long}})
    check = _check_of(tmp_path, folder, media)
    assert _categories(check) == ["message-gap-exceeded"]
    assert check["findings"][0]["trial_id"] == "trial-03"


def test_a_2_2_0_media_json_that_does_not_list_the_robot_file_is_a_finding(tmp_path):
    folder, media = _robot(tmp_path, keep=False)
    check = _check_of(tmp_path, folder, media)
    assert _categories(check).count("media-file-mismatch") == 3


def test_a_listed_robot_file_that_is_missing_or_unusable_is_a_finding(tmp_path):
    folder, media = _robot(tmp_path)
    (media / "mcap" / "trial-01.robot.mcap").unlink()
    rec.truncate(media / "mcap" / "trial-02.robot.mcap", 0.5)
    check = _check_of(tmp_path, folder, media)
    assert {f["trial_id"] for f in check["findings"]} == {"trial-01", "trial-02"}
    assert set(_categories(check)) == {"media-file-mismatch"}


def test_the_robot_file_is_not_read_when_the_format_predates_it(tmp_path):
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    rec.edit_media(
        media,
        lambda d: [t.update(robot_mcap={"path": "mcap/none.mcap"}) for t in d["trials"]],
    )
    assert _check_of(tmp_path, folder, media)["findings"] == []


def test_the_default_clean_run_is_unchanged(tmp_path):
    _, check = _doctored(tmp_path)
    assert check["findings"] == [] and check["percentage"] == 100
