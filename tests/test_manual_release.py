"""Check the release-to-manual contract without running Actions or publishing."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def verify_step(job, name):
    return next(step for step in job["steps"] if step.get("name") == name)


def test_ordinary_checks_and_verified_manual_precede_exact_release():
    workflow_config = workflow("verify.yml")
    jobs = workflow_config["jobs"]
    assert "release_tag" in workflow_config["on"]["workflow_dispatch"]["inputs"]
    assert jobs["version"]["uses"].endswith("semantic-release-candidate.yml@v9.9.2")
    assert jobs["version"]["permissions"] == {"contents": "read"}
    assert jobs["manual"]["needs"] == "version"
    assert jobs["manual"]["with"]["version"] == "${{ needs.version.outputs.semver-version }}"
    assert jobs["manual"]["with"]["source-commit"] == "${{ needs.version.outputs.commit }}"
    assert "pytest -q --junitxml=artifacts/tests.xml" in " ".join(
        step.get("run", "") for step in jobs["verify"]["steps"]
    )
    writer = jobs["release"]
    assert set(writer["needs"]) == {"verify", "version", "manual"}
    assert writer["uses"].endswith("semantic-release.yml@v9.9.2")
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
