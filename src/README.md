# src/ layout

```
src/
├── rules_v1.yaml     # SINGLE SOURCE OF TRUTH for scoring (SHA-256 hashed at load)
├── requirements.txt
├── .env.example      # copy to .env; blank watsonx creds => offline extractor
├── run.py            # python run.py  ->  http://127.0.0.1:8000
├── sync_web_mirror.py # regenerates web/index.html's offline mirror from the rules
├── app/
│   ├── models.py       # Pydantic v2 schemas (RawExtractedItem is strict)
│   ├── rules.py        # loads + hashes rules_v1.yaml; condition normalization
│   ├── scoring.py      # PURE deterministic score_item / rank_items (Decimal)
│   ├── extraction.py   # Bob layer: validate + retry(2) + manual-review fallback
│   ├── llm_client.py   # watsonx Granite client + deterministic offline client
│   ├── audit.py        # SQLite evidence_log (replay past runs)
│   ├── main.py         # FastAPI: /extract /score /triage /audit /health
│   └── mcp_server.py   # MCP tools so IBM Bob can drive the pipeline
├── tests/            # pytest — exact-match determinism, retry, tie-break, API, mirror sync
└── web/index.html    # single-page console (fetch /triage, offline fallback)
```

The boundary that matters: **`extraction.py` is the only module that talks to the
model. `scoring.py` never imports it and never makes an LLM call.** That
separation is what makes every schedule reproducible and auditable.
