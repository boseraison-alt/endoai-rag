# Endo AI — clinical endodontics RAG assistant

Retrieves primary literature from a Neon/pgvector library or live PubMed,
scores each paper, bands it by study design, and asks Claude to synthesise an
answer that cites only what it was given. Flask UI in `app.py`, engine in
`endo_ai.py`, RAG store in `rag.py`.

Read `HANDOVER.md` before changing anything — it documents the recurring bug
classes and why the tests are shaped the way they are.

## Setup

Requires Python 3.14 (the pinned wheel set is what runs in production).

```
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then fill in keys (see below)
python app.py                   # http://127.0.0.1:5000
```

`requirements.txt` pins every dependency to the exact version in use,
including the torch / sentence-transformers stack. Do not loosen pins;
regenerate them deliberately after an intentional upgrade.

## Environment variables

See `.env.example` for the full annotated list. The load-bearing ones:

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Claude synthesis |
| `DATABASE_URL` | yes | Neon Postgres (pgvector library + caches) |
| `OPENAI_API_KEY` | no | TTS + GPT-4o vision fallback |
| `GEMINI_API_KEY` | no | Gemini vision (X-ray path, if enabled) |
| `NCBI_API_KEY`, `NCBI_EMAIL` | no | Higher eutils rate limits |
| `ADMIN_TOKEN` | no | Enables the admin routes (below) |
| `ENABLE_XRAY` | no | Enables `POST /api/analyze-xray` (default OFF) |

## Admin routes

`GET /admin/costs`, `GET /admin/evidence-mapping` and `POST /cache/clear` are
operator-only and gated behind a shared secret. Requests must send an
`X-Admin-Token` header matching the `ADMIN_TOKEN` environment variable:

```
curl -H "X-Admin-Token: <your token>" http://127.0.0.1:5000/admin/costs
```

Deny by default: if `ADMIN_TOKEN` is unset or empty, these routes return 403
for everyone — there is no unauthenticated fallback. Generate a token with
e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"` and set it
in `.env`.

`DELETE /learn_history/<file>` is deliberately *not* token-gated: the UI
sidebar's delete button calls it, it is path-validated, and it can only touch
files inside `learn_history/`. If you gate it later, the UI fetch in
`templates/index.html` must learn to send the header too.

## X-ray analysis (disabled by default)

`POST /api/analyze-xray` sends a radiograph to a third-party vision API.
Patient imagery is PHI: the route returns 403 unless `ENABLE_XRAY=true`, and
**enabling it in production requires a BAA with the vision provider** (see
HANDOVER.md). When enabled, uploads are re-encoded to strip EXIF/PNG metadata
and only a sanitized tooth number — never case text — accompanies the image.

## Tests

```
python -m pytest -q                    # offline suite
RUN_NETWORK_TESTS=1 python -m pytest   # adds live PubMed syntax checks
python eval/run_eval.py --diff         # retrieval eval vs baseline
```

Network-dependent tests are opt-in; every one has an offline twin.
