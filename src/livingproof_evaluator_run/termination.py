"""termination 1.0.0: every trial that ended on its own records a stop reason the plan allows.

The contract (livingproof-evaluator ``schema/integrity/checks/termination.schema.json`` and
``docs/run-integrity.md``, v1.1.0) fixes the rule and the vocabulary. A trial that ended on its
own records exactly one stop reason. A missing reason, one outside the vocabulary, one the plan
does not allow, and a trial record that disagrees with the manifest are test-system findings.

``completeness`` owns timeout and crash. A trial whose termination is ``timeout`` or ``crash`` is
never judged here and raises no finding: it is listed under ``referrals`` with the
``completeness`` category that reports it, so each ending is reported once. A referral is not a
finding and changes neither ``success`` nor ``percentage``. ``percentage`` is 100 times the
judged trials without a finding over the judged trials, and with no judged trial the check is not
applicable.

Where the evidence comes from (``livingproof-hallway-evidence/2.0.0``, as livingproof-sim-mujoco
writes it):

* the trial's stop reason is ``end`` in its observation file, ``trials/trial-NN.json``;
* the manifest copies it as ``trials.results[].outcome``, the other record it must agree with;
* the runner's words map to the contract's (``END_TO_STOP_REASON``): ``crossed_exit`` is
  ``mission-done``, ``left_hallway`` (hallway) and ``left_world`` (route) are ``left-world``, ``time_limit`` is ``time-limit`` and
  ``non_finite_state`` is ``simulation-broken``. A word that is not in the table is kept as
  written, so it is reported as unknown rather than passed;
* the plan's allowed list is ``plan.allowed_stop_reasons`` in the manifest, else the same key in
  the embedded lock's plan, else ``DEFAULT_ALLOWED_STOP_REASONS``. The default leaves out
  ``simulation-broken``, so a trial whose simulation broke is never allowed unless a plan says it
  is. A declaration that names no known stop reason is not used: the default applies and the
  summary says so. It can therefore never allow more than the default by being malformed.

Only trials that ``completeness`` found complete are judged on a manifest: a missing or
hash-mismatched trial file stays a ``completeness`` finding and is not repeated here. Nothing in
evidence 2.0.0 records a timeout or a crash (livingproof-sim-mujoco#105 and
capability-verifier#155 would), so on a manifest ``referrals`` is empty. On a
``livingproof-evaluator-request`` the trials carry ``termination``, and the check refers a
timeout or crash exactly as the contract's ``timeout-single-report`` example does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from livingproof_evaluator_run.plain import shown

TERMINATION_ID = "termination"
TERMINATION_VERSION = "1.0.0"
# The contract's stop reason vocabulary.
STOP_REASONS = (
    "time-limit",
    "mission-done",
    "left-world",
    "simulation-broken",
    "adapter-or-scenario-done",
)
# What a plan allows when it declares nothing. simulation-broken is deliberately absent.
DEFAULT_ALLOWED_STOP_REASONS = (
    "time-limit",
    "mission-done",
    "left-world",
    "adapter-or-scenario-done",
)
# The contract's category enum.
CATEGORIES = (
    "missing-stop-reason",
    "unknown-stop-reason",
    "disallowed-stop-reason",
    "stop-reason-mismatch",
)
# The runner's ``end`` values, as livingproof-sim-mujoco writes them, in the contract's words.
# adapter_done is the word the contract's own example data uses; no runner writes it today.
END_TO_STOP_REASON = {
    "crossed_exit": "mission-done",
    "left_hallway": "left-world",
    "left_world": "left-world",
    "time_limit": "time-limit",
    "non_finite_state": "simulation-broken",
    "adapter_done": "adapter-or-scenario-done",
}
# The completeness category that reports a trial that did not end on its own.
_COMPLETENESS_CATEGORY = {"timeout": "ended-by-timeout", "crash": "ended-by-crash"}


@dataclass
class Trial:
    """One trial as this check sees it. A stop reason is None when none was recorded."""

    id: str
    termination: str | None = None
    stop_reason: str | None = None
    manifest_stop_reason: str | None = None


@dataclass
class Outcome:
    """What the check found. ``applicable`` false means no trial was judged."""

    applicable: bool
    findings: list[dict] = field(default_factory=list)
    referrals: list[dict] = field(default_factory=list)
    judged: int = 0
    failing: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        """100 times the judged trials without a finding over the judged trials."""
        return 100 * (self.judged - self.failing) / self.judged


def _finding(category: str, summary: str, trial_id: str) -> dict:
    return {
        "category": category,
        "classification": "test_system",
        "summary": summary,
        "trial_id": trial_id,
    }


def allowed_stop_reasons(*declared: object) -> tuple[list[str], str | None]:
    """The plan's allowed list from the first source that declares a usable one.

    ``declared`` are the candidate declarations, most specific first. A usable one is a list with
    at least one name from the vocabulary; names outside it are ignored. With none usable the
    default applies. Returns the list and, when the default was used, a plain sentence saying so
    for the summary (None when the plan's own list was used).
    """
    for value in declared:
        if isinstance(value, list):
            names = [name for name in STOP_REASONS if name in value]
            if names:
                return names, None
    why = (
        "the plan declares none"
        if all(value is None for value in declared)
        else "the plan's list names no known stop reason"
    )
    return list(DEFAULT_ALLOWED_STOP_REASONS), (
        f"Stop reasons: the default allowed list, which excludes simulation-broken ({why})."
    )


def judge(allowed: list[str], trials: list[Trial]) -> Outcome:
    """Judge each trial that ended on its own. Findings follow the contract's order."""
    findings: list[dict] = []
    referrals: list[dict] = []
    judged = 0
    failing: set[str] = set()
    for trial in trials:
        if trial.termination in _COMPLETENESS_CATEGORY:
            referrals.append(
                {
                    "trial_id": trial.id,
                    "check": "completeness",
                    "category": _COMPLETENESS_CATEGORY[trial.termination],
                }
            )
            continue
        judged += 1
        reason = trial.stop_reason
        if reason is None:
            failing.add(trial.id)
            findings.append(
                _finding("missing-stop-reason", "The trial records no stop reason.", trial.id)
            )
        elif reason not in STOP_REASONS:
            failing.add(trial.id)
            findings.append(
                _finding(
                    "unknown-stop-reason",
                    f"The stop reason {shown(reason)} is not in the stop reason vocabulary.",
                    trial.id,
                )
            )
        elif reason not in allowed:
            failing.add(trial.id)
            findings.append(
                _finding(
                    "disallowed-stop-reason",
                    f"The stop reason {reason} is not one the plan allows.",
                    trial.id,
                )
            )
        manifest = trial.manifest_stop_reason
        if reason is not None and manifest not in (None, reason):
            failing.add(trial.id)
            findings.append(
                _finding(
                    "stop-reason-mismatch",
                    f"The trial records {shown(reason)} and the manifest records {shown(manifest)}.",
                    trial.id,
                )
            )
    return Outcome(judged > 0, findings, referrals, judged, len(failing))


def _recorded(value: object) -> str | None:
    """A recorded stop reason as text, or None when none was recorded. Text that is not a string
    is kept as JSON so that it is reported as unknown rather than ignored."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _runner_word(value: object) -> str | None:
    """A runner ``end`` in the contract's words. A word with no mapping is kept as written."""
    text = _recorded(value)
    return None if text is None else END_TO_STOP_REASON.get(text, text)


def _dig(document: object, *path: str) -> object:
    for key in path:
        if not isinstance(document, dict):
            return None
        document = document.get(key)
    return document


def _not_applicable(outcome: Outcome, reason: str) -> Outcome:
    outcome.notes.append(f"Not checked: termination, {reason}.")
    return outcome


def from_evidence(
    manifest: dict,
    manifest_path: Path,
    planned: int,
    results: dict[int, dict],
    complete: set[int],
) -> Outcome:
    """Check a ``livingproof-hallway-evidence/2.0.0`` manifest and its trial files.

    ``results`` are the manifest's result rows by index and ``complete`` the indexes
    ``completeness`` found complete; only those are judged.
    """
    allowed, note = allowed_stop_reasons(
        _dig(manifest, "plan", "allowed_stop_reasons"),
        _dig(manifest, "lock", "content", "plan", "allowed_stop_reasons"),
    )
    trials: list[Trial] = []
    for index in range(1, planned + 1):
        row = results.get(index)
        if index not in complete or row is None:
            continue
        observation = _read(manifest_path.parent / str(row.get("path")))
        trials.append(
            Trial(
                id=f"trial-{index:02d}",
                stop_reason=_runner_word(observation.get("end")),
                manifest_stop_reason=_runner_word(row.get("outcome")),
            )
        )
    outcome = judge(allowed, trials)
    if not outcome.applicable:
        return _not_applicable(outcome, "no trial has an observation file to read")
    if note:
        outcome.notes.append(note)
    return outcome


def _read(path: Path) -> dict:
    """The observation in a trial file, or an empty one when it is not a JSON object."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document if isinstance(document, dict) else {}


def from_request(integrity: dict) -> Outcome:
    """Check ``integrity.evidence['termination']`` against each trial's ``termination``."""
    evidence = _dig(integrity, "evidence", TERMINATION_ID)
    if not isinstance(evidence, dict):
        return _not_applicable(Outcome(False), "the request carries no termination evidence")
    allowed, note = allowed_stop_reasons(evidence.get("allowed_stop_reasons"))
    recorded: dict[str, dict] = {}
    entries = evidence.get("trials")
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            recorded[entry["id"]] = entry
    trials: list[Trial] = []
    listed = integrity.get("trials") if isinstance(integrity, dict) else None
    for item in listed if isinstance(listed, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        entry = recorded.get(item["id"], {})
        termination = item.get("termination")
        trials.append(
            Trial(
                id=item["id"],
                termination=termination if isinstance(termination, str) else None,
                stop_reason=_recorded(entry.get("stop_reason")),
                manifest_stop_reason=_recorded(entry.get("manifest_stop_reason")),
            )
        )
    outcome = judge(allowed, trials)
    if not outcome.applicable:
        return _not_applicable(outcome, "no trial ended on its own")
    if note:
        outcome.notes.append(note)
    return outcome
