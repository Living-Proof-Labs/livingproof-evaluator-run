"""A small, standalone reader for MCAP recordings.

It opens a recording, says whether it is complete, lists its channels, iterates its messages in
file order and reports, per channel, the message count, the timestamps that go backwards and the
largest gap. It knows nothing of checks, findings or the result format, and imports nothing from
this package, so it can move to a shared package unchanged. It is built on the ``mcap`` package
(1.6.0, the version livingproof-sim-mujoco writes with).

"Complete" means the file opens, has its closing magic, a valid footer and a summary section,
every chunk reads (CRCs are validated), and the messages can be read to the end. Anything else
is incomplete with a ``reason``; ``inspect`` never raises on a bad file.

Times are the messages' ``log_time`` in nanoseconds. Messages are read in the order they are
stored, not sorted by time, so a timestamp that goes backwards stays visible; only the gap is
taken from the sorted times.

A gap is the largest step between two consecutive messages of one channel in log-time order, so
messages written out of order are not a capture gap (livingproof-evaluator#34). A step back in
file order is still counted in ``backward_steps``; equal times are neither a gap nor a step back.
``max_gap_seconds`` is ``max_gap_ns / 1e9``, the double nearest the decimal value, so a gap that
equals a decimal limit such as 0.1 s compares equal to it.

Hostile files. A recording is evidence from outside this process, and a few kilobytes of
compressed chunk can expand to gigabytes (livingproof-evaluator-run#17: 32 KB became 1 GiB,
about 43 s and 1 GB of memory). Before the ``mcap`` package decompresses or parses anything,
``_check_caps`` walks the chunks it is about to read and refuses the file, without reading
past the limit, when it holds more than ``Caps`` allow: bytes per chunk, bytes in total,
records (messages, channels and schemas) and chunks. A chunk header's own size is not trusted
(the decompressor ignores it when the frame states another), so each chunk is decompressed
into a buffer no larger than the per-chunk limit and counted as it is. Exceeding a limit is
not a crash: ``inspect`` returns an incomplete result with ``cap_exceeded`` true and a
reason that names the limit, and ``messages`` raises ``ReadCapError``. The caps are on
size and counts, not on a timer, so the result does not depend on how fast the machine is.
"""

from __future__ import annotations

import io
import os
import struct
from array import array
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import lz4.frame
import zstandard
from mcap.reader import SeekingReader


class ReadError(Exception):
    """The file cannot be read as a complete MCAP recording."""


class ReadCapError(ReadError):
    """The recording is bigger than the reader's caps allow, so it was not read.

    ``limit`` names the cap (``chunk-bytes``, ``total-bytes``, ``records`` or ``chunks``, the
    contract's words) and ``value`` is its value from ``Caps``.
    """

    def __init__(self, message: str, limit: str | None = None, value: int | None = None) -> None:
        super().__init__(message)
        self.limit = limit
        self.value = value


@dataclass(frozen=True)
class Caps:
    """What the reader will take from one recording before it refuses to read it.

    ``max_chunk_bytes``: one chunk, decompressed. ``max_total_bytes``: all chunks, decompressed.
    ``max_records``: records inside chunks (messages, channels, schemas). ``max_chunks``: chunks.
    A value at the limit is read; one over it is refused.
    """

    max_chunk_bytes: int = 32 << 20
    max_total_bytes: int = 2 << 30
    max_records: int = 50_000_000
    max_chunks: int = 100_000

    def __post_init__(self) -> None:
        for name in ("max_chunk_bytes", "max_total_bytes", "max_records", "max_chunks"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer, not {value!r}")


STANDARD_CAPS = Caps()


@dataclass(frozen=True)
class Message:
    """One message: the channel's topic and the message's ``log_time`` in nanoseconds."""

    topic: str
    log_time: int


@dataclass(frozen=True)
class ChannelStats:
    """What a recording holds for one channel."""

    topic: str
    message_count: int
    backward_steps: int
    max_gap_ns: int

    @property
    def max_gap_seconds(self) -> float:
        return self.max_gap_ns / 1e9


@dataclass(frozen=True)
class Inspection:
    """The result of ``inspect``. ``channels`` are sorted by topic."""

    complete: bool
    reason: str | None
    channels: tuple[ChannelStats, ...]
    cap_exceeded: bool = False
    over_limit: tuple[str, int] | None = None  # the cap that was hit and its value


def channel_stats(
    messages: Iterable[Message], topics: Iterable[str] = ()
) -> tuple[ChannelStats, ...]:
    """Per-channel statistics for ``messages``, sorted by topic.

    ``backward_steps`` follows the order given; ``max_gap_ns`` follows log-time order.

    ``topics`` lists channels to report even when no message was seen (count 0).
    """
    count: dict[str, int] = {topic: 0 for topic in topics}
    times: dict[str, array] = {}
    backward: dict[str, int] = {}
    for message in messages:
        topic = message.topic
        count[topic] = count.get(topic, 0) + 1
        seen = times.setdefault(topic, array("Q"))
        if seen and message.log_time < seen[-1]:
            backward[topic] = backward.get(topic, 0) + 1
        seen.append(message.log_time)
    return tuple(
        ChannelStats(topic, count[topic], backward.get(topic, 0), _largest_step(times.get(topic)))
        for topic in sorted(count)
    )


def _largest_step(times: array | None) -> int:
    """The largest step between consecutive values of ``times`` once sorted, 0 for fewer than two."""
    if times is None or len(times) < 2:
        return 0
    ordered = sorted(times)
    return max(b - a for a, b in zip(ordered, ordered[1:], strict=False))


def messages(path: Path, caps: Caps = STANDARD_CAPS) -> Iterator[Message]:
    """The messages of the recording at ``path`` in file order.

    Raises ``ReadError`` if the file cannot be read, ``ReadCapError`` if it is over ``caps``
    (before any message is yielded); messages already yielded stand.
    """
    try:
        with Path(path).open("rb") as stream:
            reader = _open(stream)
            _check_caps(stream, reader.get_summary(), caps)
            for _schema, channel, message in reader.iter_messages(log_time_order=False):
                yield Message(channel.topic, message.log_time)
    except ReadError:
        raise
    except Exception as exc:
        raise ReadError(_reason(exc)) from exc


def inspect(path: Path, caps: Caps = STANDARD_CAPS) -> Inspection:
    """Whether the recording at ``path`` is complete, and what it holds per channel.

    Never raises on a bad file. A file with no summary still reports the channels read from its
    data; one that cannot be read to the end reports none. A file over ``caps`` is not read:
    it is incomplete, reports no channels, and has ``cap_exceeded`` set.
    """
    reason: str | None = None
    topics: list[str] = []
    try:
        with Path(path).open("rb") as stream:
            reader = _open(stream)
            summary = reader.get_summary()
            _check_caps(stream, summary, caps)
            if summary is None:
                reason = "the file has no summary section"
            else:
                topics = [channel.topic for channel in summary.channels.values()]
            found = channel_stats(
                (
                    Message(channel.topic, message.log_time)
                    for _schema, channel, message in reader.iter_messages(log_time_order=False)
                ),
                topics,
            )
    except ReadCapError as exc:
        hit = (exc.limit, exc.value) if exc.limit and exc.value is not None else None
        return Inspection(False, str(exc), (), True, hit)
    except Exception as exc:
        return Inspection(False, _reason(exc), ())
    return Inspection(reason is None, reason, found)


def _open(stream) -> SeekingReader:
    return SeekingReader(stream, validate_crcs=True)


def _mib(count: int) -> str:
    if count % (1 << 30) == 0:
        return f"{count >> 30} GiB"
    return f"{count >> 20} MiB" if count % (1 << 20) == 0 else f"{count} bytes"


_RECORD = struct.Struct("<BQ")  # opcode, body length: every MCAP record starts like this
_CHUNK_FIXED = struct.Struct("<QQQI")  # start time, end time, uncompressed size, crc
_CHUNK, _DATA_END, _FOOTER = 6, 15, 2
_BLOCK = 1 << 20


class _Meter:
    """What has been counted so far, and the caps it is counted against."""

    def __init__(self, caps: Caps) -> None:
        self.caps = caps
        self.chunks = 0
        self.total = 0
        self.records = 0

    def chunk(self) -> None:
        self.chunks += 1
        if self.chunks > self.caps.max_chunks:
            raise ReadCapError(
                f"the recording holds more chunks than the limit of {self.caps.max_chunks:,} chunks",
                "chunks",
                self.caps.max_chunks,
            )

    def bytes(self, size: int) -> None:
        self.total += size
        if self.total > self.caps.max_total_bytes:
            raise ReadCapError(
                f"the chunks expand past the limit of {_mib(self.caps.max_total_bytes)} in total",
                "total-bytes",
                self.caps.max_total_bytes,
            )

    def add_records(self, count: int) -> None:
        self.records += count
        if self.records > self.caps.max_records:
            raise ReadCapError(
                f"the recording holds more records than the limit of {self.caps.max_records:,} records",
                "records",
                self.caps.max_records,
            )


def _check_caps(stream, summary, caps: Caps) -> None:
    """Raise ``ReadCapError`` if reading the chunks ``mcap`` is about to read would pass a limit.

    It looks at exactly the chunks the reader will: those the summary indexes, or, with no index,
    every record of the data section. Only the current chunk is held; the totals are counts, so
    the total cap bounds time and not memory. A problem that is not a limit (a bad record, a
    corrupt frame) is left to the reader, which reports it in its own words.
    """
    meter = _Meter(caps)
    size = stream.seek(0, os.SEEK_END)
    indexes = summary.chunk_indexes if summary is not None else []
    if indexes:
        if len(indexes) > caps.max_chunks:
            meter.chunks = len(indexes)
            meter.chunk()
        for index in indexes:
            _scan_chunk(stream, index.chunk_start_offset + 1 + 8, size, meter)
        return
    position = 8  # after the magic
    while position + _RECORD.size <= size:
        stream.seek(position)
        head = stream.read(_RECORD.size)
        if len(head) < _RECORD.size:
            return
        opcode, length = _RECORD.unpack(head)
        if opcode in (_DATA_END, _FOOTER):
            return
        if opcode == _CHUNK:
            _scan_chunk(stream, position + _RECORD.size, size, meter)
        else:
            meter.add_records(1)
        position += _RECORD.size + length


def _scan_chunk(stream, body: int, size: int, meter: _Meter) -> None:
    """Count one chunk whose body starts at ``body``; raise ``ReadCapError`` past a limit."""
    meter.chunk()
    caps = meter.caps
    try:
        stream.seek(body)
        fixed = stream.read(_CHUNK_FIXED.size)
        if len(fixed) < _CHUNK_FIXED.size:
            return
        declared = _CHUNK_FIXED.unpack(fixed)[2]
        (name_length,) = struct.unpack("<I", stream.read(4))
        if name_length > 64:
            return
        compression = stream.read(name_length).decode("utf-8", "replace")
        (data_length,) = struct.unpack("<Q", stream.read(8))
        if data_length > size - stream.tell():
            return  # truncated: the reader reports it
        data = stream.read(data_length)
    except (struct.error, OSError, ValueError):
        return
    if declared > caps.max_chunk_bytes:
        raise ReadCapError(
            f"a chunk claims to expand past the limit of {_mib(caps.max_chunk_bytes)} per chunk",
            "chunk-bytes",
            caps.max_chunk_bytes,
        )
    raw = _bounded(compression, data, caps.max_chunk_bytes)
    if raw is None:
        return
    meter.bytes(len(raw))
    meter.add_records(_count_records(raw, caps.max_records - meter.records))


def _bounded(compression: str, data: bytes, limit: int) -> bytes | None:
    """``data`` decompressed, never holding more than ``limit`` bytes; None when it cannot be.

    Raises ``ReadCapError`` when it would be more than ``limit``.
    """
    over = ReadCapError(
        f"a chunk expands past the limit of {_mib(limit)} per chunk", "chunk-bytes", limit
    )
    if compression == "zstd":
        try:
            stated = zstandard.frame_content_size(data)
        except zstandard.ZstdError:
            return None
        if stated > limit:
            raise over
        try:
            parts, total = [], 0
            with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as source:
                while block := source.read(min(_BLOCK, limit + 1 - total)):
                    total += len(block)
                    if total > limit:
                        raise over
                    parts.append(block)
        except zstandard.ZstdError:
            return None
        return b"".join(parts)
    if compression == "lz4":
        try:
            decoder, parts, total = lz4.frame.LZ4FrameDecompressor(), [], 0
            pending = data
            while True:
                block = decoder.decompress(pending, max_length=min(_BLOCK, limit + 1 - total))
                pending = b""
                total += len(block)
                if total > limit:
                    raise over
                parts.append(block)
                if decoder.eof or not block:
                    break
        except RuntimeError:
            return None
        return b"".join(parts)
    if len(data) > limit:
        raise over
    return data


def _count_records(raw: bytes, room: int) -> int:
    """The records in a decompressed chunk, stopping once there are more than ``room``."""
    position, count, end = 0, 0, len(raw)
    unpack = _RECORD.unpack_from
    while position + 9 <= end:
        count += 1
        if count > room:
            return count
        position += 9 + unpack(raw, position)[1]
    return count


def _reason(exc: Exception) -> str:
    """A short, plain reason for a read failure."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return f"{type(exc).__name__}: {text}"[:200] if text else type(exc).__name__
