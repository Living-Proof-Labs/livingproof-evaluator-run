"""Small crafted MCAP files that expand far beyond their size (livingproof-evaluator-run#17).

Each is written byte by byte, because the ``mcap`` writer will not produce a chunk whose header
lies or whose frame has no content size. The compressed file stays a few tens of kilobytes; the
chunk inside would expand to ``EXPANDS_TO`` bytes if a reader trusted it. Built per test and not
committed, so nothing large or opaque lives in the repository.
"""

from __future__ import annotations

import struct
from pathlib import Path

import lz4.frame
import zstandard

MAGIC = b"\x89MCAP0\r\n"
EXPANDS_TO = 512 << 20  # 512 MiB: above every default limit, about 1 GiB of RSS if it were read
_ZEROS = b"\0" * (1 << 20)

HEADER, FOOTER, CHUNK, CHUNK_INDEX, DATA_END = 0x01, 0x02, 0x06, 0x08, 0x0F


def _string(text: str) -> bytes:
    raw = text.encode()
    return struct.pack("<I", len(raw)) + raw


def _record(opcode: int, body: bytes) -> bytes:
    return struct.pack("<BQ", opcode, len(body)) + body


def zeros_zstd(size: int = EXPANDS_TO, *, content_size: bool = True) -> bytes:
    """A zstd frame of ``size`` zero bytes. ``content_size`` False leaves the size out of the
    frame header, as a streaming compressor does."""
    if content_size:
        return zstandard.ZstdCompressor(level=3).compress(b"\0" * size)
    compressor = zstandard.ZstdCompressor(level=3, write_content_size=False).compressobj()
    parts = [compressor.compress(_ZEROS) for _ in range(size >> 20)]
    parts.append(compressor.flush())
    return b"".join(parts)


def zeros_lz4(size: int = EXPANDS_TO) -> bytes:
    compressor = lz4.frame.LZ4FrameCompressor()
    parts = [compressor.begin()]
    parts += [compressor.compress(_ZEROS) for _ in range(size >> 20)]
    parts.append(compressor.flush())
    return b"".join(parts)


def mcap_with_chunk(
    compressed: bytes,
    *,
    compression: str = "zstd",
    declared: int | None = None,
    summary: bool = True,
) -> bytes:
    """An MCAP with one chunk holding ``compressed``.

    ``declared`` is the uncompressed size the chunk header claims (default: the real EXPANDS_TO,
    so pass a small number to make the header lie). ``summary`` False writes no summary section,
    so a reader must walk the data section.
    """
    claimed = EXPANDS_TO if declared is None else declared
    out = bytearray(MAGIC)
    out += _record(HEADER, _string("") + _string("bomb"))
    start = len(out)
    body = (
        struct.pack("<QQQI", 0, 0, claimed, 0)
        + _string(compression)
        + struct.pack("<Q", len(compressed))
        + compressed
    )
    out += _record(CHUNK, body)
    chunk_length = len(out) - start
    out += _record(DATA_END, struct.pack("<I", 0))
    if not summary:
        out += _record(FOOTER, struct.pack("<QQI", 0, 0, 0)) + MAGIC
        return bytes(out)
    summary_start = len(out)
    index = (
        struct.pack("<QQQQ", 0, 0, start, chunk_length)
        + struct.pack("<I", 0)  # no message index offsets
        + struct.pack("<Q", 0)
        + _string(compression)
        + struct.pack("<QQ", len(compressed), claimed)
    )
    out += _record(CHUNK_INDEX, index)
    out += _record(FOOTER, struct.pack("<QQI", summary_start, 0, 0)) + MAGIC
    return bytes(out)


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
