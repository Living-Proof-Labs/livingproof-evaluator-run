"""Checkout livingproof-evaluator v1.1.0 for the conformance kit."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / ".livingproof-evaluator"
TAG = "v1.1.0"
REPO = "https://github.com/Living-Proof-Labs/livingproof-evaluator.git"


def main() -> int:
    if DEST.is_dir():
        try:
            checked = subprocess.check_output(
                ["git", "-C", str(DEST), "describe", "--tags", "--exact-match"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            checked = ""
        if checked == TAG:
            print(f"Using livingproof-evaluator {TAG} at {DEST}")
            return 0
    if DEST.exists():
        raise SystemExit(f"{DEST} exists and is not {TAG}")
    subprocess.run(
        [
            "git",
            "-c",
            "advice.detachedHead=false",
            "clone",
            "--depth",
            "1",
            "--branch",
            TAG,
            REPO,
            str(DEST),
        ],
        check=True,
    )
    print(f"Fetched livingproof-evaluator {TAG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
