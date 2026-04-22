# decision-intelligence-tool — archived

> **This repo has moved.** All active development on the blind multi-analyst decision tool (now called **Phronesis**) continues in the IntellCluster monorepo:
>
> **→ https://github.com/wtsaleksandr-lang/intellcluster**
>
> The live product is hosted at **https://intellcluster.com/phronesis**.

---

## Why was this archived?

`decision-intelligence-tool` and `ai-orchestrator` were merged into a single product: **IntellCluster** — a platform with two complementary AI tools:

- **Phronesis** — decision intelligence (this tool's successor)
- **Synthesis** — multi-model deep research

The tools share a unified design system, shared LLM provider registry, intent routing, and a single pricing + billing surface.

## Where to find things

| Old (this repo)                | New (IntellCluster)                              |
|--------------------------------|--------------------------------------------------|
| `main.py`                      | `intellcluster/main.py` — unified FastAPI app    |
| `engine/`                      | `phronesis/engine/`                              |
| `templates/index.html`         | `phronesis/templates/index.html`                 |
| Shared providers (LLM clients) | `shared/providers/`                              |
| Pricing, admin, auth           | `shared/pricing.py`, `shared/admin.py`           |

The commit history of this repo is preserved here for reference. No new commits or issues will be accepted on this archive.

## Migration notes for anyone following the old URL

- `/` on the old deployment → `https://intellcluster.com/phronesis`
- `/result/{run_id}` → `https://intellcluster.com/phronesis/result/{run_id}` (the monorepo also ships a legacy redirect)
- API endpoints previously at `/api/decide` are now `/phronesis/api/decide`
- Environment variables carried over as-is (API keys, model IDs)

If you were self-hosting `decision-intelligence-tool` and want to upgrade, clone `intellcluster` instead. The setup instructions in its `README.md` cover both Replit and Docker deploys.
