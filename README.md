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

`GET /admin/costs`, `GET /admin/evidence-mapping`, `POST /cache/clear` and
`DELETE /learn_history/<file>` are operator-only and gated behind a shared
secret. Requests must send an `X-Admin-Token` header matching the
`ADMIN_TOKEN` environment variable:

```
curl -H "X-Admin-Token: <your token>" http://127.0.0.1:5000/admin/costs
```

Deny by default: if `ADMIN_TOKEN` is unset or empty, these routes return 403
for everyone — there is no unauthenticated fallback. Generate a token with
e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"` and set it
in `.env` as `ADMIN_TOKEN=<paste the generated value>`.

### The delete button and the token in the page

`DELETE /learn_history/<file>` is the one gated route the UI itself calls (the
sidebar's per-report delete button). So that it can send the header, `GET /`
renders `ADMIN_TOKEN` into `<meta name="admin-token">` and the button forwards
it as `X-Admin-Token`.

**Tradeoff, stated plainly: anyone who can load the page can read the token
out of the HTML.** That is acceptable here because Endo AI is a single-user
app bound to localhost and the token gates only local admin routes — it is not
a credential for anything else. Do not reuse this token elsewhere, and do not
carry this pattern into a hosted or multi-user deployment; that would need a
session/CSRF-token scheme instead.

With `ADMIN_TOKEN` unset the delete button gets a 403 and the report list says
so — the row stays put and the file stays on disk. It never looks like the
delete worked. Set `ADMIN_TOKEN`, restart the server, and reload the page to
enable deleting.

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
