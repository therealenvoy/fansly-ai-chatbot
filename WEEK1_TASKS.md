# 📋 Week 1 Task List: Data Collection & Infrastructure

## ✅ Completed
- [x] Project structure created
- [x] Data schema defined
- [x] Requirements documented

## 🎯 This Week's Goals

### Day 1-2: Export Existing Conversations
**Task:** Export DM history from Railway project database

```bash
# Connect to your Neon database
export DATABASE_URL="postgresql://neondb_owner:***@ep-young-mud-a1m5bb-pooler.us-east-1.aws.neon.tech/neondb"

# Export conversations (modify based on your schema)
psql $DATABASE_URL -c "COPY (
  SELECT 
    conversation_id,
    subscriber_id,
    messages,
    outcome,
    created_at
  FROM conversations
  WHERE created_at >= NOW() - INTERVAL '90 days'
) TO STDOUT CSV HEADER" > data/raw/conversations_export.csv
```

**Deliverable:** At least **500 conversations** (mix of won/lost)

---

### Day 3-4: Manual Annotation
**Task:** Label 100 high-quality conversations

**What to label:**
1. **Personality Type** (instant_buyer/quiet_lurker/attention_seeker/tester)
2. **Conversation Stage** per message (start/explore/lead/lock)
3. **Purchase Intent** (0-10 scale) per user message
4. **Sentiment** (very_negative → very_positive)
5. **Outcome** (purchased: yes/no, amount)

**Tool:** Use the annotation script below

```bash
python src/data_collection/annotate_conversations.py \
  --input data/raw/conversations_export.csv \
  --output data/labeled/annotated_conversations.json
```

**Deliverable:** 100 fully labeled conversations in JSON format

---

### Day 5: Data Quality Check
**Task:** Validate and analyze labeled data

```bash
python src/data_collection/validate_dataset.py \
  --input data/labeled/annotated_conversations.json
```

**Check for:**
- All required fields present
- Conversion rate matches expectations (15-65%)
- Personality distribution is diverse
- Stage progression makes sense

**Deliverable:** Clean, validated dataset ready for training

---

### Day 6-7: Creator Voice Profile
**Task:** Create detailed voice guide for LLM fine-tuning

**Required fields:**
1. **Tone:** (casual/flirty/professional/dominant/submissive)
2. **Language:** (formal/slang/mix)
3. **Emoji usage:** (heavy/moderate/minimal)
4. **Signature phrases:** 10-15 phrases the creator always uses
5. **Topics to avoid:** Hard boundaries
6. **Response style:** (short/long, questions/statements)
7. **Example winning messages:** 20+ actual messages that converted

**Template:** See `config/creator_voice_template.yaml`

**Deliverable:** Complete voice profile for sunny-charm creator

---

## 📊 Week 1 Success Metrics

- [ ] 500+ raw conversations exported
- [ ] 100+ conversations fully labeled
- [ ] Dataset validated (no errors)
- [ ] Creator voice profile completed
- [ ] Baseline statistics calculated:
  - Current conversion rate: ____%
  - Avg purchase amount: $____
  - Avg exchanges per conversion: ____
  - Top performing personality type: ________

---

## 🚨 Blockers & Solutions

**Problem:** "I don't have access to DM history"
- **Solution:** Start fresh. Collect next 2 weeks of conversations in real-time using webhook logger

**Problem:** "Labeling is too slow"
- **Solution:** Use GPT-4 for initial labels, then human review/correction

**Problem:** "Not sure how to judge personality type"
- **Solution:** Use decision tree:
  - Bought first PPV? → Instant Buyer
  - Messages <5 times? → Quiet Lurker  
  - Messages >20 times asking for attention? → Attention Seeker
  - Questions prices/asks for discounts? → Tester

---

## 📁 File Structure After Week 1

```
data/
├── raw/
│   └── conversations_export.csv          # Raw export
├── labeled/
│   ├── annotated_conversations.json      # 100 labeled
│   └── annotation_progress.json          # Tracking
└── processed/
    └── dataset_stats.json                # Quality metrics

config/
└── sunny_charm_voice.yaml                # Creator voice profile
```

---

## 🎓 Pro Tips

1. **Label your BEST conversations first** — These are gold for training
2. **Note objections and rebuttals** — Build library for Phase 3
3. **Mark "whale" subscribers** — Separate training set for high-value handling
4. **Save voice notes separately** — You'll need these for voice cloning (Phase 4)
5. **Document what you DON'T want AI to say** — Boundaries are critical

---

## ⏭️ Next: Week 2 Preview

Once data is ready, we'll build:
- Emotion detection pipeline (VADER + BERT)
- Real-time sentiment analysis API
- Emotional arc tracker (warming up vs cooling off)

**Preparation:** Review your labeled data and identify:
- Which emotions led to purchases?
- Which sentiment patterns preceded objections?
- When did engagement spike or drop?
