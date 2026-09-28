# 3-Minute Demo Video Script — Team REAVER

**Problem Statement 03 · Track 1 · AI-Based Crime Scene Evidence Prioritization**

Total runtime ≈ 3:00. Record your screen at `127.0.0.1:8000` with the reference
case loaded. Speaker cues in **bold**; on-screen actions in _italics_. Practice
once so the clicks land on the words.

---

### 0:00 – 0:30 · The problem (hook)

> **"In the 2019 Hyderabad homicide, investigators recovered over 3,000
> photographs and 200 physical items. A DNA-bearing cigarette butt — the single
> piece most likely to identify the killer — was nearly missed on the first
> sweep. And overloaded forensic labs delay testing by weeks."**
>
> **"The problem isn't a lack of evidence. It's the lack of a defensible way to
> decide what the lab should examine first. That's what team REAVER built."**

_On screen: the console header and the reference-case intake panel._

---

### 0:30 – 1:00 · The one idea that matters

> **"Here's our core design rule, and it's what makes this court-admissible in
> spirit: the AI never decides the priority."**
>
> **"IBM Bob — running watsonx Granite — does only the language work. It reads
> the officer's plain-text item list and classifies each item into a fixed
> forensic taxonomy. It never assigns a score, never ranks, never decides
> urgency. All of that happens in deterministic Python from a versioned ruleset."**

_On screen: point at the tagline under the logo — "Bob extracts & classifies ·
deterministic engine scores & ranks."_

---

### 1:00 – 2:00 · Live demo

> **"Let's run it. Crime type: homicide. Here are the recovered items."**

_Click **Run triage**._

> **"In one call, Bob structured every item, and the engine scored, flagged, and
> ranked them into an FSL examination schedule."**

> **"Notice the cigarette butt — the item nearly missed in the real case — is
> flagged URGENT and near the top. Not because a model had a hunch, but because
> it's biological, weather-exposed, and touch-DNA-bearing."**

_Click **Breakdown** on the knife or cigarette butt row._

> **"And we can prove every number. Base weight times the crime-type multiplier,
> plus degradation risk, plus context-flag bonus. No black box. An examiner — or
> a defence lawyer — can audit exactly why item three outranks item seven."**

_Point at the URGENT vs ROUTINE pills and the score meters._

> **"Urgency is a separate boolean rule, so a low-scoring but perishable item is
> never buried."**

---

### 2:00 – 2:40 · Why it's trustworthy (reproducibility)

_Switch to a terminal, run `curl http://127.0.0.1:8000/health`._

> **"Every result is stamped with the SHA-256 hash of the exact ruleset that
> produced it. Same input, same rules, same schedule — byte for byte, every
> time. We have a test that runs the scorer a thousand times to prove it never
> drifts, and a SQLite audit log that can replay any past run without calling the
> model again."**

_Optional: show `pytest -q` → "57 passed"._

---

### 2:40 – 3:00 · Impact and close

> **"For an investigating officer at 2 a.m., this turns an overwhelming pile into
> a ranked, defensible worklist. For the lab, it means the highest-value,
> most-perishable evidence is tested first."**
>
> **"Bob does the language. The rules decide the priority. And we can prove it.
> That's team REAVER's Evidence Triage Console. Thank you."**

---

## Recording tips
- Keep the browser at 100% zoom; the console is already high-contrast for capture.
- If you have watsonx credentials wired, mention "this is Granite doing the
  extraction live" during the demo — it strengthens the Bob-integration score.
- Use an unlisted YouTube / Loom / Box link with "anyone with the link" access.
