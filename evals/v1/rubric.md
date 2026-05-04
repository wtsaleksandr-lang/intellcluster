# IntellCluster Accuracy Rubric (v1)

Each response is scored on 5 dimensions, 0–10 each, total 50.

---

## 1. Correctness (0–10)

Does the answer align with expert consensus or correct reasoning on the question?

- **10**: Reaches the right conclusion with sound reasoning. Aligns with the case's grading guide.
- **7-8**: Right conclusion, reasoning has minor gaps OR slightly wrong conclusion with strong reasoning that's defensible.
- **4-6**: Partially right; misses key considerations the grading guide flags.
- **1-3**: Mostly wrong; uses bad reasoning or misses fundamental considerations.
- **0**: Wrong answer with confidently bad reasoning, OR refuses to answer when question is answerable.

## 2. Completeness (0–10)

Does the answer address all aspects of the question and surface the considerations a thoughtful expert would?

- **10**: Covers every angle the grading guide expected, plus possibly additional valid ones.
- **7-8**: Covers most major angles; minor omissions.
- **4-6**: Covers half the expected angles; notable omissions.
- **1-3**: Hits one or two angles, misses the rest.
- **0**: Doesn't engage with the actual question.

## 3. Hallucination Freedom (0–10)

Does it invent facts, misattribute sources, or fabricate specifics?

- **10**: No fabricated facts. All specific numbers / names / sources verifiable.
- **7-8**: One or two minor inaccuracies that don't change the conclusion.
- **4-6**: Several questionable specifics; some clearly invented.
- **1-3**: Multiple confidently-stated fabrications.
- **0**: Riddled with invented "facts" presented authoritatively.

## 4. Calibration (0–10)

Does its expressed confidence match its actual reliability? Does it acknowledge uncertainty where appropriate?

- **10**: Confidence levels track truth. Says "I'm not sure" or shows uncertainty bands where warranted. Says "I'm confident" only when actually right.
- **7-8**: Mostly well-calibrated, occasionally over-confident on something it gets right anyway.
- **4-6**: Generic hedging ("it depends") OR confidently wrong without flagging uncertainty.
- **1-3**: Either tries to please by hedging everything (no real recommendation) OR confidently wrong on multiple claims.
- **0**: Confident assertions on things it should be uncertain about, no internal probability sense.

## 5. Specificity (0–10)

Does it give actionable specifics, or does it punt with vague platitudes?

- **10**: Specific numbers, named entities, concrete recommendations. "Pick option B because the EV is $525K vs $750K and you're 28 with no dependents."
- **7-8**: Mostly specific, occasional vagueness.
- **4-6**: Mix of specifics and "depends on your goals" punting.
- **1-3**: Mostly generic. "Both options have pros and cons. Consider what's important to you."
- **0**: Pure platitudes. No usable signal.

---

## Total scoring

| Total | Interpretation |
|---|---|
| 45–50 | Excellent — the answer is at the level of a senior expert in the domain |
| 38–44 | Good — minor flaws but the user gets value |
| 28–37 | Mediocre — usable starting point but needs verification |
| 17–27 | Weak — wrong or vague enough that the user could be misled |
| 0–16 | Bad — actively misleading |

## Notes for graders (LLM or human)

- **Score blind.** Model labels in the runs file are randomized. Don't try to identify which model wrote which answer.
- **Don't penalize length per se.** A 200-word answer that's right scores higher than a 1500-word answer that's wrong. Brevity-with-correctness is excellent.
- **Don't reward author confidence.** A confidently wrong answer scores 0 on correctness AND 0 on calibration.
- **Don't penalize disagreement with the grading guide if the reasoning is genuinely strong.** The grading guide is a suggested correct answer; the model's answer can deviate if it justifies the deviation.
- **Hallucination check is binary per claim.** If the answer cites "the 2022 Stanford study by Smith et al." and that study doesn't exist, that's a hallucination.
- **Don't reward hedging.** "It depends" is a 0 on specificity, not a 10 on calibration.
