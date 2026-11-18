"""pins 1.0.0: the pins a run recorded match the pins its verification lock declares.

The contract (livingproof-evaluator ``schema/integrity/checks/pins.schema.json``) names five
subjects: specs, runner, verifier, world and configuration. Each is compared once, from the
evidence only. Nothing is resolved against GitHub, and nothing here says whether a pin is
current.

A subject is *not checked* when the lock declares nothing for it, or the run recorded no
actual for it. It is never reported as matching, and it never fails the check. Today's
``livingproof-hallway-evidence/2.0.0`` records no spec file digests and no verifier image
digest, so ``specs`` and ``verifier`` are always not checked on that path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from livingproof_evaluator_run.plain import shown

PINS_ID = "pins"
PINS_VERSION = "1.0.0"
# The order of the contract's ``subject`` enum.
SUBJECTS = ("specs", "runner", "verifier", "world", "configuration")
RUN_MANIFEST = "run-manifest.json"


@dataclass
class Comparison:
    """One subject: what the lock declares and what the run recorded, by source name."""

    subject: str
    declared: str | None = None
    recorded: dict[str, str] = field(default_factory=dict)

    @property
    def checked(self) -> bool:
        return self.declared is not None and bool(self.recorded)

    @property
    def differing(self) -> dict[str, str]:
        return {name: value for name, value in self.recorded.items() if value != self.declared}


@dataclass
class PinsOutcome:
    comparisons: list[Comparison]

    @property
    def findings(self) -> list[dict]:
        found = []
        for item in self.comparisons:
            if item.checked and item.differing:
                found.append(
                    {
                        "category": "hash-mismatch",
                        "classification": "test_system",
                        "summary": _summary(item),
                        "subject": item.subject,
                    }
                )
        return found

    @property
    def compared(self) -> bool:
        """True when at least one subject had both a declared and a recorded pin."""
        return any(c.checked for c in self.comparisons)

    @property
    def matched(self) -> list[str]:
        return [c.subject for c in self.comparisons if c.checked and not c.differing]

    @property
    def not_checked(self) -> list[str]:
        return [c.subject for c in self.comparisons if not c.checked]

    @property
    def percentage(self) -> float:
        if not self.findings:
            return 100
        return 100 * len(self.matched) / len(SUBJECTS)


def _summary(item: Comparison) -> str:
    # Both sides come from the evidence, so they are shown escaped and bounded (see plain.py).
    seen = "; ".join(f"{shown(value)} ({name})" for name, value in item.differing.items())
    return (
        f"The {item.subject} pin differs: the verification lock declares "
        f"{shown(item.declared)}, the run recorded {seen}."
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _dig(document: object, *path: str) -> object:
    for key in path:
        if not isinstance(document, dict):
            return None
        document = document.get(key)
    return document


def _empty() -> dict[str, Comparison]:
    return {subject: Comparison(subject) for subject in SUBJECTS}


def from_evidence(manifest: dict, manifest_path: Path) -> PinsOutcome | None:
    """Compare ``manifest.lock.content`` with what the manifest recorded.

    ``None`` when the manifest embeds no lock: there is nothing to compare against.
    """
    lock = _dig(manifest, "lock", "content")
    if not isinstance(lock, dict):
        return None
    pins = _empty()

    # world: the lock's loaded-source digest first (that is what the run consumes), then the
    # legacy ``world.sha256``. The 2.0.0 manifest has no world digest of its own; the run
    # writes it to ``run-manifest.json`` beside it, for the same run.
    pins["world"].declared = _text(_dig(lock, "sources", "world", "sha256")) or _text(
        _dig(lock, "world", "sha256")
    )
    world = _text(_dig(manifest, "world", "sha256"))
    if world is not None:
        pins["world"].recorded["manifest world.sha256"] = world
    else:
        sibling = _run_manifest(manifest, manifest_path)
        world = _text(_dig(sibling, "world", "sha256"))
        if world is not None:
            pins["world"].recorded[f"{RUN_MANIFEST} world.sha256"] = world

    # configuration: the lock entry with the recorded configuration's name.
    name = _dig(manifest, "configuration", "name")
    entries = lock.get("configurations") if isinstance(lock.get("configurations"), list) else []
    for entry in entries:
        if isinstance(entry, dict) and name is not None and entry.get("name") == name:
            pins["configuration"].declared = _text(entry.get("sha256"))
            break
    recorded = _text(_dig(manifest, "configuration", "sha256"))
    if recorded is not None:
        pins["configuration"].recorded["configuration.sha256"] = recorded

    # runner: the simulator package is also the adapter, so both recorded commits must
    # equal the commit the lock names for the runner release.
    pins["runner"].declared = _text(_dig(lock, "releases", "runner", "commit"))
    for label, path in (
        ("environment.runner.commit", ("environment", "runner", "commit")),
        ("environment.simulator.adapter_commit", ("environment", "simulator", "adapter_commit")),
    ):
        value = _text(_dig(manifest, *path))
        if value is not None:
            pins["runner"].recorded[label] = value

    # specs and verifier: the lock declares file digests and an image digest, and the 2.0.0
    # manifest records neither the bytes loaded nor the image run. Not checked.
    return PinsOutcome([pins[subject] for subject in SUBJECTS])


def _run_manifest(manifest: dict, manifest_path: Path) -> dict | None:
    path = Path(manifest_path).parent / RUN_MANIFEST
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    # Only a record of this very run counts.
    if _text(document.get("run_id")) is None or document.get("run_id") != manifest.get("run_id"):
        return None
    return document


def from_request(integrity: dict) -> PinsOutcome | None:
    """Compare ``manifest.pins`` with ``lock.pins`` on a livingproof-evaluator-request.

    ``None`` when neither side carries any pin.
    """
    recorded = _dig(integrity, "manifest", "pins")
    declared = _dig(integrity, "lock", "pins")
    recorded = recorded if isinstance(recorded, dict) else {}
    declared = declared if isinstance(declared, dict) else {}
    if not recorded and not declared:
        return None
    pins = _empty()
    for subject in SUBJECTS:
        pins[subject].declared = _text(_dig(declared, subject, "sha256"))
        value = _text(_dig(recorded, subject, "sha256"))
        if value is not None:
            pins[subject].recorded["manifest pins sha256"] = value
    return PinsOutcome([pins[subject] for subject in SUBJECTS])
