# LivingProof Run Evaluator

Evaluates run infrastructure and evidence suitability for judging robot capabilities.

## Start here

The first slice is a completeness check on hallway evidence: planned trial
count versus observation files present, and declared digests matching. Four checks
follow: `pins`, `plan-conformance`, `termination` and `recording`. It reports test-system status only. It never
grades the robot. Later checks are added one
at a time; see [issue 3](https://github.com/Living-Proof-Labs/livingproof-evaluator-run/issues/3).

```bash
python -m livingproof_evaluator_run evidence/manifest.json --out result.json
python -m livingproof_evaluator_run evidence/manifest.json --media media --out result.json
```

`--media` is the media job's artifact (`media.json` and `mcap/`) and is optional. See
`recording` below.

## Checks

- `completeness` 1.1.0: see above. It also reads `media.json` when `--media` is given: every
  recording `media.json` lists must be there, readable and not empty. A listed recording that is
  missing is `missing-recording`, one with no valid footer and summary is `truncated-recording`,
  and an empty file is `empty-recording`. Completeness owns all three, so a truncated recording is
  reported once, here, and `recording` does not judge it. Without `--media`, or when the
  manifest's preconditions are unmet, recordings are not looked at. The check never carries
  `not_checked`.
- `pins` 1.1.0: compares the pins the verification lock declares (embedded in the
  manifest as `lock.content`) with what the run recorded, for five subjects.
  A mismatch is one `hash-mismatch` finding on that subject. It names the declared
  and the recorded value, is a test-system finding, and never changes a robot grade.

| Subject | Declared by the lock | Recorded by the run |
| --- | --- | --- |
| `world` | `sources.world.sha256`, else `world.sha256` | `world.sha256` in `manifest.json`, else in `run-manifest.json` beside it for the same run |
| `configuration` | `configurations[].sha256` for the recorded configuration | `configuration.sha256` |
| `runner` | `releases.runner.commit` | `environment.runner.commit` and `environment.simulator.adapter_commit` |
| `specs` | `releases.specs.files` | not recorded, so not checked |
| `verifier` | `releases.verifier.digest` | not recorded, so not checked |

A subject with no declared or no recorded value is **not checked**. It is listed in the
check's `not_checked` (reason `not-declared` when neither side carries the pin, `not-recorded`
when the lock declares it and the run did not) and in the result summary. It is never counted as
matching and never fails the check. An empty `not_checked` means every subject was compared. Until the
runner and verifier record the spec files and image digest they used
(livingproof-sim-mujoco#104, capability-verifier#153 and #154), `specs` and
`verifier` stay not checked. The share is the matching subjects divided by the subjects that were compared
when a subject differs, and 100 otherwise (1.0.0 divided by five). When no subject could be compared (no
embedded lock, a lock that declares nothing the run recorded, or a run that recorded
nothing the lock declares), `pins` is reported as not applicable rather than as a pass.

What "recorded" means: `configuration.sha256` and `runner.commit` are copied from the
lock by the runner, so a match on those two shows the run carried the lock's values,
not that anything was measured. Only `world` and `adapter_commit` are truly measured.
The `sha256:` prefix and letter case of a digest are compared as written; they are
normalised once livingproof-sim-mujoco#104 and capability-verifier#153 and #154 land.
The robot-profile fixture listed in
[issue 5](https://github.com/Living-Proof-Labs/livingproof-evaluator-run/issues/5) is
out of scope for this check.

Values copied from evidence into the summary are shown escaped and shortened to 100
characters (a newline as `\x0a`, `<` as `\u003c`), so the result always matches the
contract's descriptor plain-text pattern. If a descriptor still would not match, the
command exits 1 and writes no result. In particular, a blank trial identifier (empty,
whitespace only, or format characters only) has no visible characters and fails closed:
an empty identifier exits 2 with nothing written, and an invisible identifier exits 1
with nothing written.

The same holds for lengths: in the descriptor a finding's trial is cut to 40 characters
and its text to 280, ending in an ellipsis and never splitting an escape sequence (the
check's own findings keep the full trial id), and a descriptor field over the contract's
maximum length also exits 1 with nothing written. The descriptor holds at most 50
findings; when more than 50 are reported, it shows the first 49 and adds a 50th note
(`And N more findings (showing 49 of M).`) in both the summary findings and
`details_copy`, while the check's own findings keep all of them.

- `plan-conformance` 1.1.0: the trials that ran are the trials that were planned. It reads
  structure only and never opens a trial file, so a missing or hash-mismatched trial file stays
  a `completeness` finding and a `plan-conformance` finding carries no trial id. Every finding
  is classified `test_system`; none carries a robot verdict.

| Subject | Finding when it disagrees |
| --- | --- |
| `trials.count`, the number of `trials.results` entries, and the lock's `plan.trials.count`, each against `plan.trials.count` | `trial-count-mismatch` |
| `plan.command_speed` against the lock's, when both record one | `command-speed-mismatch` |
| each index 1 to N (N is the plan's trial count) | `index-missing` when no entry has it, `index-duplicate` when several do, `path-mismatch` when an entry's `path` is not `trials/trial-NN.json` for its own index |
| each entry whose index is not an integer from 1 to N | `index-out-of-range` |

The share is the subjects without a finding divided by all subjects, times 100. The subjects
are the comparisons that were made: one per count compared, one for the command speed when it
was compared, one per index 1 to N, and one per entry outside 1 to N. When the manifest embeds
no lock, the lock comparisons are not made and are not counted, and the summary says
`Not checked: the plan against the lock.` A command speed is compared only when both the plan
and the lock record one.

A run whose preconditions are unmet runs no trials. The manifest then lists a precondition
with `"met": false` (and no `"required": false`), `trials.results` is empty and the planned
count stays at least 1. `plan-conformance` is **not applicable** (`applicable: false`, no
percentage), not an error and not a pass. Evidence that cannot be compared (no plan trial
count, no `trials.count`, `trials.results` not a list) is also not applicable, and the summary
says what was missing. An entry that cannot be placed, such as an index that is a string, a
boolean or a number with a fraction, or a path that is not text, is a finding and never an
exception. `completeness` still reports a run with unmet preconditions by its own rule; this
check does not change that.

At 1.1.0 the check says what it left out in `not_checked` (required; empty when nothing was
left out). With no lock in the evidence both lock comparisons are listed, `lock-trial-count` and
`lock-command-speed`, with the reason `not-declared`; with a lock that records no command speed,
`lock-command-speed` is listed alone. A check that is not applicable lists both.

On an evaluator request the evidence is `integrity.evidence["plan-conformance"]`, as the
contract defines it. A request without it reports the check as not applicable. The check
follows the contract's reference rules (`tests/integrity_rules.py` in the contract kit): the
tests run both against 600 generated cases. Seeds do not exist in evidence 2.0.0, so the
indexes stand for them; if seeds return in a later evidence version that is a new check
version.

- `termination` 1.1.0: every trial that ended on its own records a stop reason, and the plan
  allows it. `completeness` owns a timeout or a crash, so `termination` never raises a finding
  for one; it lists the trial under `referrals` with the `completeness` category that reports
  it (`ended-by-timeout` or `ended-by-crash`). A referral is not a finding and changes neither
  `success` nor the percentage, so each ending is reported once.

| Where it is read | What |
| --- | --- |
| the trial's stop reason | `end` in the trial's observation file, `trials/trial-NN.json` |
| the manifest's copy | `trials.results[].outcome` |
| the plan's allowed list | `plan.allowed_stop_reasons` in the manifest, else the same key in the embedded lock's plan, else the default |

The runner's words map to the contract's stop reasons: `crossed_exit` is `mission-done`,
`left_hallway` and `left_world` are `left-world`, `time_limit` is `time-limit`, `non_finite_state` is
`simulation-broken`, and `adapter_done` is `adapter-or-scenario-done` (the word the contract's
own examples use; no runner writes it today). A word with no mapping is kept as written and is
reported as `unknown-stop-reason`.

**The default allowed list** is `time-limit`, `mission-done`, `left-world` and
`adapter-or-scenario-done`. It leaves out `simulation-broken`, so a trial whose physics state
went non-finite is a `disallowed-stop-reason` finding. **At 1.1.0 `simulation-broken` is never
allowed**: a plan that lists it does not make it so, and the finding says the reason is never
allowed (1.0.0 let a plan allow it). A
declaration that is not a list, or names no known stop reason, is not used: the default applies
and the summary says so. A malformed declaration can therefore never allow more than the default.
No plan declares a list today, so the default applies to every run.

| Category | When |
| --- | --- |
| `missing-stop-reason` | the trial file has no `end`, or is not a JSON object |
| `unknown-stop-reason` | the stop reason is outside the vocabulary, or is not text |
| `disallowed-stop-reason` | the reason is in the vocabulary and the plan does not allow it |
| `stop-reason-mismatch` | the observation and the manifest's `outcome` differ (a missing `outcome` is not a mismatch) |

Findings carry the trial id and never a verdict. The share is the judged trials without a
finding over the judged trials; `time-limit` and `left-world` are clean endings here, and what
they mean for the robot is for the Scenario evaluator. The findings do not change a trial's own
status: that stays with `completeness`, as in the contract's examples.

On a manifest only the trials `completeness` found complete are judged, so a missing or
hash-mismatched trial file stays a `completeness` finding and is not repeated. With no judged
trial the check is not applicable. **What it cannot see:** an evidence manifest records no
timeout, crash or killed process, so on a manifest `referrals` is always empty and a crash is
only visible as a missing trial file (`completeness`). Recording them is
[livingproof-sim-mujoco#105](https://github.com/Living-Proof-Labs/livingproof-sim-mujoco/issues/105)
and [capability-verifier#155](https://github.com/Living-Proof-Labs/capability-verifier/issues/155).
On a `livingproof-evaluator-request` each trial carries its `termination`, `completeness`
reports `ended-by-timeout` or `ended-by-crash` for it, and the stop reasons are read from
`integrity.evidence["termination"]` as the contract defines them (already in the contract's
words, so nothing is mapped). The tests run the contract's reference rules against these on 600
generated cases.

- `recording` 1.2.0: each recording that is present is a usable MCAP file that matches
  `media.json` and the run evidence. A recording the reader refuses at a size limit is still
  present and is `recording-over-limit`. A breach is a test-system finding that names the trial;
  it never changes a robot grade or a trial's own status.

**Where the recordings come from.** livingproof-sim-mujoco's `media` module writes
`mcap/trial-NN.mcap` for every trial and `media.json`
(`livingproof-hallway-media/2.0.0`: `trials[].index`, `observation_sha256` and
`mcap.{path,bytes,sha256}`) in capability-verifier's optional `media` job, which uploads them as
the artifact `<prefix>mcap-<configuration>`. The evidence manifest records neither, so the
evaluator takes the artifact's directory as `--media DIR`. The runner re-runs each trial for its
recording and keeps the file only if the observation hashes to the evidence's digest, which is why
`observation_sha256` is the link back to `trials.results[].sha256`.

| Where it is read | What |
| --- | --- |
| the recording | `DIR/<mcap.path>` for each trial `media.json` lists, read with the `mcap` package |
| the size and digest it should have | `mcap.bytes` and `mcap.sha256` in `media.json` |
| the observation it belongs to | `observation_sha256` in `media.json`, against `trials.results[].sha256` in the manifest |
| the gap limit | `plan.recording.max_gap_seconds` in the manifest, else the same key in the embedded lock's plan. **No default.** |
| the required channels | `plan.recording.required_channels`, else the lock's plan, else `/base_pose` and `/joint_states` (the two channels the media job always writes), and the summary says so |

**The gap limit.** It comes from the evidence and from nowhere else. A gap equal to the limit is
not a finding; only a larger one is. When the check is applicable its `limits.max_gap_seconds` is
exactly the evidence's value. A value that is not a finite number above zero is not used. With no
usable limit the check is not applicable even when media is present, and the summary says that
it declares none and there is no default: the check never assumes one. No plan declares a limit
today. The `0.1` s in the contract's examples is a proposal that has not been approved, and
nothing here uses it.

| Category | When |
| --- | --- |
| `mcap-incomplete` | **1.0.0 only.** At 1.1.0 a file with no valid footer is truncated, and `completeness` reports it as `truncated-recording`. This check never emits it |
| `missing-channel` | a required channel is absent or has no messages |
| `timestamps-backwards` | a channel has a message earlier than the one before it (counted per channel) |
| `recording-over-limit` | **1.2.0.** The reader stopped at a size limit (`chunk-bytes`, `total-bytes`, `records` or `chunks`); the summary names it and its value. The trial is judged and fails closed. It is not truncation, so `completeness` reports nothing and no other recording finding follows |
| `message-gap-exceeded` | the largest gap between consecutive messages on a channel, in log-time order, is over the limit. Messages written out of order are not a gap; they are `timestamps-backwards` |
| `media-file-mismatch` | the file's size or sha256 differs from `media.json` |
| `observation-link-mismatch` | `observation_sha256` in `media.json` differs from the run evidence |

The share is the judged recordings without a finding over the judged recordings. A recording is
judged when `media.json` lists a planned trial and its file is there and readable. Every other
planned trial is listed in the check's `not_checked`, which is required at 1.1.0 and empty when
everything was judged:

| Reason | When |
| --- | --- |
| `not-present` | `media.json` lists the trial's recording and it is missing, truncated or empty. `completeness` reports it |
| `not-recorded` | nothing was recorded for the trial: it is not in `media.json` |

With nothing judged, or no media, the check is not applicable: it reports no percentage and no
`limits`, and `not_checked` is empty. A run with no media passes as it did before this check, and
its card carries no note about it. A run with media but no usable gap limit is also not
applicable, with an empty `not_checked` and one note that the limit is not declared: it does not
list each trial as `not-recorded`.

**Truncation is reported once.** A recording with no valid footer is `truncated-recording` from
`completeness`, which is why `recording` lists the trial `not-present` and says nothing else. On a
`livingproof-evaluator-request` a trial whose `recording.state` is `present` while
`evidence.recording` says its file is incomplete contradicts itself. That request is malformed:
the command prints `malformed request` and why on stderr, exits 2 and writes no result, since any
result would hide a truncation that nothing reports. The published 1.0.0 `recording/findings`
request is such a request and is rejected at 1.1.0; it is still judged at 1.0.0 in the
comparison tests.

**Size limits (hostile recordings).** A recording comes from outside the evaluator, and a few
kilobytes of compressed chunk can decompress to gigabytes: a 32 KB file that expands to 1 GiB
took about 43 s and 1 GB of memory to read. Before it decompresses anything, the reader checks
the chunks it is about to read against these limits and fails closed when one is passed:

| Limit | Default |
| --- | --- |
| one chunk, decompressed | 32 MiB |
| all chunks, decompressed | 2 GiB |
| records inside chunks (messages, channels, schemas) | 50,000,000 |
| chunks | 100,000 |

A value equal to a limit is read; one over it is not. The recording is then not read at all:
at 1.1.0 it counts as truncated: `completeness` reports one `truncated-recording` finding that
says it expands past the evaluator's size limit when decompressed, `recording` lists the trial
`not-present`, and there are no channel findings and no crash (1.0.0 reported one `mcap-incomplete`
finding). The contract has no finding named for this;
[livingproof-evaluator#42](https://github.com/Living-Proof-Labs/livingproof-evaluator/issues/42)
(owned by Rivet) asks for one, and adoption of that should use it once it exists. A chunk
header's own size is not trusted, because the
decompressor ignores it when the compressed frame states another size, so each chunk is
decompressed into a buffer no larger than the per-chunk limit and counted as it is. The reader
streams one chunk at a time, so the total cap bounds time and not memory. The limits are on bytes
and counts and not on a timer, so a slow machine gives the same answer. They are far above a real
recording (the real fixture, a 50 Hz trial, is one chunk of 443 KB decompressed holding 1,122
records, in a 120 KB file) and are values of `mcap_reader.Caps`, not options of the command line.
If an override is ever needed, it goes under `plan.recording.*`. The compressed file is still
hashed in full against `media.json`; the limits do not cap its size on disk.

**What runs today, and what waits.** Run by hand with `--media` on a downloaded media artifact,
the check works as above once the evidence declares a gap limit. In the capability-verifier
workflow it cannot: the `run-integrity` job needs only `plan` and `evidence`, so it is not given
the recordings or `media.json` (capability-verifier#156) and the check is not applicable on every
run. Until something declares `plan.recording.max_gap_seconds` it is not applicable even then.
The check is tested against a real recording from verification run 43402628666 and synthetic
ones written as the runner writes them; it has not run inside the workflow. On a
`livingproof-evaluator-request` the facts come from `integrity.evidence["recording"]` as the
contract defines them, and only recordings the request's trials report as `present` are judged;
the tests run the contract's reference rules against ours on 600 generated cases.

**Two recordings per trial.** livingproof-sim-mujoco#108 would split the recording into a
robot-reported and a ground-truth file and version `media.json`. This check does not implement
that. The rules (`recording.judge`) work on facts and know nothing of where they were read, and
the reader (`mcap_reader`) knows nothing of the rules, so a second file is another reading step,
and a new `media.json` format is read beside the 2.0.0 one rather than changing a rule.

Start with this scope and the [verification limits](verification.md). To propose
behavior, use
[Help / report an issue](https://github.com/Living-Proof-Labs/livingproof-evaluator-run/issues).

## Find related work

[Documentation home](https://docs.livingprooflabs.com/) is the organization manual
and directory of related projects. Capability requirements belong to
[robot-capability-specs source](https://github.com/Living-Proof-Labs/robot-capability-specs);
this evaluator does not define or claim to implement those contracts yet.

[Source](https://github.com/Living-Proof-Labs/livingproof-evaluator-run) ·
[Version and source](version.md) · [Contribute and license](contribute.md)
