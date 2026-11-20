"""Publisher identity from the livingproof-evaluator contract examples (v1.2.0)."""

from __future__ import annotations

import importlib.metadata
import re

EVALUATOR_ID = "livingproof-run-integrity"
DISPLAY_NAME = "Run Integrity"
PUBLISHER = "Living Proof Labs"
KIND = "integrity"
EXECUTION = "deterministic"
RESULT_FORMAT = "livingproof-evaluator-result/1.2.0"
# Subset-legal mark from livingproof-evaluator examples/descriptor/integrity-with-icon.
ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">'
    '<rect x="3.5" y="4.5" width="17" height="15" rx="3.5" stroke="currentColor" '
    'stroke-width="2"/><path d="M6.5 12.5h3l1.2-3 2.2 7 1.6-4H17.5" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)
PURPOSE = "Judges whether the run and the test system can be trusted."
DESCRIPTOR_KIND = "Test system"
TIER = "test_system_status"


# Contract evaluator.version is SemVer. hatch-vcs reports PEP 440 dev versions
# (0.1.devN) until a release tag exists; map those onto a SemVer pre-release.
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_PEP440_DEV = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?\.dev(0|[1-9]\d*)$")


def package_version() -> str:
    try:
        raw = importlib.metadata.version("livingproof-evaluator-run")
    except importlib.metadata.PackageNotFoundError:
        raw = "0.1.dev0"
    if _SEMVER.fullmatch(raw):
        return raw
    match = _PEP440_DEV.fullmatch(raw)
    if match:
        major, minor, patch, dev = match.groups()
        return f"{major}.{minor}.{patch or '0'}-dev.{dev}"
    return "0.1.0"
