# 🤖 Fansly AI Sales Chatbot - Phase 1

> **Mission:** Build a world-class AI sales chatbot that performs like the top 0.000001% human chatters on OnlyFans/Fansly platforms.

**Status:** Foundation phase complete ✅ | Week 2 implementation ready 🚀

---

## 📚 Quick Navigation

### **👉 START HERE:**
- **[QUICK_START.md](QUICK_START.md)** - Copy-paste cheat sheet for Week 2 execution
- **[MANUAL_EXECUTION_GUIDE.md](docs/MANUAL_EXECUTION_GUIDE.md)** - Complete step-by-step guide (3 hours)

### **📋 Planning:**
- **[PHASE1_STATUS.md](PHASE1_STATUS.md)** - Current status & overview
- **[WEEK1_TASKS.md](WEEK1_TASKS.md)** - Data collection tasks
- **[Week 2 Plan](docs/plans/2026-07-24-week2-emotion-detection.md)** - Detailed implementation plan (9 tasks)

### **🎓 Documentation:**
- **[EMOTION_API.md](docs/EMOTION_API.md)** - Emotion detection API docs (after Week 2)

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
| **Week 2** | Emotion Detection | 📋 Plan Ready | 3 hours |
| **Week 3** | User Profiling | 📅 Upcoming | 3 hours |
| **Week 4** | LLM Fine-Tuning | 📅 Upcoming | 4-6 hours |

**Current Status:** Week 2 implementation plan complete, ready for execution

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

# Week 2 tests (after implementation)
pytest tests/emotion/ -v        # 18 tests
pytest tests/api/ -v            # 4 tests
pytest tests/test_integration.py -v  # 2 tests
# Total: 24 tests

# Manual test
python src/cli/analyze_emotion.py "I love this!"
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
