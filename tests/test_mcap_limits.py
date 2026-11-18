"""A small hostile recording cannot exhaust the evaluator (livingproof-evaluator-run#17).

Vera's review of PR 16 measured a 32 KB file that expands to 1 GiB taking about 43 s and 1 GB
RSS, and 4 GiB taking about 171 s and 4 GB. The reader now refuses, before it decompresses or
parses past a limit, any recording whose chunks expand beyond a documented cap, and says so as a
clear ``mcap-incomplete`` finding instead of crashing or running out of memory.

The bombs are crafted per test (``tests/bombs.py``): a few tens of kilobytes that would expand to
512 MiB. Each is read in a fresh interpreter that reports its own elapsed time and peak RSS, so
the assertions are about bounded time and memory, not just about the finding. Peak RSS is
``ru_maxrss``; an unguarded read of these files needs well over 1 GB.
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
    import json, resource, sys, time
    from pathlib import Path
    from livingproof_evaluator_run import mcap_reader
    started = time.monotonic()
    inspection = mcap_reader.inspect(Path(sys.argv[1]))
    elapsed = time.monotonic() - started
    print(json.dumps({
        "elapsed": elapsed,
        "rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "complete": inspection.complete,
        "reason": inspection.reason,
        "limit_exceeded": getattr(inspection, "limit_exceeded", None),
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
    assert result["limit_exceeded"] is True
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


def test_messages_raises_a_read_limit_error_for_a_bomb(tmp_path: Path) -> None:
    path = bombs.write(tmp_path / "bomb.mcap", bombs.mcap_with_chunk(bombs.zeros_zstd(1 << 28)))
    with pytest.raises(mcap_reader.ReadLimitError, match="limit"):
        list(mcap_reader.messages(path))
    assert issubclass(mcap_reader.ReadLimitError, mcap_reader.ReadError)


# The limits themselves, lowered so a normal recording can cross each one quickly.


def _recording(tmp_path: Path, count: int = 100) -> Path:
    return rec.write_mcap(tmp_path / "r.mcap", rec.default_channels(count))


def test_the_defaults_are_the_documented_values() -> None:
    limits = mcap_reader.DEFAULT_LIMITS
    assert limits == mcap_reader.Limits(
        max_chunk_bytes=64 << 20,
        max_total_bytes=256 << 20,
        max_messages=2_000_000,
        max_chunks=100_000,
    )


def test_a_normal_recording_is_complete_under_the_defaults(tmp_path: Path) -> None:
    inspection = mcap_reader.inspect(_recording(tmp_path))
    assert inspection.complete and inspection.limit_exceeded is False
    assert [c.message_count for c in inspection.channels] == [100, 100]


def test_the_real_recording_is_complete_under_the_defaults() -> None:
    path = base.REAL / "mcap" / "trial-01.mcap"
    assert mcap_reader.inspect(path).complete


@pytest.mark.parametrize(
    ("limits", "name"),
    [
        ({"max_chunk_bytes": 1024}, "per chunk"),
        ({"max_total_bytes": 4096}, "in total"),
        ({"max_messages": 150}, "messages"),
        ({"max_chunks": 3}, "chunks"),
    ],
)
def test_each_limit_refuses_a_recording_that_crosses_it(
    tmp_path: Path, limits: dict, name: str
) -> None:
    inspection = mcap_reader.inspect(_recording(tmp_path), mcap_reader.Limits(**limits))
    assert not inspection.complete
    assert inspection.limit_exceeded is True
    assert name in inspection.reason
    assert inspection.channels == ()


def test_a_recording_exactly_at_a_limit_is_read(tmp_path: Path) -> None:
    path = _recording(tmp_path)
    assert mcap_reader.inspect(path, mcap_reader.Limits(max_messages=200)).complete
    assert not mcap_reader.inspect(path, mcap_reader.Limits(max_messages=199)).complete


def test_a_truncated_file_is_incomplete_but_not_a_limit_breach(tmp_path: Path) -> None:
    path = _recording(tmp_path)
    rec.truncate(path)
    inspection = mcap_reader.inspect(path)
    assert not inspection.complete and inspection.limit_exceeded is False


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "64"])
def test_a_limit_must_be_a_positive_integer(bad: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        mcap_reader.Limits(max_messages=bad)  # type: ignore[arg-type]


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
    summary = base.module().LIMIT_SUMMARY
    assert len(summary) <= 160


# Where the limits are documented.


def test_the_docs_state_every_default() -> None:
    text = (ROOT / "docs" / "index.md").read_text(encoding="utf-8")
    for needle in ("64 MiB", "256 MiB", "2,000,000", "100,000"):
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
