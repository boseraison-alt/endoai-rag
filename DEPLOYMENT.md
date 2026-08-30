# Curo (endo-ai-rag) — Deployment Handover

This document is self-contained: it is written so it can be handed to any
assistant or engineer who has never seen this codebase, together with access to
the GitHub repo, and be sufficient to get the app hosted. Facts below were
verified against the actual code and git history on 2026-08-31, not assumed.

## What this is

Curo is a clinical endodontics evidence assistant: a Flask web app that takes a
clinical question, retrieves papers from a local pgvector library and/or live
PubMed, scores and tiers them by study design, has Claude synthesize an answer
that cites only retrieved papers, and then validates every citation against the
abstracts before showing it. One HTML page, JSON endpoints, background worker
threads, polling for progress.

**Stack:** Python / Flask 3.1 · Neon Postgres + pgvector (cloud-hosted) ·
Anthropic API (Opus/Sonnet/Haiku) · NCBI E-utilities · sentence-transformers
(all-MiniLM-L6-v2, runs locally on CPU) · single-page UI in
`templates/index.html`.

## Current state — what is already done

| Item | State |
|---|---|
| GitHub repo | `https://github.com/boseraison-alt/endoai-rag` — `main` is pushed and up to date, tags `mvp-demo` / `mvp-demo-2` pushed |
| Secrets hygiene | Verified: `.env` was never committed in any revision; full-history scans for API-key and connection-string patterns are clean; `.gitignore` blocks `.env*`, logs, generated media, and runtime data |
| Env templates | `.env.example` / `.env.template` are tracked and contain placeholders only |
| Database | Already hosted on Neon (serverless Postgres with pgvector). ~2,400 papers with embeddings, plus caches. **Nothing to migrate — a server only needs `DATABASE_URL`.** Tables auto-create on first run if pointed at an empty DB, but the paper library would start empty |
| Tests | 600+ pass locally (`python -m pytest -q`; network-dependent tests are opt-in via `RUN_NETWORK_TESTS=1`) |

## ⚠️ Read this before choosing hosting

1. **The app has NO end-user authentication.** Anyone who can reach it can ask
   questions, and every live question spends real Anthropic API money
   (~$0.20–$1.20 per literature review, ~$1.20 per Deep Learning curriculum).
   Do not put it on the open internet as-is. Acceptable options: host behind an
   auth proxy (Cloudflare Access, Tailscale, basic-auth in the reverse proxy),
   keep it on a private network, or add a login layer first. Only the
   *admin/destructive* routes are gated (see `ADMIN_TOKEN` below).
2. **`app.run(debug=True)` at the bottom of `app.py` is the dev entry point.**
   Never run that in production — Flask debug mode exposes the Werkzeug
   debugger, which is remote code execution. Use gunicorn (see below).
3. **Exactly ONE worker process.** Job state (`jobs` dict) lives in process
   memory and long tasks run on background threads inside the process. With
   multiple gunicorn workers, the `/status/<job_id>` poll lands on a worker
   that has never heard of the job and everything appears broken. Correct
   invocation:
   ```
   gunicorn -w 1 --threads 16 --timeout 600 -b 0.0.0.0:8000 app:app
   ```
   (`gunicorn` is not yet in `requirements.txt` — add `gunicorn==23.0.0` on the
   server, or `waitress` on Windows.)
4. **Patient imagery / PHI:** the X-ray/vision path is disabled by default
   (`ENABLE_XRAY=false`) and must stay off unless a BAA is in place with the
   model provider. Text questions are not patient records, but do not log or
   expose them publicly either.

## Server requirements

- **Python 3.12+** (developed and tested on 3.14).
- **RAM: 2 GB minimum** — PyTorch plus the MiniLM embedding model run in-process
  on CPU. 512 MB / 1 GB instances will OOM.
- **Disk: ~7 GB free** for dependencies (torch is multi-GB) plus the model.
- **First boot downloads the embedding model** (~90 MB, all-MiniLM-L6-v2) from
  Hugging Face on the first embedding call. Needs outbound internet; cached
  afterwards. Setting `HF_HOME` to a persistent path avoids re-downloading.
- **Outbound HTTPS** to: `api.anthropic.com`, `eutils.ncbi.nlm.nih.gov`,
  Neon's Postgres host (port 5432, TLS), `huggingface.co` (first boot),
  `fonts.googleapis.com`/`fonts.gstatic.com` are client-side (browser).
- **Writable dirs at repo root:** the app appends runtime files next to the
  code — `learn_history/` (saved curricula, ~$1 each to regenerate),
  `answers/`, `audit_logs/`, `cost_log.jsonl`, `pubmed_audit.jsonl`,
  `evidence_mapping.jsonl`. On a platform with ephemeral filesystems
  (Render/Railway/Fly), attach a persistent volume or accept that history and
  audit logs vanish on redeploy. The paper library itself is in Neon and is
  safe either way.

## Environment variables

Copy `.env.example` to `.env` (the app loads it via python-dotenv), or set
these in the host's env-var UI.

**Required:**

| Var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | All synthesis/validation calls. Set a monthly spend limit in the Anthropic console before going live |
| `DATABASE_URL` | Neon Postgres connection string (`postgresql://...?sslmode=require`). The existing database already holds the paper library |
| `FLASK_SECRET_KEY` | Signs the admin session cookie. Generate: `python -c "import secrets;print(secrets.token_hex(32))"`. Admin auth **fails closed** without it |
| `ADMIN_TOKEN` | Shared secret for admin login (`/admin/costs`, `/cache/clear`, deleting saved curricula). Unset ⇒ those routes are 403 for everyone — safe, but the UI's delete button won't work |

**Recommended:**

| Var | Default | Purpose |
|---|---|---|
| `NCBI_API_KEY` | unset | Free key from an NCBI account. Raises PubMed rate limit 3→9 req/sec; retrieval is ~3× slower without it (the app prints a reminder at startup) |
| `NCBI_EMAIL` | placeholder | Identifies the client to NCBI per their usage policy |
| `DB_POOL_MAX` | 32 | Keep ≤ your Neon plan's connection limit |
| `LIBRARY_WRITE_BACK` | true | Live results are written back into the library so it learns. Set false to freeze the corpus |

**Leave alone unless you know why:** `ENABLE_XRAY` (false — see PHI note),
`USE_IMPACT_FACTOR` (false — deliberate scoring decision),
`CITATION_SUPPORT_CHECK` / `CACHE_EQUIVALENCE_CHECK` (true — safety
guardrails), `CURRICULUM_MAX_WORKERS`, `DB_POOL_MIN`,
`WRITEBACK_SESSION_GAP_SECONDS`. `OPENAI_API_KEY`/`GEMINI_API_KEY` are unused
placeholders.

## Hosting options, ranked

**A. Small VPS (recommended — most control, ~$6–12/mo).** Hetzner CX22,
DigitalOcean, Lightsail: 2 vCPU / 4 GB. Ubuntu 24.04 →
`git clone` → `python3 -m venv .venv && pip install -r requirements.txt gunicorn`
→ write `.env` → run gunicorn as a systemd service → put Caddy or nginx in
front for TLS (Caddy: two lines, automatic HTTPS) → add basic-auth or
Cloudflare Access at the proxy. Everything persists; no platform quirks.

**B. Render / Railway (easiest, ~$7–25/mo).** Connect the GitHub repo, set
env vars in the dashboard, start command = the gunicorn line above. You need
the tier with ≥2 GB RAM (free tiers OOM on torch). Add a persistent disk
mounted at the repo path for `learn_history/` + logs, or accept losing them
on deploy. Watch the build: installing torch can exceed free build limits.

**C. Fly.io / Docker anywhere.** A starting Dockerfile (untested — verify the
build before relying on it):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0
COPY . .
ENV HF_HOME=/data/hf-cache
EXPOSE 8000
CMD ["gunicorn", "-w", "1", "--threads", "16", "--timeout", "600", "-b", "0.0.0.0:8000", "app:app"]
```

Not suitable: serverless/lambda-style platforms (long background jobs,
in-memory state) and anything under 2 GB RAM.

## Deployment checklist

1. Clone; create venv; `pip install -r requirements.txt gunicorn`.
2. Set the four required env vars (+ `NCBI_API_KEY`).
3. Start gunicorn with **one worker**, many threads.
4. Open the app: the Curo page should load with the tooth logo.
5. Ask a **cached** question first (costs ~$0): *"Single-visit versus
   multiple-visit root canal treatment for necrotic teeth with apical
   periodontitis"* — should answer in seconds from cache.
6. Ask an uncached review question — expect ~60–90 s with streaming text,
   and a cost line in the answer footer. This confirms Anthropic + NCBI +
   Neon are all reachable.
7. Check `GET /admin/costs` without a token returns 403.
8. Set an Anthropic spend cap and confirm the auth story (proxy auth or
   private network) before sharing the URL with anyone.

## Facts an assistant will otherwise get wrong

- The database is **already in the cloud** (Neon). Do not provision Postgres
  on the server, do not run migrations — just supply `DATABASE_URL`.
- Embeddings are **local CPU** (sentence-transformers), not an API — that is
  why RAM matters and why no embedding key exists.
- One gunicorn **worker**, not one thread. Scaling horizontally requires
  moving job state out of process memory first (not done).
- `requirements.txt` is fully pinned; install exactly those versions. The
  pins exist because a torch/transformers mismatch silently breaks
  embeddings.
- The repo's `WORKLIST.md`, `HANDOVER.md`, `DEMO_RUNBOOK.md` are engineering
  history for developers; this file supersedes them for deployment purposes.
- Runtime artifacts (`cost_log.jsonl`, `pubmed_audit.jsonl`, `learn_history/`)
  are append-only evidence trails the app expects to be able to write; they
  are gitignored, so a fresh clone starts them empty. That is fine.

## What the owner still needs to decide

1. Hosting option A/B/C above, and budget.
2. The access-control story (Cloudflare Access / proxy basic-auth / VPN /
   private-only) — required before public exposure.
3. A domain name, if any (point DNS at the proxy; Caddy issues TLS
   automatically).
4. Anthropic monthly spend cap value.
