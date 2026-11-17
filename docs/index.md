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
