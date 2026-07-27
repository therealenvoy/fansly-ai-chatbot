# 🤖 Fansly AI Sales Chatbot - Phase 1

> **Mission:** Build a world-class AI sales chatbot that performs like the top 0.000001% human chatters on OnlyFans/Fansly platforms.

**Status:** Foundation phase complete ✅ | **Week 2 COMPLETE** ✅ | 46 tests passing 🚀

---

## Production conversation mode

`BOT_MODE=conversation` runs an autonomous text-only conversation agent:

- replies once to each unread fan conversation, combining consecutive unread
  messages into one contextual turn;
- observes bounded batches of known Fansly users and can queue one opener on a
  durable offline-to-online transition;
- follows up once when a fully synchronized conversation has been quiet for
  the configured interval and the creator sent the latest message;
- uses recent stored history, creator persona, and learned facts through
  DeepSeek Chat;
- supports unlimited global proactive volume when the three
  `MAX_PROACTIVE_*` values are zero, while durable episode keys prevent
  repeated stalled follow-ups until that fan replies again;
- rejects media, PPV, prices, tips, unlock language, and sales delivery at the
  generation, outbox, and provider-delivery boundaries.

Production startup remains fail-closed. Conversation mode requires a configured
`DEEPSEEK_API_KEY`; online outreach additionally requires a provider that
exposes Fansly `lastSeenAt`. Keep `CONTROLLED_LAUNCH=true`,
`BOT_ENABLED_DEFAULT=false`, and a small `FAN_ALLOWLIST` until presence has been
validated with a fan account you control.

The authenticated **Settings** page can validate and replace the DeepSeek API
key and select `deepseek-v4-flash` or `deepseek-v4-pro` without restarting the
service. CRM-entered keys are encrypted before being stored and are never sent
back to the browser. Configure a stable `CREDENTIAL_ENCRYPTION_KEY` of at least
32 random characters in the server environment before saving a key through the
CRM. `deepseek-v4-flash` is the default and recommended chat model.

See [`.env.example`](.env.example) for the complete configuration.

## 📚 Quick Navigation

### **👉 START HERE:**
- **[QUICK_START.md](QUICK_START.md)** - Copy-paste cheat sheet for Week 2 execution
- **[MANUAL_EXECUTION_GUIDE.md](docs/MANUAL_EXECUTION_GUIDE.md)** - Complete step-by-step guide (3 hours)

### **📋 Planning:**
- **[PHASE1_STATUS.md](PHASE1_STATUS.md)** - Current status & overview
- **[WEEK1_TASKS.md](WEEK1_TASKS.md)** - Data collection tasks
- **[Week 2 Plan](docs/plans/2026-07-24-week2-emotion-detection.md)** - Detailed implementation plan (9 tasks) ✅

### **🎓 Documentation:**
- **[EMOTION_DETECTION.md](docs/EMOTION_DETECTION.md)** - Complete emotion system documentation ✅
- **[EMOTION_API.md](docs/api/EMOTION_API.md)** - REST API reference ✅
- **[emotion_usage.py](docs/examples/emotion_usage.py)** - Code examples ✅

---

## 🎯 What Is This?

This project builds an AI chatbot that:
- Analyzes subscriber **emotions** in real-time (sentiment, joy, anger, etc.)
- Scores **purchase intent** (0-10 scale)
- Tracks **emotional arc** (warming/cooling detection)
- Profiles **personality types** (DISC model)
- Generates **personalized responses** using fine-tuned LLM
- Maximizes **DM-based revenue** conversion

**Target Performance:** Match top 0.000001% human chatters (62% PPV conversion vs 18% baseline)

---

## 📦 Project Structure

```
fansly-ai-chatbot/
├── data/               # Training data
│   ├── raw/           # Raw conversation exports
│   ├── labeled/       # Human-labeled training data
│   └── processed/     # Processed datasets
├── models/            # Trained model checkpoints
├── src/
│   ├── emotion/       # Week 2: Emotion detection pipeline
│   ├── profiling/     # Week 3: User profiling system
│   ├── llm/           # Week 4: LLM fine-tuning
│   ├── memory/        # Context management
│   ├── api/           # REST API endpoints
│   └── cli/           # CLI tools
├── tests/             # Test suite (TDD)
├── docs/              # Documentation
│   ├── plans/         # Implementation plans
│   └── MANUAL_EXECUTION_GUIDE.md
├── QUICK_START.md     # ⚡ START HERE
└── requirements.txt   # Python dependencies
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.8+
- 3-4 hours for Week 2 implementation
- 100+ labeled conversations (Week 1 task)

### Quick Setup

```bash
# 1. Clone / navigate
cd /opt/data/fansly-ai-chatbot

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Open quick-start guide
cat QUICK_START.md
```

### Execute Week 2

**Option A: Quick (Automated)**
Ask Hermes to execute with subagents:
> "Execute Week 2 plan using subagent-driven-development"

**Option B: Manual (3 hours)**
1. Open **[QUICK_START.md](QUICK_START.md)** for copy-paste commands
2. Open **[MANUAL_EXECUTION_GUIDE.md](docs/MANUAL_EXECUTION_GUIDE.md)** for detailed steps
3. Open **[Week 2 Plan](docs/plans/2026-07-24-week2-emotion-detection.md)** for complete code
4. Follow tasks 1-9

---

## 📊 Phase 1 Timeline

| Week | Focus | Status | Time |
|------|-------|--------|------|
| **Week 1** | Data Collection | ✅ Foundation | 1-2 days |
| **Week 2** | Emotion Detection | ✅ **COMPLETE** | 3 hours |
| **Week 3** | User Profiling | 📅 Upcoming | 3 hours |
| **Week 4** | LLM Fine-Tuning | 📅 Upcoming | 4-6 hours |

**Current Status:** Week 2 COMPLETE ✅ | 46 tests passing | Ready for Week 3 🚀

---

## 🛠️ Week 2: Emotion Detection Pipeline

**What You'll Build:**

```python
from src.emotion.pipeline import EmotionPipeline

pipeline = EmotionPipeline()
result = pipeline.analyze("I love this! 😍 How much for custom?")

# Output:
# • Sentiment: very_positive (VADER: 0.85)
# • Emotion: joy (confidence: 0.92)
# • Purchase Intent: 9/10
# • Processing: ~250ms
```

**Components:**
1. ✅ VADER sentiment analyzer (fast, rule-based)
2. ✅ BERT emotion classifier (accurate, ML-based)
3. ✅ Purchase intent scorer (keyword + sentiment)
4. ✅ Emotional arc tracker (warming/cooling detection)
5. ✅ FastAPI REST endpoint
6. ✅ CLI analysis tool
7. ✅ **46 passing tests** (34 unit + 12 integration)
8. ✅ **Complete documentation**

**Delivered:**
- Full emotion detection pipeline with VADER + BERT
- Conversational arc tracking system
- REST API with 3 endpoints
- CLI with analyze/batch/demo commands
- Comprehensive test suite (100% pass rate)
- Full documentation + API reference + code examples

**Performance Targets:**
- Sentiment analysis: ~5ms per message
- Emotion classification: ~100-300ms (GPU: ~50ms)
- Complete pipeline: <500ms per message
- Accuracy: ~85% on emotional messages

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Week 2 tests (COMPLETE ✅)
pytest tests/emotion/ -v         # 34 unit tests ✅
pytest tests/integration/ -v     # 12 integration tests ✅
# Total: 46 tests passing

# Quick test
python -m src.emotion.cli analyze "I love this!"
```

---

## 📖 Documentation

- **[QUICK_START.md](QUICK_START.md)** - Fast-track execution guide
- **[MANUAL_EXECUTION_GUIDE.md](docs/MANUAL_EXECUTION_GUIDE.md)** - Detailed walkthrough
- **[Week 2 Plan](docs/plans/2026-07-24-week2-emotion-detection.md)** - Complete implementation plan
- **[EMOTION_API.md](docs/EMOTION_API.md)** - API reference (after Week 2)

---

## 🎓 Skills & Technologies

**ML/AI:**
- VADER (rule-based sentiment)
- DistilRoBERTa (transformer emotion classification)
- Purchase intent scoring
- Emotional arc analysis

**Backend:**
- FastAPI (REST API)
- Pydantic (data validation)
- PyTest (TDD)

**Future Phases:**
- Axolotl (LLM fine-tuning)
- Weights & Biases (experiment tracking)
- PostgreSQL (persistence)
- Railway (deployment)

---

## 📈 Research Foundation

Based on comprehensive research covering:
- **S.E.L.L. Framework** (62% PPV conversion)
- **4-stage emotional arc** (Rapport → Teasing → Sales → After-care)
- **NLP persuasion triggers** (reciprocity, future pacing, embedded commands)
- **4 buyer types** (Instant Buyer, Quiet Lurker, Window Shopper, Time Waster)
- **8 Key KPIs** (DM response rate, PPV conversion, LTV, etc.)

---

## 🤝 Contributing

This is a structured, test-driven project:

1. **All changes** must have tests first (TDD)
2. **Each task** = one atomic commit
3. **Follow the plan** in `docs/plans/`
4. **Document** all APIs and complex logic

---

## 📝 License

Proprietary - For sunny-charm fansly-bot project

---

## 🆘 Need Help?

- **Stuck on Week 1:** Check [WEEK1_TASKS.md](WEEK1_TASKS.md)
- **Ready for Week 2:** Start with [QUICK_START.md](QUICK_START.md)
- **Detailed guide:** See [MANUAL_EXECUTION_GUIDE.md](docs/MANUAL_EXECUTION_GUIDE.md)
- **Technical issues:** Review troubleshooting in manual guide
- **Ask Hermes:** Describe your issue with context

---

**Current Status:** Phase 1 foundation complete ✅ | Week 2 ready for execution 🚀

**Next Step:** Execute Week 2 → [QUICK_START.md](QUICK_START.md)
│   └── processed/        # Cleaned, structured data
├── models/
│   ├── emotion/          # Sentiment & emotion models
│   ├── profiling/        # Personality classifiers
│   └── llm/              # Fine-tuned LLM checkpoints
├── src/
│   ├── emotion/          # Emotion detection pipeline
│   ├── profiling/        # User profiling system
│   ├── llm/              # LLM fine-tuning & inference
│   └── memory/           # Context & memory management
├── config/               # Configuration files
└── logs/                 # Training & inference logs
```

## Phase 1 Goals (Weeks 1-4)

- [x] Week 1: Data collection & infrastructure
- [ ] Week 2: Emotion detection pipeline
- [ ] Week 3: User profiling system
- [ ] Week 4: Creator voice fine-tuning

## Installation

```bash
cd /opt/data/fansly-ai-chatbot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Quick Start

See individual module READMEs for detailed instructions.
