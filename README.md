# livingproof-evaluator-run

Run integrity grows one check at a time. Every time we lose time to something that wasn't the robot, the follow-up is a new integrity check, plus the run that would have caught it.

This repository implements the [Run Integrity](https://github.com/Living-Proof-Labs/livingproof-evaluator/blob/v1.1.0/docs/run-integrity.md) evaluator. It gives a separate opinion on whether anything besides the robot shaped a run. It invalidates the run; it does not grade the robot.

The first slice is one check, `completeness` 1.0.0: planned trial count versus observation files present, and `trials.results[].sha256` matching, on `livingproof-hallway-evidence/2.0.0`. It does not claim MCAP completeness or empty or truncated distinctions beyond a missing or mismatched file. It does not detect a `timeout` or a `crash` from an evidence manifest, which records neither; on a `livingproof-evaluator-request` a trial whose `termination` is `timeout` or `crash` is an `ended-by-timeout` or `ended-by-crash` finding.

```bash
python -m livingproof_evaluator_run evidence/manifest.json --out result.json
```

`pins` 1.0.0 compares the pins the verification lock declares with what the run recorded: world, configuration and runner today. Specs and verifier are reported as not checked until the evidence records them. See [the checks](docs/index.md#checks).

`plan-conformance` 1.0.0 checks that the trials that ran are the trials that were planned: the plan, `trials.count`, the number of `trials.results` entries and the lock's plan agree on the trial count and the command speed, and the indexes are exactly 1 to N with each path `trials/trial-NN.json` for its own index. A run whose preconditions are unmet is not applicable. See [the checks](docs/index.md#checks).

`termination` 1.0.0 checks that every trial that ended on its own records a stop reason the plan allows. The reason is the `end` in the trial's observation file, mapped to the contract's words (`crossed_exit` is `mission-done`, `left_hallway` and `left_world` are `left-world`, `time_limit` is `time-limit`, `non_finite_state` is `simulation-broken`), and it must agree with `trials.results[].outcome` in the manifest. The plan's allowed list is `plan.allowed_stop_reasons`, else the lock's plan, else a default that leaves out `simulation-broken`. A timeout or crash is `completeness`'s finding, and `termination` only refers to it. It does not detect a crash or a killed runner from an evidence manifest: nothing records one yet (livingproof-sim-mujoco#105, capability-verifier#155). See [the checks](docs/index.md#checks).

`recording` 1.0.0 checks that each recording that is present is a usable MCAP file: complete, with every required channel carrying messages, no timestamp that goes backwards, no gap over the limit, and the size, sha256 and observation digest that `media.json` and the run evidence record. The recordings are the media job's artifact, so they are a separate input: `--media DIR` (a directory with `media.json` and `mcap/`). Without it there is no media and the check is not applicable. A recording that would decompress past a size limit (32 MiB a chunk, 256 MiB in all, 2,000,000 records, 100,000 chunks) is not read and is one `mcap-incomplete` finding, so a small hostile file cannot exhaust the evaluator. **The gap limit has no default.** It must be declared in the evidence (`plan.recording.max_gap_seconds`), and without one the check is not applicable and says so. Nothing declares one yet, and capability-verifier#156 has not yet given the Run Integrity job the recordings, so on a real run today the check is not applicable. See [the checks](docs/index.md#checks).

The result is a `livingproof-evaluator-result/1.1.0` document. A failed check reports test-system status `ERROR` and conclusion `INCONCLUSIVE`. It never changes a robot grade.

**Documentation** — [manual source](docs/index.md)
(publication pending; no verified live manual yet).

[Documentation home](https://docs.livingprooflabs.com/) ·
[Build and verification](docs/verification.md) ·
[Contribute and license](docs/contribute.md)
