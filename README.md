# Fansly AI Sales Chatbot - Phase 1 Foundation

## Project Structure

```
fansly-ai-chatbot/
├── data/
│   ├── raw/              # Raw conversation exports
│   ├── labeled/          # Human-labeled training data
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
