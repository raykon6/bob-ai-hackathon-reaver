"""Regenerate the offline-mirror data embedded in web/index.html.

The console's in-browser fallback needs the ruleset and the offline extractor's
keyword lists. Rather than copying them by hand (and letting them drift), they are
generated from the authoritative sources — rules_v1.yaml and app/llm_client.py —
into a single <script type="application/json" id="engine-mirror"> block.

    python sync_web_mirror.py          # rewrite the block in web/index.html
    python sync_web_mirror.py --check  # exit 1 if the block is out of date

tests/test_web_mirror.py runs the same check, so a stale mirror fails CI.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from app.llm_client import _CATEGORY_KEYWORDS, _CONDITION_RULES, _FLAG_RULES
from app.rules import load_rules

INDEX_HTML = Path(__file__).resolve().parent / "web" / "index.html"
_BLOCK_RE = re.compile(
    r'(<script type="application/json" id="engine-mirror">)(.*?)(</script>)', re.S
)


def build_mirror() -> dict:
    r = load_rules()
    return {
        "rules": {
            "version": r.version,
            "version_hash": r.version_hash,
            "category_base_weights": r.category_base_weights,
            "crime_type_multipliers": r.crime_type_multipliers,
            "degradation_risk_by_condition": r.degradation_risk_by_condition,
            "condition_normalization": r.condition_normalization,
            "default_condition": r.default_condition,
            "context_flag_modifiers": r.context_flag_modifiers,
            "score_urgent": r.score_urgent,
            "force_urgent_flags": r.force_urgent_flags,
        },
        "category_keywords": [[c, list(w)] for c, w in _CATEGORY_KEYWORDS],
        "condition_rules": [[c, list(w)] for c, w in _CONDITION_RULES],
        "flag_rules": [[f, list(w)] for f, w in _FLAG_RULES],
    }


def render_block() -> str:
    return "\n" + json.dumps(build_mirror(), indent=1, ensure_ascii=False) + "\n"


def embedded_block(html: str) -> str:
    m = _BLOCK_RE.search(html)
    if not m:
        raise ValueError("engine-mirror block not found in web/index.html")
    return m.group(2)


def main() -> int:
    html = INDEX_HTML.read_text(encoding="utf-8")
    fresh = render_block()
    if "--check" in sys.argv:
        if embedded_block(html) != fresh:
            print("web/index.html engine-mirror is STALE — run: python sync_web_mirror.py")
            return 1
        print("web/index.html engine-mirror is in sync")
        return 0
    embedded_block(html)  # raises if the block is missing
    new = _BLOCK_RE.sub(lambda m: m.group(1) + fresh + m.group(3), html, count=1)
    INDEX_HTML.write_text(new, encoding="utf-8", newline="\n")
    print("web/index.html engine-mirror updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
