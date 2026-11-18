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
stored, not sorted by time, so a timestamp that goes backwards stays visible.

A gap is the largest step forward between two consecutive messages of one channel, in file
order. A step back is counted in ``backward_steps`` and is not a gap; equal times are neither.
``max_gap_seconds`` is ``max_gap_ns / 1e9``, the double nearest the decimal value, so a gap that
equals a decimal limit such as 0.1 s compares equal to it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from mcap.reader import make_reader


class ReadError(Exception):
    """The file cannot be read as a complete MCAP recording."""


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


def channel_stats(
    messages: Iterable[Message], topics: Iterable[str] = ()
) -> tuple[ChannelStats, ...]:
    """Per-channel statistics for ``messages`` in the order given, sorted by topic.

    ``topics`` lists channels to report even when no message was seen (count 0).
    """
    count: dict[str, int] = {topic: 0 for topic in topics}
    last: dict[str, int] = {}
    backward: dict[str, int] = {}
    gap: dict[str, int] = {}
    for message in messages:
        topic = message.topic
        count[topic] = count.get(topic, 0) + 1
        if topic in last:
            step = message.log_time - last[topic]
            if step < 0:
                backward[topic] = backward.get(topic, 0) + 1
            elif step > gap.get(topic, 0):
                gap[topic] = step
        last[topic] = message.log_time
    return tuple(
        ChannelStats(topic, count[topic], backward.get(topic, 0), gap.get(topic, 0))
        for topic in sorted(count)
    )


def messages(path: Path) -> Iterator[Message]:
    """The messages of the recording at ``path`` in file order.

    Raises ``ReadError`` if the file cannot be read; messages already yielded stand.
    """
    try:
        with Path(path).open("rb") as stream:
            reader = make_reader(stream, validate_crcs=True)
            for _schema, channel, message in reader.iter_messages(log_time_order=False):
                yield Message(channel.topic, message.log_time)
    except ReadError:
        raise
    except Exception as exc:
        raise ReadError(_reason(exc)) from exc


def inspect(path: Path) -> Inspection:
    """Whether the recording at ``path`` is complete, and what it holds per channel.

    Never raises on a bad file. A file with no summary still reports the channels read from its
    data; one that cannot be read to the end reports none.
    """
    reason: str | None = None
    topics: list[str] = []
    try:
        with Path(path).open("rb") as stream:
            reader = make_reader(stream, validate_crcs=True)
            summary = reader.get_summary()
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
    except Exception as exc:
        return Inspection(False, _reason(exc), ())
    return Inspection(reason is None, reason, found)


def _reason(exc: Exception) -> str:
    """A short, plain reason for a read failure."""
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return f"{type(exc).__name__}: {text}"[:200] if text else type(exc).__name__
