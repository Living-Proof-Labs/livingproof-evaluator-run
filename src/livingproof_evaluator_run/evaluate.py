"""Evaluate completeness, pins and plan-conformance (all 1.0.0) on evidence or a request."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from livingproof_evaluator_run import pins, plan_conformance
from livingproof_evaluator_run.plain import (
    DESCRIPTOR_LIMITS,
    FINDING_LIMITS,
    MAX_FINDINGS,
    is_plain,
    plain,
)
from livingproof_evaluator_run.identity import (
    CHECK_ID,
    CHECK_VERSION,
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
COMPLETENESS_SUCCESS = "Every planned trial has its observation file."


@dataclass
class Report:
    """One check's result plus the plain text the descriptor shows for it."""

    check: dict
    success_copy: str | None = None
    notes: list[str] = field(default_factory=list)
    shown: list[dict] = field(default_factory=list)


def evaluate_evidence(manifest_path: Path, out: Path) -> int:
    """Write a 1.1.0 integrity result for the evidence manifest at ``manifest_path``."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned = _planned_count(manifest)
    if planned <= 0:
        return 2
    results = _results_by_index(manifest)
    findings: list[dict] = []
    trials: list[dict] = []
    inputs = [_input("manifest", manifest_path)]
    complete = 0
    for index in range(1, planned + 1):
        trial_id = f"trial-{index:02d}"
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
        expected = entry.get("sha256")
        if not isinstance(expected, str) or digest != expected:
            findings.append(
                _finding(
                    "missing-observations",
                    trial_id,
                    f"Trial {trial_id} observation digest does not match the declared sha256.",
                )
            )
            trials.append(_trial_status(trial_id, ok=False))
            continue
        complete += 1
        trials.append(_trial_status(trial_id, ok=True))
    reports = [_completeness(findings, complete, planned)]
    outcome = pins.from_evidence(manifest, manifest_path)
    reports.append(_pins(outcome))
    reports.append(_plan_conformance(plan_conformance.from_evidence(manifest)))
    return _write_result(
        out,
        run_id=str(manifest.get("run_id") or "run"),
        inputs=inputs,
        trials=trials,
        reports=reports,
    )


def evaluate(source: Path, out: Path) -> int:
    """Evaluate an evidence manifest or a livingproof-evaluator-request."""
    source = Path(source)
    document = json.loads(source.read_text(encoding="utf-8"))
    fmt = document.get("format")
    if isinstance(fmt, str) and fmt.startswith("livingproof-evaluator-request/"):
        return _evaluate_request(document, source, out)
    return evaluate_evidence(source, out)


def _evaluate_request(request: dict, _source: Path, out: Path) -> int:
    payload = request.get("integrity") if isinstance(request.get("integrity"), dict) else {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    planned = [
        item["id"]
        for item in manifest.get("planned_trials") or []
        if isinstance(item, dict) and item.get("id")
    ]
    evidence = {
        item["id"]: item
        for item in payload.get("trials") or []
        if isinstance(item, dict) and item.get("id")
    }
    if not planned:
        return 2
    findings: list[dict] = []
    trials: list[dict] = []
    complete = 0
    for trial_id in planned:
        trial = evidence.get(trial_id)
        if trial is None:
            findings.append(
                _finding(
                    "missing-trial", trial_id, f"Planned trial {trial_id} has no trial evidence."
                )
            )
            trials.append(_trial_status(trial_id, ok=False))
            continue
        observations = (
            trial.get("observations") if isinstance(trial.get("observations"), dict) else {}
        )
        if observations.get("state") == "missing":
            findings.append(
                _finding(
                    "missing-observations",
                    trial_id,
                    f"Planned trial {trial_id} has no observations.",
                )
            )
            trials.append(_trial_status(trial_id, ok=False))
            continue
        complete += 1
        trials.append(_trial_status(trial_id, ok=True))
    inputs = list(request.get("inputs") or [])
    reports = [_completeness(findings, complete, len(planned))]
    reports.append(_pins(pins.from_request(payload)))
    reports.append(_plan_conformance(plan_conformance.from_request(payload)))
    return _write_result(
        out,
        run_id=str(manifest.get("id") or "run"),
        inputs=inputs,
        trials=trials,
        reports=reports,
    )


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


def _finding(category: str, trial_id: str, summary: str) -> dict:
    return {
        "category": category,
        "classification": "test_system",
        "summary": summary,
        "trial_id": trial_id,
    }


def _trial_status(trial_id: str, *, ok: bool) -> dict:
    return {
        "id": trial_id,
        "test_system_status": "COMPLETED" if ok else "ERROR",
        "success": ok,
        "percentage": 100 if ok else 0,
    }


def _completeness(findings: list[dict], complete: int, planned: int) -> Report:
    check = {
        "id": CHECK_ID,
        "version": CHECK_VERSION,
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
    """pins 1.0.0. If nothing could be compared it is not applicable, never a pass.

    That is no lock in the evidence, a lock that declares nothing the run recorded, or a run
    that recorded nothing the lock declares: success and 100 would be a pass nothing earned.
    """
    if outcome is None or not outcome.compared:
        check = {
            "id": pins.PINS_ID,
            "version": pins.PINS_VERSION,
            "applicable": False,
            "success": True,
            "findings": [],
        }
        notes = [f"Not checked: {', '.join(outcome.not_checked)}."] if outcome else []
        return Report(check, notes=notes)
    findings = outcome.findings
    check = {
        "id": pins.PINS_ID,
        "version": pins.PINS_VERSION,
        "applicable": True,
        "success": not findings,
        "percentage": outcome.percentage,
        "findings": findings,
    }
    notes = []
    if outcome.not_checked:
        notes.append(f"Not checked: {', '.join(outcome.not_checked)}.")
    success = None
    if not findings:
        matched = ", ".join(outcome.matched) or "nothing"
        success = f"Matched the verification lock: {matched}."
    shown = [
        {"text": _clip(item["summary"], 280), "severity": "Needs attention"} for item in findings
    ]
    return Report(check, success_copy=success, notes=notes, shown=shown)


def _plan_conformance(outcome: plan_conformance.Outcome) -> Report:
    """plan-conformance 1.0.0. Nothing compared is not applicable, never a pass.

    Its findings carry no trial id (a missing trial file is a completeness finding), so the
    descriptor's findings name no trial either.
    """
    check = {
        "id": plan_conformance.PLAN_CONFORMANCE_ID,
        "version": plan_conformance.PLAN_CONFORMANCE_VERSION,
        "applicable": outcome.applicable,
        "success": not outcome.findings,
    }
    if outcome.applicable:
        check["percentage"] = outcome.percentage
    check["findings"] = outcome.findings
    if not outcome.applicable or outcome.findings:
        shown = [
            {"text": _clip(item["summary"], 280), "severity": "Needs attention"}
            for item in outcome.findings
        ]
        return Report(check, notes=outcome.notes, shown=shown)
    agree = "The plan, the trials and the lock" if outcome.with_lock else "The plan and the trials"
    return Report(
        check,
        success_copy=f"{agree} agree on the trial count.",
        notes=outcome.notes,
    )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


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
    percentage = min((check["percentage"] for check in applicable), default=100)
    success = all(check["success"] for check in checks)
    run: dict = {
        "id": run_id,
        "test_system_status": "COMPLETED" if success else "ERROR",
        "success": success,
        "percentage": percentage,
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
    # Text copied out of evidence is escaped, so the descriptor matches the contract's
    # plain-text pattern whatever the evidence holds.
    # They are also cut to the contract's lengths. The check's own findings keep the full
    # trial id; only the descriptor's short form is clipped.
    shown = [
        {
            key: _clip(plain(value), FINDING_LIMITS.get(key, 280))
            if isinstance(value, str)
            else value
            for key, value in item.items()
        }
        for report in reports
        for item in report.shown
    ][:MAX_FINDINGS]
    if success:
        parts = [report.success_copy for report in reports if report.success_copy] + (
            [notes] if notes else []
        )
        descriptor["success_copy"] = _clip(" ".join(parts), 400)
    else:
        problems = " ".join(item["text"] for item in shown)
        room = 1000 - (len(notes) + 1 if notes else 0)
        text = _clip(problems, room)
        descriptor["details_copy"] = f"{text} {notes}" if notes else text
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
