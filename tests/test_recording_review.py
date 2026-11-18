"""Independent review checks for recording 1.0.0 (livingproof-evaluator-run#8, PR 16).

Each test is a hand check that was scripted so it does not have to be done by hand again.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
import recordings as rec
import test_completeness as base
from test_recording import _check, _declare, _evidence, _media, _run

from livingproof_evaluator_run import mcap_reader

MAGIC = b"\x89MCAP0\r\n"


def test_the_locks_required_channels_are_used_when_the_manifest_plan_declares_none(
    tmp_path: Path,
) -> None:
    """The channels fall back to the embedded lock's plan, as the limit does, before the default."""
    only_pose = {i: {rec.POSE: rec.steps(50)} for i in (1, 2, 3)}
    folder = _evidence(tmp_path)  # the manifest's plan declares the limit and no channels
    _declare(folder, gap=None, channels=["/base_pose"], where="lock")
    media = _media(tmp_path, folder, channels=only_pose)
    document = _run(folder, tmp_path, media)
    check = _check(document)
    assert check["success"] is True and check["findings"] == []
    assert "required channels are the default" not in document["descriptor"]["success_copy"]


def _record(opcode: int, body: bytes) -> bytes:
    return bytes([opcode]) + struct.pack("<Q", len(body)) + body


def _text(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("<I", len(raw)) + raw


_HEADER = _record(1, _text("") + _text("hostile"))
_CHUNK_HEAD = struct.pack("<QQQI", 0, 0, 64 << 30, 0)

HOSTILE = {
    "declared record length of 2^62": MAGIC + _HEADER + bytes([5]) + struct.pack("<Q", 1 << 62),
    "declared string length of 4 GiB": MAGIC + _record(1, struct.pack("<I", 0xFFFFFFFF) + b"abcd"),
    "declared chunk records length of 2^62": MAGIC
    + _HEADER
    + _record(6, struct.pack("<QQQI", 0, 0, 10, 0) + _text("zstd") + struct.pack("<Q", 1 << 62)),
    "declared uncompressed size of 64 GiB over a tiny payload": MAGIC
    + _HEADER
    + _record(6, _CHUNK_HEAD + _text("none") + struct.pack("<Q", 4) + b"\x00" * 4),
    "magic only": MAGIC,
    "seven bytes": MAGIC[:7],
    "header only": MAGIC + _HEADER,
    "zero bytes": b"",
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_a_hostile_recording_is_incomplete_without_a_crash_or_a_large_allocation(
    name: str, tmp_path: Path
) -> None:
    path = tmp_path / "hostile.mcap"
    path.write_bytes(HOSTILE[name])
    import resource
    import time

    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.monotonic()
    inspection = mcap_reader.inspect(path)
    assert inspection.complete is False
    assert inspection.reason
    assert inspection.channels == ()
    assert time.monotonic() - started < 5
    assert resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before < 512 * 1024  # KiB


def test_a_hostile_recording_in_a_run_is_a_finding_not_a_crash(tmp_path: Path) -> None:
    folder = _evidence(tmp_path)
    media = _media(tmp_path, folder)
    target = media / "mcap" / "trial-02.mcap"
    target.write_bytes(HOSTILE["declared record length of 2^62"])
    document = json.loads((media / "media.json").read_text(encoding="utf-8"))
    document["trials"][1]["mcap"]["bytes"] = target.stat().st_size
    document["trials"][1]["mcap"]["sha256"] = rec.sha256(target)
    (media / "media.json").write_text(json.dumps(document), encoding="utf-8")
    result = _run(folder, tmp_path, media)
    check = _check(result)
    assert check["findings"] == []
    assert [i["trial_id"] for i in check["not_checked"]] == ["trial-02"]
    completeness = _check(result, "completeness")
    assert [(i["trial_id"], i["category"]) for i in completeness["findings"]] == [
        ("trial-02", "truncated-recording")
    ]
    assert base._validate(result) == []
