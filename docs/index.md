# LivingProof Run Evaluator

Evaluates run infrastructure and evidence suitability for judging robot capabilities.

## Start here

The first slice is one completeness check on hallway evidence: planned trial
count versus observation files present, and declared digests matching. It reports
test-system status only. It never grades the robot. Later checks are added one
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
when a subject differs, and 100 otherwise. A manifest with no embedded lock reports
`pins` as not applicable.

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
