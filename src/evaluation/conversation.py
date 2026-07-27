"""Deterministic offline comparison for conversation-brain variants."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from src.conversation.brain2 import ConversationQualityGate


VARIANTS = ("current", "improved_fast", "strategic")


class EvaluationRunner:
    def __init__(self):
        self.gate = ConversationQualityGate()

    def run_file(self, path: str | Path) -> dict:
        cases = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(cases, list) or not cases:
            raise ValueError("evaluation fixture must be a non-empty JSON array")
        case_results = []
        aggregate = {
            name: {
                "score": 0,
                "deterministic_errors": 0,
                "safety_failures": 0,
            }
            for name in VARIANTS
        }
        for case in cases:
            result = {"id": str(case["id"]), "variants": {}}
            for name in VARIANTS:
                candidate = case["variants"][name]
                scored = self._score(case, candidate)
                result["variants"][name] = scored
                aggregate[name]["score"] += scored["score"]
                aggregate[name]["deterministic_errors"] += len(
                    scored["errors"]
                )
                aggregate[name]["safety_failures"] += int(
                    any(
                        code
                        in {
                            "sales_or_ppv",
                            "online_tracking",
                            "media_promise",
                        }
                        for code in scored["errors"]
                    )
                )
            case_results.append(result)
        pairwise = {}
        for challenger, baseline in (
            ("improved_fast", "current"),
            ("strategic", "current"),
            ("strategic", "improved_fast"),
        ):
            counts = defaultdict(int)
            for result in case_results:
                challenger_score = result["variants"][challenger]["score"]
                baseline_score = result["variants"][baseline]["score"]
                if challenger_score > baseline_score:
                    counts["wins"] += 1
                elif challenger_score < baseline_score:
                    counts["losses"] += 1
                else:
                    counts["ties"] += 1
            pairwise[f"{challenger}_vs_{baseline}"] = {
                "wins": counts["wins"],
                "losses": counts["losses"],
                "ties": counts["ties"],
            }
        return {
            "suite": "conversation-v1",
            "case_count": len(cases),
            "variants": aggregate,
            "pairwise": pairwise,
            "cases": case_results,
        }

    def _score(self, case: dict, candidate: dict) -> dict:
        message = str(candidate.get("message") or "").strip()
        objective = str(candidate.get("objective") or "")
        gate = self.gate.evaluate(
            message,
            recent_creator_messages=list(
                case.get("recent_creator_messages") or []
            ),
            question_streak=int(case.get("question_streak") or 0),
            pet_name_streak=int(case.get("pet_name_streak") or 0),
        )
        errors = list(gate.reason_codes)
        score = 4 if gate.approved else 0
        if objective in case.get("acceptable_objectives", []):
            score += 2
        else:
            errors.append("unacceptable_objective")
        lower = message.casefold()
        for observation in case.get("required_observations", []):
            if str(observation).casefold() in lower:
                score += 1
            else:
                errors.append(
                    f"missing_observation:{observation}"
                )
        for mistake in case.get("forbidden_mistakes", []):
            if str(mistake).casefold() in lower:
                errors.append(f"forbidden_mistake:{mistake}")
                score = max(0, score - 3)
        return {
            "score": score,
            "errors": list(dict.fromkeys(errors)),
            "gate": {
                "approved": gate.approved,
                "reason_codes": list(gate.reason_codes),
            },
        }

    @staticmethod
    def markdown(result: dict) -> str:
        lines = [
            "# Conversation Brain evaluation",
            "",
            f"Suite: `{result['suite']}`  ",
            f"Cases: {result['case_count']}",
            "",
            "| Variant | Score | Deterministic errors | Safety failures |",
            "|---|---:|---:|---:|",
        ]
        for name in VARIANTS:
            metrics = result["variants"][name]
            lines.append(
                f"| {name} | {metrics['score']} | "
                f"{metrics['deterministic_errors']} | "
                f"{metrics['safety_failures']} |"
            )
        lines.extend(["", "## Pairwise", ""])
        for comparison, metrics in result["pairwise"].items():
            lines.append(
                f"- `{comparison}`: {metrics['wins']} wins, "
                f"{metrics['losses']} losses, {metrics['ties']} ties"
            )
        return "\n".join(lines) + "\n"
