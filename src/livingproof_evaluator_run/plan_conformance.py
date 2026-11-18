"""plan-conformance 1.0.0: the trials that ran are the trials that were planned.

The contract (livingproof-evaluator ``schema/integrity/checks/plan-conformance.schema.json``
and ``docs/run-integrity.md``, v1.1.0) fixes the rule. The plan's trial count, ``trials.count``,
the number of ``trials.results`` entries and the lock's own plan trial count agree. The plan's
``command_speed`` equals the lock's. ``trials.results[].index`` is exactly 1 to N, and each
``path`` is ``trials/trial-NN.json`` for its own index.

This check reads structure only. It never opens a trial file: a missing or hash-mismatched
trial file stays a ``completeness`` finding, so a finding here carries no trial id. It never
grades the robot.

*Subjects* are the comparisons that were made: each count compared with the plan's, the command
speed when both the plan and the lock record one, one per index 1 to N, and one per result entry
whose index is outside 1 to N. The share is the subjects without a finding over all subjects.
The lock comparisons are not made, and not counted, when there is no lock to compare with.

The evidence is the contract's ``evidence['plan-conformance']``. ``from_evidence`` builds it
from a ``livingproof-hallway-evidence/2.0.0`` manifest, ``from_request`` reads it from a
``livingproof-evaluator-request``. Both go through ``conformance``.

Evidence that cannot be compared (no plan trial count, no ``trials.count``, results that are not
a list) makes the check *not applicable*, never a pass. A result entry that cannot be placed (an
index that is not an integer, a path that is not text) is a finding, never an exception.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from livingproof_evaluator_run.plain import shown

PLAN_CONFORMANCE_ID = "plan-conformance"
PLAN_CONFORMANCE_VERSION = "1.0.0"
# The contract's category enum.
CATEGORIES = (
    "trial-count-mismatch",
    "command-speed-mismatch",
    "index-missing",
    "index-duplicate",
    "index-out-of-range",
    "path-mismatch",
)


@dataclass
class Outcome:
    """What the check found. ``applicable`` false means nothing was compared."""

    applicable: bool
    findings: list[dict] = field(default_factory=list)
    subjects: int = 0
    failing: int = 0
    # Plain text for the descriptor: why nothing was compared, or what was left out.
    notes: list[str] = field(default_factory=list)
    # True when the plan was compared with the lock's plan.
    with_lock: bool = False

    @property
    def percentage(self) -> float:
        """100 times the subjects without a finding over the subjects."""
        return 100 * (self.subjects - self.failing) / self.subjects


def _not_applicable(reason: str) -> Outcome:
    return Outcome(applicable=False, notes=[f"Not checked: plan-conformance, {reason}."])


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# A side that records no command speed. Both sides must record one for it to be compared.
NO_SPEED = object()


def _speed(value: object) -> object:
    """The recorded command speed as written, or NO_SPEED when there is none (absent or null)."""
    return NO_SPEED if value is None else value


def _same_speed(plan: object, lock: object) -> bool:
    """Equal by value, and both a positive number (the contract's type). Anything else, such as
    a string or a boolean, is not a command speed and is not equal to anything."""
    return (
        all(
            isinstance(value, int | float) and not isinstance(value, bool) and value > 0
            for value in (plan, lock)
        )
        and plan == lock
    )


def _trial_path(index: int) -> str:
    return f"trials/trial-{index:02d}.json"


def _text(value: object) -> str:
    """A recorded path for a finding's summary, bounded and escaped (see plain.py). Text is shown
    as written; anything else as JSON."""
    return shown(value) if isinstance(value, str) else _json(value)


def _json(value: object) -> str:
    """A recorded value as JSON, bounded and escaped, so ``"2"`` and ``2`` differ."""
    try:
        return shown(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return shown(repr(value))


def _finding(category: str, summary: str) -> dict:
    return {"category": category, "classification": "test_system", "summary": summary}


def conformance(
    *,
    planned: int,
    plan_speed: object,
    trials_count: int,
    results: list,
    lock_count: int | None,
    lock_speed: object,
    has_lock: bool,
) -> Outcome:
    """Compare the plan with the trials and the lock. Findings come in the contract's order:
    the counts, the command speed, then each index 1 to N, then each entry out of range."""
    findings: list[dict] = []
    subjects = 0
    failing = 0

    counts = [
        ("trials.count", trials_count),
        ("the number of trials.results entries", len(results)),
    ]
    if lock_count is not None:
        counts.append(("the lock's plan trial count", lock_count))
    for name, value in counts:
        subjects += 1
        if value != planned:
            failing += 1
            findings.append(
                _finding(
                    "trial-count-mismatch", f"The plan has {planned} trials and {name} is {value}."
                )
            )

    if plan_speed is not NO_SPEED and lock_speed is not NO_SPEED:
        subjects += 1
        if not _same_speed(plan_speed, lock_speed):
            failing += 1
            findings.append(
                _finding(
                    "command-speed-mismatch",
                    f"The plan's command_speed is {_json(plan_speed)}"
                    f" and the lock's is {_json(lock_speed)}.",
                )
            )

    # An entry is placed by an integer index. Anything else cannot be placed and is out of range.
    entries = [entry if isinstance(entry, dict) else {} for entry in results]
    placed = [entry for entry in entries if _int(entry.get("index"))]
    for index in range(1, planned + 1):
        subjects += 1
        mine = [entry for entry in placed if entry["index"] == index]
        slot: list[dict] = []
        if not mine:
            slot.append(_finding("index-missing", f"No trials.results entry has index {index}."))
        elif len(mine) > 1:
            slot.append(
                _finding(
                    "index-duplicate", f"{len(mine)} trials.results entries have index {index}."
                )
            )
        expected = _trial_path(index)
        for entry in mine:
            path = entry.get("path")
            if path != expected:
                slot.append(
                    _finding(
                        "path-mismatch",
                        f"The entry for index {index} has path {_text(path)}, not {expected}.",
                    )
                )
        if slot:
            failing += 1
            findings.extend(slot)
    for entry in entries:
        index = entry.get("index")
        if not _int(index) or not 1 <= index <= planned:
            subjects += 1
            failing += 1
            findings.append(
                _finding(
                    "index-out-of-range",
                    f"A trials.results entry has index {_json(index)}, outside 1 to {planned}.",
                )
            )

    notes = [] if has_lock else ["Not checked: the plan against the lock."]
    return Outcome(True, findings, subjects, failing, notes, with_lock=has_lock)


def _dig(document: object, *path: str) -> object:
    for key in path:
        if not isinstance(document, dict):
            return None
        document = document.get(key)
    return document


def _unmet(preconditions: object) -> bool:
    """A precondition that is explicitly not met and required: the run ran no trials.

    Evidence 2.0.0 records ``preconditions`` as a list of ``{name, met, detail}`` and a
    precondition is required unless it says ``"required": false``. The runner stops at the
    first required one that is not met.
    """
    if not isinstance(preconditions, list):
        return False
    return any(
        isinstance(item, dict) and item.get("required", True) and item.get("met") is False
        for item in preconditions
    )


def from_evidence(manifest: dict) -> Outcome:
    """Check a ``livingproof-hallway-evidence/2.0.0`` manifest, with its embedded lock if any."""
    if _unmet(manifest.get("preconditions")):
        return _not_applicable("the run's preconditions were unmet and it ran no trials")
    planned = _dig(manifest, "plan", "trials", "count")
    trials_count = _dig(manifest, "trials", "count")
    results = _dig(manifest, "trials", "results")
    if not _int(planned) or planned < 0:
        return _not_applicable("the plan records no trial count")
    if not _int(trials_count):
        return _not_applicable("the evidence records no trials.count")
    if not isinstance(results, list):
        return _not_applicable("the evidence records no trials.results list")
    lock_plan = _dig(manifest, "lock", "content", "plan")
    lock_plan = lock_plan if isinstance(lock_plan, dict) else None
    lock_count = _dig(lock_plan, "trials", "count")
    return conformance(
        planned=planned,
        plan_speed=_speed(_dig(manifest, "plan", "command_speed")),
        trials_count=trials_count,
        results=results,
        lock_count=lock_count if _int(lock_count) else None,
        lock_speed=_speed(_dig(lock_plan, "command_speed")),
        has_lock=lock_plan is not None,
    )


def from_request(integrity: dict) -> Outcome:
    """Check ``integrity.evidence['plan-conformance']`` of a livingproof-evaluator-request."""
    evidence = _dig(integrity, "evidence", PLAN_CONFORMANCE_ID)
    if not isinstance(evidence, dict):
        return _not_applicable("the request carries no plan-conformance evidence")
    if _dig(evidence, "preconditions", "met") is False:
        return _not_applicable("the run's preconditions were unmet and it ran no trials")
    planned = _dig(evidence, "plan", "trial_count")
    trials_count = _dig(evidence, "trials", "count")
    results = _dig(evidence, "trials", "results")
    if not _int(planned) or planned < 0:
        return _not_applicable("the plan records no trial count")
    if not _int(trials_count):
        return _not_applicable("the evidence records no trials.count")
    if not isinstance(results, list):
        return _not_applicable("the evidence records no trials.results list")
    lock_plan = _dig(evidence, "lock", "plan")
    lock_plan = lock_plan if isinstance(lock_plan, dict) else None
    lock_count = _dig(lock_plan, "trial_count")
    return conformance(
        planned=planned,
        plan_speed=_speed(_dig(evidence, "plan", "command_speed")),
        trials_count=trials_count,
        results=results,
        lock_count=lock_count if _int(lock_count) else None,
        lock_speed=_speed(_dig(lock_plan, "command_speed")),
        has_lock=lock_plan is not None,
    )
