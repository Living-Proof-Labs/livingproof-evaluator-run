"""Helpers that write MCAP recordings and a ``media.json`` the way livingproof-sim-mujoco does.

The writer is set up as ``livingproof_sim_mujoco.media`` sets it up: ``mcap`` 1.6.0, JSON
messages, zstd chunks, an empty profile, channels ``/base_pose`` and ``/joint_states``. Times are
nanoseconds on the simulation clock. The files are synthetic; the one real recording under
``tests/fixtures/recording/real`` comes from verification run 43402628666.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from mcap.writer import CompressionType, Writer

FORMAT = "livingproof-hallway-media/2.0.0"
POSE = "/base_pose"
JOINTS = "/joint_states"
PERIOD_NS = 20_000_000  # 50 Hz, the runner's MCAP_HZ


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def steps(count: int, period_ns: int = PERIOD_NS, start: int = 0) -> list[int]:
    """``count`` log times, ``period_ns`` apart."""
    return [start + i * period_ns for i in range(count)]


def default_channels(count: int = 100) -> dict[str, list[int]]:
    return {POSE: steps(count), JOINTS: steps(count)}


def write_mcap(path: Path, channels: dict[str, list[int]] | None = None) -> Path:
    """Write a complete MCAP. Messages go out in the order given, so a channel's times can go
    backwards. Small chunks, so one file holds several of them."""
    channels = default_channels() if channels is None else channels
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer = Writer(stream, chunk_size=2048, compression=CompressionType.ZSTD)
        writer.start(profile="", library="livingproof_sim_mujoco.media")
        ids = {
            topic: writer.register_channel(
                topic,
                "json",
                writer.register_schema(
                    "foxglove.PoseInFrame" if topic == POSE else "livingproof.JointState",
                    "jsonschema",
                    b"{}",
                ),
            )
            for topic in channels
        }
        longest = max((len(times) for times in channels.values()), default=0)
        for position in range(longest):
            for topic, times in channels.items():
                if position < len(times):
                    writer.add_message(
                        ids[topic],
                        log_time=times[position],
                        publish_time=times[position],
                        data=json.dumps({"sequence": position}).encode(),
                        sequence=position,
                    )
        writer.finish()
    return path


def write_empty_channel(path: Path, topic: str, *, others: dict[str, list[int]]) -> Path:
    """A complete MCAP in which ``topic`` is registered but has no message."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        writer = Writer(stream, chunk_size=2048, compression=CompressionType.ZSTD)
        writer.start(profile="", library="livingproof_sim_mujoco.media")
        writer.register_channel(topic, "json", writer.register_schema("x", "jsonschema", b"{}"))
        for other, times in others.items():
            channel = writer.register_channel(
                other, "json", writer.register_schema("y", "jsonschema", b"{}")
            )
            for position, time in enumerate(times):
                writer.add_message(channel, time, b"{}", time, position)
        writer.finish()
    return path


def without_summary(path: Path) -> None:
    """Cut the summary section out and give the file a footer that points at nothing."""
    data = path.read_bytes()
    summary_start = struct.unpack("<Q", data[-8 - 20 + 0 : -8 - 20 + 8])[0]
    footer = b"\x02" + struct.pack("<Q", 20) + struct.pack("<QQI", 0, 0, 0)
    path.write_bytes(data[:summary_start] + footer + data[-8:])


def truncate(path: Path, keep: float = 0.5) -> None:
    data = path.read_bytes()
    path.write_bytes(data[: int(len(data) * keep)])


def build_media(
    out: Path,
    evidence: Path,
    *,
    indexes: tuple[int, ...] = (1, 2, 3),
    channels: dict[int, dict[str, list[int]]] | None = None,
    edit=None,
) -> dict:
    """Write ``out/mcap/trial-NN.mcap`` and ``out/media.json`` for an evidence folder.

    ``channels`` gives a trial its own channels; ``edit(index, path)`` may damage a file after it
    is written. ``media.json`` is written last, from the files as they then are, so it agrees
    with them unless a test changes it. ``observation_sha256`` is the manifest's digest of the
    trial, as the real media job writes it.
    """
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    rows = {row["index"]: row for row in manifest["trials"]["results"]}
    entries = []
    for index in indexes:
        path = out / "mcap" / f"trial-{index:02d}.mcap"
        write_mcap(path, (channels or {}).get(index))
        if edit is not None:
            edit(index, path)
        entries.append(
            {
                "index": index,
                "observation_sha256": rows[index]["sha256"] if index in rows else "0" * 64,
                "mcap": {
                    "path": f"mcap/trial-{index:02d}.mcap",
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                },
            }
        )
    document = {
        "format": FORMAT,
        "configuration": "fixture",
        "run_id": manifest.get("run_id", "run"),
        "trials": entries,
    }
    (out / "media.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def edit_media(out: Path, change) -> None:
    path = out / "media.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
