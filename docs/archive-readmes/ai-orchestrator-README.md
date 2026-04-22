# ai-orchestrator — archived

> **This repo has moved.** All active development on the multi-model deep research tool (now called **Synthesis**) continues in the IntellCluster monorepo:
>
> **→ https://github.com/wtsaleksandr-lang/intellcluster**
>
> The live product is hosted at **https://intellcluster.com/synthesis**.

---

## Why was this archived?

`ai-orchestrator` and `decision-intelligence-tool` were merged into a single product: **IntellCluster** — a platform with two complementary AI tools:

- **Phronesis** — decision intelligence (blind multi-analyst ranking of options against weighted criteria)
- **Synthesis** — multi-model deep research (this tool's successor)

The tools share a unified design system, shared provider registry, intent routing, and a single pricing + billing surface. Maintaining two separate repos had diverged and duplicated too much shared code.

## Where to find things

| Old (this repo)                | New (IntellCluster)                                  |
|--------------------------------|------------------------------------------------------|
| `main.py`                      | `intellcluster/main.py` — unified FastAPI app        |
| `orchestrator/`                | `synthesis/orchestrator/`                            |
| `templates/index.html`         | `synthesis/templates/index.html`                     |
| Shared providers (LLM clients) | `shared/providers/`                                  |
| Pricing, admin, auth           | `shared/pricing.py`, `shared/admin.py`               |

The commit history of this repo is preserved here for reference. No new commits or issues will be accepted on this archive.

## Migration notes for anyone following the old URL

- `/` on the old deployment → `https://intellcluster.com/synthesis`
- API endpoints previously at `/api/run` are now under `/synthesis/api/run`
- Environment variables carried over as-is (API keys, model IDs)

If you were self-hosting `ai-orchestrator` and want to upgrade, clone `intellcluster` instead. The setup instructions in its `README.md` cover both Replit and Docker deploys.
