# IntellCluster v2 Architecture — Eval Results

Baseline run: `ts_20260504_045610`  ·  V2 run: `ts_20260504_073731`
Judge: `claude-sonnet-4-6`

## Per-source averages (max 50)

| Source | n | Baseline avg | V2 avg | Δ |
|---|---|---|---|---|
| gpt4o_solo | 20 → 20 | 28.6 | 26.85 | **-1.75** |
| sonnet_solo | 20 → 20 | 43.5 | 42.25 | **-1.25** |
| gemini_solo | 20 → 20 | 34.6 | 31.6 | **-3.00** |
| intellcluster | 20 → 20 | 31.75 | 39.5 | **+7.75** |

## Per-dimension delta for IntellCluster orchestration

| Dimension | Baseline | V2 | Δ |
|---|---|---|---|
| correctness | 6.25 | 8.15 | **+1.90** |
| completeness | 6.3 | 8.9 | **+2.60** |
| hallucination_freedom | 6.65 | 6.4 | **-0.25** |
| calibration | 6.25 | 7.4 | **+1.15** |
| specificity | 6.3 | 8.65 | **+2.35** |

## IntellCluster — paired per-case results

Each row = same case, same judging rubric.

| Case | Baseline | V2 | Δ |
|---|---|---|---|
| DEC-01-saas-pricing | 17 | 40 | +23 |
| DEC-02-job-offer | 18 | 43 | +25 |
| DEC-03-ecommerce-stack | 36 | 35 | -1 |
| DEC-04-investment-allocation | 27 | 37 | +10 |
| DEC-05-restaurant-pricing | 18 | 30 | +12 |
| DEC-06-database-migration | 30 | 37 | +7 |
| DEC-07-life-insurance | 29 | 34 | +5 |
| DEC-08-car-purchase | 24 | 37 | +13 |
| DEC-09-brand-spinoff | 19 | 43 | +24 |
| DEC-10-college-major | 30 | 42 | +12 |
| RES-01-self-driving-timeline | 43 | 43 | 0 |
| RES-02-recession-defensive | 43 | 43 | 0 |
| RES-03-glp1-comparison | 39 | 46 | +7 |
| RES-04-llm-carbon-footprint | 42 | 30 | -12 |
| RES-05-college-rankings | 44 | 41 | -3 |
| RES-06-microdosing-psilocybin | 31 | 31 | 0 |
| RES-07-mobile-stack-comparison | 46 | 46 | 0 |
| RES-08-section-230-reform | 24 | 39 | +15 |
| RES-09-four-day-workweek | 46 | 47 | +1 |
| RES-10-solar-roi-boston | 29 | 46 | +17 |
| **Average** | **31.75** | **39.50** | **+7.75** |

**Win/loss summary:** 13 wins / 3 losses / 4 ties (n=20)

**Standard deviation of delta:** 9.94

## IntellCluster v2 vs each solo baseline

Per-case: did v2 IntellCluster beat the solo model on the same case?

| Solo model | Wins | Losses | Ties | IC v2 avg | Solo avg |
|---|---|---|---|---|---|
| gpt4o_solo | 18 | 2 | 0 | 39.50 | 26.85 |
| sonnet_solo | 8 | 12 | 0 | 39.50 | 42.25 |
| gemini_solo | 16 | 4 | 0 | 39.50 | 31.60 |

## Notes

- Each total is out of 50 (5 dimensions × 10 each).
- Wilcoxon-style win/loss is a non-parametric sanity check; for small N it's a directional signal not a formal p-value.
- Cases where any source errored are excluded from comparisons.
