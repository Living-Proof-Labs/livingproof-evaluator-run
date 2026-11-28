"""Evaluate completeness, pins, plan-conformance, termination and recording (all 1.1.0)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from livingproof_evaluator_run import (
    completeness,
    pins,
    plan_conformance,
    recording,
    termination,
)
from livingproof_evaluator_run.plain import (
    DESCRIPTOR_LIMITS,
    FINDING_LIMITS,
    MAX_FINDINGS,
    is_plain,
    plain,
)
from livingproof_evaluator_run.identity import (
    DESCRIPTOR_KIND,
    DISPLAY_NAME,
    EVALUATOR_ID,
    EXECUTION,
    ICON,
    KIND,
    PUBLISHER,
    PURPOSE,
    RESULT_FORMAT,
    TIER,
    package_version,
)

EVIDENCE_FORMAT = "livingproof-hallway-evidence/2.0.0"
COMPLETENESS_SUCCESS = completeness.SUCCESS_COPY


@dataclass
class Report:
    """One check's result plus the plain text the descriptor shows for it."""

    check: dict
    success_copy: str | None = None
    notes: list[str] = field(default_factory=list)
    # What the check left out, as short names for the descriptor's one "Not checked" sentence.
    unchecked: list[str] = field(default_factory=list)
    shown: list[dict] = field(default_factory=list)


def evaluate_evidence(manifest_path: Path, out: Path, media: Path | None = None) -> int:
    """Write a 1.1.0 integrity result for the evidence manifest at ``manifest_path``.

    ``media`` is the directory holding ``media.json`` and ``mcap/`` (the media job's artifact).
    ``completeness`` reads the recordings ``media.json`` lists, and ``recording`` judges the ones
    that are present; without ``media`` neither looks at a recording and ``recording`` is not
    applicable.
    """
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned = _planned_count(manifest)
    if planned <= 0:
        return 2
    results = _results_by_index(manifest)
    read = recording.read_media(media, planned, results)
    refusal = recording.refused_without_limit(manifest, read)
    if refusal is not None:
        # A broken media.json with no gap limit has no result the contract can carry: write none.
        print(
            f"livingproof-evaluator-run: media is refused: {refusal}; no result written",
            file=sys.stderr,
        )
        return 2
    findings: list[dict] = []
    trials: list[dict] = []
    inputs = [_input("manifest", manifest_path)]
    complete = 0
    # The trials whose observation file is there and matches its digest: termination judges those,
    # whatever the state of the trial's recording.
    observed_indexes: set[int] = set()
    applicable = completeness.applicable_for_evidence(manifest)
    for index in range(1, planned + 1):
        trial_id = f"trial-{index:02d}"
        if not applicable:
            # The run ran no trials: nothing is wrong with a trial that never ran.
            trials.append(_trial_status(trial_id, ok=True))
            continue
        entry = results.get(index)
        recorded = entry.get("path") if entry else None
        path = manifest_path.parent / recorded if isinstance(recorded, str) and recorded else None
        if entry is None or path is None or not path.is_file():
            findings.append(
                _finding(
                    "missing-trial", trial_id, f"Planned trial {trial_id} has no trial evidence."
                )
            )
            trials.append(_trial_status(trial_id, ok=False))
            continue
        digest = _sha256(path)
        inputs.append(_input("observations", path, uri=str(entry["path"])))
        mine: list[dict] = []
        found = completeness.recording_finding(trial_id, read.state(index) if read else None)
        if found:
            mine.append(found)
        expected = entry.get("sha256")
        if not isinstance(expected, str) or digest != expected:
            mine.append(
                _finding(
                    "missing-observations",
                    trial_id,
                    f"Trial {trial_id} observation digest does not match the declared sha256.",
                )
            )
        else:
            observed_indexes.add(index)
        if mine:
            findings.extend(mine)
            trials.append(_trial_status(trial_id, ok=False))
            continue
        complete += 1
        trials.append(_trial_status(trial_id, ok=True))
    reports = [_completeness(findings, complete, planned, applicable)]
    outcome = pins.from_evidence(manifest, manifest_path)
    reports.append(_pins(outcome))
    reports.append(_plan_conformance(plan_conformance.from_evidence(manifest)))
    reports.append(
        _termination(
            termination.from_evidence(manifest, manifest_path, planned, results, observed_indexes)
        )
    )
    reports.append(
        _recording(recording.from_evidence(manifest, media, planned, results, read=read))
    )
    return _write_result(
        out,
        run_id=str(manifest.get("run_id") or "run"),
        inputs=inputs,
        trials=trials,
        reports=reports,
    )


def evaluate(source: Path, out: Path, media: Path | None = None) -> int:
    """Evaluate an evidence manifest or a livingproof-evaluator-request.

    ``media`` applies to a manifest only; a request carries its recording evidence.
    """
    source = Path(source)
    document = json.loads(source.read_text(encoding="utf-8"))
    fmt = document.get("format")
    if isinstance(fmt, str) and fmt.startswith("livingproof-evaluator-request/"):
        try:
            return _evaluate_request(document, source, out)
        except recording.MalformedRequest as exc:
            # An inconsistent request gives no trustworthy result: write none, exit 2, the same
            # as for any other malformed request.
            print(
                f"livingproof-evaluator-run: malformed request: {exc}; no result written",
                file=sys.stderr,
            )
            return 2
    return evaluate_evidence(source, out, media)


def _evaluate_request(request: dict, _source: Path, out: Path) -> int:
    payload = request.get("integrity") if isinstance(request.get("integrity"), dict) else {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    raw_planned = manifest.get("planned_trials") or []
    if not raw_planned or any(
        not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]
        for item in raw_planned
    ):
        return 2
    planned = [item["id"] for item in raw_planned]
    evidence = {
        item["id"]: item
        for item in payload.get("trials") or []
        if isinstance(item, dict) and item.get("id")
    }
    findings: list[dict] = []
    trials: list[dict] = []
    complete = 0
    applicable = completeness.applicable_for_request(payload)
    for trial_id in planned:
        if not applicable:
            # The run ran no trials: nothing is wrong with a trial that never ran.
            trials.append(_trial_status(trial_id, ok=True))
            continue
        trial = evidence.get(trial_id)
        if trial is None:
            findings.append(
                _finding(
                    "missing-trial", trial_id, f"Planned trial {trial_id} has no trial evidence."
                )
            )
            trials.append(_trial_status(trial_id, ok=False))
            continue
        ended = trial.get("termination")
        if ended in ("timeout", "crash"):
            # completeness owns a trial that did not end on its own; termination refers to this.
            # It is the one report of that ending, so the trial has no other finding.
            findings.append(
                _finding(
                    f"ended-by-{ended}",
                    trial_id,
                    f"The trial did not end on its own: it ended by {ended}.",
                )
            )
            trials.append(_trial_status(trial_id, ok=False))
            continue
        mine = [
            found
            for found in (
                completeness.recording_finding(trial_id, _state(trial, "recording")),
                completeness.observations_finding(trial_id, _state(trial, "observations")),
            )
            if found
        ]
        if mine:
            findings.extend(mine)
            trials.append(_trial_status(trial_id, ok=False))
            continue
        complete += 1
        trials.append(_trial_status(trial_id, ok=True))
    inputs = list(request.get("inputs") or [])
    reports = [_completeness(findings, complete, len(planned), applicable)]
    reports.append(_pins(pins.from_request(payload)))
    reports.append(_plan_conformance(plan_conformance.from_request(payload)))
    reports.append(_termination(termination.from_request(payload)))
    reports.append(_recording(recording.from_request(payload)))
    # Overflow counts every descriptor finding, including pins, plan-conformance
    # and termination, so a non-plain trial id at the 50th completeness slot can
    # be dropped from the descriptor.
    shown_items = [item for report in reports for item in report.shown]
    visible = shown_items[: MAX_FINDINGS - 1] if len(shown_items) > MAX_FINDINGS else shown_items
    in_descriptor = [item["trial"] for item in visible if "trial" in item]
    if any(not is_plain(plain(tid)) for tid in planned) and not any(
        not is_plain(plain(tid)) for tid in in_descriptor
    ):
        print(
            "livingproof-evaluator-run: planned trial id is not plain text; no result written",
            file=sys.stderr,
        )
        return 1
    return _write_result(
        out,
        run_id=str(manifest.get("id") or "run"),
        inputs=inputs,
        trials=trials,
        reports=reports,
    )


def _state(trial: dict, key: str) -> object:
    """The ``state`` of a trial's ``recording`` or ``observations``, None when it has none."""
    value = trial.get(key)
    return value.get("state") if isinstance(value, dict) else None


def _planned_count(manifest: dict) -> int:
    plan = manifest.get("plan") if isinstance(manifest.get("plan"), dict) else {}
    trials_plan = plan.get("trials") if isinstance(plan.get("trials"), dict) else {}
    if isinstance(trials_plan.get("count"), int):
        return trials_plan["count"]
    trials = manifest.get("trials") if isinstance(manifest.get("trials"), dict) else {}
    if isinstance(trials.get("count"), int):
        return trials["count"]
    raise ValueError("evidence manifest has no plan.trials.count or trials.count")


def _results_by_index(manifest: dict) -> dict[int, dict]:
    trials = manifest.get("trials") if isinstance(manifest.get("trials"), dict) else {}
    rows = trials.get("results") if isinstance(trials.get("results"), list) else []
    found: dict[int, dict] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("index"), int):
            found[row["index"]] = row
    return found


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _input(role: str, path: Path, uri: str | None = None) -> dict:
    return {"role": role, "uri": uri or path.name, "sha256": _sha256(path)}


_finding = completeness.finding


def _trial_status(trial_id: str, *, ok: bool) -> dict:
    return {
        "id": trial_id,
        "test_system_status": "COMPLETED" if ok else "ERROR",
        "success": ok,
        "percentage": 100 if ok else 0,
    }


def _completeness(findings: list[dict], complete: int, planned: int, applicable: bool) -> Report:
    """completeness 1.1.0. Not applicable when the run's preconditions were unmet (it ran no
    trials), so no planned trial is reported as missing."""
    if not applicable:
        check = {
            "id": completeness.COMPLETENESS_ID,
            "version": completeness.COMPLETENESS_VERSION,
            "applicable": False,
            "success": True,
            "findings": [],
        }
        note = "Not checked: completeness, the run's preconditions were unmet and it ran no trials."
        return Report(check, notes=[note])
    check = {
        "id": completeness.COMPLETENESS_ID,
        "version": completeness.COMPLETENESS_VERSION,
        "applicable": True,
        "success": not findings,
        "percentage": 100 * complete / planned,
        "findings": findings,
    }
    shown = [
        {"text": item["summary"], "severity": "Needs attention", "trial": item["trial_id"]}
        for item in findings
    ]
    return Report(check, success_copy=COMPLETENESS_SUCCESS, shown=shown)


def _pins(outcome: pins.PinsOutcome | None) -> Report:
    """pins 1.1.0. If nothing could be compared it is not applicable, never a pass.

    That is no lock in the evidence, a lock that declares nothing the run recorded, or a run
    that recorded nothing the lock declares: success and 100 would be a pass nothing earned. The
    subjects that were not checked are in ``not_checked``, and the descriptor's note is made from
    that list.
    """
    nothing = outcome is None
    outcome = outcome or pins.nothing_to_compare()
    check: dict = {
        "id": pins.PINS_ID,
        "version": outcome.version,
        "applicable": outcome.compared,
        "success": not outcome.findings,
    }
    # No lock, or none declared on either side, is not a note on every card.
    unchecked = [] if nothing else outcome.unchecked
    if not outcome.compared:
        check["findings"] = []
        if outcome.not_checked is not None:
            check["not_checked"] = outcome.not_checked
        return Report(check, unchecked=unchecked)
    findings = outcome.findings
    check["percentage"] = outcome.percentage
    check["findings"] = findings
    if outcome.not_checked is not None:
        check["not_checked"] = outcome.not_checked
    success = None
    if not findings:
        matched = ", ".join(outcome.matched) or "nothing"
        success = f"Matched the verification lock: {matched}."
    shown = [
        {"text": _clip(item["summary"], 280), "severity": "Needs attention"} for item in findings
    ]
    return Report(check, success_copy=success, unchecked=unchecked, shown=shown)


def _words(subject: str) -> str:
    """A not-checked subject as the descriptor says it: ``lock-command-speed`` is
    ``lock command speed``."""
    return subject.replace("-", " ")


def _plan_conformance(outcome: plan_conformance.Outcome) -> Report:
    """plan-conformance 1.1.0. Nothing compared is not applicable, never a pass.

    Its findings carry no trial id (a missing trial file is a completeness finding), so the
    descriptor's findings name no trial either. The comparisons not made are in ``not_checked``,
    and the descriptor's note is made from that list.
    """
    check = {
        "id": plan_conformance.PLAN_CONFORMANCE_ID,
        "version": outcome.version,
        "applicable": outcome.applicable,
        "success": not outcome.findings,
    }
    if outcome.applicable:
        check["percentage"] = outcome.percentage
    check["findings"] = outcome.findings
    notes = outcome.notes
    unchecked: list[str] = []
    if outcome.not_checked is not None:
        check["not_checked"] = outcome.not_checked
        if outcome.applicable:
            notes = []
            unchecked = [_words(item["subject"]) for item in outcome.not_checked]
    if not outcome.applicable or outcome.findings:
        shown = [
            {"text": _clip(item["summary"], 280), "severity": "Needs attention"}
            for item in outcome.findings
        ]
        return Report(check, notes=notes, unchecked=unchecked, shown=shown)
    agree = "The plan, the trials and the lock" if outcome.with_lock else "The plan and the trials"
    return Report(
        check,
        success_copy=f"{agree} agree on the trial count.",
        notes=notes,
        unchecked=unchecked,
    )


def _termination(outcome: termination.Outcome) -> Report:
    """termination 1.1.0. No judged trial is not applicable, never a pass.

    A referral points at a ``completeness`` finding and is not a finding: it changes neither
    ``success`` nor ``percentage``. ``referrals`` is always present on this check.
    """
    check = {
        "id": termination.TERMINATION_ID,
        "version": outcome.version,
        "applicable": outcome.applicable,
        "success": not outcome.findings,
    }
    if outcome.applicable:
        check["percentage"] = outcome.percentage
    check["findings"] = outcome.findings
    check["referrals"] = outcome.referrals
    shown = [
        {
            "text": _clip(item["summary"], 280),
            "severity": "Needs attention",
            "trial": item["trial_id"],
        }
        for item in outcome.findings
    ]
    success = None
    if outcome.applicable and not outcome.findings:
        success = "Every trial that ended on its own stopped for a reason the plan allows."
    return Report(check, success_copy=success, notes=outcome.notes, shown=shown)


def _recording(outcome: recording.Outcome) -> Report:
    """recording 1.2.0. Nothing judged is not applicable, never a pass.

    ``limits`` is present exactly when the check is applicable, and equals the evidence's gap limit.
    ``not_checked`` lists every trial that was not judged, and the descriptor's note is made from
    that list.
    """
    check = {
        "id": recording.RECORDING_ID,
        "version": outcome.version,
        "applicable": outcome.applicable,
        "success": not outcome.findings,
    }
    if outcome.applicable:
        check["percentage"] = outcome.percentage
        check["limits"] = outcome.limits
    check["findings"] = outcome.findings
    notes = list(outcome.notes)
    if outcome.not_checked is not None:
        check["not_checked"] = outcome.not_checked
        for reason, words in (("not-present", "not present"), ("not-recorded", "not recorded")):
            ids = [item["trial_id"] for item in outcome.not_checked if item["reason"] == reason]
            if ids:
                notes.append(f"Not checked: recording of {recording.listed_ids(ids)} ({words}).")
    shown = [
        {
            "text": _clip(item["summary"], 280),
            "severity": "Needs attention",
            "trial": item["trial_id"],
        }
        for item in outcome.findings
    ]
    success = None
    if outcome.applicable and not outcome.findings:
        gap = outcome.limits["max_gap_seconds"]
        success = (
            "Every recording read is a usable MCAP file that matches media.json,"
            f" with no gap over {gap} s."
        )
    return Report(check, success_copy=success, notes=notes, shown=shown)


_ESCAPE = re.compile(r"\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4})")


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = max(0, limit - 1)
    for match in _ESCAPE.finditer(text):
        if match.start() >= cut:
            break
        if match.end() > cut:
            cut = match.start()
            break
    return text[:cut].rstrip() + "\u2026"


def _write_result(
    out: Path,
    *,
    run_id: str,
    inputs: list[dict],
    trials: list[dict],
    reports: list[Report],
) -> int:
    checks = [report.check for report in reports]
    applicable = [check for check in checks if check["applicable"]]
    success = all(check["success"] for check in checks)
    run: dict
    if not applicable:
        # Result format 1.2.0 (livingproof-evaluator#38): no check applied, so nothing was
        # judged. The run is INCONCLUSIVE, not a pass, and carries no percentage.
        run = {
            "id": run_id,
            "test_system_status": "INCONCLUSIVE",
            "conclusion": "INCONCLUSIVE",
            "success": False,
        }
    else:
        run = {
            "id": run_id,
            "test_system_status": "COMPLETED" if success else "ERROR",
            "success": success,
            "percentage": min(check["percentage"] for check in applicable),
        }
        if not success:
            run["conclusion"] = "INCONCLUSIVE"
    version = package_version()
    descriptor = {
        "title": DISPLAY_NAME,
        "purpose": PURPOSE,
        "version": version,
        "kind": DESCRIPTOR_KIND,
        "source": PUBLISHER,
        "tier": TIER,
        "icon": ICON,
        "icon_accessible_name": DISPLAY_NAME,
    }
    notes = " ".join(note for report in reports for note in report.notes)
    unchecked = [name for report in reports for name in report.unchecked]
    if unchecked:
        # One sentence, so what the checks left out costs the 400-character card the least.
        notes = " ".join(part for part in (notes, f"Not checked: {', '.join(unchecked)}.") if part)
    # Text copied out of evidence is escaped, so the descriptor matches the contract's
    # plain-text pattern whatever the evidence holds.
    # They are also cut to the contract's lengths on whole escape boundaries. The check's
    # own findings keep the full trial id; only the descriptor's short form is clipped.
    all_shown = [
        {
            key: _clip(plain(value), FINDING_LIMITS.get(key, 280))
            if isinstance(value, str)
            else value
            for key, value in item.items()
        }
        for report in reports
        for item in report.shown
    ]
    overflow_note = ""
    if len(all_shown) > MAX_FINDINGS:
        keep = MAX_FINDINGS - 1
        dropped = len(all_shown) - keep
        noun = "finding" if dropped == 1 else "findings"
        overflow_note = f"And {dropped} more {noun} (showing {keep} of {len(all_shown)})."
        shown = [*all_shown[:keep], {"text": overflow_note}]
    else:
        shown = all_shown
    if not applicable:
        details = "No check applied to this run, so run integrity is not graded."
        descriptor["details_copy"] = _clip(
            " ".join(part for part in (details, notes) if part),
            DESCRIPTOR_LIMITS["details_copy"],
        )
        descriptor["findings"] = []
    elif success:
        # success_copy is at most 400 characters. "Stop reasons" notes are dropped
        # first when that summary is tight, then a check-passed sentence is dropped
        # last-check-first, before a "Not checked" note is ever cut. The report
        # shows details_copy whenever it is present, and only falls back to
        # success_copy when details_copy is empty (livingproof-evaluator-run#70),
        # so the full card text (a sentence for every check, plus the notes,
        # including stop reasons) is written to details_copy, up to 1000
        # characters, after the 400-character summary is packed.
        all_parts = [report.success_copy for report in reports if report.success_copy]
        raw_notes = [note for report in reports for note in report.notes]
        if unchecked:
            raw_notes.append(f"Not checked: {', '.join(unchecked)}.")
        parts = list(all_parts)
        stop, kept = [], []
        for note in raw_notes:
            (stop if note.startswith("Stop reasons:") else kept).append(note)

        def packed(pass_parts: list[str], extra: list[str]) -> str:
            return " ".join([*pass_parts, *extra])

        tail = [*stop, *kept]
        dropped_notes = []
        while stop and len(packed(parts, tail)) > 400:
            dropped_notes.insert(0, stop.pop())
            tail = [*stop, *kept, "More notes."]
        if dropped_notes:
            descriptor["details_copy"] = " ".join(dropped_notes)
        while parts and len(packed(parts, tail)) > 400:
            parts.pop()
        descriptor["success_copy"] = _clip(packed(parts, tail), 400)
        details = " ".join(part for part in (*all_parts, *raw_notes) if part)
        if details:
            descriptor["details_copy"] = _clip(details, DESCRIPTOR_LIMITS["details_copy"])
    else:
        kept = all_shown[: MAX_FINDINGS - 1] if overflow_note else shown
        problems = " ".join(item["text"] for item in kept)
        tail = " ".join(part for part in (overflow_note, notes) if part)
        room = max(0, DESCRIPTOR_LIMITS["details_copy"] - (len(tail) + 1 if tail else 0))
        text = _clip(problems, room)
        descriptor["details_copy"] = f"{text} {tail}" if text and tail else (tail or text)
        descriptor["findings"] = shown
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    document = {
        "format": RESULT_FORMAT,
        "evaluator": {
            "id": EVALUATOR_ID,
            "version": version,
            "kind": KIND,
            "execution": EXECUTION,
            "display_name": DISPLAY_NAME,
            "publisher": PUBLISHER,
            "icon": ICON,
        },
        "inputs": inputs,
        "timestamps": {"started_at": now, "completed_at": now},
        "integrity": {"run": run, "trials": trials, "checks": checks},
        "descriptor": descriptor,
    }
    refused = _refused(descriptor)
    if refused:
        # Never write a result the contract would reject and report success.
        print(
            f"livingproof-evaluator-run: descriptor {refused}; no result written",
            file=sys.stderr,
        )
        return 1
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n")
    return 0


def _refused(descriptor: dict) -> str | None:
    """Why the contract would reject the descriptor's text, or None.

    Checks the plain-text pattern and the maximum length of each field (the contract's
    ``descriptor.schema.json``), for the descriptor and for every finding.
    """
    findings = descriptor.get("findings", [])
    if len(findings) > MAX_FINDINGS:
        return f"has {len(findings)} findings, more than {MAX_FINDINGS}"
    for key, value in descriptor.items():
        if key not in ("icon", "findings"):
            reason = _text_problem(key, value, DESCRIPTOR_LIMITS)
            if reason:
                return reason
    for index, item in enumerate(findings):
        for key, value in item.items():
            reason = _text_problem(f"findings[{index}].{key}", value, FINDING_LIMITS, key)
            if reason:
                return reason
    return None


def _text_problem(
    name: str, value: object, limits: dict[str, int], key: str | None = None
) -> str | None:
    if not isinstance(value, str):
        return None
    if not is_plain(value):
        return f"text is not plain text ({name})"
    limit = limits.get(key or name)
    if limit is not None and len(value) > limit:
        return f"text is too long ({name} is {len(value)} characters, the limit is {limit})"
    return None
