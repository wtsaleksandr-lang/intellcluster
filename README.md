# IntellCluster

Multi-model AI intelligence, applied two ways.

**IntellCluster.com** hosts two tools in a unified ecosystem:

- **Phronesis** (`/phronesis`) — Practical wisdom for every decision. Describe your options in plain language; three independent AI analysts evaluate them blindly and rank them by weighted criteria.
- **Synthesis** (`/synthesis`) — Deep multi-model research. One question → five frontier AI models research in parallel → strategist layer filters weak signals → one synthesized answer.

---

## Stack

- Python 3.11+
- FastAPI
- Jinja2 templates (server-rendered)
- 6 LLM provider adapters (OpenAI, Anthropic, Google, DeepSeek, xAI, Mock)

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Add your API keys to .env
python main.py
```

App runs on `http://localhost:5000`.

## Structure

```
intellcluster/
├── main.py                     # FastAPI app, mounts both tools
├── config.py                   # Root settings + API key detection
├── shared/
│   ├── providers/              # LLM adapters (used by both tools)
│   ├── templates/base.html     # Unified design system
│   ├── static/                 # Shared static assets
│   └── tracking/               # Cost + history tracking
├── phronesis/
│   ├── engine/                 # Decision pipeline + extractor + validator
│   ├── judges/                 # Blind judges + rubric + aggregator
│   ├── benchmark/              # Quality benchmark system
│   └── templates/              # Phronesis UI pages
├── synthesis/
│   ├── config.py               # Orchestrator-specific settings
│   ├── orchestrator/           # Multi-agent pipeline
│   ├── evaluation/             # Orchestrator benchmark system
│   └── templates/              # Synthesis UI pages
└── homepage/
    └── index.html              # IntellCluster.com landing page
```

## Routes

| Route | Purpose |
|---|---|
| `/` | Homepage — tool selector |
| `/phronesis` | Phronesis decision tool |
| `/phronesis/result/{id}` | Shareable decision result |
| `/synthesis` | Synthesis research tool |
| `/api/health` | Service status |

## Benchmarks

- **Phronesis:** 7.3/10 overall quality across 20 decision categories (Round 3)
- **Synthesis:** Multi-phase research with 5-model parallel execution

See individual `*/benchmark/` and `*/evaluation/` directories.
