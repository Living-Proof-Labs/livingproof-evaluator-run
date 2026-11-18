"""The MCAP reader (livingproof-evaluator-run#8), on its own.

``mcap_reader`` knows nothing of checks, findings or the result format. It opens a recording,
says whether it is complete, lists its channels, iterates its messages in file order and
reports, per channel, the message count, the timestamps that go backwards and the largest gap.
These tests never touch ``recording`` or ``evaluate``, so the reader could move to a shared
package unchanged.

The real recording under ``tests/fixtures/recording/real`` is trial 1 of verification run
43402628666 (unitree-go1, playground). The other files are synthetic, written the way
livingproof-sim-mujoco writes them (``tests/recordings.py``).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
import recordings as rec

SRC = Path(__file__).resolve().parent.parent / "src" / "livingproof_evaluator_run"
REAL = Path(__file__).parent / "fixtures" / "recording" / "real" / "mcap" / "trial-01.mcap"


def reader():
    return importlib.import_module("livingproof_evaluator_run.mcap_reader")


def _stats(inspection) -> dict:
    return {c.topic: c for c in inspection.channels}


# A real recording and a synthetic one.


def test_a_real_recording_is_complete_with_both_channels() -> None:
    result = reader().inspect(REAL)
    assert result.complete is True
    assert result.reason is None
    stats = _stats(result)
    assert sorted(stats) == [rec.POSE, rec.JOINTS]
    for channel in stats.values():
        assert channel.message_count == 559
        assert channel.backward_steps == 0
        assert channel.max_gap_ns == rec.PERIOD_NS
        assert channel.max_gap_seconds == 0.02


def test_a_synthetic_recording_is_complete(tmp_path: Path) -> None:
    path = rec.write_mcap(tmp_path / "a.mcap", rec.default_channels(100))
    result = reader().inspect(path)
    assert result.complete is True
    assert [c.topic for c in result.channels] == [rec.POSE, rec.JOINTS]
    assert all(c.message_count == 100 for c in result.channels)


def test_channels_are_listed_in_a_fixed_order(tmp_path: Path) -> None:
    one = rec.write_mcap(tmp_path / "a.mcap", {"/b": rec.steps(3), "/a": rec.steps(3)})
    two = rec.write_mcap(tmp_path / "b.mcap", {"/a": rec.steps(3), "/b": rec.steps(3)})
    assert [c.topic for c in reader().inspect(one).channels] == ["/a", "/b"]
    assert [c.topic for c in reader().inspect(two).channels] == ["/a", "/b"]


def test_messages_come_in_file_order_with_topic_and_log_time(tmp_path: Path) -> None:
    path = rec.write_mcap(tmp_path / "a.mcap", {"/a": [0, 20, 10, 30], "/b": [5, 6]})
    got = [(m.topic, m.log_time) for m in reader().messages(path)]
    assert [t for t in got if t[0] == "/a"] == [("/a", 0), ("/a", 20), ("/a", 10), ("/a", 30)]
    assert [t for t in got if t[0] == "/b"] == [("/b", 5), ("/b", 6)]
    assert len(got) == 6


def test_a_channel_with_no_message_is_listed_with_a_count_of_zero(tmp_path: Path) -> None:
    path = rec.write_empty_channel(tmp_path / "a.mcap", "/silent", others={"/a": rec.steps(4)})
    stats = _stats(reader().inspect(path))
    assert stats["/silent"].message_count == 0
    assert stats["/silent"].max_gap_ns == 0
    assert stats["/a"].message_count == 4


# What is not complete.


def _incomplete(path: Path) -> object:
    result = reader().inspect(path)
    assert result.complete is False
    assert isinstance(result.reason, str) and result.reason
    return result


def test_a_truncated_file_is_incomplete(tmp_path: Path) -> None:
    path = rec.write_mcap(tmp_path / "a.mcap")
    rec.truncate(path, 0.5)
    _incomplete(path)


def test_a_file_that_lost_its_footer_is_incomplete(tmp_path: Path) -> None:
    path = rec.write_mcap(tmp_path / "a.mcap")
    path.write_bytes(path.read_bytes()[:-20])
    _incomplete(path)


def test_a_file_that_lost_its_closing_magic_is_incomplete(tmp_path: Path) -> None:
    path = rec.write_mcap(tmp_path / "a.mcap")
    path.write_bytes(path.read_bytes()[:-8])
    _incomplete(path)


def test_a_file_with_no_summary_is_incomplete_but_keeps_what_it_holds(tmp_path: Path) -> None:
    path = rec.write_mcap(tmp_path / "a.mcap", rec.default_channels(30))
    rec.without_summary(path)
    result = _incomplete(path)
    assert {c.topic: c.message_count for c in result.channels} == {rec.POSE: 30, rec.JOINTS: 30}


def test_a_damaged_chunk_is_incomplete(tmp_path: Path) -> None:
    """A byte flipped inside a chunk's data fails its CRC. (A flip in an index record leaves the
    messages intact; ``media.json``'s digest is what catches that, see the recording check.)"""
    from mcap.reader import make_reader

    path = rec.write_mcap(tmp_path / "a.mcap", rec.default_channels(200))
    with path.open("rb") as stream:
        index = make_reader(stream).get_summary().chunk_indexes[0]
    data = bytearray(path.read_bytes())
    data[index.chunk_start_offset + index.chunk_length // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    _incomplete(path)


@pytest.mark.parametrize("content", [b"", b"hello world" * 10, b"\x89MCAP0\r\n"])
def test_a_file_that_is_not_a_recording_is_incomplete(content: bytes, tmp_path: Path) -> None:
    path = tmp_path / "a.mcap"
    path.write_bytes(content)
    result = _incomplete(path)
    assert result.channels == ()


def test_a_path_that_does_not_exist_is_incomplete(tmp_path: Path) -> None:
    _incomplete(tmp_path / "nope.mcap")


def test_a_directory_is_incomplete(tmp_path: Path) -> None:
    _incomplete(tmp_path)


def test_reading_messages_from_a_bad_file_raises_the_readers_own_error(tmp_path: Path) -> None:
    path = tmp_path / "a.mcap"
    path.write_bytes(b"not a recording")
    with pytest.raises(reader().ReadError):
        list(reader().messages(path))


# Timestamps that go backwards, and gaps. These are the pure part: no file.


def _times(values: dict[str, list[int]]):
    r = reader()
    return [r.Message(topic, t) for topic, times in values.items() for t in times]


def test_regular_timestamps_have_no_backward_step_and_the_period_as_the_gap() -> None:
    stats = {c.topic: c for c in reader().channel_stats(_times({"/a": rec.steps(10)}))}
    assert stats["/a"].backward_steps == 0
    assert stats["/a"].max_gap_ns == rec.PERIOD_NS
    assert stats["/a"].message_count == 10


def test_a_timestamp_before_the_one_before_it_is_a_backward_step() -> None:
    (a,) = reader().channel_stats(_times({"/a": [0, 20, 10, 30]}))
    assert a.backward_steps == 1
    assert a.message_count == 4


def test_each_backward_step_is_counted() -> None:
    (a,) = reader().channel_stats(_times({"/a": [50, 40, 30, 60, 10]}))
    assert a.backward_steps == 3


def test_equal_timestamps_are_not_backwards_and_are_not_a_gap() -> None:
    (a,) = reader().channel_stats(_times({"/a": [5, 5, 5]}))
    assert a.backward_steps == 0
    assert a.max_gap_ns == 0


def test_the_gap_is_measured_in_log_time_order_not_file_order() -> None:
    """Out-of-order writes are not a capture gap (livingproof-evaluator#34): the gap is the
    largest step between consecutive log times, whatever order the messages were stored in."""
    (a,) = reader().channel_stats(_times({"/a": [0, 20, 10, 30]}))
    # In log time 0, 10, 20, 30: the largest step is 10. In file order it would be 20.
    assert a.max_gap_ns == 10
    (b,) = reader().channel_stats(_times({"/a": [0, 10, 5, 100]}))
    # In log time 0, 5, 10, 100.
    assert b.max_gap_ns == 90
    (c,) = reader().channel_stats(_times({"/a": [100, 0, 10, 5]}))
    assert c.max_gap_ns == 90


def test_a_step_back_is_still_counted_when_the_gap_is_measured_in_log_time() -> None:
    (a,) = reader().channel_stats(_times({"/a": [0, 20, 10, 30]}))
    assert a.backward_steps == 1


def test_one_message_has_no_gap() -> None:
    (a,) = reader().channel_stats(_times({"/a": [7]}))
    assert (a.message_count, a.backward_steps, a.max_gap_ns) == (1, 0, 0)


def test_channels_do_not_affect_each_other() -> None:
    stats = {
        c.topic: c
        for c in reader().channel_stats(
            _times({"/a": [0, 10, 20], "/b": [0, 1000, 5]}),
        )
    }
    assert stats["/a"].backward_steps == 0 and stats["/a"].max_gap_ns == 10
    # Log times 0, 5, 1000.
    assert stats["/b"].backward_steps == 1 and stats["/b"].max_gap_ns == 995


def test_the_gap_in_seconds_is_exact_for_a_decimal_limit() -> None:
    """ns / 1e9 is the double nearest the decimal, so a gap that equals a limit compares equal."""
    for text in ("0.1", "0.02", "0.3", "0.07", "1.5", "0.123456789"):
        ns = round(float(text) * 1e9)
        (a,) = reader().channel_stats(_times({"/a": [0, ns]}))
        assert a.max_gap_seconds == float(text)


def test_a_recording_with_a_backward_step_reports_it(tmp_path: Path) -> None:
    channels = rec.default_channels(50)
    channels[rec.POSE] = [t for t in channels[rec.POSE]]
    channels[rec.POSE][20], channels[rec.POSE][21] = channels[rec.POSE][21], channels[rec.POSE][20]
    path = rec.write_mcap(tmp_path / "a.mcap", channels)
    result = reader().inspect(path)
    assert result.complete is True
    stats = _stats(result)
    assert stats[rec.POSE].backward_steps == 1
    assert stats[rec.JOINTS].backward_steps == 0


def test_a_recording_with_two_swapped_messages_has_no_gap_over_the_period(tmp_path: Path) -> None:
    channels = rec.default_channels(50)
    channels[rec.POSE][20], channels[rec.POSE][21] = channels[rec.POSE][21], channels[rec.POSE][20]
    stats = _stats(reader().inspect(rec.write_mcap(tmp_path / "a.mcap", channels)))
    # In file order the step 19 -> 21 is two periods; in log time every step is one period.
    assert stats[rec.POSE].backward_steps == 1
    assert stats[rec.POSE].max_gap_ns == rec.PERIOD_NS


def test_a_recording_with_a_hole_reports_the_gap(tmp_path: Path) -> None:
    times = rec.steps(10) + rec.steps(10, start=10 * rec.PERIOD_NS + 480_000_000)
    path = rec.write_mcap(tmp_path / "a.mcap", {rec.POSE: times, rec.JOINTS: rec.steps(20)})
    stats = _stats(reader().inspect(path))
    assert stats[rec.POSE].max_gap_ns == rec.PERIOD_NS + 480_000_000
    assert stats[rec.POSE].max_gap_seconds == 0.5
    assert stats[rec.JOINTS].max_gap_ns == rec.PERIOD_NS


# The reader stays separate.


def test_the_reader_imports_nothing_of_the_check_or_the_result() -> None:
    tree = ast.parse((SRC / "mcap_reader.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            imported.add((node.module or "").split(".")[0])
    assert "livingproof_evaluator_run" not in imported
    assert imported <= {
        "__future__",
        "array",
        "dataclasses",
        "io",
        "lz4",
        "mcap",
        "os",
        "pathlib",
        "collections",
        "struct",
        "typing",
        "zstandard",
    }


def test_the_readers_small_api() -> None:
    module = reader()
    assert {"inspect", "messages", "channel_stats", "ReadError", "Message"} <= set(dir(module))


def test_a_gap_limit_is_not_a_reader_concern() -> None:
    names = {name.lower() for name in dir(reader())}
    assert not [n for n in names if "limit" in n or "default" in n or "required" in n]


def test_a_chunk_whose_crc_does_not_match_is_incomplete(tmp_path: Path) -> None:
    """Only the chunk's stored CRC is changed; its data still decompresses, so only the CRC check
    can tell."""
    import struct

    from mcap.reader import make_reader

    path = rec.write_mcap(tmp_path / "a.mcap", rec.default_channels(200))
    with path.open("rb") as stream:
        index = make_reader(stream).get_summary().chunk_indexes[0]
    data = bytearray(path.read_bytes())
    # opcode (1) + record length (8) + start time (8) + end time (8) + uncompressed size (8)
    at = index.chunk_start_offset + 1 + 8 + 8 + 8 + 8
    (crc,) = struct.unpack_from("<I", data, at)
    assert crc != 0
    struct.pack_into("<I", data, at, crc ^ 1)
    path.write_bytes(bytes(data))
    result = _incomplete(path)
    assert "CRC" in result.reason or "crc" in result.reason.lower()
