"""Write a Run Integrity result for one evidence manifest or evaluator request.

python -m livingproof_evaluator_run evidence/manifest.json --out result.json
python -m livingproof_evaluator_run evidence/manifest.json --media media --out result.json
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
        help="Path for the livingproof-evaluator-result/1.2.0 document",
    )
    parser.add_argument(
        "--media",
        type=Path,
        default=None,
        help=(
            "Directory with media.json and mcap/ (the media job's artifact); "
            "without it the recording check is not applicable"
        ),
    )
    args = parser.parse_args(argv)
    return evaluate(args.source, args.out, args.media)


if __name__ == "__main__":
    raise SystemExit(main())
