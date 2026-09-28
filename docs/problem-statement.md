# Problem Statement — AI-Based Crime Scene Evidence Prioritization

## Who is affected

- **Investigating officers / IOs** at a major crime scene, who must decide what to
  seize, package, and rush to the lab — often at night, under time pressure, with
  a decomposing or weather-exposed scene.
- **Forensic Science Laboratory (FSL) examiners**, who receive far more exhibits
  than they can test quickly and have no standard signal for what to examine first.
- **Prosecutors and courts**, who need the chain from scene to result to be
  defensible and reproducible.

## The specific pain

A serious scene produces **hundreds of physical items and thousands of
photographs**. In the **2019 Hyderabad veterinarian homicide**, investigators dealt
with **3,000+ photographs and 200+ physical items**. A **DNA-bearing cigarette
butt was nearly missed** on the first sweep — the single item most likely to
individualize a suspect. Meanwhile, **overloaded FSLs delay testing by weeks**,
and perishable evidence (wet bloodstains, biological material, volatile residues)
degrades while lower-value items sit ahead of it in the queue.

## Why existing approaches don't solve it

- **Human triage doesn't scale** and is inconsistent between officers; fatigue at
  hour 6 of a scene is when the cigarette butt gets missed.
- **Generic checklists** are static — they don't weigh *this* item against *this*
  crime type, or account for how fast it degrades.
- **A naive "ask the AI to prioritize" tool is inadmissible in spirit**: a model
  that assigns a score is non-reproducible and unexplainable. Run it twice, get two
  answers; a defence counsel dismantles it. Forensic decisions must be traceable to
  a fixed, versioned rule — not to a model's mood on a given day.

## Quantified stakes

| Signal | Figure |
|---|---|
| Photographs at one scene (Hyderabad, 2019) | 3,000+ |
| Physical items at that scene | 200+ |
| Highest-value item's fate without triage | DNA cigarette butt nearly missed |
| Typical FSL testing delay when unprioritized | weeks |

## Why now

Indian forensics is digitizing (CCTNS, e-FSL workflows), and accessible LLMs can
finally read an officer's plain-language item list. The missing piece is not more
AI autonomy — it is a tool that uses AI **only** for the language step and keeps
the priority decision in a fixed, auditable ruleset. That is exactly what this
project builds.
