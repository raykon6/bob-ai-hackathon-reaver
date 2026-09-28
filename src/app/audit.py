"""SQLite audit log — one row per scored item, so a past run can be inspected or
explained later. Time and I/O live here on purpose; the scoring engine stays pure.

Each row records the crime type and rank alongside the validated extracted item and
the full score breakdown, so a stored run reflects exactly what was ranked and why.
`raw_model_output` holds the verbatim model response for the run — the /triage
pipeline captures and passes it — so a stored run can be re-derived from the exact
text the model returned, and re-scored to confirm the result (see GET /audit?verify).
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import ScoredItem

DEFAULT_DB_PATH = os.environ.get("TRIAGE_DB_PATH", "evidence_audit.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id         TEXT NOT NULL,
    rank               INTEGER,
    crime_type         TEXT,
    item_name          TEXT NOT NULL,
    category           TEXT,
    extracted_item     TEXT,
    raw_model_output   TEXT,
    score_breakdown    TEXT,
    final_score        REAL,
    urgency_flag       INTEGER NOT NULL,
    rules_version_hash TEXT NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evidence_log_session ON evidence_log(session_id);
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def log_run(
    session_id: str,
    scored: list[ScoredItem],
    crime_type: str = "unknown",
    db_path: str | Path = DEFAULT_DB_PATH,
    raw_model_output: str | None = None,
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    rows = [
        (
            session_id,
            s.rank,
            crime_type,
            s.item.item_name,
            s.item.category.value if s.item.category else None,
            s.item.model_dump_json(),
            raw_model_output,
            s.breakdown.model_dump_json() if s.breakdown else None,
            s.final_score,
            1 if s.urgency_flag else 0,
            s.rules_version_hash,
            created_at,
        )
        for s in scored
    ]
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.executemany(
            """INSERT INTO evidence_log
               (session_id, rank, crime_type, item_name, category, extracted_item,
                raw_model_output, score_breakdown, final_score, urgency_flag,
                rules_version_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()


def get_run(session_id: str, db_path: str | Path = DEFAULT_DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        cur = conn.execute(
            "SELECT * FROM evidence_log WHERE session_id = ? ORDER BY rank ASC, id ASC",
            (session_id,),
        )
        out = []
        for row in cur.fetchall():
            d = dict(row)
            d["urgency_flag"] = bool(d["urgency_flag"])
            for jf in ("extracted_item", "score_breakdown"):
                if d.get(jf):
                    try:
                        d[jf] = json.loads(d[jf])
                    except json.JSONDecodeError:
                        pass
            out.append(d)
        return out
