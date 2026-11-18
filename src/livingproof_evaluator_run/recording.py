"""recording 1.0.0: every recording that is present is a usable MCAP file that matches the run.

The contract (livingproof-evaluator ``schema/integrity/checks/recording.schema.json`` and
``docs/run-integrity.md``, v1.1.0) fixes the rule. A recording that is present must be a complete
MCAP, hold every required channel with messages, have no timestamp that goes backwards, no gap
over the limit, the size and sha256 ``media.json`` records, and the observation digest the run
evidence records. Each breach is a test-system finding. ``percentage`` is 100 times the judged
recordings without a finding over the judged recordings, and with none judged the check is not
applicable. When applicable the check reports ``limits.max_gap_seconds``, equal to the evidence's.

The gap limit has no default. It comes from the evidence and nowhere else, and a gap equal to the
limit is not a finding (only a larger one is). Without a usable limit the check is not applicable
and says so; it never assumes one. The required channels come from the evidence too; on a
manifest, where a plan may leave them out, ``DEFAULT_REQUIRED_CHANNELS`` applies and the summary
says so. They are the two channels livingproof-sim-mujoco's media job always writes.

Where the evidence comes from:

* ``mcap/trial-NN.mcap`` and ``media.json`` (``livingproof-hallway-media/2.0.0``) are written by
  livingproof-sim-mujoco's ``media`` module in capability-verifier's ``media`` job and uploaded as
  the artifact ``<prefix>mcap-<configuration>``. The evidence manifest records neither, so on a
  manifest the media directory is a separate input (``--media DIR``). Without one there is no
  media and the check is not applicable;
* the gap limit and the channels are ``plan.recording.max_gap_seconds`` and
  ``plan.recording.required_channels`` in the manifest, else the same keys in the embedded
  lock's plan. Nothing declares them today, so a manifest is not judged until something does;
* each trial's observation digest is ``trials.results[].sha256`` in the manifest, which
  ``media.json`` repeats as ``observation_sha256``.

A recording is judged when its file is present: ``media.json`` lists its trial, the trial is in the
plan, and the file is there. A trial without a file is left to ``completeness`` (which, on a
manifest, does not look at recordings yet, so the summary names the trials not judged). The rules
are in ``judge`` and know nothing of where the facts came from, so a second recording per trial
(livingproof-sim-mujoco#108) is another reading step, not another rule.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from livingproof_evaluator_run import mcap_reader
from livingproof_evaluator_run.plain import shown

RECORDING_ID = "recording"
RECORDING_VERSION = "1.0.0"
# The contract's category enum, in the order the rules report them within a trial.
CATEGORIES = (
    "mcap-incomplete",
    "missing-channel",
    "timestamps-backwards",
    "message-gap-exceeded",
    "media-file-mismatch",
    "observation-link-mismatch",
)
# What a manifest's plan requires when it declares no channels: the two channels the media job
# always writes (``/base_pose`` and ``/joint_states``). Versioned with this check.
DEFAULT_REQUIRED_CHANNELS = ("/base_pose", "/joint_states")
MEDIA_FORMAT = "livingproof-hallway-media/2.0.0"
_TOPIC = re.compile(r"^/.+")
_LISTED = 5


@dataclass
class Channel:
    """One channel of a recording, as the contract's evidence records it."""

    topic: object
    message_count: object
    backward_steps: object
    max_gap_seconds: object


@dataclass
class Trial:
    """One present recording and the facts the rules compare."""

    id: str
    complete: bool
    bytes: object
    sha256: object
    channels: list[Channel]
    media_bytes: object
    media_sha256: object
    media_observation_sha256: object
    evidence_observation_sha256: object


@dataclass
class Outcome:
    """What the check found. ``applicable`` false means no recording was judged."""

    applicable: bool
    findings: list[dict] = field(default_factory=list)
    judged: int = 0
    failing: int = 0
    limits: dict | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        """100 times the judged recordings without a finding over the judged recordings."""
        return 100 * (self.judged - self.failing) / self.judged


def _finding(category: str, summary: str, trial_id: str) -> dict:
    return {
        "category": category,
        "classification": "test_system",
        "summary": summary,
        "trial_id": trial_id,
    }


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _over(value: object, limit: float) -> bool:
    """True when ``value`` is a gap over ``limit``. A value that is no number cannot be shown to
    be within it, so it counts as over."""
    return not _number(value) or value > limit  # type: ignore[operator]


def _same(left: object, right: object) -> bool:
    return isinstance(left, str) and left == right


def usable_limit(value: object) -> float | None:
    """The gap limit when it is a finite number above zero (not a boolean), else None."""
    if _number(value) and math.isfinite(value) and value > 0:  # type: ignore[arg-type]
        return value  # type: ignore[return-value]
    return None


def usable_channels(value: object) -> list[str] | None:
    """The required channels when it is a non-empty list of topics (``^/.+``), else None."""
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(topic, str) and _TOPIC.match(topic) for topic in value):
        return None
    return list(dict.fromkeys(value))


def judge(required_channels: list[str], max_gap_seconds: float, trials: list[Trial]) -> Outcome:
    """Judge each present recording. ``max_gap_seconds`` has no default: the caller takes it from
    the evidence. Findings follow the contract's order."""
    findings: list[dict] = []
    failing: set[str] = set()
    for trial in trials:
        mine: list[dict] = []
        if not trial.complete:
            mine.append(
                _finding(
                    "mcap-incomplete",
                    "The recording does not open or has no valid footer and summary.",
                    trial.id,
                )
            )
        channels = {channel.topic: channel for channel in trial.channels}
        for topic in required_channels:
            channel = channels.get(topic)
            if channel is None or not _number(channel.message_count) or channel.message_count == 0:
                mine.append(
                    _finding(
                        "missing-channel",
                        f"The required channel {shown(topic)} is absent or has no messages.",
                        trial.id,
                    )
                )
        for topic, channel in channels.items():
            name = shown(str(topic))
            steps = channel.backward_steps
            if not _number(steps) or steps > 0:  # type: ignore[operator]
                mine.append(
                    _finding(
                        "timestamps-backwards",
                        f"Channel {name} has {_say(steps)} timestamps that go backwards.",
                        trial.id,
                    )
                )
            if _over(channel.max_gap_seconds, max_gap_seconds):
                mine.append(
                    _finding(
                        "message-gap-exceeded",
                        f"Channel {name} has a gap of {_say(channel.max_gap_seconds)} s,"
                        f" over the limit of {max_gap_seconds} s.",
                        trial.id,
                    )
                )
        if not _same(trial.sha256, trial.media_sha256) or trial.bytes != trial.media_bytes:
            mine.append(
                _finding(
                    "media-file-mismatch",
                    "The recording's size or sha256 differs from media.json.",
                    trial.id,
                )
            )
        if not _same(trial.media_observation_sha256, trial.evidence_observation_sha256):
            mine.append(
                _finding(
                    "observation-link-mismatch",
                    "The observation_sha256 in media.json differs from the run evidence.",
                    trial.id,
                )
            )
        if mine:
            failing.add(trial.id)
            findings.extend(mine)
    if not trials:
        return Outcome(False)
    return Outcome(True, findings, len(trials), len(failing), {"max_gap_seconds": max_gap_seconds})


def _say(value: object) -> str:
    return str(value) if _number(value) else shown(json.dumps(value, default=str))


def _not_applicable(reason: str, notes: list[str] | None = None) -> Outcome:
    return Outcome(False, notes=[*(notes or []), f"Not checked: recording, {reason}."])


def _dig(document: object, *path: str) -> object:
    for key in path:
        if not isinstance(document, dict):
            return None
        document = document.get(key)
    return document


def from_request(integrity: dict) -> Outcome:
    """Check ``integrity.evidence['recording']`` against each trial's ``recording.state``."""
    evidence = _dig(integrity, "evidence", RECORDING_ID)
    if not isinstance(evidence, dict):
        return _not_applicable("the request carries no recording evidence")
    if evidence.get("media_available") is not True:
        return _not_applicable("the run has no media")
    limit = usable_limit(evidence.get("max_gap_seconds"))
    if limit is None:
        return _not_applicable(
            "the evidence declares no usable max_gap_seconds and there is no default"
        )
    channels = usable_channels(evidence.get("required_channels"))
    if channels is None:
        return _not_applicable("the evidence declares no usable required_channels")
    present = {
        item["id"]
        for item in integrity.get("trials") or []
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and _dig(item, "recording", "state") == "present"
    }
    trials: list[Trial] = []
    entries = evidence.get("trials")
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("id") not in present:
            continue
        mcap = entry.get("mcap") if isinstance(entry.get("mcap"), dict) else {}
        media = entry.get("media") if isinstance(entry.get("media"), dict) else {}
        found = mcap.get("channels")
        trials.append(
            Trial(
                id=entry["id"],
                complete=mcap.get("state") == "complete",
                bytes=mcap.get("bytes"),
                sha256=mcap.get("sha256"),
                channels=[
                    Channel(
                        item.get("topic"),
                        item.get("message_count"),
                        item.get("backward_steps"),
                        item.get("max_gap_seconds"),
                    )
                    for item in (found if isinstance(found, list) else [])
                    if isinstance(item, dict)
                ],
                media_bytes=media.get("mcap_bytes"),
                media_sha256=media.get("mcap_sha256"),
                media_observation_sha256=media.get("observation_sha256"),
                evidence_observation_sha256=entry.get("evidence_observation_sha256"),
            )
        )
    outcome = judge(channels, limit, trials)
    if not outcome.applicable:
        return _not_applicable("no recording is present to judge")
    return outcome


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _file(media: Path, name: object) -> Path | None:
    """The recording file ``name`` inside ``media``, or None when it is not a file there.

    The name must be a relative path that stays inside the directory, symlinks included.
    """
    if not isinstance(name, str) or not name:
        return None
    parts = PurePosixPath(name)
    if parts.is_absolute() or ".." in parts.parts:
        return None
    try:
        root = media.resolve()
        path = (media / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            return None
    except (OSError, ValueError):
        return None
    return path


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def _listed(ids: list[str]) -> str:
    if len(ids) <= _LISTED:
        return ", ".join(ids)
    return f"{', '.join(ids[:_LISTED])} and {len(ids) - _LISTED} more"


def from_evidence(
    manifest: dict, media: Path | None, planned: int, results: dict[int, dict]
) -> Outcome:
    """Check the recordings in the ``media`` directory against a manifest's trial digests.

    ``results`` are the manifest's result rows by index. ``media`` is the directory holding
    ``media.json`` and ``mcap/``, or None when the run has no media.
    """
    if media is None:
        return _not_applicable("no media was given")
    media = Path(media)
    document = _read_json(media / "media.json")
    if not isinstance(document, dict):
        return _not_applicable("there is no readable media.json in the media directory")
    fmt = document.get("format")
    if fmt != MEDIA_FORMAT:
        return _not_applicable(
            f"media.json is {shown(str(fmt))}, and this check reads {MEDIA_FORMAT}"
        )
    listed = document.get("trials")
    if not isinstance(listed, list):
        return _not_applicable("media.json lists no trials")
    limit = usable_limit(_dig(manifest, "plan", RECORDING_ID, "max_gap_seconds")) or usable_limit(
        _dig(manifest, "lock", "content", "plan", RECORDING_ID, "max_gap_seconds")
    )
    if limit is None:
        return _not_applicable(
            "the evidence declares no usable max_gap_seconds and there is no default"
        )
    declared = _dig(manifest, "plan", RECORDING_ID, "required_channels")
    channels = usable_channels(declared)
    if channels is None:
        declared = _dig(manifest, "lock", "content", "plan", RECORDING_ID, "required_channels")
        channels = usable_channels(declared)
    notes: list[str] = []
    if channels is None:
        why = "the plan declares none" if declared is None else "the plan's list is not usable"
        channels = list(DEFAULT_REQUIRED_CHANNELS)
        notes.append(f"Recording: required channels are the default {', '.join(channels)} ({why}).")
    by_index: dict[int, dict] = {}
    for entry in listed:
        index = entry.get("index") if isinstance(entry, dict) else None
        if isinstance(index, int) and not isinstance(index, bool) and index not in by_index:
            by_index[index] = entry
    trials: list[Trial] = []
    skipped: list[str] = []
    for index in range(1, planned + 1):
        row = results.get(index)
        if row is None:
            continue  # no trial evidence: completeness reports it
        trial_id = f"trial-{index:02d}"
        entry = by_index.get(index)
        mcap = entry.get("mcap") if entry and isinstance(entry.get("mcap"), dict) else {}
        path = _file(media, mcap.get("path"))
        if entry is None or path is None:
            skipped.append(trial_id)
            continue
        inspection = mcap_reader.inspect(path)
        recorded_bytes = mcap.get("bytes")
        trials.append(
            Trial(
                id=trial_id,
                complete=inspection.complete,
                bytes=path.stat().st_size,
                sha256=_digest(path),
                channels=[
                    Channel(c.topic, c.message_count, c.backward_steps, c.max_gap_seconds)
                    for c in inspection.channels
                ],
                media_bytes=recorded_bytes if _number(recorded_bytes) else None,
                media_sha256=mcap.get("sha256"),
                media_observation_sha256=entry.get("observation_sha256"),
                evidence_observation_sha256=row.get("sha256"),
            )
        )
    if skipped:
        notes.append(f"Not checked: recording of {_listed(skipped)} (no file to read).")
    outcome = judge(channels, limit, trials)
    if not outcome.applicable:
        return _not_applicable(
            "no recording file is present to judge", notes[-1:] if skipped else []
        )
    outcome.notes = notes
    return outcome
