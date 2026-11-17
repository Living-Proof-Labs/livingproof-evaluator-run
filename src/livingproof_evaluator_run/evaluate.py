"""Evaluate completeness 1.0.0 against hallway evidence or an integrity request."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

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


def evaluate_evidence(manifest_path: Path, out: Path) -> int:
    """Write a 1.1.0 integrity result for the evidence manifest at ``manifest_path``."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned = _planned_count(manifest)
    results = _results_by_index(manifest)
    findings: list[dict] = []
    trials: list[dict] = []
    inputs = [_input("manifest", manifest_path)]
    complete = 0
    for index in range(1, planned + 1):
        trial_id = f"trial-{index:02d}"
        entry = results.get(index)
        path = manifest_path.parent / entry["path"] if entry and entry.get("path") else None
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
    return _write_result(
        out,
        run_id=str(manifest.get("run_id") or "run"),
        inputs=inputs,
        trials=trials,
        findings=findings,
        complete=complete,
        planned=planned,
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
        complete += 1
        trials.append(_trial_status(trial_id, ok=True))
    inputs = list(request.get("inputs") or [])
    return _write_result(
        out,
        run_id=str(manifest.get("id") or "run"),
        inputs=inputs,
        trials=trials,
        findings=findings,
        complete=complete,
        planned=len(planned) or 1,
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


def _write_result(
    out: Path,
    *,
    run_id: str,
    inputs: list[dict],
    trials: list[dict],
    findings: list[dict],
    complete: int,
    planned: int,
) -> int:
    percentage = 100 * complete / planned
    success = not findings
    check = {
        "id": CHECK_ID,
        "version": CHECK_VERSION,
        "applicable": True,
        "success": success,
        "percentage": percentage,
        "findings": findings,
    }
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
    if success:
        descriptor["success_copy"] = "Every planned trial has its observation file."
    else:
        descriptor["details_copy"] = " ".join(item["summary"] for item in findings)
        descriptor["findings"] = [
            {"text": item["summary"], "severity": "Needs attention", "trial": item["trial_id"]}
            for item in findings
        ]
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
        "integrity": {"run": run, "trials": trials, "checks": [check]},
        "descriptor": descriptor,
    }
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n")
    return 0
