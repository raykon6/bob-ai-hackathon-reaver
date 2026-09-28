# Submission notes

This repository follows the Bob AI Hackathon submission template structure. Keep
the top-level files and folders in place — the automated validator and the
evaluators depend on them.

- `submission.yaml` is read first — keep every `# REQUIRED` field filled.
- Put all source under `src/`. Never commit `.env` (real credentials) or the
  SQLite `*.db` files.
- If you created this repo from the **official** hackathon template, keep the
  template's `.github/workflows/validate.yml`; the copy here is a faithful
  stand-in for teams building from these files directly.

## Working on the code

```bash
cd src
pip install -r requirements.txt
pytest -q            # all tests must stay green — they pin the scoring formula
```

The scoring engine (`src/app/scoring.py`) is pure and deterministic by design. If
you change any weight, change it in `src/rules_v1.yaml` (the single source of
truth) and bump its `version`; never hardcode a weight in Python. Then run
`python sync_web_mirror.py` so the web console's offline mirror picks up the
change (`tests/test_web_mirror.py` fails until you do).
