# Presentation

The deck is [`slides.pptx`](slides.pptx). Export a `slides.pdf` copy next to it
if the submission portal prefers PDF.

Suggested flow (maps to the evaluation rubric):

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
