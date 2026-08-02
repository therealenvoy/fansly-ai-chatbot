"""Ingest one compiled corpus release without granting send authority."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.conversation.intelligence_v3.corpus import CorpusIngestor, load_compiled_corpus
from src.persistence.database import create_database_engine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--creator-id", required=True)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts" / "tiffany-training-v1.json",
    )
    args = parser.parse_args()
    payload = load_compiled_corpus(args.artifact)
    engine = create_database_engine(args.database_url)
    result = CorpusIngestor(engine, creator_id=args.creator_id).ingest(
        payload,
        mode="shadow",
    )
    print(
        f"ingested {result['release_key']}@{result['version']} "
        f"status={result['status']} documents={result['documents']} "
        f"rules={result['rules']} examples={result['examples']} cached={result['cached']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
