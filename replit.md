# IntellCluster

A multi-model AI intelligence platform with two tools:

1. **Phronesis** — Decision intelligence: three independent AI analysts blindly evaluate and rank options based on weighted criteria.
2. **Synthesis** — Deep multi-model research: five frontier AI models research in parallel, filtered by a strategist layer, producing one synthesized answer.

## Tech Stack

- **Language**: Python 3.11+
- **Web Framework**: FastAPI + Uvicorn
- **Templating**: Jinja2 (server-rendered)
- **AI Providers**: OpenAI, Anthropic, Google Gemini, DeepSeek, xAI (Grok), Mock (for testing)
- **Payments**: Stripe
- **Package Manager**: pip / requirements.txt

## Project Structure

- `main.py` — FastAPI entry point; mounts routes for homepage, Phronesis, Synthesis
- `config.py` — Root settings and API key detection
- `shared/` — Common logic: LLM providers, templates, static assets, Stripe, analytics, rate limiting, admin
- `phronesis/` — Decision intelligence engine, judges, benchmark, templates
- `synthesis/` — Multi-model research orchestrator, evaluation, templates
- `homepage/` — Landing pages, SEO content, pricing, terms, privacy

## Running the App

```
uvicorn main:app --host 0.0.0.0 --port 5000
```

The workflow "Start application" is configured to run on port 5000.

## Environment Variables

See `.env.example` for all required and optional variables. Key ones:

- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` — at least one required for AI features
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_SECRET_KEY` — admin panel access
- `STRIPE_*` — payment integration (optional)
- `PORT` — defaults to 5000

## Deployment

Configured for autoscale deployment using gunicorn with UvicornWorker on port 5000.
