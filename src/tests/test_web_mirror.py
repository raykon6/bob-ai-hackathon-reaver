"""The console's offline mirror must never drift from the real engine: its data
block is generated from rules_v1.yaml + app/llm_client.py by sync_web_mirror.py."""
from sync_web_mirror import INDEX_HTML, embedded_block, render_block


def test_web_mirror_matches_rules_and_keywords():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert embedded_block(html) == render_block(), (
        "web/index.html offline mirror is stale — run `python sync_web_mirror.py` from src/"
    )
