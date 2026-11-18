# LivingProof Run Evaluator

Evaluates run infrastructure and evidence suitability for judging robot capabilities.

## Start here

The first slice is a completeness check on hallway evidence: planned trial
count versus observation files present, and declared digests matching. Three checks
follow: `pins`, `plan-conformance` and `termination`. It reports test-system status only. It never
grades the robot. Later checks are added one
at a time; see [issue 3](https://github.com/Living-Proof-Labs/livingproof-evaluator-run/issues/3).

```bash
python -m livingproof_evaluator_run evidence/manifest.json --out result.json
```

## Checks

- `completeness` 1.0.0: see above.
- `pins` 1.0.0: compares the pins the verification lock declares (embedded in the
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

A subject with no declared or no recorded value is **not checked**. It is listed in
the result summary, never counted as matching, and never fails the check. Until the
runner and verifier record the spec files and image digest they used
(livingproof-sim-mujoco#104, capability-verifier#153 and #154), `specs` and
`verifier` stay not checked. The share is the matching subjects divided by five
when a subject differs, and 100 otherwise. When no subject could be compared (no
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
command exits 1 and writes no result. The same holds for lengths: in the descriptor a
finding's trial is cut to 40 characters and its text to 280, ending in an ellipsis (the
check's own findings keep the full trial id), and a descriptor field over the contract's
maximum length also exits 1 with nothing written.

- `plan-conformance` 1.0.0: the trials that ran are the trials that were planned. It reads
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

On an evaluator request the evidence is `integrity.evidence["plan-conformance"]`, as the
contract defines it. A request without it reports the check as not applicable. The check
follows the contract's reference rules (`tests/integrity_rules.py` in the contract kit): the
tests run both against 600 generated cases. Seeds do not exist in evidence 2.0.0, so the
indexes stand for them; if seeds return in a later evidence version that is a new check
version.

- `termination` 1.0.0: every trial that ended on its own records a stop reason, and the plan
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
went non-finite is a `disallowed-stop-reason` finding unless the plan says it is allowed. A
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
