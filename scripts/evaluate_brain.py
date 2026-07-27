"""Run the synthetic Conversation Brain benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.conversation import EvaluationRunner


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixtures",
        default="evals/conversation_v1.json",
    )
    parser.add_argument(
        "--json-output",
        default="artifacts/brain-eval.json",
    )
    parser.add_argument(
        "--markdown-output",
        default="artifacts/brain-eval.md",
    )
    args = parser.parse_args()
    runner = EvaluationRunner()
    result = runner.run_file(args.fixtures)
    json_path = Path(args.json_output)
    markdown_path = Path(args.markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    markdown_path.write_text(
        runner.markdown(result),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "suite": result["suite"],
                "case_count": result["case_count"],
                "json": str(json_path),
                "markdown": str(markdown_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
