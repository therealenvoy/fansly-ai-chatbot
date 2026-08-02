# Tiffany Training V1

## Release contract

- Release: `tiffany-training-v1@1.0.0`
- Included: Parts 00, 01, 02, 04, 05, 06, 07, 08, 09, and 10
- Intentionally excluded: Part 03
- Approval: owner-approved source drafts
- Runtime: creator-scoped V3 retrieval and Part 09 fan-memory policy
- Validation mode: shadow, with no V3 send authority

The tracked artifact is `artifacts/tiffany-training-v1.json`. It is generated
from the reviewed source folder rather than edited by hand.

## Compile

```powershell
python scripts/compile_tiffany_corpus.py `
  --source C:\path\to\outputs\tiffany-training `
  --output artifacts\tiffany-training-v1.json
```

Compilation fails if a required part is missing, the 100 positive examples do
not have 100 paired negative examples, or the release contract is incomplete.
The same input produces the same manifest fingerprint.

## Ingest in shadow mode

The ingestion command always creates a `shadow` release. The repository gates
corpus documents by release status, so an existing live V3 runtime cannot see
or use the new corpus. Live promotion is deliberately separate.

```powershell
python scripts/ingest_tiffany_corpus.py `
  --database-url $env:DATABASE_URL `
  --creator-id <creator-scope> `
  --artifact artifacts\tiffany-training-v1.json
```

Ingestion is one transaction: documents, source pages, rules, paired examples,
the memory policy, and the shadow release record become available to shadow
evaluation together or none do. It never creates reply work, an outbox row, or
a provider request.

## Per-turn behavior

1. V3 identifies the current intent and relationship state.
2. Part 09 filters fan memory by category, confidence, relevance, expiry, and
   mention policy.
3. Knowledge retrieval selects current boundaries, 3-6 relevant source rules,
   and 2-4 positive examples. Negative examples remain contrastive only.
4. The prompt includes the release fingerprint and actual bounded source
   guidance, not merely rule labels.
5. Shadow evaluation records the selected strategy, cost, latency, safety, and
   diversity evidence without changing the current reply or writing an outbox
   row.

## Promotion boundary

Passing shadow validation does not grant live authority. Production ingestion,
deployment, and live promotion require separate explicit authorization and
measured authentic-turn evidence.
