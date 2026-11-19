"""recording 1.2.0 (livingproof-evaluator-run#23): ``recording-over-limit``.

A recording the reader refused at a decompression cap is still present. The check judges the trial,
names the cap and its value (from ``mcap_reader.Caps``), and fails closed. It is not truncation, so
completeness reports nothing and no ``missing-channel`` follows. Contract: livingproof-evaluator
v1.3.4, ``docs/run-integrity.md`` and ``examples/integrity/recording/over-limit``.
"""

from __future__ import annotations

import json
from pathlib import Path

import bombs
import pytest
import test_recording as rt

from livingproof_evaluator_run import evaluate, mcap_reader, recording

EXAMPLE = rt.base.CONTRACT / "examples" / "integrity" / "recording" / "over-limit"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_result(request: dict, tmp_path: Path) -> dict:
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request), encoding="utf-8")
    out = tmp_path / "result.json"
    assert evaluate(source, out) == 0
    return _load(out)


def test_the_published_over_limit_example_gives_the_published_check(tmp_path: Path) -> None:
    document = _request_result(_load(EXAMPLE / "request.json"), tmp_path)
    want = [
        c for c in _load(EXAMPLE / "result.json")["integrity"]["checks"] if c["id"] == "recording"
    ]
    (got,) = [c for c in document["integrity"]["checks"] if c["id"] == "recording"]
    assert got == want[0]
    completeness = next(c for c in document["integrity"]["checks"] if c["id"] == "completeness")
    assert not any(f["category"] == "truncated-recording" for f in completeness["findings"])
    assert rt.base._validate(document) == []


@pytest.mark.parametrize("limit", ["chunk-bytes", "total-bytes", "records", "chunks"])
def test_a_request_names_each_limit_in_the_summary(limit: str, tmp_path: Path) -> None:
    request = _load(EXAMPLE / "request.json")
    value = {"chunk-bytes": 33_554_432, "total-bytes": 2_147_483_648}.get(limit, 1234)
    entry = request["integrity"]["evidence"]["recording"]["trials"][1]
    entry["over_limit"] = {"limit": limit, "value": value}
    document = _request_result(request, tmp_path)
    (check,) = [c for c in document["integrity"]["checks"] if c["id"] == "recording"]
    (found,) = check["findings"]
    unit = " bytes" if limit.endswith("bytes") else ""
    assert found["category"] == "recording-over-limit"
    assert f"{limit} limit of {value}{unit}," in found["summary"]


@pytest.mark.parametrize(
    ("caps", "limit", "value"),
    [
        (mcap_reader.Caps(max_chunk_bytes=1024), "chunk-bytes", 1024),
        (mcap_reader.Caps(max_total_bytes=4096), "total-bytes", 4096),
        (mcap_reader.Caps(max_records=10), "records", 10),
        (mcap_reader.Caps(max_chunks=1), "chunks", 1),
    ],
)
def test_the_reader_reports_which_cap_it_hit_and_its_value(
    caps: mcap_reader.Caps, limit: str, value: int, tmp_path: Path
) -> None:
    import recordings as rec

    path = tmp_path / "r.mcap"
    if limit == "records":
        rec.write_mcap(path, {rec.POSE: rec.steps(200), rec.JOINTS: rec.steps(200)})
    else:
        path.write_bytes(bombs.mcap_with_chunks([(bombs.zeros_zstd(2048), 2048)] * 3))
    inspection = mcap_reader.inspect(path, caps)
    assert inspection.cap_exceeded is True
    assert inspection.over_limit == (limit, value)


def test_a_file_that_is_not_over_a_limit_has_no_over_limit(tmp_path: Path) -> None:
    import recordings as rec

    path = tmp_path / "r.mcap"
    rec.write_mcap(path, {rec.POSE: rec.steps(20), rec.JOINTS: rec.steps(20)})
    assert mcap_reader.inspect(path).over_limit is None


def test_recording_is_at_1_2_0_and_remembers_1_1_0_and_1_0_0() -> None:
    assert recording.RECORDING_VERSION == "1.2.0"
    assert recording.PREVIOUS_VERSIONS == ("1.0.0", "1.1.0")
    assert "recording-over-limit" in recording.CATEGORIES


def test_a_bomb_in_a_run_keeps_the_trial_present_and_judged(tmp_path: Path) -> None:
    def swap(index: int, path: Path) -> None:
        if index == 3:
            path.write_bytes(bombs.mcap_with_chunk(bombs.zeros_zstd(1 << 28)))

    document, check = rt._doctored(tmp_path, edit=swap)
    assert [(f["trial_id"], f["category"]) for f in check["findings"]] == [
        ("trial-03", "recording-over-limit")
    ]
    assert check["percentage"] == pytest.approx(100 * 2 / 3)
    assert check["not_checked"] == []
