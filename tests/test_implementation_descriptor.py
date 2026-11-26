"""The implementation descriptor livingproof-evaluator.json (livingproof-evaluator-run#67).

A loader installs and runs this package from the descriptor alone. The schema copies
next to ``pin.json`` are livingproof-evaluator's, and ``pin.json`` is the only pin.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from packaging.specifiers import SpecifierSet
from referencing import Registry, Resource

from livingproof_evaluator_run import identity

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "livingproof-evaluator.json"
SCHEMA_DIR = ROOT / "tests" / "fixtures" / "implementation-schema"
PIN = SCHEMA_DIR / "pin.json"
README = ROOT / "README.md"
GOOD = ROOT / "tests" / "fixtures" / "completeness" / "good" / "manifest.json"
# The evidence folder the suite already runs with tests/fixtures/recording/real.
MEDIA_MANIFEST = ROOT / "tests" / "fixtures" / "pins" / "good" / "manifest.json"
MEDIA = ROOT / "tests" / "fixtures" / "recording" / "real"
DESCRIPTOR_LINE = "Living-Proof-Labs/livingproof-evaluator-run@<tag>/livingproof-evaluator.json"
TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _descriptor() -> dict:
    return _load(DESCRIPTOR)


def _pin() -> dict:
    return _load(PIN)


def _registry() -> tuple[dict, Registry]:
    """The two fixture schemas, keyed by ``$id``, so ``defs.schema.json`` resolves."""
    resources = []
    schema = None
    for name in ("implementation.schema.json", "defs.schema.json"):
        contents = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        resources.append((contents["$id"], Resource.from_contents(contents)))
        if name == "implementation.schema.json":
            schema = contents
    assert schema is not None
    return schema, Registry().with_resources(resources)


def _errors(schema: dict, registry: Registry, instance: dict) -> list:
    return list(Draft202012Validator(schema, registry=registry).iter_errors(instance))


def _fill(text: str, values: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        try:
            return values[name]
        except KeyError:
            raise AssertionError(f"placeholder {{{name}}} is not a provided input") from None

    return PLACEHOLDER.sub(replace, text)


def _expand(arguments: list, values: dict[str, str]) -> list[str]:
    """Substitute placeholders. An ``{if, then}`` item is included only when its input is given."""
    expanded: list[str] = []
    for item in arguments:
        if isinstance(item, str):
            expanded.append(_fill(item, values))
            continue
        if not isinstance(item, dict):
            raise AssertionError("argument items are strings or {if, then} objects")
        if item["if"] not in values:
            continue
        then = item["then"]
        if not isinstance(then, list) or not then:
            raise AssertionError("conditional then must be a non-empty list")
        for part in then:
            if not isinstance(part, str):
                raise AssertionError("conditional then must be argument strings")
            expanded.append(_fill(part, values))
    return expanded


def _run(manifest: Path, result: Path, media: Path | None) -> subprocess.CompletedProcess[str]:
    descriptor = _descriptor()
    values = {"evidence_manifest": str(manifest), "result": str(result)}
    if media is not None:
        values["media_dir"] = str(media)
    argv = _expand(descriptor["arguments"], values)
    if media is not None:
        assert str(media) in argv
    module = descriptor["entrypoint"]["module"]
    return subprocess.run(
        [sys.executable, "-m", module, *argv],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _assert_result(proc: subprocess.CompletedProcess[str], result: Path) -> None:
    descriptor = _descriptor()
    meaning = descriptor["exit_codes"].get(str(proc.returncode))
    assert meaning == "result", (proc.returncode, meaning, proc.stderr)
    assert result.is_file()
    document = json.loads(result.read_text(encoding="utf-8"))
    assert document["format"] == descriptor["result"]
    assert document["evaluator"]["id"] == descriptor["id"]
    assert document["evaluator"]["kind"] == descriptor["kind"]


def _allowed_minors(requires: str) -> list[str]:
    """``X.Y`` series that ``requires-python`` allows. ``>=3.12,<3.13`` gives ``3.12``."""
    spec = SpecifierSet(requires)
    found = []
    for major in range(3, 5):
        for minor in range(0, 40):
            series = f"{major}.{minor}"
            if any(spec.contains(f"{series}.{micro}") for micro in range(20)):
                found.append(series)
    return found


def _in_ci() -> bool:
    for name in ("CI", "GITHUB_ACTIONS"):
        if os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}:
            return True
    return False


def test_offline_validation() -> None:
    schema, registry = _registry()
    descriptor = _descriptor()
    assert _errors(schema, registry, descriptor) == []

    pin = _pin()
    pinned = set()
    for rel, digest in pin["files"].items():
        assert SHA256.fullmatch(digest)
        fixture = SCHEMA_DIR / Path(rel).name
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == digest
        pinned.add(fixture.name)
    present = {path.name for path in SCHEMA_DIR.iterdir() if path.name != "pin.json"}
    assert present == pinned
    assert TAG.fullmatch(pin["tag"])
    assert COMMIT.fullmatch(pin["commit"])

    other_major = {**descriptor, "result": "livingproof-evaluator-result/2.0.0"}
    assert _errors(schema, registry, other_major)
    extra = {**descriptor, "note": "not in the schema"}
    assert _errors(schema, registry, extra)


def test_pin_matches_the_release() -> None:
    if os.environ.get("LIVINGPROOF_OFFLINE") == "1":
        if _in_ci():
            pytest.fail("LIVINGPROOF_OFFLINE=1 must not skip the release pin check in CI")
        pytest.skip("LIVINGPROOF_OFFLINE=1")

    pin = _pin()
    remote = f"https://github.com/{pin['repository']}.git"
    ref = f"refs/tags/{pin['tag']}"
    peeled_ref = f"{ref}^{{}}"
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", "ls-remote", "--tags", remote, ref, peeled_ref],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    by_name = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        sha, name = line.split("\t", 1)
        by_name[name] = sha
    if peeled_ref in by_name:
        peeled = by_name[peeled_ref]
    elif list(by_name) == [ref]:
        peeled = by_name[ref]
    else:
        raise AssertionError(completed.stdout)
    assert peeled == pin["commit"]

    for rel, digest in pin["files"].items():
        url = f"https://raw.githubusercontent.com/{pin['repository']}/{pin['commit']}/{rel}"
        with urllib.request.urlopen(url, timeout=60) as response:
            body = response.read()
        assert hashlib.sha256(body).hexdigest() == digest


def test_descriptor_matches_the_code() -> None:
    descriptor = _descriptor()
    assert descriptor["id"] == identity.EVALUATOR_ID
    assert descriptor["kind"] == identity.KIND
    assert descriptor["result"] == identity.RESULT_FORMAT

    name = descriptor["package"]["name"]
    distribution = importlib.metadata.distribution(name)
    assert distribution.metadata["Name"] == name

    module = descriptor["entrypoint"]["module"]
    assert importlib.util.find_spec(module) is not None
    assert importlib.util.find_spec(f"{module}.__main__") is not None

    with (ROOT / "pyproject.toml").open("rb") as handle:
        requires = tomllib.load(handle)["project"]["requires-python"]
    assert _allowed_minors(requires) == [descriptor["runtime"]["python"]]


def test_cli_result_without_media(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    _assert_result(_run(GOOD, result, None), result)


def test_cli_result_with_media(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    _assert_result(_run(MEDIA_MANIFEST, result, MEDIA), result)


def test_cli_refuses_zero_trials(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"plan": {"trials": {"count": 0}}}),
        encoding="utf-8",
    )
    result = tmp_path / "result.json"
    proc = _run(manifest, result, None)
    meaning = _descriptor()["exit_codes"].get(str(proc.returncode))
    assert meaning == "refused", (proc.returncode, meaning, proc.stderr)
    assert not result.exists()


def test_readme_names_the_descriptor_line() -> None:
    text = README.read_text(encoding="utf-8")
    matches = [line for line in text.splitlines() if DESCRIPTOR_LINE in line]
    assert matches
    assert "livingproof-evaluator.json" in matches[0]
