# Presentation

| File | What it is |
|---|---|
| [`Evidence_Triage_Pitch.pdf`](Evidence_Triage_Pitch.pdf) ([`.pptx`](Evidence_Triage_Pitch.pptx)) | **The pitch deck** — 11 slides: the Hyderabad case, why a chatbot ranking fails in court, the classify/decide split, a fully worked score, urgency, adversarial tests, live IBM Bob run, and our ask |
| [`slides.pdf`](slides.pdf) ([`.pptx`](slides.pptx)) | Technical deck — architecture, pipeline, reproducibility and audit details |

The pitch follows this flow (maps to the evaluation rubric):

1. **Problem** — Hyderabad 2019: 3,000+ photos, 200+ items, DNA cigarette butt
   nearly missed; FSL backlog. Who hurts and why now.
2. **Solution** — one diagram: Bob extracts & classifies → deterministic engine
   scores, flags urgency, ranks → FSL schedule.
3. **The key idea** — Bob never assigns the score. Reproducible, versioned,
   court-traceable. Show the extraction/decision split.
4. **Demo** — live triage of an item list; expand a score breakdown; show the
   ruleset SHA-256 hash and the audit replay.
5. **IBM Bob integration** — MCP tools (`extract_evidence` + `score_evidence`);
   the tool boundary enforces the design rule.
6. **Technical highlights** — strict Pydantic validation + retry, Decimal scoring,
   1000× determinism test, SQLite audit.
7. **Impact & next steps** — calibrate weights against real FSL outcomes; integrate
   with e-FSL submission; multilingual intake.
