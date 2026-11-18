"""completeness 1.1.0: every planned trial has a recording and observations, and ended on its own.

The contract (livingproof-evaluator ``schema/integrity/checks/completeness.schema.json`` and
``docs/run-integrity.md``, v1.2.0) fixes the rule. A planned trial with no evidence is
``missing-trial``. A trial whose termination is ``timeout`` or ``crash`` is ``ended-by-timeout`` or
``ended-by-crash`` and has no other finding: it is the one report of that ending. Otherwise the
trial's recording and its observations are each missing, truncated or empty, or present, and the
three that are not are ``missing-``, ``truncated-`` and ``empty-`` ``recording`` or
``observations`` findings. ``percentage`` is 100 times the complete planned trials over the
planned trials.

*The recording* is the one ``media.json`` lists for the trial on an evidence manifest (read with
``recording.read_media``), and ``recording.state`` on a request. A file with no valid footer is
``truncated``, and this check owns it: ``recording`` does not judge it and lists the trial as
``not-present``, so a truncation is reported once. A listed recording that is missing makes the run
incomplete, so a run with one of three listed recordings missing is never COMPLETED and 100. A
trial ``media.json`` does not list has no recording to read here.

From 1.1.0 the check follows plan-conformance's applicability: when the run's preconditions were
unmet it ran no trials, the check is not applicable and no planned trial is reported as missing.
Version 1.0.0, which stays valid, is always applicable; ``version="1.0.0"`` selects that.
"""

from __future__ import annotations

from livingproof_evaluator_run import plan_conformance

COMPLETENESS_ID = "completeness"
COMPLETENESS_VERSION = "1.1.0"
PREVIOUS_VERSIONS = ("1.0.0",)
SUCCESS_COPY = "Every planned trial has its observation file."

# The category and the words for a recording or observations that is not present.
_RECORDING = {
    "missing": ("missing-recording", "Trial {id} has no recording."),
    "truncated": ("truncated-recording", "Trial {id} has a truncated recording."),
    "empty": ("empty-recording", "Trial {id} has an empty recording."),
}
_OBSERVATIONS = {
    "missing": ("missing-observations", "Planned trial {id} has no observations."),
    "truncated": ("truncated-observations", "Trial {id} has truncated observations."),
    "empty": ("empty-observations", "Trial {id} has empty observations."),
}


def finding(category: str, trial_id: str, summary: str) -> dict:
    return {
        "category": category,
        "classification": "test_system",
        "summary": summary,
        "trial_id": trial_id,
    }


def recording_finding(trial_id: str, state: object) -> dict | None:
    """The finding for a recording that is ``missing``, ``truncated`` or ``empty``, else None."""
    found = _RECORDING.get(state) if isinstance(state, str) else None
    return finding(found[0], trial_id, found[1].format(id=trial_id)) if found else None


def observations_finding(trial_id: str, state: object) -> dict | None:
    """The finding for observations that are ``missing``, ``truncated`` or ``empty``, else None."""
    found = _OBSERVATIONS.get(state) if isinstance(state, str) else None
    return finding(found[0], trial_id, found[1].format(id=trial_id)) if found else None


def applicable_for_request(integrity: dict, version: str = COMPLETENESS_VERSION) -> bool:
    """False when ``evidence['plan-conformance'].preconditions.met`` is false: the run ran no
    trials. 1.0.0 was always applicable."""
    if version == "1.0.0":
        return True
    evidence = integrity.get("evidence") if isinstance(integrity, dict) else None
    conformance = evidence.get("plan-conformance") if isinstance(evidence, dict) else None
    preconditions = conformance.get("preconditions") if isinstance(conformance, dict) else None
    met = preconditions.get("met", True) if isinstance(preconditions, dict) else True
    return met is not False


def applicable_for_evidence(manifest: dict, version: str = COMPLETENESS_VERSION) -> bool:
    """False when the manifest records a required precondition that was not met."""
    if version == "1.0.0":
        return True
    return not plan_conformance._unmet(manifest.get("preconditions"))
