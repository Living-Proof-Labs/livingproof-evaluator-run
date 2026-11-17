"""Write a Run Integrity result for one evidence manifest or evaluator request.

python -m livingproof_evaluator_run evidence/manifest.json --out result.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from livingproof_evaluator_run.evaluate import evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "source", type=Path, help="Evidence manifest or livingproof-evaluator-request"
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path for the livingproof-evaluator-result/1.1.0 document",
    )
    args = parser.parse_args(argv)
    return evaluate(args.source, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
