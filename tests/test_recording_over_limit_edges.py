"""Edge cases for recording 1.2.0 over-cap handling (livingproof-evaluator-run#23, Vera's checks).

Boundary: a recording exactly at a cap is read; one over it is refused. Mixed runs: several over-cap
files, and an over-cap file next to a truncated or missing-channel one, each keep their own finding.
"""

from __future__ import annotations

from pathlib import Path

import bombs
import pytest
import recordings as rec
import test_recording as rt

from livingproof_evaluator_run import mcap_reader


def _bomb(path: Path) -> None:
    path.write_bytes(bombs.mcap_with_chunk(bombs.zeros_zstd(1 << 28)))


def _smallest_passing(path: Path, field: str, high: int) -> int:
    """The smallest value of one cap that still reads ``path``: the file's own size on that axis."""
    low = 1
    while low < high:
        mid = (low + high) // 2
        inspection = mcap_reader.inspect(path, mcap_reader.Caps(**{field: mid}))
        if inspection.cap_exceeded:
            low = mid + 1
        else:
            high = mid
    return low


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("max_records", "records"),
        ("max_total_bytes", "total-bytes"),
        ("max_chunk_bytes", "chunk-bytes"),
    ],
)
def test_a_value_exactly_at_the_cap_is_read_and_one_over_is_refused(
    field: str, limit: str, tmp_path: Path
) -> None:
    path = tmp_path / "r.mcap"
    rec.write_mcap(path, {rec.POSE: rec.steps(60), rec.JOINTS: rec.steps(60)})
    at = _smallest_passing(path, field, 1 << 24)
    assert at > 1
    ok = mcap_reader.inspect(path, mcap_reader.Caps(**{field: at}))
    assert ok.cap_exceeded is False and ok.over_limit is None and ok.complete is True
    over = mcap_reader.inspect(path, mcap_reader.Caps(**{field: at - 1}))
    assert over.cap_exceeded is True
    assert over.over_limit == (limit, at - 1)


def test_the_chunk_count_cap_is_inclusive(tmp_path: Path) -> None:
    path = tmp_path / "r.mcap"
    path.write_bytes(bombs.mcap_with_chunks([(bombs.zeros_zstd(2048), 2048)] * 3))
    assert mcap_reader.inspect(path, mcap_reader.Caps(max_chunks=3)).over_limit != ("chunks", 3)
    assert mcap_reader.inspect(path, mcap_reader.Caps(max_chunks=2)).over_limit == ("chunks", 2)


def test_several_over_cap_files_each_get_exactly_one_over_limit_finding(tmp_path: Path) -> None:
    document, check = rt._doctored(tmp_path, edit=lambda i, p: _bomb(p) if i in (1, 3) else None)
    assert [(f["trial_id"], f["category"]) for f in check["findings"]] == [
        ("trial-01", "recording-over-limit"),
        ("trial-03", "recording-over-limit"),
    ]
    assert not rt._completeness(document)
    assert check["not_checked"] == []
    assert rt.base._validate(document) == []


def test_every_trial_over_cap_is_still_present_and_fails_closed(tmp_path: Path) -> None:
    document, check = rt._doctored(tmp_path, edit=lambda i, p: _bomb(p))
    assert rt._categories(check) == ["recording-over-limit"] * 3
    assert check["success"] is False
    assert not rt._completeness(document)
    rt._conforming_error(document)


def test_an_over_cap_file_next_to_a_truncated_one_keeps_both_findings(tmp_path: Path) -> None:
    def edit(index: int, path: Path) -> None:
        if index == 1:
            rec.truncate(path)
        elif index == 3:
            _bomb(path)

    document, check = rt._doctored(tmp_path, edit=edit)
    assert rt._completeness(document) == {"trial-01": "truncated-recording"}
    assert [(f["trial_id"], f["category"]) for f in check["findings"]] == [
        ("trial-03", "recording-over-limit")
    ]
    assert ("trial-01", "not-present") in rt._not_checked(check)
    assert rt.base._validate(document) == []


def test_an_over_cap_file_next_to_a_missing_channel_one_keeps_both_findings(tmp_path: Path) -> None:
    only_pose = {1: {rec.POSE: rec.steps(50)}}
    document, check = rt._doctored(
        tmp_path, channels=only_pose, edit=lambda i, p: _bomb(p) if i == 3 else None
    )
    found = {(f["trial_id"], f["category"]) for f in check["findings"]}
    assert found == {("trial-01", "missing-channel"), ("trial-03", "recording-over-limit")}
    assert not rt._completeness(document)
    assert rt.base._validate(document) == []


def _from_evidence_at(version: str, tmp_path: Path):
    import json

    folder = rt._evidence(tmp_path, channels=["/base_pose", "/joint_states"])
    media = rt._media(tmp_path, folder, edit=lambda i, p: _bomb(p) if i == 3 else None)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    results = {row["index"]: row for row in manifest["trials"]["results"]}
    return rt.module().from_evidence(manifest, media, 3, results, version)


def test_1_0_0_selection_still_reports_an_over_cap_file_as_mcap_incomplete(tmp_path: Path) -> None:
    outcome = _from_evidence_at("1.0.0", tmp_path)
    assert [(f["trial_id"], f["category"]) for f in outcome.findings] == [
        ("trial-03", "mcap-incomplete")
    ]
    assert outcome.not_checked is None


def test_1_1_0_selection_does_not_judge_an_over_cap_file_and_adds_no_finding(
    tmp_path: Path,
) -> None:
    outcome = _from_evidence_at("1.1.0", tmp_path)
    assert outcome.findings == []
    assert [i["trial_id"] for i in outcome.not_checked] == ["trial-03"]


@pytest.mark.xfail(
    strict=True,
    reason="#23 changed the 1.1.0 reason from not-present to not-recorded; behaviour was 'as before'",
)
def test_1_1_0_selection_keeps_not_present_as_the_reason_for_an_over_cap_file(
    tmp_path: Path,
) -> None:
    outcome = _from_evidence_at("1.1.0", tmp_path)
    assert outcome.not_checked == [{"trial_id": "trial-03", "reason": "not-present"}]


@pytest.mark.xfail(
    strict=True,
    reason="#26: with no gap limit declared, recording is not applicable and nothing reports an "
    "over-cap file, so the run reads COMPLETED 100 (main reported it via completeness)",
)
def test_an_over_cap_file_is_not_a_clean_run_even_when_no_gap_limit_is_declared(
    tmp_path: Path,
) -> None:
    folder = rt._evidence(tmp_path, gap=None)
    media = rt._media(tmp_path, folder, edit=lambda i, p: _bomb(p) if i == 3 else None)
    document = rt._run(folder, tmp_path, media)
    assert document["integrity"]["run"]["success"] is False
