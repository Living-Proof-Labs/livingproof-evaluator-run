"""A small hostile recording cannot exhaust the evaluator (livingproof-evaluator-run#17).

Vera's review of PR 16 measured a 32 KB file that expands to 1 GiB taking about 43 s and 1 GB
RSS, and 4 GiB taking about 171 s and 4 GB. The reader now refuses, before it decompresses or
parses past a limit, any recording whose chunks expand beyond a documented cap, and says so as a
clear ``mcap-incomplete`` finding instead of crashing or running out of memory.

The bombs are crafted per test (``tests/bombs.py``): a few tens of kilobytes that would expand to
512 MiB. Each is read in a fresh interpreter that reports its own elapsed time and peak RSS, so
the assertions are about bounded time and memory, not just about the finding. Peak RSS is
``VmHWM``; an unguarded read of these files needs well over 1 GB.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import bombs
import pytest
import recordings as rec
import test_recording as base

from livingproof_evaluator_run import mcap_reader

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "livingproof_evaluator_run"
SECONDS = 5  # a bomb is refused in well under a second; an unguarded read takes about 20 s
RSS_KB = 256 * 1024  # an unguarded read of the same file needs more than 1 GB

_PROBE = textwrap.dedent(
    """
    import json, sys, time
    from pathlib import Path
    from livingproof_evaluator_run import mcap_reader
    def peak_rss_kb():
        # VmHWM is this interpreter's own peak; ru_maxrss would also count the parent's memory
        # at fork, which here holds the bomb it just built.
        for line in open("/proc/self/status"):
            if line.startswith("VmHWM:"):
                return int(line.split()[1])

    started = time.monotonic()
    inspection = mcap_reader.inspect(Path(sys.argv[1]))
    elapsed = time.monotonic() - started
    print(json.dumps({
        "elapsed": elapsed,
        "rss_kb": peak_rss_kb(),
        "complete": inspection.complete,
        "reason": inspection.reason,
        "cap_exceeded": getattr(inspection, "cap_exceeded", None),
        "channels": len(inspection.channels),
    }))
    """
)


def _probe(path: Path) -> dict:
    done = subprocess.run(
        [sys.executable, "-c", _PROBE, str(path)],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    return json.loads(done.stdout)


def _refused(result: dict) -> None:
    assert result["elapsed"] < SECONDS, f"took {result['elapsed']:.1f} s"
    assert result["rss_kb"] < RSS_KB, f"peaked at {result['rss_kb'] // 1024} MB"
    assert result["complete"] is False
    assert result["cap_exceeded"] is True
    assert "limit" in result["reason"]
    assert result["channels"] == 0


# The bombs: every way a small file can claim or hide a huge expansion.


def test_a_zstd_bomb_with_a_summary_is_refused_fast_and_small(tmp_path: Path) -> None:
    path = bombs.write(tmp_path / "bomb.mcap", bombs.mcap_with_chunk(bombs.zeros_zstd()))
    assert path.stat().st_size < 32 * 1024
    _refused(_probe(path))


def test_a_zstd_bomb_without_a_summary_is_refused_fast_and_small(tmp_path: Path) -> None:
    data = bombs.mcap_with_chunk(bombs.zeros_zstd(), summary=False)
    _refused(_probe(bombs.write(tmp_path / "bomb.mcap", data)))


def test_a_chunk_header_that_lies_about_its_size_does_not_hide_the_bomb(tmp_path: Path) -> None:
    """The reader's own decompression ignores the header's size when the frame states one."""
    data = bombs.mcap_with_chunk(bombs.zeros_zstd(), declared=100)
    _refused(_probe(bombs.write(tmp_path / "bomb.mcap", data)))


def test_a_zstd_frame_with_no_stated_size_is_still_bounded(tmp_path: Path) -> None:
    data = bombs.mcap_with_chunk(bombs.zeros_zstd(content_size=False), declared=100)
    _refused(_probe(bombs.write(tmp_path / "bomb.mcap", data)))


def test_an_lz4_bomb_is_refused_fast_and_small(tmp_path: Path) -> None:
    data = bombs.mcap_with_chunk(bombs.zeros_lz4(128 << 20), compression="lz4", declared=100)
    _refused(_probe(bombs.write(tmp_path / "bomb.mcap", data)))


def test_a_decompression_bomb_stops_at_the_per_chunk_cap(tmp_path: Path) -> None:
    """One chunk well over 32 MiB, with a total far below 2 GiB, stops at the per-chunk cap.

    128 MiB is four times the per-chunk cap and one sixteenth of 2 GiB, so a stop here
    cannot be the total cap. The file is a few tens of kilobytes; an unguarded read would
    hold the decompressed chunk.
    """
    size = 128 << 20
    data = bombs.mcap_with_chunk(bombs.zeros_zstd(size), declared=size)
    result = _probe(bombs.write(tmp_path / "bomb.mcap", data))
    _refused(result)
    assert "per chunk" in result["reason"]
    assert "in total" not in result["reason"]


def test_a_chunk_of_millions_of_tiny_records_is_refused_fast(tmp_path: Path) -> None:
    """Each chunk is under 32 MiB and the total is under 2 GiB, but the records pass 50,000,000.

    Fifteen chunks of 30 MiB of empty records are about 52.4 million records and 450 MiB
    decompressed. The parse, not the memory, is what would take the time.
    """
    size = 30 << 20
    declared = size - size % 9
    data = bombs.mcap_with_chunks([(bombs.empty_records_zstd(size), declared)] * 15)
    result = _probe(bombs.write(tmp_path / "records.mcap", data))
    assert result["elapsed"] < 60, f"took {result['elapsed']:.1f} s"
    assert result["rss_kb"] < RSS_KB, f"peaked at {result['rss_kb'] // 1024} MB"
    assert result["complete"] is False
    assert result["cap_exceeded"] is True
    assert "records" in result["reason"]
    assert result["channels"] == 0


def test_many_chunks_each_under_the_chunk_limit_are_refused_in_total(tmp_path: Path) -> None:
    """Seventy chunks of 30 MiB: each is allowed, together they are 2,100 MiB, over 2 GiB.

    The reader streams one chunk at a time, so a file that expands past 2 GiB is refused
    without holding memory that scales with the total cap.
    """
    size = 30 << 20
    data = bombs.mcap_with_chunks([(bombs.one_record_zstd(size), size)] * 70)
    result = _probe(bombs.write(tmp_path / "many.mcap", data))
    assert result["elapsed"] < 60, f"took {result['elapsed']:.1f} s"
    assert result["cap_exceeded"] is True
    assert "in total" in result["reason"]
    assert result["rss_kb"] < RSS_KB, f"peaked at {result['rss_kb'] // 1024} MB"


def test_messages_raises_a_read_limit_error_for_a_bomb(tmp_path: Path) -> None:
    path = bombs.write(tmp_path / "bomb.mcap", bombs.mcap_with_chunk(bombs.zeros_zstd(1 << 28)))
    with pytest.raises(mcap_reader.ReadCapError, match="limit"):
        list(mcap_reader.messages(path))
    assert issubclass(mcap_reader.ReadCapError, mcap_reader.ReadError)


# The limits themselves, lowered so a normal recording can cross each one quickly.


def _recording(tmp_path: Path, count: int = 100) -> Path:
    return rec.write_mcap(tmp_path / "r.mcap", rec.default_channels(count))


def test_the_defaults_are_the_documented_values() -> None:
    limits = mcap_reader.STANDARD_CAPS
    assert limits == mcap_reader.Caps(
        max_chunk_bytes=32 << 20,
        max_total_bytes=2 << 30,
        max_records=50_000_000,
        max_chunks=100_000,
    )


def test_a_normal_recording_is_complete_under_the_defaults(tmp_path: Path) -> None:
    inspection = mcap_reader.inspect(_recording(tmp_path))
    assert inspection.complete and inspection.cap_exceeded is False
    assert [c.message_count for c in inspection.channels] == [100, 100]


def test_the_real_recording_is_complete_under_the_defaults() -> None:
    path = base.REAL / "mcap" / "trial-01.mcap"
    assert mcap_reader.inspect(path).complete


@pytest.mark.parametrize(
    ("limits", "name"),
    [
        ({"max_chunk_bytes": 1024}, "per chunk"),
        ({"max_total_bytes": 4096}, "in total"),
        ({"max_records": 150}, "records"),
        ({"max_chunks": 3}, "chunks"),
    ],
)
def test_each_limit_refuses_a_recording_that_crosses_it(
    tmp_path: Path, limits: dict, name: str
) -> None:
    inspection = mcap_reader.inspect(_recording(tmp_path), mcap_reader.Caps(**limits))
    assert not inspection.complete
    assert inspection.cap_exceeded is True
    assert name in inspection.reason
    assert inspection.channels == ()


def _records_in_chunks(path: Path) -> int:
    """Every record inside the file's chunks, counted with the ``mcap`` package itself."""
    from mcap.reader import make_reader
    from mcap.stream_reader import breakup_chunk

    with path.open("rb") as stream:
        reader = make_reader(stream)
        total = 0
        for index in reader.get_summary().chunk_indexes:
            stream.seek(index.chunk_start_offset + 9)
            from mcap.data_stream import ReadDataStream
            from mcap.records import Chunk

            total += len(list(breakup_chunk(Chunk.read(ReadDataStream(stream)))))
        return total


def test_a_recording_exactly_at_a_limit_is_read(tmp_path: Path) -> None:
    path = _recording(tmp_path)
    exact = _records_in_chunks(path)
    assert exact >= 200  # the messages, plus the channel and schema records
    assert mcap_reader.inspect(path, mcap_reader.Caps(max_records=exact)).complete
    assert not mcap_reader.inspect(path, mcap_reader.Caps(max_records=exact - 1)).complete


def test_a_truncated_file_is_incomplete_but_not_a_limit_breach(tmp_path: Path) -> None:
    path = _recording(tmp_path)
    rec.truncate(path)
    inspection = mcap_reader.inspect(path)
    assert not inspection.complete and inspection.cap_exceeded is False


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "64"])
def test_a_limit_must_be_a_positive_integer(bad: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        mcap_reader.Caps(max_records=bad)  # type: ignore[arg-type]


# The finding, end to end through a run.


def test_a_bomb_in_a_run_is_one_clear_mcap_incomplete_finding(tmp_path: Path) -> None:
    def swap(index: int, path: Path) -> None:
        if index == 2:
            path.write_bytes(bombs.mcap_with_chunk(bombs.zeros_zstd(1 << 28)))

    document, check = base._doctored(tmp_path, edit=swap)
    assert "mcap-incomplete" in base._categories(check)
    (first,) = [f for f in check["findings"] if f["category"] == "mcap-incomplete"]
    assert first["trial_id"] == "trial-02"
    assert first["classification"] == "test_system"
    assert "size limit" in first["summary"]
    assert "does not open" not in first["summary"]
    assert "missing-channel" not in base._categories(check)
    base._conforming_error(document)


def test_the_limit_summary_is_short_enough_for_a_card() -> None:
    summary = base.module().CAP_SUMMARY
    assert len(summary) <= 160


# Where the limits are documented.


def test_the_docs_state_every_default() -> None:
    text = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    for needle in ("32 MiB", "2 GiB", "50,000,000", "100,000"):
        assert needle in text, needle
    assert "decompress" in text and "fail" in text.lower()


def test_the_reader_stays_standalone() -> None:
    tree = ast.parse((SRC / "mcap_reader.py").read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    assert not any(name and name.startswith("livingproof_evaluator_run") for name in imported)


def test_no_bomb_file_is_committed() -> None:
    biggest = max((p.stat().st_size for p in (ROOT / "tests").rglob("*") if p.is_file()), default=0)
    assert biggest < 1 << 20
