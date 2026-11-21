"""recording 1.2.0: every recording that is present is a usable MCAP file that matches the run.

The contract (livingproof-evaluator ``schema/integrity/checks/recording.schema.json`` and
``docs/run-integrity.md``, v1.2.0) fixes the rule. A recording that is present must hold every
required channel with messages, have no timestamp that goes backwards, no gap over the limit
(measured in log-time order), the size and sha256 ``media.json`` records, and the observation
digest the run evidence records. Each breach is a test-system finding. ``percentage`` is 100 times
the judged recordings without a finding over the judged recordings, and with none judged the
check is not applicable. When applicable the check reports ``limits.max_gap_seconds``, equal to
the evidence's.

*Present* means readable. A recording that is missing, truncated (a file with no valid footer and
summary) or empty is not present. ``completeness`` reports it (``missing-recording``,
``truncated-recording``, ``empty-recording``), so it is reported once: this check does not judge
it, never emits ``mcap-incomplete`` and lists the trial in ``not_checked`` with the reason
``not-present``. A trial with no recording evidence at all is listed with ``not-recorded``. Every
trial that was not judged is listed when the check runs. ``not_checked`` is required at
1.1.0 and is empty when every trial was judged, when there is no media, and when no usable
gap limit was declared. ``mcap-incomplete`` is a finding of 1.0.0 only;
``version="1.0.0"`` selects the 1.0.0 rule, which judges such a file and has no ``not_checked``.

A request whose trial says the recording is ``present`` while its evidence says the file is
incomplete is inconsistent: no reliable result can come from it, and it would hide a truncation
that nothing reports. From 1.1.0 it raises ``MalformedRequest``, which the driver turns into exit
status 2 and no result. The producer's own reading classifies such a file as truncated instead.

The gap limit has no default. It comes from the evidence and nowhere else, and a gap equal to the
limit is not a finding (only a larger one is). Without a usable limit the check is not applicable
and says so, with an empty ``not_checked`` (the same as no media) and one note about the
missing limit; it never assumes one, and it does not list each trial as ``not-recorded``. The required channels come from the evidence too; on a
manifest, where a plan may leave them out, ``DEFAULT_REQUIRED_CHANNELS`` applies and the summary
says so. They are the two channels livingproof-sim-mujoco's media job always writes.

Where the evidence comes from:

* ``mcap/trial-NN.mcap`` and ``media.json`` (``livingproof-hallway-media/2.0.0``, 2.1.0 or 2.2.0;
  2.2.0 adds ``mcap/trial-NN.robot.mcap``, judged too, see ``_add_robot``) are written by
  livingproof-sim-mujoco's ``media`` module in capability-verifier's ``media`` job and uploaded as
  the artifact ``<prefix>mcap-<configuration>``. The evidence manifest records neither, so on a
  manifest the media directory is a separate input (``--media DIR``). Without one there is no
  media and the check is not applicable. ``read_media`` reads the directory once, and both this
  check and ``completeness`` use what it read;
* the gap limit and the channels are ``plan.recording.max_gap_seconds`` and
  ``plan.recording.required_channels`` in the manifest, else the same keys in the embedded
  lock's plan. Nothing declares them today, so a manifest is not judged until something does;
* each trial's observation digest is ``trials.results[].sha256`` in the manifest, which
  ``media.json`` repeats as ``observation_sha256``.

``media.json`` lists a trial's recording. If the file is there and readable it is judged. If it is
missing, truncated or empty, ``completeness`` reports it and this check lists the trial. If
``media.json`` does not list the trial, nothing was recorded for it: ``not-recorded``. The rules
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
RECORDING_VERSION = "1.2.0"
PREVIOUS_VERSIONS = ("1.0.0", "1.1.0")
# What a 1.0.0 ``mcap-incomplete`` finding says when the reader refused the file for its size
# (``mcap_reader.Caps``) instead of failing to open it. From 1.2.0 such a file is present and
# judged: ``recording-over-limit`` names the cap and its value (livingproof-evaluator#42), and
# ``completeness`` reports nothing. At 1.1.0 it was ``truncated`` and listed ``not-present``.
CAP_SUMMARY = (
    "The recording expands past the evaluator's size limit when decompressed, so it was not read."
)
# The contract's category enum, in the order the rules report them within a trial.
CATEGORIES = (
    "mcap-incomplete",
    "missing-channel",
    "timestamps-backwards",
    "message-gap-exceeded",
    "media-file-mismatch",
    "observation-link-mismatch",
    "recording-over-limit",
)
_OVER_LIMIT_UNITS = {
    "chunk-bytes": "bytes",
    "total-bytes": "bytes",
    "records": None,
    "chunks": None,
}
# What a manifest's plan requires when it declares no channels: the two channels the media job
# always writes (``/base_pose`` and ``/joint_states``). Versioned with this check.
DEFAULT_REQUIRED_CHANNELS = ("/base_pose", "/joint_states")
MEDIA_FORMAT = "livingproof-hallway-media/2.0.0"
# 2.1.0 adds a per-trial binding file and 2.2.0 a per-trial ``robot_mcap``; both are additive, so
# the 2.0.0 fields are read the same way. Only 2.2.0 lists a robot recording to judge.
MEDIA_FORMATS = (
    MEDIA_FORMAT,
    "livingproof-hallway-media/2.1.0",
    "livingproof-hallway-media/2.2.0",
)
ROBOT_FORMAT = MEDIA_FORMATS[-1]
_TOPIC = re.compile(r"^/.+")
_LISTED = 5


class MalformedRequest(ValueError):
    """The request is inconsistent, so no check result can be trusted (the contract's rule, from
    recording 1.1.0). The evaluator rejects it: no result is written and the exit status is 2."""


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
    cap_exceeded: bool = False
    # From 1.2.0, the reader's cap that the file hit and its value: ``(limit, value)``.
    over_limit: tuple[str, int] | None = None


@dataclass
class Outcome:
    """What the check found. ``applicable`` false means no recording was judged."""

    applicable: bool
    findings: list[dict] = field(default_factory=list)
    judged: int = 0
    failing: int = 0
    limits: dict | None = None
    notes: list[str] = field(default_factory=list)
    version: str = RECORDING_VERSION
    # Every trial not judged, as the contract's ``not_checked`` items. None at 1.0.0.
    not_checked: list[dict] | None = None

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


def judge(
    required_channels: list[str],
    max_gap_seconds: float,
    trials: list[Trial],
    version: str = RECORDING_VERSION,
    *,
    truncation_once: bool = False,
) -> Outcome:
    """Judge each present recording. ``max_gap_seconds`` has no default: the caller takes it from
    the evidence. Findings follow the contract's order. ``not_checked`` is the caller's to set.

    At 1.1.0 a recording is judged only when it is present, so a trial that is not ``complete``
    never reaches here and is a programming error. At 1.0.0, which the contract keeps valid, an
    incomplete recording gets ``mcap-incomplete`` and a ``missing-channel`` for each required
    channel its channel list lacks, exactly as the contract's 1.0.0 rule says. With
    ``truncation_once`` it gets ``mcap-incomplete`` and no ``missing-channel``, since the reader
    could not read it and its absent channels say nothing more (livingproof-evaluator#34). Only
    the evidence path sets it; a request is judged by the contract.
    """
    old = version == "1.0.0"
    v12 = version not in ("1.0.0", "1.1.0")
    findings: list[dict] = []
    failing: set[str] = set()
    for trial in trials:
        mine: list[dict] = []
        if v12 and trial.over_limit is not None:
            # The reader stopped at a cap, so nothing else can be said of this recording: the
            # trial is judged and fails closed with this one finding.
            findings.append(
                _finding("recording-over-limit", over_limit_summary(*trial.over_limit), trial.id)
            )
            failing.add(trial.id)
            continue
        if not trial.complete:
            if not old:
                raise ValueError(
                    f"trial {trial.id}: an incomplete recording is not judged at 1.1.0"
                )
            mine.append(
                _finding(
                    "mcap-incomplete",
                    CAP_SUMMARY
                    if trial.cap_exceeded
                    else "The recording does not open or has no valid footer and summary.",
                    trial.id,
                )
            )
        channels = {channel.topic: channel for channel in trial.channels}
        for topic in [] if truncation_once and not trial.complete else required_channels:
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
        return Outcome(False, version=version)
    return Outcome(
        True,
        findings,
        len(trials),
        len(failing),
        {"max_gap_seconds": max_gap_seconds},
        version=version,
    )


def over_limit_summary(limit: object, value: object) -> str:
    """What the contract's ``recording-over-limit`` summary says: the cap and its value."""
    unit = _OVER_LIMIT_UNITS.get(limit) if isinstance(limit, str) else None
    measured = f"{_say(value)} {unit}" if unit else _say(value)
    return (
        f"The recording expands past the reader's {shown(str(limit))} limit of {measured},"
        " so it was not fully read."
    )


def _say(value: object) -> str:
    return str(value) if _number(value) else shown(json.dumps(value, default=str))


def _not_applicable(
    reason: str,
    version: str = RECORDING_VERSION,
    not_checked: list[dict] | None = None,
    notes: list[str] | None = None,
) -> Outcome:
    """Not applicable. ``not_checked`` lists the trials that were not judged (1.1.0 only)."""
    return Outcome(
        False,
        notes=[*(notes or []), f"Not checked: recording, {reason}."],
        version=version,
        not_checked=None if version == "1.0.0" else (not_checked or []),
    )


def _items(ids: list[str], states: dict[str, str], judged: set[str]) -> list[dict]:
    """The ``not_checked`` items for the trials in ``ids`` that were not judged: ``not-present``
    for a recording that is not present, else ``not-recorded``. Each trial is listed once."""
    items = []
    for trial_id in dict.fromkeys(ids):
        if trial_id in judged:
            continue
        reason = "not-present" if states.get(trial_id, "present") != "present" else "not-recorded"
        items.append({"trial_id": trial_id, "reason": reason})
    return items


def _dig(document: object, *path: str) -> object:
    for key in path:
        if not isinstance(document, dict):
            return None
        document = document.get(key)
    return document


def from_request(integrity: dict, version: str = RECORDING_VERSION) -> Outcome:
    """Check ``integrity.evidence['recording']`` against each trial's ``recording.state``.

    At 1.1.0 a trial whose state is ``present`` and whose evidence says the file is incomplete is
    inconsistent, and ``MalformedRequest`` is raised before anything is judged.
    """
    evidence = _dig(integrity, "evidence", RECORDING_ID)
    if not isinstance(evidence, dict):
        return _not_applicable("the request carries no recording evidence", version)
    if evidence.get("media_available") is not True:
        return _not_applicable("the run has no media", version)
    listed = integrity.get("trials") if isinstance(integrity.get("trials"), list) else []
    states: dict[str, str] = {}
    for item in listed:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            states.setdefault(item["id"], str(_dig(item, "recording", "state")))
    present = {trial_id for trial_id, state in states.items() if state == "present"}
    entries = evidence.get("trials") if isinstance(evidence.get("trials"), list) else []
    if version != "1.0.0":
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("id") not in present:
                continue
            if _dig(entry, "mcap", "state") != "complete":
                if version not in ("1.1.0",) and isinstance(entry.get("over_limit"), dict):
                    continue  # the reader stopped at a cap, so the footer may be unknown
                raise MalformedRequest(
                    f"trial {entry['id']}: recording.state is present but evidence.recording"
                    " says the file is incomplete. A file with no valid footer is truncated:"
                    " classify it as truncated."
                )
    ids = [
        item["id"] for item in listed if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]

    def unjudged(judged: set[str]) -> list[dict]:
        """A recording that is not present is ``not-present``. A present one that was not judged,
        because the evidence has no entry for it or the check could not run, was never read."""
        return _items(ids, states, judged)

    limit = usable_limit(evidence.get("max_gap_seconds"))
    if limit is None:
        return _not_applicable(
            "the evidence declares no usable max_gap_seconds and there is no default",
            version,
            unjudged(set()),
        )
    channels = usable_channels(evidence.get("required_channels"))
    if channels is None:
        return _not_applicable(
            "the evidence declares no usable required_channels", version, unjudged(set())
        )
    trials: list[Trial] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") not in present:
            continue
        mcap = entry.get("mcap") if isinstance(entry.get("mcap"), dict) else {}
        media = entry.get("media") if isinstance(entry.get("media"), dict) else {}
        found = mcap.get("channels")
        hit = entry.get("over_limit") if isinstance(entry.get("over_limit"), dict) else None
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
                over_limit=(hit.get("limit"), hit.get("value")) if hit else None,  # type: ignore[arg-type]
            )
        )
    outcome = judge(channels, limit, trials, version)
    if not outcome.applicable:
        return _not_applicable("no recording is present to judge", version, unjudged(set()))
    outcome.not_checked = None if version == "1.0.0" else unjudged({t.id for t in trials})
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


def listed_ids(ids: list[str]) -> str:
    """Trial ids for a sentence: the first few, then a count of the rest."""
    if len(ids) <= _LISTED:
        return ", ".join(ids)
    return f"{', '.join(ids[:_LISTED])} and {len(ids) - _LISTED} more"


@dataclass
class Listed:
    """A recording ``media.json`` lists for a planned trial, as read from the media directory.

    ``state`` is the contract's ``recording.state``: ``missing`` when the file is not there (or the
    listed path is not a file inside the directory), ``empty`` for a file of no bytes,
    ``truncated`` for one with no valid footer and summary, else ``present``.
    """

    index: int
    state: str
    entry: dict
    mcap: dict
    path: Path | None = None
    inspection: mcap_reader.Inspection | None = None
    # The robot recording (2.2.0 only): its listing, file and reading. ``robot`` is False for an
    # earlier format, which lists none; a 2.2.0 entry that lists none or a file that is not there
    # has ``robot`` True and no ``robot_path``.
    robot: bool = False
    robot_entry: dict = field(default_factory=dict)
    robot_path: Path | None = None
    robot_inspection: mcap_reader.Inspection | None = None


@dataclass
class MediaRead:
    """What the media directory holds for a run. ``problem`` says why nothing could be read from
    it (no readable media.json, another format, no trial list); ``listed`` is by trial index."""

    problem: str | None = None
    # Why a ``media.json`` that is present is refused (#38, #41): unreadable, no text ``format``,
    # or a format this check does not know. A broken media file is an integrity failure, not an
    # opt-out, so it is reported as a finding and is not skipped.
    refusal: str | None = None
    listed: dict[int, Listed] = field(default_factory=dict)

    def state(self, index: int) -> str | None:
        """The listed recording's state, or None when ``media.json`` does not list the trial."""
        found = self.listed.get(index)
        return found.state if found else None


def read_media(media: Path | None, planned: int, results: dict[int, dict]) -> MediaRead | None:
    """Read the recordings ``media.json`` lists for the planned trials that have trial evidence.

    ``results`` are the manifest's result rows by index: a trial without one is left to
    ``completeness`` (``missing-trial``) and is not read. Every file is opened once. ``None``
    when there is no media directory.
    """
    if media is None:
        return None
    media = Path(media)
    document = _read_json(media / "media.json")
    if not isinstance(document, dict):
        problem = "there is no readable media.json in the media directory"
        if (media / "media.json").exists():
            return MediaRead(problem, refusal="media.json is not readable as a JSON object")
        return MediaRead(problem)
    fmt = document.get("format")
    known = ", ".join(MEDIA_FORMATS)
    if not isinstance(fmt, str):
        return MediaRead(
            f"media.json has no format that is text, and this check reads {known}",
            refusal=f"media.json has no format that is text; this check reads {known}",
        )
    if fmt not in MEDIA_FORMATS:
        return MediaRead(
            f"media.json is {shown(str(fmt))}, and this check reads {known}",
            refusal=f"media.json is format {shown(fmt)}, which this check does not know; "
            f"it reads {known}",
        )
    listing = document.get("trials")
    if not isinstance(listing, list):
        return MediaRead("media.json lists no trials")
    by_index: dict[int, dict] = {}
    for entry in listing:
        index = entry.get("index") if isinstance(entry, dict) else None
        if isinstance(index, int) and not isinstance(index, bool) and index not in by_index:
            by_index[index] = entry
    read = MediaRead()
    for index in range(1, planned + 1):
        if index not in results or index not in by_index:
            continue
        entry = by_index[index]
        mcap = entry.get("mcap") if isinstance(entry.get("mcap"), dict) else {}
        path = _file(media, mcap.get("path"))
        if path is None:
            read.listed[index] = Listed(index, "missing", entry, mcap)
        elif path.stat().st_size == 0:
            read.listed[index] = Listed(index, "empty", entry, mcap, path)
        else:
            inspection = mcap_reader.inspect(path)
            # A file the reader refused at a cap is present (recording 1.2.0): it is judged and
            # reported as ``recording-over-limit``, not as truncation.
            state = "present" if inspection.complete or inspection.cap_exceeded else "truncated"
            read.listed[index] = Listed(index, state, entry, mcap, path, inspection)
        if fmt == ROBOT_FORMAT:
            found = read.listed[index]
            found.robot = True
            robot = entry.get("robot_mcap")
            found.robot_entry = robot if isinstance(robot, dict) else {}
            found.robot_path = _file(media, found.robot_entry.get("path"))
            if found.robot_path is not None and found.robot_path.stat().st_size > 0:
                found.robot_inspection = mcap_reader.inspect(found.robot_path)
    return read


def _add_robot(
    outcome: Outcome,
    read: MediaRead,
    limit: float,
    results: dict[int, dict],
    judged: set[str],
    version: str,
) -> None:
    """Judge the robot recording of each judged trial that media 2.2.0 lists one for.

    The robot file gets the same structure, timestamp, gap and media.json size and sha256 rules as
    the sim file, but no required channel: a robot that publishes nothing has an empty file. Its
    observation link is the sim file's, so it is not compared again. A listing that is absent, a
    file that is not there, empty or not a usable MCAP is ``media-file-mismatch``. A trial with a
    finding in either file fails, and stays one judged trial.
    """
    added: list[dict] = []
    for index, found in sorted(read.listed.items()):
        trial_id = f"trial-{index:02d}"
        if not found.robot or trial_id not in judged:
            continue
        inspection = found.robot_inspection
        usable = inspection is not None and (
            inspection.complete or (inspection.cap_exceeded and version not in ("1.1.0",))
        )
        if found.robot_path is None or not usable:
            # One category, three causes, each said plainly.
            if not found.robot_entry.get("path"):
                why = "The robot recording is not listed in media.json."
            elif found.robot_path is None:
                why = "The robot recording media.json lists is missing from the media directory."
            else:
                why = "The robot recording is not a usable MCAP file."
            added.append(_finding("media-file-mismatch", why, trial_id))
            continue
        digest = (results.get(index) or {}).get("sha256")
        recorded = found.robot_entry.get("bytes")
        mine = Trial(
            id=trial_id,
            complete=inspection.complete,
            cap_exceeded=inspection.cap_exceeded,
            over_limit=inspection.over_limit,
            bytes=found.robot_path.stat().st_size,
            sha256=_digest(found.robot_path),
            channels=[
                Channel(c.topic, c.message_count, c.backward_steps, c.max_gap_seconds)
                for c in inspection.channels
            ],
            media_bytes=recorded if _number(recorded) else None,
            media_sha256=found.robot_entry.get("sha256"),
            media_observation_sha256=digest,
            evidence_observation_sha256=digest,
        )
        for finding in judge([], limit, [mine], version).findings:
            added.append({**finding, "summary": f"Robot recording: {finding['summary']}"})
    if not added:
        return
    outcome.findings = sorted(outcome.findings + added, key=lambda item: item["trial_id"])
    outcome.failing = len({item["trial_id"] for item in outcome.findings})


def declared_limit(manifest: dict):
    """The usable gap limit the evidence declares (plan, else the embedded lock's plan), or None."""
    return usable_limit(_dig(manifest, "plan", RECORDING_ID, "max_gap_seconds")) or usable_limit(
        _dig(manifest, "lock", "content", "plan", RECORDING_ID, "max_gap_seconds")
    )


def refused_without_limit(manifest: dict, read: MediaRead | None) -> str | None:
    """Why the evaluator must refuse, or None (#43).

    A ``media.json`` that is unreadable, has no text ``format`` or names an unknown version, with
    no usable gap limit declared, cannot be reported: a failing result needs a ``limits`` that
    does not exist, and a not-applicable one cannot carry a finding. So the run is refused (exit
    2, no result) and the message names the cause. A known version with no limit, and a media
    directory with no ``media.json``, are not refused.
    """
    if read is None or read.refusal is None or declared_limit(manifest) is not None:
        return None
    return f"{read.refusal}, and the evidence declares no gap limit"


def _refuse_broken_media(
    manifest: dict, read: MediaRead, ids: list[str], version: str
) -> Outcome | None:
    """A failing result for a ``media.json`` that is present but unusable, or None.

    Every trial gets a ``media-file-mismatch`` finding, so the run never reports success on
    recordings nobody judged. The result is applicable and carries the declared gap limit. With
    none declared this returns None and the not-applicable text names the cause: the contract
    lets only an applicable result carry findings (``applicable: false`` needs ``success: true``
    and no findings) and an applicable result needs a ``limits`` that cannot be invented (#41).
    """
    if read.refusal is None or not ids:
        return None
    limit = declared_limit(manifest)
    if limit is None:
        return None
    findings = [
        _finding("media-file-mismatch", f"{read.refusal}, so no recording was judged.", trial_id)
        for trial_id in ids
    ]
    return Outcome(
        True,
        findings,
        len(ids),
        len(ids),
        {"max_gap_seconds": limit},
        version=version,
        not_checked=None if version == "1.0.0" else [],
    )


def from_evidence(
    manifest: dict,
    media: Path | None,
    planned: int,
    results: dict[int, dict],
    version: str = RECORDING_VERSION,
    read: MediaRead | None = None,
) -> Outcome:
    """Check the recordings in the ``media`` directory against a manifest's trial digests.

    ``results`` are the manifest's result rows by index. ``media`` is the directory holding
    ``media.json`` and ``mcap/``, or None when the run has no media. A caller that has already
    read the directory passes ``read`` (``read_media``), so no file is opened twice.
    """
    old = version == "1.0.0"
    if read is None:
        read = read_media(media, planned, results)
    if read is None:
        # No media directory is not a finding about this run, so it adds no note: a note on every
        # run without media would push a pass sentence off the 400-character card.
        return Outcome(False, version=version, not_checked=None if old else [])
    ids = [f"trial-{index:02d}" for index in range(1, planned + 1) if index in results]
    if read.problem:
        refused = _refuse_broken_media(manifest, read, ids, version)
        return refused if refused is not None else _not_applicable(read.problem, version)
    # At 1.1.0 a file the reader refused at a cap was truncated, so it is ``not-present``.
    states = {
        f"trial-{i:02d}": "truncated"
        if version == "1.1.0" and found.inspection is not None and found.inspection.cap_exceeded
        else found.state
        for i, found in read.listed.items()
    }

    def unjudged(judged: set[str]) -> list[dict]:
        return _items(ids, states, judged)

    limit = usable_limit(_dig(manifest, "plan", RECORDING_ID, "max_gap_seconds")) or usable_limit(
        _dig(manifest, "lock", "content", "plan", RECORDING_ID, "max_gap_seconds")
    )
    if limit is None:
        # Same as no media: not applicable, empty not_checked, one note about the missing
        # limit. Per-trial not-recorded notes would push pass sentences off the 400-character
        # card, and not-recorded means a declared check could not be run; here nothing was
        # declared.
        return _not_applicable(
            "the evidence declares no usable max_gap_seconds and there is no default",
            version,
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
    trials: list[Trial] = []
    skipped: list[str] = []
    for index in range(1, planned + 1):
        found = read.listed.get(index)
        row = results.get(index)
        if found is None or row is None:
            continue
        trial_id = f"trial-{index:02d}"
        # 1.1.0 judges a recording only when it is present. 1.0.0 judged any file there was.
        refused = found.inspection is not None and found.inspection.cap_exceeded
        if found.path is None or (not old and found.state != "present"):
            skipped.append(trial_id)
            continue
        if version == "1.1.0" and refused:
            # 1.1.0 knew no finding for it: such a file was not readable, so it was not judged.
            skipped.append(trial_id)
            continue
        inspection = found.inspection or mcap_reader.inspect(found.path)
        recorded_bytes = found.mcap.get("bytes")
        trials.append(
            Trial(
                id=trial_id,
                complete=inspection.complete,
                cap_exceeded=inspection.cap_exceeded,
                over_limit=inspection.over_limit if not old else None,
                bytes=found.path.stat().st_size,
                sha256=_digest(found.path),
                channels=[
                    Channel(c.topic, c.message_count, c.backward_steps, c.max_gap_seconds)
                    for c in inspection.channels
                ],
                media_bytes=recorded_bytes if _number(recorded_bytes) else None,
                media_sha256=found.mcap.get("sha256"),
                media_observation_sha256=found.entry.get("observation_sha256"),
                evidence_observation_sha256=row.get("sha256"),
            )
        )
    if old and skipped:
        notes.append(f"Not checked: recording of {listed_ids(skipped)} (no file to read).")
    outcome = judge(channels, limit, trials, version, truncation_once=old)
    if outcome.applicable and not old:
        _add_robot(outcome, read, limit, results, {t.id for t in trials}, version)
    if not outcome.applicable:
        return _not_applicable(
            "no recording file is present to judge",
            version,
            unjudged(set()),
            notes[-1:] if old and skipped else [],
        )
    outcome.notes = notes
    outcome.not_checked = None if old else unjudged({trial.id for trial in trials})
    return outcome
