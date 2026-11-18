"""pins 1.1.0: the pins a run recorded match the pins its verification lock declares.

The contract (livingproof-evaluator ``schema/integrity/checks/pins.schema.json``, v1.2.0) names
five subjects: specs, runner, verifier, world and configuration. Each is compared once, from the
evidence only. Nothing is resolved against GitHub, and nothing here says whether a pin is
current.

A subject is *checked* when the lock declares a value for it and the run recorded one. Any other
subject is *not checked*: it is listed in ``not_checked``, with ``not-declared`` when the lock
declares nothing for it (this is tested first, so a pin neither side carries is ``not-declared``)
and ``not-recorded`` when the lock declares it and the run recorded no actual. It is never
reported as matching, and it never fails the check. Today's ``livingproof-hallway-evidence/2.0.0``
records no spec file digests and no verifier image digest, so ``specs`` and ``verifier`` are
``not-recorded`` on that path when the lock declares them.

``percentage`` is 100 times the checked subjects without a finding over the checked subjects. A
subject that was not checked is outside the denominator, and with none checked the check is not
applicable and lists all five. Version 1.0.0, which the contract keeps valid, divided by five and
had no ``not_checked``; ``version="1.0.0"`` selects it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from livingproof_evaluator_run.plain import shown

PINS_ID = "pins"
PINS_VERSION = "1.1.0"
PREVIOUS_VERSIONS = ("1.0.0",)
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

    @property
    def reason(self) -> str:
        """Why the subject was not checked. The lock is tested first."""
        return "not-declared" if self.declared is None else "not-recorded"


@dataclass
class PinsOutcome:
    comparisons: list[Comparison]
    version: str = PINS_VERSION

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
    def unchecked(self) -> list[str]:
        return [c.subject for c in self.comparisons if not c.checked]

    @property
    def not_checked(self) -> list[dict] | None:
        """The contract's ``not_checked`` items, in the order of its subject enum. None at 1.0.0,
        which has no such field."""
        if self.version == "1.0.0":
            return None
        return [
            {"subject": c.subject, "reason": c.reason} for c in self.comparisons if not c.checked
        ]

    @property
    def percentage(self) -> float:
        """100 times the matching checked subjects over the checked subjects (1.0.0: over five)."""
        if self.version == "1.0.0":
            if not self.findings:
                return 100
            return 100 * len(self.matched) / len(SUBJECTS)
        checked = [c for c in self.comparisons if c.checked]
        return 100 * (len(checked) - len(self.findings)) / len(checked)


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


def from_evidence(
    manifest: dict, manifest_path: Path, version: str = PINS_VERSION
) -> PinsOutcome | None:
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
    # manifest records neither the bytes loaded nor the image run. They are declared and never
    # recorded, so they are not checked, with the reason not-recorded. The value kept is only a
    # mark that the lock declares one: nothing recorded is ever compared with it.
    if isinstance(_dig(lock, "releases", "specs", "files"), dict) and _dig(
        lock, "releases", "specs", "files"
    ):
        pins["specs"].declared = "the lock's specs file digests"
    pins["verifier"].declared = _text(_dig(lock, "releases", "verifier", "digest"))
    return PinsOutcome([pins[subject] for subject in SUBJECTS], version)


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


def from_request(integrity: dict, version: str = PINS_VERSION) -> PinsOutcome | None:
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
    return PinsOutcome([pins[subject] for subject in SUBJECTS], version)


def nothing_to_compare(version: str = PINS_VERSION) -> PinsOutcome:
    """The outcome when there is no lock or neither side carries a pin: every subject is not
    declared, so the check is not applicable and lists all five."""
    return PinsOutcome(list(_empty().values()), version)
