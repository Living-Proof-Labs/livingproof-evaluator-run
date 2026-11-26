"""Check the release-to-manual contract without running Actions or publishing."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RENOVATE = ROOT / "renovate.json"
GUIDELINES_WORKFLOW = "Living-Proof-Labs/collaboration-guidelines/.github/workflows/"
PRESET_PREFIX = "github>Living-Proof-Labs/collaboration-guidelines:renovate-preset#"
PUBLISHED_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
FLOATING_TAG = re.compile(r"^v[0-9]+(?:\.[0-9]+)?$")
EXPECTED_GUIDELINES_WORKFLOWS = {
    "semantic-release-candidate.yml",
    "semantic-release.yml",
}
CANDIDATE = f"{GUIDELINES_WORKFLOW}semantic-release-candidate.yml"


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def verify_step(job, name):
    return next(step for step in job["steps"] if step.get("name") == name)


def adopted_guidelines_tag():
    """Return the guidelines release this repository currently requires.

    Renovate records that pin on the shared preset and updates workflow calls
    in the same change. The test reads it instead of keeping a third copy.
    """
    config = json.loads(RENOVATE.read_text())
    tags = [
        item.removeprefix(PRESET_PREFIX)
        for item in config["extends"]
        if item.startswith(PRESET_PREFIX)
    ]
    assert len(tags) == 1, tags
    assert PUBLISHED_TAG.fullmatch(tags[0]), tags[0]
    return tags[0]


def guidelines_pin_drift(uses, required_tag):
    """Return why a reusable-workflow reference drifts, or None when it matches.

    A match is one exact ``vMAJOR.MINOR.PATCH`` tag, the same tag the adopted
    guidelines preset requires. ``main``, a floating major or minor, and any
    other ref are drift.
    """
    if not isinstance(uses, str) or uses.strip() == "":
        return "missing reference"
    if "@" not in uses:
        return "unpinned reference"
    path, ref = uses.rsplit("@", 1)
    if path.startswith(GUIDELINES_WORKFLOW):
        name = path.removeprefix(GUIDELINES_WORKFLOW)
    else:
        name = ""
    if not name.endswith(".yml") or "/" in name:
        return "not a guidelines workflow reference"
    if ref == "main":
        return "points at main"
    if ref in {"latest", "master"} or FLOATING_TAG.fullmatch(ref):
        return "floating reference"
    if not PUBLISHED_TAG.fullmatch(ref):
        return "not a pinned published tag"
    if ref != required_tag:
        return "mismatched reference"
    return None


def guidelines_workflow_uses():
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = workflow(path.name)
        for job in (document.get("jobs") or {}).values():
            candidates = [job.get("uses", "")]
            candidates.extend(step.get("uses", "") for step in job.get("steps") or [])
            for uses in candidates:
                if GUIDELINES_WORKFLOW in uses:
                    found.append((path.name, uses))
    return found


def test_ordinary_checks_and_verified_manual_precede_exact_release():
    workflow_config = workflow("verify.yml")
    jobs = workflow_config["jobs"]
    assert "release_tag" in workflow_config["on"]["workflow_dispatch"]["inputs"]
    tag = adopted_guidelines_tag()
    assert guidelines_pin_drift(jobs["version"]["uses"], tag) is None
    assert jobs["version"]["uses"].endswith(f"semantic-release-candidate.yml@{tag}")
    assert jobs["version"]["permissions"] == {"contents": "read"}
    assert jobs["manual"]["needs"] == "version"
    assert jobs["manual"]["with"]["version"] == "${{ needs.version.outputs.semver-version }}"
    assert jobs["manual"]["with"]["source-commit"] == "${{ needs.version.outputs.commit }}"
    assert "pytest -q --junitxml=artifacts/tests.xml" in " ".join(
        step.get("run", "") for step in jobs["verify"]["steps"]
    )
    writer = jobs["release"]
    assert set(writer["needs"]) == {"verify", "version", "manual"}
    assert guidelines_pin_drift(writer["uses"], tag) is None
    assert writer["uses"].endswith(f"semantic-release.yml@{tag}")
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in writer["if"]
    assert "needs.manual.outputs.pages-attempt == github.run_attempt" in writer["if"]
    assert "needs.version.outputs.git-tag == format" in writer["if"]
    assert writer["with"] == {
        "expected-version": "${{ needs.manual.outputs.pages-version }}",
        "expected-commit": "${{ needs.manual.outputs.pages-commit }}",
    }


def test_verified_tar_is_attempt_scoped_and_deploy_uses_producer_name():
    docs = workflow("docs.yml")
    assert set(docs["on"]) == {"workflow_call"}
    assert docs["permissions"] == {"contents": "read"}
    assert docs["jobs"]["verify-pages-artifact"]["permissions"] == {"actions": "read"}
    assert set(docs["jobs"]) == {"build", "verify-pages-artifact"}
    build = docs["jobs"]["build"]
    uploads = [
        step for step in build["steps"] if "actions/upload-artifact@" in step.get("uses", "")
    ]
    assert uploads[0]["with"]["name"] == "evaluator-documentation-review-${{ github.run_attempt }}"
    assert uploads[1]["with"]["name"] == "${{ steps.package.outputs.name }}"
    proof = docs["jobs"]["verify-pages-artifact"]
    assert proof["needs"] == "build"
    download = next(
        step for step in proof["steps"] if "actions/download-artifact@" in step.get("uses", "")
    )
    assert download["with"]["artifact-ids"] == "${{ needs.build.outputs.pages-id }}"
    assert "github-token" not in download["with"]
    readback = verify_step(proof, "Verify the exact deployment tar and source identity")
    assert readback["env"]["PRODUCER_ATTEMPT"] == "${{ needs.build.outputs.pages-attempt }}"
    assert readback["env"]["EXPECTED_DIGEST"] == "${{ needs.build.outputs.pages-tar-sha256 }}"
    for key in ("version", "source_commit", "source_dirty", "run_id", "run_attempt"):
        assert repr(key) in readback["run"]
    deploy = workflow("verify.yml")["jobs"]["deploy"]
    assert set(deploy["needs"]) == {"manual", "release"}
    assert deploy["steps"][1]["with"]["artifact_name"] == "${{ needs.manual.outputs.pages-name }}"
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}


def test_no_pr_deploy_and_replay_requires_existing_published_current_main():
    deploy = workflow("verify.yml")["jobs"]["deploy"]
    conditional = deploy["if"]
    assert "github.ref == 'refs/heads/main'" in conditional
    assert "github.event_name == 'push'" in conditional
    assert "needs.release.outputs.published == 'true'" in conditional
    assert "github.event_name == 'workflow_dispatch'" in conditional
    assert "needs.release.result == 'skipped'" in conditional
    assert "pull_request" not in conditional
    assert deploy["concurrency"]["group"] == "github-pages"
    preflight = deploy["steps"][0]["run"]
    for binding in (
        'test "$RELEASE_TAG" = "v$MANUAL_VERSION"',
        'test "$SOURCE_SHA" = "$GITHUB_SHA"',
        'test "$ARTIFACT_NAME" = "github-pages-$PRODUCER_ATTEMPT"',
        ".draft == false and .prerelease == false",
        "refs/heads/main",
    ):
        assert binding in preflight


def test_drifted_guidelines_workflow_pin_is_rejected():
    """Missing, unpinned, main, floating and mismatched refs are drift.

    The v9.9.2 candidate against a required v9.9.3 is the mismatch that turned
    main red. The case is a fixture, so a later guidelines bump does not erase
    the check or retarget the repository's adopted tag.
    """
    required = "v9.9.3"
    cases = {
        None: "missing reference",
        "": "missing reference",
        CANDIDATE: "unpinned reference",
        f"{CANDIDATE}@main": "points at main",
        f"{CANDIDATE}@v9": "floating reference",
        f"{CANDIDATE}@v9.9": "floating reference",
        f"{CANDIDATE}@latest": "floating reference",
        f"{CANDIDATE}@11bd71901bbe5b1630ceea73d27597364c9af683": "not a pinned published tag",
        f"{CANDIDATE}@v9.9.2": "mismatched reference",
    }
    for uses, reason in cases.items():
        assert guidelines_pin_drift(uses, required) == reason


def test_release_read_is_authenticated_bounded_and_fails_closed():
    """The deploy release read is authenticated, bounded, and fails closed."""
    deploy = workflow("verify.yml")["jobs"]["deploy"]
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    step = verify_step(
        deploy,
        "Require a published stable release at current main inside the deployment lock",
    )
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    text = step["run"]
    script = (ROOT / "scripts" / "read-release.sh").read_text()
    assert script in text
    assert "bash scripts/read-release.sh" in text
    assert "Authorization: Bearer $GH_TOKEN" in text
    assert "sleep 5" in text
    assert "-le 3" in text
    retry = next(
        line for line in text.splitlines() if "403" in line and "429" in line and "5xx" in line
    )
    assert "404" not in retry
    assert ".tag_name == $tag and .draft == false and .prerelease == false" in text
    assert '(.published_at | type == "string" and length > 0)' in text
    assert "x-ratelimit-remaining" in text
    assert "release read failed: HTTP" in text
    assert "set +x" in script
    assert "set -x" not in script


def test_adopted_guidelines_workflows_use_that_published_tag():
    tag = adopted_guidelines_tag()
    found = guidelines_workflow_uses()
    names = set()
    for filename, uses in found:
        assert guidelines_pin_drift(uses, tag) is None, (filename, uses)
        names.add(uses.rsplit("/", 1)[-1].split("@", 1)[0])
    assert names == EXPECTED_GUIDELINES_WORKFLOWS
