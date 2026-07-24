# ⚡ Week 2 Quick Start Cheat Sheet

**Goal:** Execute all 9 tasks in ~3 hours  
**Current Directory:** `/opt/data/fansly-ai-chatbot`

---

## 🚀 One-Command Setup

```bash
cd /opt/data/fansly-ai-chatbot
source venv/bin/activate || (python -m venv venv && source venv/bin/activate)
pip install -q pytest pydantic vaderSentiment transformers torch fastapi uvicorn httpx
export PYTHONPATH=$PWD:$PYTHONPATH
```

---

## 📋 Task Checklist (Copy-Paste Each Block)

### ✅ Task 1: Module Structure (5 min)
```bash
mkdir -p src/emotion tests/emotion
touch src/emotion/__init__.py tests/emotion/__init__.py
# → Copy config.py and models.py from plan
git add src/emotion/ tests/emotion/
git commit -m "feat(emotion): add module structure and config"
```

### ✅ Task 2: VADER (15 min)
```bash
# 1. Write test → verify FAIL
pytest tests/emotion/test_vader_analyzer.py -v
# 2. Write code → verify PASS
pytest tests/emotion/test_vader_analyzer.py -v
git commit -am "feat(emotion): add VADER sentiment analyzer"
```

### ✅ Task 3: BERT (20 min)
```bash
# 1. Write test → verify FAIL
pytest tests/emotion/test_bert_classifier.py -v
# 2. Install: pip install transformers torch
# 3. Write code → verify PASS (30s first run = model download)
pytest tests/emotion/test_bert_classifier.py -v
git commit -am "feat(emotion): add BERT emotion classifier"
```

### ✅ Task 4: Intent Scorer (15 min)
```bash
pytest tests/emotion/test_intent_scorer.py -v  # FAIL
# → Write code
pytest tests/emotion/test_intent_scorer.py -v  # PASS
git commit -am "feat(emotion): add purchase intent scorer"
```

### ✅ Task 5: Pipeline (10 min)
```bash
pytest tests/emotion/test_pipeline.py -v  # FAIL
# → Write code
pytest tests/emotion/test_pipeline.py -v  # PASS
git commit -am "feat(emotion): add unified emotion pipeline"
```

### ✅ Task 6: API (15 min)
```bash
mkdir -p tests/api src/api
pytest tests/api/test_emotion_api.py -v  # FAIL
# → Write code
pytest tests/api/test_emotion_api.py -v  # PASS
git commit -am "feat(api): add emotion analysis REST API"
```

### ✅ Task 7: CLI (10 min)
```bash
mkdir -p src/cli
# → Write src/cli/analyze_emotion.py
chmod +x src/cli/analyze_emotion.py
python src/cli/analyze_emotion.py "Test!" --json
git add src/cli/
git commit -m "feat(cli): add emotion analysis CLI tool"
```

### ✅ Task 8: Arc Tracker (20 min)
```bash
pytest tests/emotion/test_arc_tracker.py -v  # FAIL
# → Write code
pytest tests/emotion/test_arc_tracker.py -v  # PASS
git commit -am "feat(emotion): add emotional arc tracker"
```

### ✅ Task 9: Integration (15 min)
```bash
mkdir -p docs
# → Write tests/test_integration.py + docs/EMOTION_API.md
pytest tests/test_integration.py -v -s
git add tests/test_integration.py docs/EMOTION_API.md
git commit -m "docs: add integration tests and API docs"
```

---

## 🎯 Final Verification

```bash
# All tests pass?
pytest tests/ -v --tb=short
# Should see: 24 passed

# API works?
uvicorn src.api.emotion_api:app &
sleep 3 && curl http://localhost:8000/health
pkill -f uvicorn

# CLI works?
python src/cli/analyze_emotion.py "I love this!"

# Git history clean?
git log --oneline --graph
```

---

## 🚨 Emergency Commands

```bash
# Reset if stuck
git reset --hard HEAD
git clean -fd

# Check test status
pytest tests/ -v --co  # List all tests without running

# Kill zombie processes
pkill -f uvicorn
pkill -f pytest

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Debug imports
python -c "import sys; print('\n'.join(sys.path))"
python -c "from src.emotion.pipeline import EmotionPipeline; print('✅')"
```

---

## 📊 Progress Tracker

```
[ ] Task 1: Structure (5 min)
[ ] Task 2: VADER (15 min)
[ ] Task 3: BERT (20 min)
[ ] Task 4: Intent (15 min)
[ ] Task 5: Pipeline (10 min)
[ ] Task 6: API (15 min)
[ ] Task 7: CLI (10 min)
[ ] Task 8: Arc (20 min)
[ ] Task 9: Integration (15 min)

Total: ___ / 9 tasks (Estimated: 2h 5m)
```

---

## 🎓 Key Files

| Need This? | Look Here |
|------------|-----------|
| Full task details | `docs/plans/2026-07-24-week2-emotion-detection.md` |
| Step-by-step guide | `docs/MANUAL_EXECUTION_GUIDE.md` |
| Code to copy | Plan markdown → each task has complete code blocks |
| Quick overview | `PHASE1_STATUS.md` |

---

## 💡 Speed Tips

1. **Open 3 windows:**
   - Terminal 1: Run tests
   - Terminal 2: Edit code
   - Browser: Plan markdown

2. **Copy-paste is EXPECTED** — code blocks are designed for it

3. **Verify FAIL before writing code** — proves tests work

4. **Commit after EVERY task** — easy rollback

5. **Skip optimization** — just make tests green

---

## ✅ Success Criteria

After 3 hours you'll have:

- ✅ 24 tests passing
- ✅ 9 git commits
- ✅ Working emotion pipeline (~300ms per message)
- ✅ REST API endpoint
- ✅ CLI tool
- ✅ Complete documentation

**Then:** Ready for Week 3 (User Profiling) 🚀

---

**START HERE:**
```bash
cd /opt/data/fansly-ai-chatbot
open docs/plans/2026-07-24-week2-emotion-detection.md
# Begin Task 1!
```
