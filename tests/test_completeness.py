"""completeness 1.0.0 (livingproof-evaluator-run#3).

Fail-first fixtures: one good evidence run, and one doctored missing-trial
run. Results must be livingproof-evaluator-result/1.1.0 documents that pass
the livingproof-evaluator v1.0.8 conformance kit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "completeness"
GOOD = FIXTURES / "good" / "manifest.json"
MISSING = FIXTURES / "missing-trial" / "manifest.json"
CONTRACT = ROOT / ".livingproof-evaluator"


def _evaluate(manifest: Path, out: Path) -> int:
    from livingproof_evaluator_run import evaluate_evidence

    return evaluate_evidence(manifest, out)


def _validate(document: dict) -> list[str]:
    if not (CONTRACT / "tools" / "validate_contract.py").is_file():
        raise RuntimeError(
            "livingproof-evaluator v1.0.8 is not checked out at "
            f"{CONTRACT}. Run: python tools/fetch_contract.py"
        )
    sys.path.insert(0, str(CONTRACT / "tests"))
    sys.path.insert(0, str(CONTRACT / "tools"))
    from validate_contract import validate_document

    return validate_document(document)


def test_good_fixture_completes_with_a_conforming_result(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    code = _evaluate(GOOD, out)
    assert code == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["format"] == "livingproof-evaluator-result/1.1.0"
    assert result["evaluator"]["id"] == "livingproof-run-integrity"
    assert result["evaluator"]["kind"] == "integrity"
    assert result["evaluator"]["display_name"] == "Run Integrity"
    assert result["evaluator"]["publisher"] == "Living Proof Labs"
    assert result["descriptor"]["title"] == "Run Integrity"
    assert result["descriptor"]["tier"] == "test_system_status"
    run = result["integrity"]["run"]
    assert run["test_system_status"] == "COMPLETED"
    assert run["success"] is True
    assert run["percentage"] == 100
    assert "conclusion" not in run
    check = result["integrity"]["checks"][0]
    assert check["id"] == "completeness"
    assert check["version"] == "1.0.0"
    assert check["success"] is True
    assert check["findings"] == []
    assert _validate(result) == []


def test_missing_trial_fixture_is_error_and_inconclusive(tmp_path: Path) -> None:
    out = tmp_path / "result.json"
    code = _evaluate(MISSING, out)
    assert code == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["format"] == "livingproof-evaluator-result/1.1.0"
    run = result["integrity"]["run"]
    assert run["test_system_status"] == "ERROR"
    assert run["conclusion"] == "INCONCLUSIVE"
    assert run["success"] is False
    check = result["integrity"]["checks"][0]
    assert check["id"] == "completeness"
    assert check["success"] is False
    categories = {finding["category"] for finding in check["findings"]}
    assert "missing-trial" in categories
    assert all(finding["classification"] == "test_system" for finding in check["findings"])
    # The evaluator invalidates the run; it does not grade the robot.
    assert "verdict" not in result
    assert "grade" not in result
    assert "verdict" not in result["integrity"]
    assert _validate(result) == []


def test_mismatched_observation_digest_is_missing_observations(tmp_path: Path) -> None:
    dest = tmp_path / "evidence"
    import shutil

    shutil.copytree(GOOD.parent, dest)
    manifest_path = dest / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["trials"]["results"][1]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    out = tmp_path / "result.json"
    assert _evaluate(manifest_path, out) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    categories = {f["category"] for f in result["integrity"]["checks"][0]["findings"]}
    assert categories == {"missing-observations"}
    assert result["integrity"]["run"]["conclusion"] == "INCONCLUSIVE"
    assert _validate(result) == []


def test_cli_writes_the_good_fixture_result(tmp_path: Path) -> None:
    import subprocess

    out = tmp_path / "result.json"
    done = subprocess.run(
        ["python", "-m", "livingproof_evaluator_run", str(GOOD), "--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["integrity"]["run"]["success"] is True
    assert _validate(result) == []
