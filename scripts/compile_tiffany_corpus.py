"""Compile approved Tiffany training sources into a deterministic V3 artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.conversation.intelligence_v3.corpus import (
    compile_tiffany_corpus,
    write_compiled_corpus,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "outputs" / "tiffany-training",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts" / "tiffany-training-v1.json",
    )
    args = parser.parse_args()
    payload = compile_tiffany_corpus(args.source)
    destination = write_compiled_corpus(payload, args.output)
    report = payload["validation_report"]
    print(
        f"compiled {payload['release_key']}@{payload['version']} "
        f"documents={report['documents']} rules={report['rules']} "
        f"examples={report['positive_examples']} fingerprint={payload['manifest_fingerprint']} "
        f"output={destination}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
