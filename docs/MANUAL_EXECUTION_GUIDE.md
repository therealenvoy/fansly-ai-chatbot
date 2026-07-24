# 🛠️ Manual Execution Guide: Week 2 Implementation

**Goal:** Execute the Week 2 emotion detection plan manually, step-by-step.

**Time Required:** 2-3 hours  
**Prerequisites:** Week 1 foundation complete (project structure exists)

---

## 📋 Pre-Flight Checklist

Before starting, ensure you have:

- [ ] Python 3.8+ installed (`python --version`)
- [ ] Virtual environment activated
- [ ] Git configured
- [ ] Text editor ready (VS Code, vim, etc.)
- [ ] Terminal open in `/opt/data/fansly-ai-chatbot`

### Setup Steps

```bash
# 1. Navigate to project
cd /opt/data/fansly-ai-chatbot

# 2. Create virtual environment (if not done)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install base dependencies
pip install --upgrade pip
pip install pytest pydantic python-dotenv

# 4. Verify Git is ready
git status  # Should show clean working tree

# 5. Open the implementation plan
cat docs/plans/2026-07-24-week2-emotion-detection.md
```

---

## 🎯 Execution Strategy

### The Manual TDD Workflow

For each task (1-9), follow this exact sequence:

```
1. Read task objective
2. Create test file
3. Write FAILING test
4. Run test → verify FAIL
5. Install dependencies (if needed)
6. Write minimal code to pass test
7. Run test → verify PASS
8. Commit
9. Move to next task
```

**IMPORTANT:** Never skip the "verify FAIL" step. This proves your test actually works.

---

## 📝 Task-by-Task Execution

### ✅ TASK 1: Module Structure Setup
**Estimated Time:** 5 minutes  
**Objective:** Create folders and config files

#### Step 1.1: Create directories
```bash
mkdir -p src/emotion
mkdir -p tests/emotion
touch src/emotion/__init__.py
touch tests/emotion/__init__.py
```

#### Step 1.2: Create config file
```bash
# Open your editor
nano src/emotion/config.py  # or: code src/emotion/config.py
```

**Copy this content:**
```python
"""
Emotion Detection Configuration
"""
from pydantic import BaseModel, Field
from typing import Literal


class EmotionConfig(BaseModel):
    """Configuration for emotion detection pipeline"""
    
    # Model settings
    bert_model: str = "j-hartmann/emotion-english-distilroberta-base"
    vader_lexicon: str = "vader_lexicon"
    
    # Thresholds
    vader_pos_threshold: float = 0.05
    vader_neg_threshold: float = -0.05
    confidence_threshold: float = 0.6
    
    # Emotional arc settings
    warming_threshold: float = 0.1
    cooling_threshold: float = -0.1
    
    # Purchase intent scoring weights
    intent_keyword_weight: float = 0.3
    intent_sentiment_weight: float = 0.4
    intent_question_weight: float = 0.3


class SentimentLabel(str):
    """Sentiment labels"""
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"


class EmotionLabel(str):
    """Emotion labels from BERT model"""
    ANGER = "anger"
    DISGUST = "disgust"
    FEAR = "fear"
    JOY = "joy"
    NEUTRAL = "neutral"
    SADNESS = "sadness"
    SURPRISE = "surprise"
```

**Save and close** (Ctrl+X, Y, Enter in nano)

#### Step 1.3: Create models file
```bash
nano src/emotion/models.py
```

**Copy the Pydantic models from the plan** (EmotionAnalysis, EmotionalArc classes)

Refer to: `docs/plans/2026-07-24-week2-emotion-detection.md` → Task 1 → Step 3

#### Step 1.4: Verify imports work
```bash
python -c "from src.emotion.config import EmotionConfig; print('✅ Config loaded')"
python -c "from src.emotion.models import EmotionAnalysis; print('✅ Models loaded')"
```

**Expected output:**
```
✅ Config loaded
✅ Models loaded
```

#### Step 1.5: Commit
```bash
git add src/emotion/
git add tests/emotion/
git commit -m "feat(emotion): add module structure and config"
git log --oneline  # Verify commit
```

**✅ Task 1 Complete!** Move to Task 2.

---

### ✅ TASK 2: VADER Sentiment Analyzer
**Estimated Time:** 15 minutes  
**Objective:** Fast rule-based sentiment analysis

#### Step 2.1: Write FAILING test FIRST
```bash
nano tests/emotion/test_vader_analyzer.py
```

**Copy test code from plan** → Task 2 → Step 1

Save and close.

#### Step 2.2: Run test to verify FAIL
```bash
pytest tests/emotion/test_vader_analyzer.py -v
```

**Expected output:**
```
ModuleNotFoundError: No module named 'src.emotion.vader_analyzer'
```

✅ **Test fails as expected!** This proves the test works.

#### Step 2.3: Install VADER
```bash
pip install vaderSentiment
```

#### Step 2.4: Write implementation
```bash
nano src/emotion/vader_analyzer.py
```

**Copy implementation from plan** → Task 2 → Step 4

Save and close.

#### Step 2.5: Run test to verify PASS
```bash
pytest tests/emotion/test_vader_analyzer.py -v
```

**Expected output:**
```
test_vader_analyzer.py::test_vader_analyzer_positive_sentiment PASSED
test_vader_analyzer.py::test_vader_analyzer_negative_sentiment PASSED
test_vader_analyzer.py::test_vader_analyzer_neutral_sentiment PASSED
test_vader_analyzer.py::test_vader_analyzer_emoji_handling PASSED

==== 4 passed in 0.XX s ====
```

✅ **All tests pass!**

#### Step 2.6: Test manually (optional but recommended)
```bash
python -c "
from src.emotion.vader_analyzer import VADERAnalyzer
analyzer = VADERAnalyzer()
result = analyzer.analyze('I love this! 😍')
print(f'Sentiment: {result[\"sentiment\"]}, Score: {result[\"compound\"]:.2f}')
"
```

**Expected:** `Sentiment: very_positive, Score: 0.XX`

#### Step 2.7: Commit
```bash
git add src/emotion/vader_analyzer.py tests/emotion/test_vader_analyzer.py
git commit -m "feat(emotion): add VADER sentiment analyzer"
```

**✅ Task 2 Complete!** Move to Task 3.

---

### ✅ TASK 3: BERT Emotion Classifier
**Estimated Time:** 20 minutes (first run downloads model ~400MB)  
**Objective:** Deep learning emotion classification

#### Step 3.1: Write FAILING test
```bash
nano tests/emotion/test_bert_classifier.py
```

Copy test code from plan → Task 3 → Step 1

#### Step 3.2: Run test to verify FAIL
```bash
pytest tests/emotion/test_bert_classifier.py -v
```

Expected: `ModuleNotFoundError`

#### Step 3.3: Install dependencies
```bash
pip install transformers torch
```

**Note:** This may take 2-3 minutes. Torch is large (~700MB).

#### Step 3.4: Write implementation
```bash
nano src/emotion/bert_classifier.py
```

Copy implementation from plan → Task 3 → Step 4

#### Step 3.5: Run test to verify PASS
```bash
pytest tests/emotion/test_bert_classifier.py -v
```

**First run:** Downloads model (~400MB), takes 30-60 seconds  
**Expected:** `4 passed`

⚠️ **Troubleshooting:**
- **Out of memory?** Close other programs, or use smaller model
- **Download fails?** Check internet connection, retry
- **Import errors?** Verify: `pip list | grep transformers`

#### Step 3.6: Commit
```bash
git add src/emotion/bert_classifier.py tests/emotion/test_bert_classifier.py
git commit -m "feat(emotion): add BERT emotion classifier"
```

**✅ Task 3 Complete!** Move to Task 4.

---

### ✅ TASK 4: Purchase Intent Scorer
**Estimated Time:** 15 minutes  
**Objective:** Calculate 0-10 purchase intent from message

#### Quick Execution
```bash
# 1. Write test
nano tests/emotion/test_intent_scorer.py
# → Copy from plan → Task 4 → Step 1

# 2. Verify FAIL
pytest tests/emotion/test_intent_scorer.py -v

# 3. Write implementation
nano src/emotion/intent_scorer.py
# → Copy from plan → Task 4 → Step 3

# 4. Verify PASS
pytest tests/emotion/test_intent_scorer.py -v
# Expected: 4 passed

# 5. Commit
git add src/emotion/intent_scorer.py tests/emotion/test_intent_scorer.py
git commit -m "feat(emotion): add purchase intent scorer"
```

**✅ Task 4 Complete!** Move to Task 5.

---

### ✅ TASK 5: Unified Pipeline
**Estimated Time:** 10 minutes  
**Objective:** Combine VADER + BERT + Intent into one pipeline

#### Quick Execution
```bash
# 1. Write test
nano tests/emotion/test_pipeline.py
# → Copy from plan → Task 5 → Step 1

# 2. Verify FAIL
pytest tests/emotion/test_pipeline.py -v

# 3. Write implementation
nano src/emotion/pipeline.py
# → Copy from plan → Task 5 → Step 3

# 4. Verify PASS
pytest tests/emotion/test_pipeline.py -v
# Expected: 3 passed

# 5. Manual test
python -c "
from src.emotion.pipeline import EmotionPipeline
pipeline = EmotionPipeline()
result = pipeline.analyze('I love this! How much?')
print(f'Sentiment: {result.sentiment}')
print(f'Emotion: {result.emotion}')
print(f'Intent: {result.purchase_intent_score}/10')
"

# 6. Commit
git add src/emotion/pipeline.py tests/emotion/test_pipeline.py
git commit -m "feat(emotion): add unified emotion pipeline"
```

**✅ Task 5 Complete!** Move to Task 6.

---

### ✅ TASK 6: FastAPI Endpoint
**Estimated Time:** 15 minutes  
**Objective:** REST API for real-time analysis

#### Step 6.1: Install FastAPI
```bash
pip install fastapi uvicorn python-multipart httpx
```

#### Step 6.2: Write test
```bash
mkdir -p tests/api
touch tests/api/__init__.py
nano tests/api/test_emotion_api.py
# → Copy from plan → Task 6 → Step 1
```

#### Step 6.3: Verify FAIL
```bash
pytest tests/api/test_emotion_api.py -v
```

#### Step 6.4: Write API
```bash
mkdir -p src/api
touch src/api/__init__.py
nano src/api/emotion_api.py
# → Copy from plan → Task 6 → Step 4
```

#### Step 6.5: Verify PASS
```bash
pytest tests/api/test_emotion_api.py -v
# Expected: 4 passed
```

#### Step 6.6: Test API manually
```bash
# Terminal 1: Start server
uvicorn src.api.emotion_api:app --reload

# Terminal 2: Test endpoint
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -d '{"message": "I love this! 😍"}'

# Should return JSON with emotion analysis

# Terminal 1: Ctrl+C to stop server
```

#### Step 6.7: Commit
```bash
git add src/api/ tests/api/
git commit -m "feat(api): add emotion analysis REST API"
```

**✅ Task 6 Complete!** Move to Task 7.

---

### ✅ TASK 7: CLI Tool
**Estimated Time:** 10 minutes  
**Objective:** Command-line analysis tool

#### Quick Execution
```bash
# 1. Create CLI directory
mkdir -p src/cli

# 2. Write script
nano src/cli/analyze_emotion.py
# → Copy from plan → Task 7 → Step 1

# 3. Make executable
chmod +x src/cli/analyze_emotion.py

# 4. Test
python src/cli/analyze_emotion.py "I love this! How much?"
# Expected: Formatted emotion analysis

# 5. Test with file
echo "I love your content!" > /tmp/test.txt
echo "How much for custom?" >> /tmp/test.txt
python src/cli/analyze_emotion.py --file /tmp/test.txt

# 6. Test JSON output
python src/cli/analyze_emotion.py "Great!" --json

# 7. Commit
git add src/cli/analyze_emotion.py
git commit -m "feat(cli): add emotion analysis CLI tool"
```

**✅ Task 7 Complete!** Move to Task 8.

---

### ✅ TASK 8: Emotional Arc Tracker
**Estimated Time:** 20 minutes  
**Objective:** Track emotional trajectory across conversation

#### Quick Execution
```bash
# 1. Write test
nano tests/emotion/test_arc_tracker.py
# → Copy from plan → Task 8 → Step 1 (includes fixture)

# 2. Verify FAIL
pytest tests/emotion/test_arc_tracker.py -v

# 3. Write implementation
nano src/emotion/arc_tracker.py
# → Copy from plan → Task 8 → Step 3

# 4. Verify PASS
pytest tests/emotion/test_arc_tracker.py -v
# Expected: 3 passed

# 5. Commit
git add src/emotion/arc_tracker.py tests/emotion/test_arc_tracker.py
git commit -m "feat(emotion): add emotional arc tracker"
```

**✅ Task 8 Complete!** Move to Task 9 (final task!).

---

### ✅ TASK 9: Integration Tests & Documentation
**Estimated Time:** 15 minutes  
**Objective:** End-to-end tests and final docs

#### Step 9.1: Write integration test
```bash
nano tests/test_integration.py
# → Copy from plan → Task 9 → Step 1
```

#### Step 9.2: Run integration tests
```bash
pytest tests/test_integration.py -v -s
# Expected: 2 passed + printed benchmarks
```

**Example output:**
```
✅ Conversation Analysis:
   Sentiment Trend: warming
   Dominant Emotion: joy
   Purchase Readiness: 0.78
   Warning Signals: []

⚡ Performance:
   Total messages: 30
   Total time: 6.45s
   Avg per message: 215.0ms
```

#### Step 9.3: Create documentation
```bash
mkdir -p docs
nano docs/EMOTION_API.md
# → Copy from plan → Task 9 → Step 3
```

#### Step 9.4: Final verification
```bash
# Run ALL tests
pytest tests/ -v

# Expected output:
# tests/emotion/test_vader_analyzer.py::... 4 passed
# tests/emotion/test_bert_classifier.py::... 4 passed
# tests/emotion/test_intent_scorer.py::... 4 passed
# tests/emotion/test_pipeline.py::... 3 passed
# tests/api/test_emotion_api.py::... 4 passed
# tests/emotion/test_arc_tracker.py::... 3 passed
# tests/test_integration.py::... 2 passed
#
# ==== 24 passed in XX s ====
```

#### Step 9.5: Final commit
```bash
git add tests/test_integration.py docs/EMOTION_API.md
git commit -m "docs: add emotion API documentation and integration tests"
```

**✅ Task 9 Complete! Week 2 FINISHED! 🎉**

---

## 🎊 Week 2 Completion

### Final Verification Checklist

Run this final check:

```bash
# 1. All tests pass
pytest tests/ -v --tb=short
# Should see: 24 passed

# 2. API works
uvicorn src.api.emotion_api:app &
sleep 3
curl http://localhost:8000/health
pkill -f uvicorn
# Should return: {"status":"healthy","version":"1.0.0"}

# 3. CLI works
python src/cli/analyze_emotion.py "Test message"
# Should print: Message, Sentiment, Emotion, etc.

# 4. Git history clean
git log --oneline
# Should show 9+ commits

# 5. File structure complete
tree src/ tests/ docs/
# Should show all modules
```

### Success Metrics

✅ **24 tests passing**  
✅ **9 Git commits**  
✅ **REST API functional**  
✅ **CLI tool working**  
✅ **Documentation complete**  
✅ **Performance: <500ms per message**  

---

## 🚨 Troubleshooting

### Common Issues

**1. Import errors**
```bash
# Fix: Check you're in virtual environment
source venv/bin/activate
which python  # Should show venv path

# Verify imports
python -c "from src.emotion.pipeline import EmotionPipeline"
```

**2. Tests fail with "ModuleNotFoundError"**
```bash
# Fix: Add project root to PYTHONPATH
export PYTHONPATH=/opt/data/fansly-ai-chatbot:$PYTHONPATH
pytest tests/ -v
```

**3. BERT model download fails**
```bash
# Fix: Manual download
from transformers import AutoTokenizer, AutoModel
AutoTokenizer.from_pretrained("j-hartmann/emotion-english-distilroberta-base")
```

**4. Out of memory with BERT**
```bash
# Fix: Use CPU explicitly
# In src/emotion/bert_classifier.py:
self.device = torch.device("cpu")  # Force CPU
```

**5. API tests hang**
```bash
# Fix: Kill orphan uvicorn process
pkill -f uvicorn
pytest tests/api/ -v
```

---

## 📊 Expected Time Investment

| Task | Estimated | Typical Actual |
|------|-----------|----------------|
| Task 1: Structure | 5 min | 8 min |
| Task 2: VADER | 15 min | 20 min |
| Task 3: BERT | 20 min | 30 min (download) |
| Task 4: Intent | 15 min | 15 min |
| Task 5: Pipeline | 10 min | 12 min |
| Task 6: API | 15 min | 20 min |
| Task 7: CLI | 10 min | 10 min |
| Task 8: Arc | 20 min | 25 min |
| Task 9: Integration | 15 min | 20 min |
| **Total** | **2h 5m** | **2h 40m** |

**Add 30-45 min for:**
- First-time setup (venv, reading docs)
- Troubleshooting
- Coffee breaks

**Realistic total: 3-3.5 hours**

---

## 🎯 Next Steps

After Week 2 completion:

1. **Test the emotion system** on real conversations
2. **Benchmark performance** on your hardware
3. **Review Week 3 plan** (User Profiling)
4. **Celebrate!** You just built production-grade emotion AI 🎉

---

## 💡 Pro Tips

**Speed up execution:**
- Keep plan open in browser/editor while coding
- Use split-screen (editor + terminal)
- Copy-paste code blocks directly (it's designed for it)
- Don't optimize code yet — just make tests pass
- Commit after EVERY task (easy rollback if needed)

**Quality checks:**
- Never skip the "verify FAIL" step
- Read test output carefully
- Test manually after each component
- Run full test suite before final commit

**Stay motivated:**
- Take a 5-min break after Task 3 (BERT download)
- Celebrate each green test suite
- Track progress: "3/9 tasks done!"
- Remember: You're building world-class AI 🚀

---

**READY TO START?**

```bash
cd /opt/data/fansly-ai-chatbot
source venv/bin/activate
# Open this guide + implementation plan
# Start with Task 1!
```

Good luck! 🍀
