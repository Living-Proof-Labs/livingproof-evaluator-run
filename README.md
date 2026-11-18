# livingproof-evaluator-run

Run integrity grows one check at a time. Every time we lose time to something that wasn't the robot, the follow-up is a new integrity check, plus the run that would have caught it.

This repository implements the [Run Integrity](https://github.com/Living-Proof-Labs/livingproof-evaluator/blob/v1.0.8/docs/run-integrity.md) evaluator. It gives a separate opinion on whether anything besides the robot shaped a run. It invalidates the run; it does not grade the robot.

The first slice is one check, `completeness` 1.0.0: planned trial count versus observation files present, and `trials.results[].sha256` matching, on `livingproof-hallway-evidence/2.0.0`. It does not claim MCAP completeness, empty or truncated distinctions beyond a missing or mismatched file, or `timeout` / `crash` termination.

```bash
python -m livingproof_evaluator_run evidence/manifest.json --out result.json
```

`pins` 1.0.0 compares the pins the verification lock declares with what the run recorded: world, configuration and runner today. Specs and verifier are reported as not checked until the evidence records them. See [the checks](docs/index.md#checks).

The result is a `livingproof-evaluator-result/1.1.0` document. A failed check reports test-system status `ERROR` and conclusion `INCONCLUSIVE`. It never changes a robot grade.

**Documentation** — [manual source](docs/index.md)
(publication pending; no verified live manual yet).

[Documentation home](https://docs.livingprooflabs.com/) ·
[Build and verification](docs/verification.md) ·
[Contribute and license](docs/contribute.md)
