# Conversation Brain evaluation

Suite: `conversation-v1`
Cases: 21

**Evidence scope:** Synthetic deterministic regression only. This does not prove live reply-rate or revenue improvement.

| Variant | Score | Deterministic errors | Safety failures |
|---|---:|---:|---:|
| current | 64 | 38 | 2 |
| improved_fast | 143 | 0 | 0 |
| strategic | 143 | 0 | 0 |

## Pairwise

- `improved_fast_vs_current`: 20 wins, 0 losses, 1 ties
- `strategic_vs_current`: 20 wins, 0 losses, 1 ties
- `strategic_vs_improved_fast`: 0 wins, 0 losses, 21 ties
