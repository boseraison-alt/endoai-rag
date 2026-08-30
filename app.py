"""
Endo AI — Flask Web Server
Wraps the original endo_ai.py engine with a browser UI.
Background threading so long PubMed fetches don't block the page.
"""

import os
import sys
import uuid
import threading
import tempfile
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
from dotenv import load_dotenv

# Load .env FIRST so all os.getenv() calls below (and in imported modules) see the keys
# override=True needed because Claude Code pre-sets ANTHROPIC_API_KEY='' in environment
load_dotenv(override=True)

# Force UTF-8 stdout/stderr on Windows so Unicode in print() never raises UnicodeEncodeError.
# Reconfigure first; if that fails or stream is non-standard, re-wrap the underlying buffer.
import io as _io_init
for _name in ('stdout', 'stderr'):
    _stream = getattr(sys, _name, None)
    if _stream is None:
        continue
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        try:
            buf = getattr(_stream, 'buffer', None)
            if buf is not None:
                setattr(sys, _name,
                        _io_init.TextIOWrapper(buf, encoding='utf-8',
                                                errors='replace', line_buffering=True))
        except Exception:
            pass

# ── TTS backends (prefer OpenAI, fall back to gTTS) ──────
try:
    from openai import OpenAI as _OpenAI
    _oai_tts = _OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    OPENAI_TTS_AVAILABLE = bool(os.getenv("OPENAI_API_KEY"))
except Exception:
    OPENAI_TTS_AVAILABLE = False

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

TTS_AVAILABLE = OPENAI_TTS_AVAILABLE or GTTS_AVAILABLE
if not TTS_AVAILABLE:
    print("Warning: No TTS backend -- set OPENAI_API_KEY or run: pip install gTTS")

# ── moviepy (narrated video) ─────────────────────────────
# Point imageio-ffmpeg (used by moviepy) at the native ffmpeg binary if present.
# A native install (e.g. via `winget install Gyan.FFmpeg`) is several times faster
# than imageio's bundled fallback.
def _find_native_ffmpeg():
    import shutil
    p = shutil.which("ffmpeg")
    if p: return p
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if os.path.exists(c): return c
    return None

_native_ffmpeg = _find_native_ffmpeg()
if _native_ffmpeg:
    os.environ["IMAGEIO_FFMPEG_EXE"] = _native_ffmpeg
    print(f"  Using native ffmpeg: {_native_ffmpeg}")

try:
    from moviepy import ImageClip, AudioFileClip, concatenate_videoclips
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    print("Warning: moviepy not installed -- run: pip install moviepy")

# ── PPTX ─────────────────────────────────────────────────
try:
    from pptx import Presentation as _Prs
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False
    print("Warning: python-pptx not installed -- run: pip install python-pptx")

from endo_ai import (build_evidence_base, ask_clinical_question, ask_learn_question,
                     build_deep_learning_module,
                     save_answer, generate_clarifying_questions,
                     classify_question_intent,
                     analyze_radiograph, _analysis_to_prefill,
                     calculate_case_difficulty, match_case_to_profile,
                     generate_referral_letter, generate_podcast_script,
                     generate_audio_script)
from rag import (setup_query_cache, get_cached_answer, save_query_cache,
                 setup_abstract_cache, get_cached_abstract, cache_abstract)

setup_query_cache()
setup_abstract_cache()

app = Flask(__name__)

# ── Admin authentication ─────────────────────────────────
# Shared-secret gate for operator-only / destructive routes. The token is
# checked at REQUEST time (not import time) so tests and deployments can set
# or rotate ADMIN_TOKEN without restarting differently-configured workers.
#
# Deny by default: if ADMIN_TOKEN is unset, the gated routes return 403 —
# they never fail open. This is bug class (d) in HANDOVER.md (a check that
# fails open) applied to auth.
import hmac as _admin_hmac
from functools import wraps as _admin_wraps


def require_admin_token(fn):
    """403 unless the request carries X-Admin-Token matching env ADMIN_TOKEN.

    Comparison is constant-time (hmac.compare_digest) so the token can't be
    recovered byte-by-byte from response timing.
    """
    @_admin_wraps(fn)
    def _admin_guard(*args, **kwargs):
        expected = (os.getenv("ADMIN_TOKEN") or "").strip()
        if not expected:
            return jsonify({
                "error": "Admin routes are disabled: ADMIN_TOKEN is not set "
                         "on the server. Set ADMIN_TOKEN in .env to enable "
                         "them (see README)."
            }), 403
        provided = request.headers.get("X-Admin-Token", "")
        if not _admin_hmac.compare_digest(provided.encode("utf-8"),
                                          expected.encode("utf-8")):
            return jsonify({"error": "Invalid or missing X-Admin-Token header."}), 403
        return fn(*args, **kwargs)
    return _admin_guard


# ── In-memory job store ──────────────────────────────────
jobs      = {}
jobs_lock = threading.Lock()

# ── Audio job store ───────────────────────────────────────
audio_jobs      = {}
audio_jobs_lock = threading.Lock()

# ── Case conversation evidence store ─────────────────────
case_convs      = {}   # conv_id → {"evidence": dict}
case_convs_lock = threading.Lock()


def create_job(question: str, mode: str = "review") -> str:
    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "id":         job_id,
            "question":   question,
            "mode":       mode,
            "status":     "running",
            "progress":   0,
            "message":    "Starting...",
            "answer":     None,
            "papers":     [],
            "images":     [],
            "cost_usd":   None,
            "error":      None,
            "abort":      False,
            "created_at": datetime.now().isoformat(),
        }
    return job_id


def is_aborted(job_id: str) -> bool:
    with jobs_lock:
        return jobs.get(job_id, {}).get("abort", False)


def update_job(job_id: str, **kwargs):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)


# ── Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tos")
def tos():
    return render_template("tos.html")


@app.route("/clarify", methods=["POST"])
def clarify():
    """Return 2-3 clarifying questions for a clinical query, or [] if none needed."""
    data     = request.json or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"questions": []}), 400
    try:
        questions = generate_clarifying_questions(question)
        return jsonify({"questions": questions})
    except Exception as e:
        return jsonify({"questions": [], "error": str(e)})


@app.route("/ask", methods=["POST"])
def ask():
    data     = request.json or {}
    question = data.get("question", "").strip()
    mode     = data.get("mode", "review")
    context  = data.get("context", "")   # clarification Q&A — set after user answers
    skip_clarify = data.get("skip_clarify", False)  # true when context already provided
    if mode not in ("review", "learn"):
        mode = "review"
    if not question:
        return jsonify({"error": "Question required"}), 400

    # ── Clarify gate: check if questions needed (unless context already provided) ──
    if not skip_clarify and not context:
        try:
            questions = generate_clarifying_questions(question)
            if questions:
                return jsonify({"needs_clarification": True, "questions": questions})
        except Exception:
            pass   # On any error, proceed normally

    # Build enriched question if user answered clarifying questions
    full_question = question
    if context:
        full_question = f"{question}\n\nAdditional clinical context provided by the clinician:\n{context}"

    job_id = create_job(question, mode)
    thread = threading.Thread(
        target=run_question,
        args=(job_id, full_question, mode),
        daemon=True
    )
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/abort/<job_id>", methods=["POST"])
def abort(job_id: str):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["abort"] = True
    return jsonify({"ok": True})


@app.route("/cache/clear", methods=["POST"])
@require_admin_token
def cache_clear():
    """Delete a specific cached answer so it gets regenerated fresh."""
    from rag import get_conn
    data     = request.json or {}
    question = data.get("question", "").strip()
    mode     = data.get("mode", "review")
    if not question:
        return jsonify({"error": "Question required"}), 400

    cache_key = f"[{mode}] {question}"
    from rag import embed
    try:
        q_vec = embed(cache_key)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM query_cache
            WHERE 1 - (question_embedding <=> %s::vector) >= 0.99;
        """, (q_vec,))
        deleted = cur.rowcount
        conn.commit()
        return jsonify({"deleted": deleted})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


def _safe_papers(papers: list) -> list:
    """Strip abstract/raw text from papers before sending to browser.
    Users see only metadata (PMID, title, authors, year, journal, score, level).
    Abstract text stays server-side as Claude context only — never exposed to clients.
    """
    ALLOWED = {"pmid", "title", "authors", "year", "journal",
               "journal_abbrev", "volume", "issue", "pages",
               "impact_factor", "sample_size", "followup_months",
               "citations", "level_key", "score",
               # Provenance badges — metadata only, no abstract text
               "has_coi", "coi_funder", "coi_status", "is_registered", "registry",
               "has_erratum", "has_retraction", "medline_indexed",
               # Superseded rows are filtered out of search, so this is empty in
               # practice today. It carries the PMID of the current version, so
               # the UI can point a clinician at it rather than just hiding the
               # stale one — and the whitelist has silently dropped provenance
               # fields twice before.
               "superseded_by", "is_reference_text"}
    return [{k: v for k, v in p.items() if k in ALLOWED} for p in (papers or [])]


@app.route("/status/<job_id>")
def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    # Return a copy with abstracts stripped — never expose raw copyrighted text to client
    safe = dict(job)
    safe["papers"] = _safe_papers(job.get("papers", []))
    return jsonify(safe)


# ── Background worker ────────────────────────────────────

def run_question(job_id: str, question: str, mode: str = "review"):
    try:
        # Cache key includes mode so review/learn answers are stored separately
        cache_key = f"[{mode}] {question}"

        # ── Cache check ───────────────────────────────────
        # Deep Learning: 7-day TTL (curricula go stale as literature evolves).
        # Other modes: no age limit on cache hits.
        update_job(job_id, message="Checking answer cache...", progress=3)
        # Review answers expire too. They previously had NO ttl, so a cached
        # clinical recommendation could be served at $0 indefinitely, never
        # re-validated against newer literature — the opposite of the intended
        # ordering, since a point-of-care recommendation is exactly the thing
        # that should go stale.
        ttl = LEARN_HISTORY_TTL_DAYS if mode == "learn" else REVIEW_CACHE_TTL_DAYS
        cached = get_cached_answer(cache_key, max_age_days=ttl)
        if cached:
            age_days = cached.get("age_days")
            if mode == "learn" and age_days is not None:
                age_label = "today" if age_days == 0 else f"{age_days}d ago"
                msg = f"Done (from history — saved {age_label})"
            else:
                msg = "Done (from cache)"
            update_job(
                job_id,
                status   = "complete",
                progress = 100,
                message  = msg,
                answer   = cached["answer"],
                papers   = cached["papers"],
                images   = [],
                cost_usd = 0.0,
            )
            return

        # ── Intent routing (Haiku triage) ─────────────────
        # Runs ahead of retrieval so we can pick a cheaper pipeline
        # for trivial questions and tell the clinician what we're doing.
        update_job(job_id, message="Routing question...", progress=2)
        intent = classify_question_intent(question)
        intent_cost = float(intent.get("cost") or 0.0)
        print(f"[intent] kind={intent['kind']} retrieval={intent['retrieval']} "
              f"clarify={intent['needs_clarify']} reason={intent['reason']}")

        # ── Full pipeline ─────────────────────────────────
        if mode == "learn":
            # Agentic curriculum builder: syllabus → per-module retrieval →
            # per-module writing → stitch. Density-capped at ~20 minutes.
            update_job(job_id, message="Planning teaching curriculum...", progress=5)

            def _learn_progress(pct: int, msg: str):
                if is_aborted(job_id):
                    raise RuntimeError("Cancelled by user")
                update_job(job_id, message=msg, progress=pct)

            try:
                answer, cost, evidence = build_deep_learning_module(
                    question, progress_cb=_learn_progress
                )
            except RuntimeError as ce:
                if "Cancelled" in str(ce):
                    update_job(job_id, status="aborted", progress=100, message="Cancelled")
                    return
                raise
        else:
            kind_label = {"simple": "definition", "standard": "clinical question",
                          "complex": "complex multi-system question"}.get(intent["kind"], "question")
            update_job(job_id, message=f"Routing as {kind_label} — generating search terms...",
                       progress=5)
            evidence = build_evidence_base_with_progress(job_id, question)

            if is_aborted(job_id):
                update_job(job_id, status="aborted", progress=100, message="Cancelled")
                return

            update_job(job_id, message="Asking Claude to synthesize the evidence...", progress=80)
            answer, cost = ask_clinical_question(question, evidence)

        cost = float(cost or 0.0) + intent_cost
        images = []

        if is_aborted(job_id):
            update_job(job_id, status="aborted", progress=100, message="Cancelled")
            return

        # Pull top papers for display
        summary = evidence.get("_summary", {})
        papers  = summary.get("all_scored", [])

        save_answer(question, answer, evidence)
        save_query_cache(cache_key, answer, papers)
        write_citation_audit(question, answer, mode)

        # Deep Learning curricula get an additional persistent file archive
        # under learn_history/. The 7-day re-use window is enforced via the
        # query_cache age filter above; this folder is the durable record.
        if mode == "learn":
            save_learn_output(question, answer, evidence, cost)

        update_job(
            job_id,
            status   = "complete",
            progress = 100,
            message  = "Done",
            answer   = answer,
            papers   = papers,
            images   = images,
            cost_usd = round(cost, 4),
        )

    except Exception as e:
        update_job(job_id, status="error", progress=100, error=str(e), message=str(e))


# ── Library relevance gate ───────────────────────────────
# The floor and the count that interprets it are ONE setting, kept together
# deliberately. See HANDOVER.md "The similarity floor asks a different question
# than you think" for the measurement behind these numbers.
#
# similarity_floor 0.45 -> 0.55 on 2026-08-30. all-MiniLM-L6-v2 scores any two
# endodontic texts around 0.45 on shared domain vocabulary alone, so at 0.45
# "how many hits clear the floor" answers "is this endodontics?" rather than
# "is this the question?". Measured across the 20 eval questions, 0.45 routed
# 18/20 to the library — including "root canal treatment in pregnancy", 63
# hits above the floor and not one on-topic paper.
#
# Raising the floor without re-reading min_relevant would have been the same
# mistake in the other direction: 12 papers above 0.55 is a much stronger
# claim than 12 above 0.45, and the pair has to be tuned as a pair.
RELEVANCE_GATE = {
    "similarity_floor": 0.55,   # cosine; below this a hit is same-specialty noise
    "min_relevant":     12,     # hits that must clear the floor to serve locally
    "min_hits":         20,     # raw KNN hits before relevance is even considered
    "max_topic_age_yr":  3,     # newest on-topic paper older than this -> go live
    "max_per_tier":     25,     # cap per tier, mirrors the live path
}


def build_evidence_base_with_progress(job_id: str, question: str,
                                      force_route: str = None) -> dict:
    """
    RAG-first evidence pipeline.
    Searches the full library without level_key filter (level_key is empty
    in the current library build). Falls back to PubMed if < MIN_RAG_RESULTS.

    force_route pins retrieval for evaluation runs: "live" skips the library
    gate entirely, "library" refuses to fall back to PubMed. Production always
    passes None and lets the gate decide.

    This exists because write-back makes the eval set decay silently. The laser
    regression was a failure of live search-term generation; once that run wrote
    196 papers back, the same question began serving from the library, and the
    eval case stopped exercising the generator that broke. A future "3-7 word"
    regression would have passed. Route has to be pinned by the harness, not
    left to whatever the library happens to hold on the day.
    """
    from endo_ai import (
        generate_search_terms, generate_multi_search_terms,
        fetch_cochrane, fetch_papers,
        COCHRANE_TERM, LEVEL_1_TERMS, LEVEL_2_TERMS,
        LEVEL_3A_TERMS, LEVEL_3B_TERMS,
        LEVEL_4_TERMS, LEVEL_5_TERMS,
        detect_outliers, apply_currency_tags,
        build_synthesis_order, TIER_LABEL, TIER_ORDER,
        flag_superseded_by_review,
    )
    from rag import search as rag_search, rag_results_to_scored, library_stats

    # Cosine KNN always returns its nearest neighbours, relevant or not, so a
    # bare count gate ("did we get 20 hits?") is really asking "does the
    # library exist?" — it passes for every question against a 1,886-paper
    # library and the network is then almost never consulted. These thresholds
    # make the gate ask whether the library actually COVERS the question.
    # All five read from RELEVANCE_GATE at module level — see the note there
    # on why the floor and the count that interprets it must move together.
    MIN_RAG_RESULTS         = RELEVANCE_GATE["min_hits"]
    RAG_SIMILARITY_FLOOR    = RELEVANCE_GATE["similarity_floor"]
    MIN_RAG_RELEVANT        = RELEVANCE_GATE["min_relevant"]
    MAX_RAG_PAPERS_PER_TIER = RELEVANCE_GATE["max_per_tier"]
    RAG_MAX_TOPIC_AGE_YEARS = RELEVANCE_GATE["max_topic_age_yr"]
    evidence        = {}
    all_scored      = []

    if force_route not in (None, "live", "library"):
        raise ValueError(f"force_route must be None, 'live' or 'library', got {force_route!r}")

    # Check if library is populated
    try:
        stats      = library_stats()
        library_ok = stats["total"] >= 50
    except Exception:
        library_ok = False

    if force_route == "live":
        library_ok = False
        print("  [rag_gate] force_route=live — library skipped")

    update_job(job_id, message="Generating smart search terms...", progress=8)
    smart_topic = generate_search_terms(question)

    # ── Try RAG for full evidence base ────────────────────
    if library_ok:
        update_job(job_id, message="Searching local library...", progress=15)
        # Search without level_key filter — library stores all levels together
        rag_results = rag_search(smart_topic, level_key=None, limit=100)

        # Coverage test, not just a count: enough genuinely-similar papers, and
        # at least one high-tier design among them. A library that answers with
        # only case reports and narrative reviews should defer to live PubMed
        # even when it returns plenty of near neighbours.
        relevant = [r for r in rag_results
                    if float(r.get("similarity") or 0) >= RAG_SIMILARITY_FLOOR]
        has_high_tier = any((r.get("level_key") or "") in ("cochrane", "level1")
                            for r in relevant)
        newest_year = max((int(r["year"]) for r in relevant
                           if str(r.get("year", "")).isdigit()), default=0)

        # Staleness escape hatch. Write-back plus a library-first gate means a
        # topic gets searched live once and is then served from that single
        # search forever. If the freshest paper the library holds on this topic
        # is older than the cutoff, go live regardless of coverage and let
        # write-back refresh the topic.
        from datetime import datetime as _dt
        topic_age = _dt.now().year - newest_year if newest_year else 99
        topic_is_stale = topic_age > RAG_MAX_TOPIC_AGE_YEARS

        library_covers_question = (
            len(rag_results) >= MIN_RAG_RESULTS
            and len(relevant) >= MIN_RAG_RELEVANT
            and has_high_tier
            and not topic_is_stale
        ) if force_route != "library" else True
        # force_route="library" holds the library path even when coverage is
        # thin, so a library-mode eval case measures what the library actually
        # returns instead of quietly becoming a live-path case.
        print(f"  [rag_gate] {len(rag_results)} hits, {len(relevant)} above "
              f"similarity {RAG_SIMILARITY_FLOOR}, high-tier={has_high_tier}, "
              f"newest={newest_year} (age {topic_age}y, stale={topic_is_stale}) "
              f"-> {'LIBRARY' if library_covers_question else 'LIVE PUBMED'}")

        if library_covers_question:
            update_job(job_id, message=f"Found {len(rag_results)} papers in library — building evidence...", progress=40)
            # Build the evidence from the RELEVANT hits only. Feeding all 100
            # nearest neighbours put topically unrelated papers in front of
            # Claude — a question about regenerative endodontics was answered
            # citing papers on apex locators and sealer heat properties, which
            # the claim-support check then correctly flagged. The similarity
            # floor has to filter the evidence, not merely decide the gate.
            all_rag = rag_results_to_scored(relevant)

            # Band by STUDY DESIGN (level_key), rank by score WITHIN each band.
            #
            # This previously banded by score alone (>=70 -> cochrane/level1,
            # 50-70 -> level2/3, <50 -> level4/5), which inverted the product's
            # central guarantee: a well-cited recent case series scoring 72 was
            # handed to Claude labelled "Level I — RCTs and Systematic Reviews",
            # while a smaller Cochrane review scoring 58 was demoted to Level
            # II/III — and the system prompt instructs Claude to trust the tier
            # label absolutely. Score must rank papers within a tier and never
            # promote one across tiers.
            #
            # The score-banding was a workaround for 37% of the library having
            # no level_key; that has since been backfilled from PubMed
            # publication types. The backfill left 2 rows unlabelled, but this
            # is not a closed problem — live write-back keeps producing them
            # (14 as of 2026-08-29), so the fallback below is load-bearing
            # rather than a leftover. test_end_to_end.py pins it.
            by_tier = {}
            for p in all_rag:
                tier = (p.get("level_key") or "").strip()
                # Retracted rows are excluded by search() already; this is the
                # second lock. Without it the unlabelled-fallback below would
                # re-band a 'retracted' tier to level5 and hand it to Claude.
                if tier == "retracted" or p.get("has_retraction"):
                    continue
                # An unlabelled paper has an UNKNOWN design. Placing it in the
                # weakest tier is the safe direction: it can still inform the
                # answer but can never masquerade as high-tier evidence.
                if tier not in TIER_ORDER:
                    tier = "level5"
                by_tier.setdefault(tier, []).append(p)

            for tier in TIER_ORDER:
                bucket = by_tier.get(tier)
                if not bucket:
                    continue
                bucket.sort(key=lambda x: x["score"], reverse=True)
                bucket = bucket[:MAX_RAG_PAPERS_PER_TIER]
                evidence[tier] = {
                    "text":   _scored_to_text(bucket, TIER_LABEL.get(tier, tier.upper())),
                    "ids":    [p["pmid"] for p in bucket],
                    "scored": bucket,
                    "source": "rag",
                }
                all_scored.extend(bucket)

            update_job(job_id, message="Library search complete — asking Claude...", progress=75)
            # Apply outlier detection and currency tags to RAG results
            all_scored = detect_outliers(apply_currency_tags(all_scored))
            flag_superseded_by_review(evidence)
            avg_score = sum(p["score"] for p in all_scored) / len(all_scored) if all_scored else 0
            evidence["_summary"] = {
                "total_scored":    len(all_scored),
                "avg_score":       round(avg_score, 1),
                "all_scored":      sorted(all_scored, key=lambda x: x["score"], reverse=True),
                "synthesis_order": build_synthesis_order(evidence),
            }
            return evidence

    # ── Full PubMed fallback ──────────────────────────────
    # Generate multiple search terms for broader coverage (Feature 6)
    update_job(job_id, message="Generating multi-angle search terms...", progress=12)
    search_terms = generate_multi_search_terms(question, smart_topic)
    print(f"  Multi-term search: {search_terms}")

    update_job(job_id, message="Searching Cochrane Reviews...", progress=15)
    cochrane_direct = fetch_cochrane(smart_topic)
    if cochrane_direct:
        evidence["cochrane"] = {"text": cochrane_direct, "ids": [], "scored": [],
                                "source": "pubmed"}
    else:
        text, ids, scored = fetch_papers(smart_topic, COCHRANE_TERM, "Cochrane Reviews (PubMed)", "cochrane")
        evidence["cochrane"] = {"text": text, "ids": ids, "scored": scored,
                                "source": "pubmed"}
        all_scored.extend(scored)

    levels = [
        ("level1",  LEVEL_1_TERMS,  TIER_LABEL["level1"],  30),
        ("level2",  LEVEL_2_TERMS,  TIER_LABEL["level2"],  45),
        ("level3a", LEVEL_3A_TERMS, TIER_LABEL["level3a"], 53),
        ("level3b", LEVEL_3B_TERMS, TIER_LABEL["level3b"], 58),
        ("level4",  LEVEL_4_TERMS,  TIER_LABEL["level4"],  65),
        ("level5",  LEVEL_5_TERMS,  TIER_LABEL["level5"],  72),
    ]

    seen_pmids: set = set()
    for level_key, terms, label, pct in levels:
        if is_aborted(job_id):
            break
        update_job(job_id, message=f"{label} — searching PubMed...", progress=pct)
        level_scored: list = []
        level_ids:   list = []
        level_text = ""

        # Fetch for each search term and deduplicate by PMID
        for term in search_terms:
            if is_aborted(job_id):
                break
            text, ids, scored = fetch_papers(term, " OR ".join(terms), label, level_key)
            new_scored = [p for p in scored if p["pmid"] not in seen_pmids]
            new_ids    = [i for i in ids    if i not in seen_pmids]
            for p in new_scored:
                seen_pmids.add(p["pmid"])
            level_scored.extend(new_scored)
            level_ids.extend(new_ids)
            if text and not level_text:
                level_text = text  # use text from first successful term

        level_scored.sort(key=lambda x: x["score"], reverse=True)
        evidence[level_key] = {"text": level_text, "ids": level_ids,
                               "scored": level_scored, "source": "pubmed"}
        all_scored.extend(level_scored)

    # Apply outlier detection and currency tags to PubMed results
    all_scored = detect_outliers(apply_currency_tags(all_scored))
    flag_superseded_by_review(evidence)
    avg_score = sum(p["score"] for p in all_scored) / len(all_scored) if all_scored else 0
    evidence["_summary"] = {
        "total_scored":    len(all_scored),
        "avg_score":       round(avg_score, 1),
        "all_scored":      sorted(all_scored, key=lambda x: x["score"], reverse=True),
        "synthesis_order": build_synthesis_order(evidence),
        # Distinct PMIDs that came back from PubMed across every term and tier,
        # before the per-tier cap. This is the number that actually collapsed in
        # the laser regression (5 across 28 queries), and it moves independently
        # of the final paper count, so the eval can tell a broken query apart
        # from a genuinely thin topic.
        "distinct_pmids_retrieved": len(seen_pmids),
    }
    return evidence


def _scored_to_text(scored_papers: list, label: str) -> str:
    """Convert scored paper dicts back to annotated text for Claude context.

    Uses the SAME renderer as the live-PubMed path so provenance badges (COI,
    pre-registration, corrections, indexing) appear identically regardless of
    which retrieval path answered. Previously this built its own line and
    emitted no badges at all, so library-served evidence reached Claude
    stripped of every integrity signal.
    """
    from endo_ai import format_paper_context_line
    text = f"\n[{label}]\n"
    for p in scored_papers:
        text += format_paper_context_line(p)
    return text


# ── Deep Learning history archive ─────────────────────────
# Every completed Deep Learning curriculum is persisted as JSON to
# learn_history/. The 7-day re-use window is enforced via the query_cache
# (see rag.get_cached_answer's max_age_days param) — this folder is the
# durable browsable archive (no auto-cleanup).
import re as _learn_re

_LEARN_HISTORY_DIR        = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "learn_history")
LEARN_HISTORY_TTL_DAYS    = 7   # cache window for auto re-use
REVIEW_CACHE_TTL_DAYS     = 30  # clinical answers must be re-derived periodically

def save_learn_output(question: str, answer: str, evidence: dict, cost: float) -> str:
    """Persist one completed Deep Learning curriculum to learn_history/.
    Returns the file path written, or '' on failure."""
    try:
        os.makedirs(_LEARN_HISTORY_DIR, exist_ok=True)

        # Filesystem-safe slug from the question
        slug = _learn_re.sub(r"[^a-z0-9]+", "_",
                             (question or "").lower()).strip("_")[:60]
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(_LEARN_HISTORY_DIR, f"{ts}_{slug or 'untitled'}.json")

        summary = (evidence or {}).get("_summary", {}) or {}
        payload = {
            "question":          question,
            "timestamp":         datetime.now().isoformat(),
            "answer":            answer,
            "cost_usd":          round(float(cost or 0.0), 4),
            "total_papers":      summary.get("total_scored", 0),
            "avg_paper_score":   summary.get("avg_score", 0),
            "top_pmids":         [p.get("pmid", "") for p in (summary.get("all_scored") or [])[:10]],
            # Paper metadata (no abstracts) so archived reports can render
            # author-style citations instead of bare PMIDs.
            "papers":            _safe_papers(summary.get("all_scored") or []),
        }
        with open(path, "w", encoding="utf-8") as fh:
            _audit_json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"  [learn_history] saved -> {os.path.basename(path)}")
        return path
    except Exception as e:
        print(f"  [learn_history] save failed: {e}")
        return ""


@app.route("/learn_history/<filename>")
def get_learn_history_item(filename: str):
    """Return the full archived Deep Learning curriculum (answer + metadata)."""
    # Tight path validation — only allow filenames that exist in the archive
    if "/" in filename or "\\" in filename or ".." in filename or not filename.endswith(".json"):
        return jsonify({"error": "invalid filename"}), 400
    path = os.path.join(_LEARN_HISTORY_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    try:
        with open(path, encoding="utf-8") as fh:
            rec = _audit_json.load(fh)
        return jsonify(rec)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/learn_history/<filename>", methods=["DELETE"])
def delete_learn_history_item(filename: str):
    """Permanently delete a single archived Deep Learning curriculum."""
    if "/" in filename or "\\" in filename or ".." in filename or not filename.endswith(".json"):
        return jsonify({"error": "invalid filename"}), 400
    path = os.path.join(_LEARN_HISTORY_DIR, filename)
    if not os.path.isfile(path):
        return jsonify({"error": "not found"}), 404
    try:
        os.remove(path)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/learn_history")
def list_learn_history():
    """List archived Deep Learning curricula, newest first."""
    if not os.path.isdir(_LEARN_HISTORY_DIR):
        return jsonify({"items": [], "ttl_days": LEARN_HISTORY_TTL_DAYS})
    items = []
    for fn in sorted(os.listdir(_LEARN_HISTORY_DIR), reverse=True):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(_LEARN_HISTORY_DIR, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                rec = _audit_json.load(fh)
            ts = datetime.fromisoformat(rec.get("timestamp", ""))
            age_days = (datetime.now() - ts).days
            items.append({
                "file":           fn,
                "question":       rec.get("question", ""),
                "timestamp":      rec.get("timestamp", ""),
                "age_days":       age_days,
                "in_ttl_window":  age_days <= LEARN_HISTORY_TTL_DAYS,
                "total_papers":   rec.get("total_papers", 0),
                "cost_usd":       rec.get("cost_usd", 0),
            })
        except Exception:
            continue
    return jsonify({"items": items, "ttl_days": LEARN_HISTORY_TTL_DAYS})


# ── Citation audit log (FDA CDS verifiability) ────────────
import re as _audit_re
import json as _audit_json
import hashlib as _audit_hash

_AUDIT_DIR = os.path.join(os.path.dirname(__file__), "audit_logs")

def write_citation_audit(question: str, answer: str, mode: str) -> int:
    """Extract every claim → PMID mapping from the answer and persist to disk
    so a clinician (or auditor) can later reconstruct exactly which paper
    supported each statement. Returns the number of claims logged."""
    if not answer:
        return 0

    # Match: <sentence-ish text>(one-or-more [[PMID:N]] markers)
    # Anchor sentence start at \n, sentence boundary punctuation, or doc start.
    pattern = _audit_re.compile(
        r'([^\n.!?]{10,400}?)\s*((?:\[\[PMID:\d+\]\]\s*)+)',
        _audit_re.MULTILINE,
    )

    claims = []
    for m in pattern.finditer(answer):
        sentence = m.group(1).strip()
        pmids    = _audit_re.findall(r'\[\[PMID:(\d+)\]\]', m.group(2))
        if sentence and pmids:
            claims.append({"claim": sentence, "pmids": pmids})

    if not claims:
        return 0

    try:
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _audit_hash.sha256(question.encode("utf-8")).hexdigest()[:10]
        path = os.path.join(_AUDIT_DIR, f"audit_{ts}_{slug}.json")
        payload = {
            "timestamp":       datetime.now().isoformat(),
            "mode":            mode,
            "question":        question,
            "answer_sha256":   _audit_hash.sha256(answer.encode("utf-8")).hexdigest(),
            "claim_count":     len(claims),
            "claim_citations": claims,
        }
        with open(path, "w", encoding="utf-8") as fh:
            _audit_json.dump(payload, fh, indent=2, ensure_ascii=False)
        print(f"  [audit] wrote {len(claims)} claim citations -> {os.path.basename(path)}")
    except Exception as e:
        print(f"  [audit] write failed: {e}")

    return len(claims)


# ── Provenance / inline-citation abstract endpoint ────────
# Backs the [[PMID:n]] click-through side panel in the UI. Per FDA CDS
# verifiability guidance, every clinical claim the AI emits should be
# independently inspectable by the clinician.

import requests as _prov_requests
_ABSTRACT_CACHE     = {}      # PMID -> dict ; simple LRU by insertion order
_ABSTRACT_CACHE_MAX = 500

def _trim_abstract_cache():
    while len(_ABSTRACT_CACHE) > _ABSTRACT_CACHE_MAX:
        _ABSTRACT_CACHE.pop(next(iter(_ABSTRACT_CACHE)))

def _eutils_params(extra: dict) -> dict:
    """Merge eutils params with NCBI tool/email + api_key (if set in env).

    Unauthenticated eutils is rate-limited to 3 req/sec on slow servers; an
    API key bumps that to 10 req/sec on prioritised hardware. Set
    NCBI_API_KEY in .env to enable.
    """
    p = dict(extra or {})
    p.setdefault("tool",  "endo-ai-rag")
    p.setdefault("email", os.getenv("NCBI_EMAIL", "endoai@research.local"))
    api_key = (os.getenv("NCBI_API_KEY") or "").strip()
    if api_key:
        p["api_key"] = api_key
    return p


def _eutils_get(url: str, params: dict):
    """GET an eutils endpoint with one retry on transient failures.

    NCBI eutils routinely takes 5-15s under load; an 8s timeout was making
    abstract panel loads fail visibly. We use (connect=5, read=20) and retry
    once on timeout/connection errors before surfacing the failure.
    """
    last_exc = None
    final_params = _eutils_params(params)
    for attempt in (1, 2):
        try:
            return _prov_requests.get(url, params=final_params, timeout=(5, 20))
        except (_prov_requests.exceptions.ReadTimeout,
                _prov_requests.exceptions.ConnectTimeout,
                _prov_requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt == 2:
                raise
    raise last_exc  # unreachable, satisfies linters


@app.route("/api/abstract/<pmid>")
def get_abstract(pmid):
    """Fetch full abstract + metadata for a single PMID.

    Three-tier cache lookup:
      L1 — in-process dict (zero ms)
      L2 — Postgres abstract_cache (one local round-trip; populated for free
            during build_evidence_base())
      L3 — live NCBI eutils (last resort; slow + rate-limited)

    On L3 fetch, we backfill L2 + L1 so the next click is instant.
    """
    if not pmid.isdigit() or len(pmid) > 10:
        return jsonify({"error": "invalid PMID"}), 400

    # L1 — in-process
    if pmid in _ABSTRACT_CACHE:
        resp = dict(_ABSTRACT_CACHE[pmid])
        resp["source"] = "memory"
        return jsonify(resp)

    # L2 — Postgres abstract_cache (populated during build_evidence_base)
    cached = get_cached_abstract(pmid)
    if cached and cached.get("abstract") and len(cached.get("abstract") or "") >= 50:
        result = {
            "pmid":     pmid,
            "title":    (cached.get("title") or "Title unavailable").rstrip("."),
            "abstract": cached.get("abstract") or "Abstract unavailable.",
            "journal":  cached.get("journal") or "",
            "year":     cached.get("year")    or "",
            "authors":  cached.get("authors") or "",
            "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source":   "postgres",
        }
        _ABSTRACT_CACHE[pmid] = result
        _trim_abstract_cache()
        return jsonify(result)

    # L3 — live eutils (slow path)
    try:
        # esummary for structured metadata (title, journal, year, authors)
        s = _eutils_get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "json"},
        )
        meta = (s.json().get("result", {}) or {}).get(pmid, {}) or {}

        # efetch text for the abstract body
        f = _eutils_get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"},
        )
        raw = f.text or ""

        # PubMed efetch returns: citation line, title, authors, affiliation,
        # then abstract, then DOI/PMID footer. Heuristic: pull paragraphs and
        # keep the longest one (which is virtually always the abstract).
        paragraphs = []
        current    = []
        for line in raw.split("\n"):
            line = line.rstrip()
            if line.strip():
                current.append(line.strip())
            else:
                if current:
                    paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))
        # Discard trivially short paragraphs that aren't the abstract
        candidates = [p for p in paragraphs if len(p) >= 200]
        abstract   = max(candidates, key=len) if candidates else (
            max(paragraphs, key=len) if paragraphs else "")

        authors_list = meta.get("authors", []) or []
        names = [a.get("name", "") for a in authors_list if a.get("name")]
        if len(names) > 5:
            authors_str = ", ".join(names[:5]) + ", et al."
        else:
            authors_str = ", ".join(names)

        result = {
            "pmid":     pmid,
            "title":    (meta.get("title", "") or "Title unavailable").rstrip("."),
            "abstract": abstract or "Abstract unavailable.",
            "journal":  meta.get("fulljournalname", "") or meta.get("source", ""),
            "year":     (meta.get("pubdate", "") or "")[:4],
            "authors":  authors_str,
            "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source":   "eutils_live",
        }
        _ABSTRACT_CACHE[pmid] = result
        _trim_abstract_cache()
        # Backfill Postgres so the next click on this PMID is instant
        if abstract and len(abstract) >= 50:
            try:
                cache_abstract(
                    pmid     = pmid,
                    title    = result["title"],
                    abstract = result["abstract"],
                    journal  = result["journal"],
                    year     = result["year"],
                    authors  = result["authors"],
                    source   = "eutils_live",
                )
            except Exception as ce:
                print(f"  [abstract_cache] backfill skipped (pmid={pmid}): {ce}")
        return jsonify(result)

    except (_prov_requests.exceptions.ReadTimeout,
            _prov_requests.exceptions.ConnectTimeout) as e:
        return jsonify({
            "error": "PubMed (NCBI eutils) is slow right now — request timed out after retry. "
                     "Try again in a moment, or open the source directly:",
            "url":   f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "kind":  "timeout",
        }), 504
    except _prov_requests.exceptions.ConnectionError as e:
        return jsonify({
            "error": "Could not reach PubMed (NCBI eutils). Check your internet connection, "
                     "or open the source directly:",
            "url":   f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "kind":  "connection",
        }), 502
    except Exception as e:
        return jsonify({
            "error": f"Could not load abstract: {e}",
            "url":   f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "kind":  "other",
        }), 502


# ── Cost telemetry ────────────────────────────────────────
# Reads endo_ai's append-only cost_log.jsonl and returns aggregate stats
# so the operator can measure savings from the model-routing changes.

@app.route("/admin/costs")
@require_admin_token
def admin_costs():
    """Aggregate Claude API cost data over the last N days.

    Optional query params:
      ?days=7    window length (default 7)

    Returns:
      total_cost_usd
      total_calls
      window_days
      by_mode          — { mode: { calls, total_cost, avg_cost_per_call } }
      by_model         — { model: { calls, total_cost, in_tokens, out_tokens } }
      by_function      — { fn:    { calls, total_cost, avg_cost_per_call } }
      avg_cost_per_request_by_mode — see note below
    """
    from endo_ai import _COST_LOG_PATH
    from datetime import timedelta
    import json

    try:
        days = int(request.args.get("days", "7"))
    except ValueError:
        days = 7
    cutoff = datetime.now() - timedelta(days=days)

    if not os.path.exists(_COST_LOG_PATH):
        return jsonify({
            "total_cost_usd": 0.0, "total_calls": 0, "window_days": days,
            "by_mode": {}, "by_model": {}, "by_function": {},
            "avg_cost_per_request_by_mode": {},
            "note": "cost_log.jsonl does not exist yet — no Claude calls logged.",
        })

    by_mode:     dict = {}
    by_model:    dict = {}
    by_function: dict = {}
    total_cost   = 0.0
    total_calls  = 0

    with open(_COST_LOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts  = datetime.fromisoformat(rec.get("ts", ""))
            except Exception:
                continue
            if ts < cutoff:
                continue

            cost = float(rec.get("cost_usd", 0.0))
            mode = rec.get("mode", "unknown")
            mdl  = rec.get("model", "unknown")
            fn   = rec.get("function", "unknown")
            in_t = int(rec.get("input_tokens", 0))
            out_t = int(rec.get("output_tokens", 0))

            total_cost  += cost
            total_calls += 1

            m = by_mode.setdefault(mode, {"calls": 0, "total_cost": 0.0})
            m["calls"] += 1; m["total_cost"] += cost

            mm = by_model.setdefault(mdl, {"calls": 0, "total_cost": 0.0,
                                            "in_tokens": 0, "out_tokens": 0})
            mm["calls"] += 1; mm["total_cost"] += cost
            mm["in_tokens"] += in_t; mm["out_tokens"] += out_t

            f = by_function.setdefault(fn, {"calls": 0, "total_cost": 0.0})
            f["calls"] += 1; f["total_cost"] += cost

    # Round + add per-call averages
    for d in (by_mode, by_function):
        for k, v in d.items():
            v["total_cost"] = round(v["total_cost"], 4)
            v["avg_cost_per_call"] = round(v["total_cost"] / max(v["calls"], 1), 6)
    for k, v in by_model.items():
        v["total_cost"] = round(v["total_cost"], 4)

    # Approximate "cost per user-initiated request" by mode.
    # Each mode has a designated "primary" function whose call count proxies
    # the request count. Multi-step pipelines (Learn) sum all sub-call costs
    # then divide by the count of the terminal stitch call.
    PRIMARY_FN = {
        "review":     "ask_clinical_question",
        "learn":      "stitch_curriculum",       # 1 stitch == 1 user request
        "case":       "ask_case_question",       # per-turn, not per-conv
        "assessment": "generate_referral_letter",
        "export":     "generate_slides_content", # treat any export as a "request"
    }
    avg_per_request = {}
    for mode, primary in PRIMARY_FN.items():
        n_requests = (by_function.get(primary) or {}).get("calls", 0)
        mode_total = (by_mode.get(mode)        or {}).get("total_cost", 0.0)
        if n_requests:
            avg_per_request[mode] = {
                "requests":           n_requests,
                "avg_cost_per_request": round(mode_total / n_requests, 4),
                "primary_fn":         primary,
            }

    return jsonify({
        "window_days":                  days,
        "total_calls":                  total_calls,
        "total_cost_usd":               round(total_cost, 4),
        "by_mode":                      by_mode,
        "by_model":                     by_model,
        "by_function":                  by_function,
        "avg_cost_per_request_by_mode": avg_per_request,
        "note": (
            "avg_cost_per_request_by_mode uses a primary-function heuristic: "
            "for Deep Learning, request count = stitch_curriculum calls "
            "(each Learn request fires 1 syllabus + 4 modules + 1 stitch)."
        ),
    })


# ── Evidence-mapping telemetry ────────────────────────────
# Reads endo_ai's append-only evidence_mapping.jsonl and returns aggregate
# pass/fail/retry stats so the operator can monitor whether Claude is
# actually grounding its claims in the retrieved evidence base.

@app.route("/admin/evidence-mapping")
@require_admin_token
def admin_evidence_mapping():
    """Aggregate evidence-mapping validation results over the last N days.

    Optional query params:
      ?days=7          window length (default 7)
      ?failures=true   include the most recent failure records (capped at 50)

    Returns:
      window_days
      total_attempts            (= 1st-attempts + retry-attempts)
      total_first_attempts
      first_attempt_pass_rate   (proportion of attempts=1 that passed)
      retry_count               (count of attempts=2)
      retry_pass_rate           (proportion of attempts=2 that passed)
      by_function               { fn: { attempts, first_pass, retries, retry_pass,
                                        avg_score, fabricated_total, unattributed_total,
                                        gap_total } }
      failure_breakdown         { reason_prefix: count }
      recent_failures           (only if failures=true)
    """
    from endo_ai import _EVMAP_LOG_PATH
    from datetime import timedelta
    import json

    try:
        days = int(request.args.get("days", "7"))
    except ValueError:
        days = 7
    include_failures = request.args.get("failures", "").lower() in ("1", "true", "yes")
    cutoff = datetime.now() - timedelta(days=days)

    if not os.path.exists(_EVMAP_LOG_PATH):
        return jsonify({
            "window_days": days, "total_attempts": 0, "total_first_attempts": 0,
            "first_attempt_pass_rate": None, "retry_count": 0, "retry_pass_rate": None,
            "by_function": {}, "failure_breakdown": {},
            "note": "evidence_mapping.jsonl does not exist yet — no validations logged.",
        })

    by_function: dict = {}
    failure_breakdown: dict = {}
    recent_failures: list = []
    total_attempts = 0
    first_attempts_total = 0
    first_attempts_passed = 0
    retry_count = 0
    retry_passed = 0

    with open(_EVMAP_LOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                ts  = datetime.fromisoformat(rec.get("ts", ""))
            except Exception:
                continue
            if ts < cutoff:
                continue

            attempt = int(rec.get("attempt", 1))
            passed  = bool(rec.get("passed"))
            score   = float(rec.get("score") or 0.0)
            fn      = rec.get("function", "unknown")
            reason  = rec.get("failure_reason") or ""

            total_attempts += 1
            if attempt == 1:
                first_attempts_total += 1
                if passed:
                    first_attempts_passed += 1
            elif attempt == 2:
                retry_count += 1
                if passed:
                    retry_passed += 1

            f = by_function.setdefault(fn, {
                "attempts": 0, "first_pass": 0, "retries": 0, "retry_pass": 0,
                "score_sum": 0.0, "fabricated_total": 0,
                "unattributed_total": 0, "gap_total": 0,
            })
            f["attempts"] += 1
            f["score_sum"] += score
            f["fabricated_total"]   += int(rec.get("n_fabricated") or 0)
            f["unattributed_total"] += int(rec.get("n_unattributed") or 0)
            f["gap_total"]          += int(rec.get("n_gap_sections") or 0)
            if attempt == 1 and passed:
                f["first_pass"] += 1
            if attempt == 2:
                f["retries"] += 1
                if passed:
                    f["retry_pass"] += 1

            if reason:
                # Prefix = part before first colon, e.g. "FABRICATED_PMIDS"
                prefix = reason.split(":", 1)[0].strip()
                failure_breakdown[prefix] = failure_breakdown.get(prefix, 0) + 1
                if include_failures and len(recent_failures) < 50:
                    recent_failures.append({
                        "ts":               rec.get("ts"),
                        "function":         fn,
                        "attempt":          attempt,
                        "score":            score,
                        "failure_reason":   reason,
                        "fabricated_pmids": rec.get("fabricated_pmids") or [],
                        "gap_sections":     rec.get("gap_sections") or [],
                        "unattributed_sample": rec.get("unattributed_sample") or [],
                    })

    # Finalise per-function averages
    for k, v in by_function.items():
        v["avg_score"] = round(v["score_sum"] / max(v["attempts"], 1), 1)
        del v["score_sum"]

    response = {
        "window_days":              days,
        "total_attempts":           total_attempts,
        "total_first_attempts":     first_attempts_total,
        "first_attempt_pass_rate":  (round(first_attempts_passed / first_attempts_total, 3)
                                      if first_attempts_total else None),
        "retry_count":              retry_count,
        "retry_pass_rate":          (round(retry_passed / retry_count, 3)
                                      if retry_count else None),
        "by_function":              by_function,
        "failure_breakdown":        failure_breakdown,
    }
    if include_failures:
        response["recent_failures"] = recent_failures
    return jsonify(response)


# ── History ──────────────────────────────────────────────

@app.route("/history")
def history():
    """Return recent cached queries for the history sidebar."""
    from rag import get_conn
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            SELECT id, question_text, created_at, hit_count
            FROM query_cache
            ORDER BY created_at DESC
            LIMIT 50;
        """)
        rows = cur.fetchall()
        items = []
        for r in rows:
            qt = r[1] or ""
            # Parse mode prefix from cache key  [review]/[learn]/[case]
            mode_tag = "review"
            question = qt
            for tag in ("learn", "review", "case"):
                prefix = f"[{tag}] "
                if qt.startswith(prefix):
                    mode_tag = tag
                    question = qt[len(prefix):]
                    break
            items.append({
                "id":         r[0],
                "question":   question,
                "mode":       mode_tag,
                "created_at": r[2].isoformat() if r[2] else None,
                "hit_count":  r[3] or 0,
            })
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/history/<int:cache_id>")
def history_detail(cache_id: int):
    """Return full answer + papers for a cached history entry."""
    from rag import get_conn
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute(
            "SELECT question_text, answer, papers FROM query_cache WHERE id = %s",
            (cache_id,)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        qt, answer, papers = row
        mode_tag = "review"
        question = qt or ""
        for tag in ("learn", "review", "case"):
            prefix = f"[{tag}] "
            if question.startswith(prefix):
                mode_tag = tag
                question = question[len(prefix):]
                break
        return jsonify({
            "question": question,
            "mode":     mode_tag,
            "answer":   answer or "",
            "papers":   papers or [],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


# ── Case Discussion ───────────────────────────────────────

@app.route("/case_chat", methods=["POST"])
def case_chat():
    data         = request.json or {}
    messages     = data.get("messages", [])
    conv_id      = data.get("conv_id") or str(uuid.uuid4())
    skip_clarify = data.get("skip_clarify", False)
    question     = (messages[0]["content"] if messages else "").strip()
    if not question:
        return jsonify({"error": "No message provided"}), 400

    # Clarify gate — first message only, not a follow-up in an ongoing chat
    if not skip_clarify and len(messages) == 1:
        try:
            questions = generate_clarifying_questions(question)
            if questions:
                return jsonify({"needs_clarification": True, "questions": questions})
        except Exception:
            pass

    job_id = create_job(question, mode="case")
    thread = threading.Thread(
        target=run_case_chat,
        args=(job_id, messages, conv_id),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "conv_id": conv_id})


def run_case_chat(job_id: str, messages: list, conv_id: str):
    try:
        original_q = messages[0]["content"] if messages else ""
        # Latest user message drives THIS turn's literature search
        latest_user = next((m["content"] for m in reversed(messages)
                            if (m or {}).get("role") == "user"), original_q)
        is_followup = len(messages) > 1

        # Search query: combine original case context with the latest follow-up
        # so vague follow-ups ("what about MTA?") still hit relevant literature.
        if is_followup and latest_user.strip().lower() != original_q.strip().lower():
            search_q = f"{original_q} -- {latest_user}"
        else:
            search_q = original_q

        update_job(job_id,
                   message=("Searching literature for this question..."
                            if is_followup else
                            "Searching evidence base for this case..."),
                   progress=10)
        evidence = build_evidence_base_with_progress(job_id, search_q)

        # Persist the most recent evidence for this conversation
        with case_convs_lock:
            case_convs[conv_id] = {"evidence": evidence}

        if is_aborted(job_id):
            update_job(job_id, status="aborted", progress=100, message="Cancelled")
            return

        from endo_ai import ask_case_question
        answer, cost = ask_case_question(messages, evidence)

        papers = evidence.get("_summary", {}).get("all_scored", [])
        update_job(
            job_id,
            status   = "complete",
            progress = 100,
            message  = "Done",
            answer   = answer,
            papers   = papers,
            images   = [],
            cost_usd = round(cost, 4),
        )
    except Exception as e:
        update_job(job_id, status="error", progress=100, error=str(e), message=str(e))


# ── Audio Export ──────────────────────────────────────────

@app.route("/generate_audio", methods=["POST"])
def generate_audio_endpoint():
    if not TTS_AVAILABLE:
        return jsonify({"error": "No TTS backend available"}), 503

    data           = request.json or {}
    job_id         = data.get("job_id", "")
    length_minutes = int(data.get("length_minutes", 10))
    length_minutes = max(5, min(60, length_minutes))
    voice          = data.get("voice", "onyx")
    style          = data.get("style", "lecture")   # "lecture" | "conversation"

    with jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.get("answer"):
        return jsonify({"error": "Job not found or no answer to convert"}), 404

    audio_id = str(uuid.uuid4())
    with audio_jobs_lock:
        import time as _t_audio
        audio_jobs[audio_id] = {
            "status":         "running",
            "phase":          "script",     # "script" → "audio" → "complete"
            "file_path":      None,
            "script":         None,         # list of {host,text} for conversation
            "style":          style,
            "question":       job["question"],
            "length_minutes": length_minutes,
            "error":          None,
            "started_at":     _t_audio.time(),
            "slides_done":    0, "slides_total": 0,
        }

    thread = threading.Thread(
        target=run_generate_audio,
        args=(audio_id, job["answer"], job["question"], length_minutes, voice, style),
        daemon=True,
    )
    thread.start()
    return jsonify({"audio_id": audio_id})


@app.route("/audio_status/<audio_id>")
def audio_status(audio_id: str):
    import time as _t_status
    with audio_jobs_lock:
        job = audio_jobs.get(audio_id)
        if job is not None:
            job_copy = dict(job)
        else:
            job_copy = None
    if not job_copy:
        return jsonify({"error": "Not found"}), 404

    elapsed = None
    eta     = None
    started = job_copy.get("started_at")
    done    = int(job_copy.get("slides_done", 0) or 0)
    total   = int(job_copy.get("slides_total", 0) or 0)
    if started:
        elapsed = max(0, int(_t_status.time() - started))
        if job_copy.get("status") in ("complete", "error", "cancelled"):
            eta = 0
        elif done > 0 and total > 0 and done < total:
            per_slide = elapsed / done
            eta = max(0, int(per_slide * (total - done)))
        elif total > 0:
            # No slide done yet -- rough heuristic: 8s per slide for content+TTS+encode
            eta = max(0, int(8 * total) - elapsed)

    return jsonify({
        "status":       job_copy["status"],
        "phase":        job_copy.get("phase", "script"),
        "style":        job_copy.get("style", "lecture"),
        "script":       job_copy.get("script"),
        "error":        job_copy.get("error"),
        "slides_done":  done,
        "slides_total": total,
        "elapsed_seconds": elapsed,
        "eta_seconds":     eta,
    })


@app.route("/audio_download/<audio_id>")
def audio_download(audio_id: str):
    with audio_jobs_lock:
        job = audio_jobs.get(audio_id)
    if not job or job["status"] != "complete" or not job.get("file_path"):
        return jsonify({"error": "Audio not ready"}), 404
    style = job.get("style", "lecture")
    fname = f"endo_ai_podcast_{audio_id[:8]}.mp3" if style == "conversation" else f"endo_ai_lecture_{audio_id[:8]}.mp3"
    return send_file(
        job["file_path"],
        as_attachment=True,
        download_name=fname,
        mimetype="audio/mpeg",
    )


def run_generate_audio(audio_id: str, answer: str, question: str,
                       length_minutes: int, voice: str = "onyx",
                       style: str = "lecture"):
    try:
        # ── CONVERSATION style (two-host podcast) ───────────────
        if style == "conversation":
            with audio_jobs_lock:
                audio_jobs[audio_id]["phase"]  = "script"
                audio_jobs[audio_id]["status"] = "generating_script"

            print(f"  Generating {length_minutes}-min conversation script (DR. CHEN / ALEX)...")
            lines = generate_podcast_script(answer, question, length_minutes)
            print(f"  Script: {len(lines)} lines")

            with audio_jobs_lock:
                audio_jobs[audio_id]["script"] = lines   # expose immediately for transcript
                audio_jobs[audio_id]["phase"]  = "audio"
                audio_jobs[audio_id]["status"] = "converting_to_audio"

            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()

            if OPENAI_TTS_AVAILABLE:
                HOST1_VOICE = "onyx"   # DR. CHEN
                HOST2_VOICE = "nova"   # ALEX
                audio_bytes = b""
                for i, line in enumerate(lines):
                    host  = line.get("host", "")
                    text  = (line.get("text") or "").strip()
                    if not text:
                        continue
                    v = HOST1_VOICE if "CHEN" in host.upper() else HOST2_VOICE
                    try:
                        resp = _oai_tts.audio.speech.create(
                            model="tts-1-hd", voice=v, input=text[:4096])
                        audio_bytes += resp.content
                        print(f"    [{i+1}/{len(lines)}] {host} OK ({v})")
                    except Exception as tts_err:
                        print(f"    [{i+1}/{len(lines)}] TTS error: {tts_err}")
                with open(tmp.name, "wb") as f:
                    f.write(audio_bytes)
            elif GTTS_AVAILABLE:
                # Fallback: concatenate all text as one block
                full_text = " ".join(l.get("text", "") for l in lines)
                tts = gTTS(text=full_text[:5000], lang="en", slow=False)
                tts.save(tmp.name)
            else:
                raise RuntimeError("No TTS backend available")

            with audio_jobs_lock:
                audio_jobs[audio_id]["status"]    = "complete"
                audio_jobs[audio_id]["file_path"] = tmp.name
                q   = audio_jobs[audio_id].get("question", "")
                dur = audio_jobs[audio_id].get("length_minutes", 10)
            _persist_media(tmp.name, audio_id, "mp3", q, "conversation", "audio", dur)
            print(f"  Podcast audio saved: {tmp.name}")
            return

        # ── LECTURE style (single-voice, default) ───────────────
        with audio_jobs_lock:
            audio_jobs[audio_id]["phase"]  = "script"
            audio_jobs[audio_id]["status"] = "generating_script"

        print(f"  Generating {length_minutes}-min lecture script...")
        script = generate_audio_script(answer, question, length_minutes)
        words  = len(script.split())
        print(f"  Script: {words} words")

        with audio_jobs_lock:
            audio_jobs[audio_id]["phase"]  = "audio"
            audio_jobs[audio_id]["status"] = "converting_to_audio"

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()

        if OPENAI_TTS_AVAILABLE:
            print(f"  Using OpenAI TTS voice: {voice}")
            CHUNK = 4000
            chunks = [script[i:i+CHUNK] for i in range(0, len(script), CHUNK)]
            audio_bytes = b""
            for chunk in chunks:
                resp = _oai_tts.audio.speech.create(
                    model="tts-1-hd", voice=voice, input=chunk)
                audio_bytes += resp.content
            with open(tmp.name, "wb") as f:
                f.write(audio_bytes)
        elif GTTS_AVAILABLE:
            print("  Using gTTS fallback...")
            tts = gTTS(text=script, lang="en", slow=False)
            tts.save(tmp.name)
        else:
            raise RuntimeError("No TTS backend available")

        with audio_jobs_lock:
            audio_jobs[audio_id]["status"]    = "complete"
            audio_jobs[audio_id]["file_path"] = tmp.name
            q   = audio_jobs[audio_id].get("question", "")
            dur = audio_jobs[audio_id].get("length_minutes", 10)
        _persist_media(tmp.name, audio_id, "mp3", q, "lecture", "audio", dur)
        print(f"  Audio saved: {tmp.name}")

    except Exception as e:
        print(f"  Audio generation error: {e}")
        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "error"
            audio_jobs[audio_id]["error"]  = str(e)


# ── PPTX Slides ──────────────────────────────────────────

@app.route("/generate_slides", methods=["POST"])
def generate_slides_endpoint():
    if not PPTX_AVAILABLE:
        return jsonify({"error": "python-pptx not installed"}), 503

    data           = request.json or {}
    job_id         = data.get("job_id", "")
    length_minutes = int(data.get("length_minutes", 10))
    length_minutes = max(5, min(60, length_minutes))
    voice          = data.get("voice", "onyx")

    with jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.get("answer"):
        return jsonify({"error": "Job not found or no answer"}), 404

    audio_id = str(uuid.uuid4())
    with audio_jobs_lock:
        import time as _t_slides
        audio_jobs[audio_id] = {
            "status": "running", "file_path": None, "error": None, "type": "pptx",
            "question": job["question"], "length_minutes": length_minutes,
            "started_at": _t_slides.time(),
            "slides_done": 0, "slides_total": 0,
        }

    thread = threading.Thread(
        target=run_generate_slides,
        args=(audio_id, job["answer"], job["question"], length_minutes, voice),
        daemon=True,
    )
    thread.start()
    return jsonify({"audio_id": audio_id})


@app.route("/slides_download/<audio_id>")
def slides_download(audio_id: str):
    with audio_jobs_lock:
        job = audio_jobs.get(audio_id)
    if not job or job["status"] != "complete" or not job.get("file_path"):
        return jsonify({"error": "Slides not ready"}), 404
    return send_file(
        job["file_path"],
        as_attachment=True,
        download_name=f"endo_ai_slides_{audio_id[:8]}.pptx",
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@app.route("/generate_video", methods=["POST"])
def generate_video_endpoint():
    if not MOVIEPY_AVAILABLE:
        return jsonify({"error": "moviepy not installed — run: pip install moviepy"}), 503

    data           = request.json or {}
    job_id         = data.get("job_id", "")
    length_minutes = int(data.get("length_minutes", 10))
    length_minutes = max(5, min(60, length_minutes))
    voice          = data.get("voice", "onyx")

    with jobs_lock:
        job = jobs.get(job_id)
    if not job or not job.get("answer"):
        return jsonify({"error": "Job not found or no answer"}), 404

    audio_id = str(uuid.uuid4())
    import time as _t_init
    with audio_jobs_lock:
        audio_jobs[audio_id] = {
            "status": "running", "file_path": None,
            "error": None, "file_ext": "mp4", "type": "video",
            "question": job["question"], "length_minutes": length_minutes,
            "started_at": _t_init.time(),
            "slides_done": 0, "slides_total": 0,
        }

    thread = threading.Thread(
        target=run_generate_video,
        args=(audio_id, job["answer"], job["question"], length_minutes, voice),
        daemon=True,
    )
    thread.start()
    return jsonify({"audio_id": audio_id})


@app.route("/video_download/<audio_id>")
def video_download(audio_id: str):
    with audio_jobs_lock:
        job = audio_jobs.get(audio_id)
    if not job or job["status"] != "complete" or not job.get("file_path"):
        return jsonify({"error": "Video not ready"}), 404
    return send_file(
        job["file_path"],
        as_attachment=True,
        download_name=f"endo_ai_lecture_{audio_id[:8]}.mp4",
        mimetype="video/mp4",
    )


import base64 as _b64, zipfile as _zipfile, re as _re

# Tiny 1×1 transparent PNG — used as the audio-shape icon in each slide
_AUDIO_ICON_PNG = _b64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'
    '+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
)
_NS_P    = 'http://schemas.openxmlformats.org/presentationml/2006/main'
_NS_A    = 'http://schemas.openxmlformats.org/drawingml/2006/main'
_NS_R    = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_NS_REL  = 'http://schemas.openxmlformats.org/package/2006/relationships'
_NS_CT   = 'http://schemas.openxmlformats.org/package/2006/content-types'
_AUDIO_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio'
_IMAGE_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'


def _patch_slide_xml_zip(data: bytes, slide_num: int) -> bytes:
    """
    String-based injection of hidden audio shape + autoplay timing into slide XML.
    Uses p:audioFile (not p:sndAc) in p:nvPr — the only valid OOXML media element there.
    No inline namespace redeclarations (root element already declares them).
    """
    xml = data.decode('utf-8')
    shape_id  = 900 + slide_num
    rId_audio = f'rIdAudio{slide_num}'
    rId_icon  = f'rIdAIcon{slide_num}'

    # 1. Hidden audio p:pic — no inline namespace redeclarations (already at root).
    #    p:audioFile with r:link is the correct OOXML way to embed audio in a shape.
    #    cx/cy="457200" = 0.5 inch; valid non-zero EMU value.
    pic = (
        f'<p:pic>'
        f'<p:nvPicPr>'
        f'<p:cNvPr id="{shape_id}" name="Narration {slide_num}">'
        f'<a:hlinkClick r:id="" action="ppaction://media"/>'
        f'</p:cNvPr>'
        f'<p:cNvPicPr><a:picLocks noRot="1"/></p:cNvPicPr>'
        f'<p:nvPr><p:audioFile r:link="{rId_audio}"/></p:nvPr>'
        f'</p:nvPicPr>'
        f'<p:blipFill>'
        f'<a:blip r:embed="{rId_icon}"/>'
        f'<a:srcRect/>'
        f'<a:stretch><a:fillRect/></a:stretch>'
        f'</p:blipFill>'
        f'<p:spPr>'
        f'<a:xfrm><a:off x="457200" y="457200"/><a:ext cx="457200" cy="457200"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'</p:spPr>'
        f'</p:pic>'
    )
    if '</p:spTree>' in xml:
        xml = xml.replace('</p:spTree>', pic + '</p:spTree>', 1)

    # 2. Strip any existing <p:timing> block
    xml = _re.sub(r'<p:timing\b[^>]*>[\s\S]*?</p:timing>', '', xml)

    # 3. Autoplay timing — no inline namespace redeclarations.
    #    p:prevCondLst / p:nextCondLst are DIRECT children of p:seq (no p:nav wrapper —
    #    p:nav is not a valid OOXML element and causes PowerPoint to reject the file).
    timing = (
        f'<p:timing>'
        f'<p:tnLst><p:par>'
        f'<p:cTn id="1" dur="indefinite" restart="whenNotActive" nodeType="tmRoot">'
        f'<p:childTnLst><p:seq concurrent="1" nextAc="seek">'
        f'<p:cTn id="2" dur="indefinite" nodeType="mainSeq">'
        f'<p:childTnLst><p:par><p:cTn id="3" fill="hold">'
        f'<p:stCondLst><p:cond delay="0"/></p:stCondLst>'
        f'<p:childTnLst><p:par><p:cTn id="4" fill="hold">'
        f'<p:stCondLst><p:cond delay="0"/></p:stCondLst>'
        f'<p:childTnLst><p:audio>'
        f'<p:cMediaNode vol="80000" mute="0" numSld="0" showWhenStopped="0">'
        f'<p:cTn id="5" fill="hold" display="0">'
        f'<p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
        f'<p:tgtEl><p:spTgt spid="{shape_id}"/></p:tgtEl>'
        f'</p:cMediaNode></p:audio></p:childTnLst>'
        f'</p:cTn></p:par></p:childTnLst>'
        f'</p:cTn></p:par></p:childTnLst></p:cTn>'
        f'<p:prevCondLst><p:cond evt="onPrevClick" delay="0"><p:tn/></p:cond></p:prevCondLst>'
        f'<p:nextCondLst><p:cond evt="onNextClick" delay="0"><p:tn/></p:cond></p:nextCondLst>'
        f'</p:seq></p:childTnLst></p:cTn>'
        f'</p:par></p:tnLst>'
        f'<p:bldLst><p:bldP spid="{shape_id}" grpId="0" uiExpand="1" build="p"/></p:bldLst>'
        f'</p:timing>'
    )
    if '</p:sld>' in xml:
        xml = xml.replace('</p:sld>', timing + '</p:sld>', 1)

    return xml.encode('utf-8')


def _patch_slide_rels_zip(data: bytes, slide_num: int) -> bytes:
    """String-based injection of audio + icon relationships into slide rels XML."""
    xml = data.decode('utf-8')
    rId_audio = f'rIdAudio{slide_num}'
    rId_icon  = f'rIdAIcon{slide_num}'
    inserts = ''
    if rId_audio not in xml:
        inserts += (f'<Relationship Id="{rId_audio}" Type="{_AUDIO_REL}"'
                    f' Target="../media/narration_s{slide_num}.mp3"/>')
    if rId_icon not in xml:
        inserts += (f'<Relationship Id="{rId_icon}" Type="{_IMAGE_REL}"'
                    f' Target="../media/audio_icon.png"/>')
    if inserts and '</Relationships>' in xml:
        xml = xml.replace('</Relationships>', inserts + '</Relationships>', 1)
    return xml.encode('utf-8')


def _inject_audio_into_pptx(pptx_path: str, slide_audios: dict) -> str:
    """
    Rewrite a saved PPTX, injecting per-slide MP3 narration via direct ZIP surgery.
    slide_audios: {slide_num_1based: mp3_bytes}
    Returns path to the new narrated PPTX (original is untouched).
    """
    import io as _sysio

    in_data = open(pptx_path, 'rb').read()
    out_buf = _sysio.BytesIO()

    with _zipfile.ZipFile(_sysio.BytesIO(in_data), 'r') as zin:
        patched_rels: set = set()

        with _zipfile.ZipFile(out_buf, 'w', _zipfile.ZIP_DEFLATED) as zout:

            # ── Patch [Content_Types].xml (string-based, no lxml) ─
            ct_xml = zin.read('[Content_Types].xml').decode('utf-8')
            for ext, ctype in [('mp3', 'audio/mpeg'), ('png', 'image/png')]:
                if f'Extension="{ext}"' not in ct_xml:
                    ct_xml = ct_xml.replace(
                        '</Types>',
                        f'<Default Extension="{ext}" ContentType="{ctype}"/></Types>', 1)
            zout.writestr('[Content_Types].xml', ct_xml.encode('utf-8'))

            # ── Process all existing ZIP members ───────────────
            for item in zin.infolist():
                fname = item.filename
                if fname == '[Content_Types].xml':
                    continue
                data = zin.read(fname)

                m = _re.match(r'ppt/slides/slide(\d+)\.xml$', fname)
                if m:
                    snum = int(m.group(1))
                    if snum in slide_audios:
                        try:
                            data = _patch_slide_xml_zip(data, snum)
                        except Exception as ex:
                            print(f"  WARN XML patch failed slide {snum}: {ex}")

                m = _re.match(r'ppt/slides/_rels/slide(\d+)\.xml\.rels$', fname)
                if m:
                    snum = int(m.group(1))
                    if snum in slide_audios:
                        try:
                            data = _patch_slide_rels_zip(data, snum)
                            patched_rels.add(snum)
                        except Exception as ex:
                            print(f"  WARN Rels patch failed slide {snum}: {ex}")

                zout.writestr(item, data)

            # ── Create rels files for slides that had none ─────
            for snum in slide_audios:
                if snum not in patched_rels:
                    zout.writestr(
                        f'ppt/slides/_rels/slide{snum}.xml.rels',
                        (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         f'<Relationships xmlns="{_NS_REL}">'
                         f'<Relationship Id="rIdAudio{snum}" Type="{_AUDIO_REL}"'
                         f' Target="../media/narration_s{snum}.mp3"/>'
                         f'<Relationship Id="rIdAIcon{snum}" Type="{_IMAGE_REL}"'
                         f' Target="../media/audio_icon.png"/>'
                         f'</Relationships>').encode('utf-8')
                    )

            # ── Add media files ────────────────────────────────
            zout.writestr('ppt/media/audio_icon.png', _AUDIO_ICON_PNG)
            for snum, mp3_bytes in slide_audios.items():
                zout.writestr(f'ppt/media/narration_s{snum}.mp3', mp3_bytes)

    out_path = pptx_path[:-5] + '_narrated.pptx'
    with open(out_path, 'wb') as f:
        f.write(out_buf.getvalue())
    return out_path


# ── PLACEHOLDER (replaced by ZIP injection below) ─────────
def _embed_slide_audio(slide, prs, mp3_bytes: bytes, slide_num: int) -> bool:
    """
    Embed MP3 narration into a slide with autoplay on slide entry.
    Uses a 1×1 invisible sp shape with sndAc + OOXML timing animation.
    Returns True on success.
    """
    try:
        from pptx.opc.part import Part
        from pptx.opc.packuri import PackURI
        from lxml import etree

        AUDIO_REL = ('http://schemas.openxmlformats.org/'
                     'officeDocument/2006/relationships/audio')
        NS_P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
        NS_A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
        NS_R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

        shape_id = 900 + slide_num  # high id, no collision with content shapes

        # 1. Register audio part with the slide
        audio_part = Part(
            PackURI(f'/ppt/media/narration_s{slide_num}.mp3'),
            'audio/mpeg',
            mp3_bytes,
            prs.part.package,
        )
        rId = slide.part.relate_to(audio_part, AUDIO_REL)

        # 2. Invisible 1×1 EMU shape carrying the audio reference
        sp_xml = (
            f'<p:sp xmlns:p="{NS_P}" xmlns:a="{NS_A}" xmlns:r="{NS_R}">'
            f'<p:nvSpPr>'
            f'<p:cNvPr id="{shape_id}" name="Narration {slide_num}"/>'
            f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>'
            f'<p:nvPr>'
            f'<p:sndAc><p:stSnd>'
            f'<p:snd r:embed="{rId}" name="narration{slide_num}.mp3"/>'
            f'</p:stSnd></p:sndAc>'
            f'</p:nvPr>'
            f'</p:nvSpPr>'
            f'<p:spPr>'
            f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="1" cy="1"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f'<a:noFill/>'
            f'</p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>'
            f'</p:sp>'
        )
        slide.shapes._spTree.append(etree.fromstring(sp_xml))

        # 3. Autoplay timing — triggers audio at delay=0 (slide entry, no click needed)
        timing_xml = (
            f'<p:timing xmlns:p="{NS_P}" xmlns:a="{NS_A}">'
            f'<p:tnLst><p:par>'
            f'<p:cTn id="1" dur="indefinite" restart="whenNotActive" nodeType="tmRoot">'
            f'<p:childTnLst><p:seq concurrent="1" nextAc="seek">'
            f'<p:cTn id="2" dur="indefinite" nodeType="mainSeq">'
            f'<p:childTnLst><p:par>'
            f'<p:cTn id="3" fill="hold">'
            f'<p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            f'<p:childTnLst><p:par>'
            f'<p:cTn id="4" fill="hold">'
            f'<p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            f'<p:childTnLst><p:audio>'
            f'<p:cMediaNode vol="80000" mute="0" numSld="0" showWhenStopped="0">'
            f'<p:cTn id="5" fill="hold" display="0">'
            f'<p:stCondLst><p:cond delay="0"/></p:stCondLst>'
            f'</p:cTn>'
            f'<p:tgtEl><p:spTgt spid="{shape_id}"/></p:tgtEl>'
            f'</p:cMediaNode>'
            f'</p:audio></p:childTnLst>'
            f'</p:cTn>'
            f'</p:par></p:childTnLst>'
            f'</p:cTn>'
            f'</p:par></p:childTnLst>'
            f'</p:cTn>'
            f'<p:nav>'
            f'<p:prevCondLst><p:cond evt="onPrevClick" delay="0"><p:tn/></p:cond></p:prevCondLst>'
            f'<p:nextCondLst><p:cond evt="onNextClick" delay="0"><p:tn/></p:cond></p:nextCondLst>'
            f'</p:nav>'
            f'</p:seq></p:childTnLst>'
            f'</p:cTn>'
            f'</p:par></p:tnLst>'
            f'<p:bldLst>'
            f'<p:bldP spid="{shape_id}" grpId="0" uiExpand="1" build="p"/>'
            f'</p:bldLst>'
            f'</p:timing>'
        )
        slide._element.append(etree.fromstring(timing_xml))
        return True

    except Exception as exc:
        print(f"    WARN  Audio embed failed (slide {slide_num}): {exc}")
        return False


# ── Slide image renderer (Pillow) ────────────────────────

def _draw_wrapped_text(draw, text: str, x: int, y: int, max_w: int,
                       font, color, align: str = 'left') -> int:
    """Word-wrap text into max_w pixels. Returns new y after last line."""
    if not text:
        return y
    words = text.split()
    lines, cur = [], ''
    for w in words:
        test = (cur + ' ' + w).strip()
        try:
            tw = draw.textlength(test, font=font)
        except Exception:
            tw = len(test) * 12  # fallback
        if tw > max_w and cur:
            lines.append(cur); cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    try:
        lh = draw.textbbox((0, 0), 'Ag', font=font)[3] + 8
    except Exception:
        lh = 28
    for line in lines:
        if align == 'center':
            try:
                lw = draw.textlength(line, font=font)
            except Exception:
                lw = len(line) * 12
            draw.text((x - int(lw) // 2, y), line, fill=color, font=font)
        else:
            draw.text((x, y), line, fill=color, font=font)
        y += lh
    return y


# ── Three palettes; one is picked at random per generation ───
# Keys are stored as (R, G, B) tuples; the picker copies them into both
# _BRAND_RGB (Pillow video) and _BRAND (PPTX RGBColor) at the start of each job.
_PALETTES = {
    "warm_clinical": {
        "name":       "Warm Clinical",
        "bg":         (0x0F, 0x2A, 0x3F),  # deep navy
        "bg_dark":    (0x0A, 0x1F, 0x2F),  # deeper navy
        "card":       (0xF4, 0xF1, 0xEC),  # warm cream
        "card_text":  (0x1F, 0x29, 0x37),  # charcoal
        "card_alt":   (0xE5, 0xE0, 0xD7),
        "accent":     (0xC9, 0x95, 0x6B),  # muted copper
        "accent2":    (0xE1, 0xC6, 0x99),  # soft gold
        "teal":       (0x4A, 0x6F, 0xA5),  # slate blue (secondary)
        "white":      (0xFF, 0xFF, 0xFF),
        "muted":      (0xB8, 0xC4, 0xD0),  # pale steel
        "subtle":     (0x6B, 0x72, 0x80),
        "header_alt": (0xE5, 0xE0, 0xD7),
    },
    "cool_corporate": {
        "name":       "Cool Corporate",
        "bg":         (0x1F, 0x29, 0x37),  # charcoal slate
        "bg_dark":    (0x11, 0x18, 0x27),
        "card":       (0xF2, 0xEF, 0xE9),  # cool cream
        "card_text":  (0x1F, 0x29, 0x37),
        "card_alt":   (0xE3, 0xDF, 0xD7),
        "accent":     (0x5C, 0x7A, 0xEA),  # muted indigo
        "accent2":    (0xE0, 0xB8, 0x72),  # warm amber
        "teal":       (0x4F, 0x86, 0xC6),  # steel blue
        "white":      (0xFF, 0xFF, 0xFF),
        "muted":      (0xC7, 0xD2, 0xE0),
        "subtle":     (0x6B, 0x72, 0x80),
        "header_alt": (0xE3, 0xDF, 0xD7),
    },
    "teal_rose": {
        "name":       "Deep Teal & Dusty Rose",
        "bg":         (0x0E, 0x3B, 0x43),  # deep teal
        "bg_dark":    (0x08, 0x2B, 0x30),
        "card":       (0xF7, 0xF4, 0xED),  # paper
        "card_text":  (0x1F, 0x29, 0x37),
        "card_alt":   (0xE6, 0xE0, 0xD3),
        "accent":     (0xC2, 0x82, 0x85),  # dusty rose
        "accent2":    (0xD4, 0xB8, 0x96),  # champagne
        "teal":       (0x2A, 0x6F, 0x77),  # mid teal
        "white":      (0xFF, 0xFF, 0xFF),
        "muted":      (0xC0, 0xD6, 0xD8),
        "subtle":     (0x6B, 0x72, 0x80),
        "header_alt": (0xE6, 0xE0, 0xD3),
    },
}

# Default palette (overridden per-job by _apply_random_palette)
_BRAND_RGB = dict(_PALETTES["warm_clinical"])
_BADGE_RGB = {
    "green": (0x10, 0xB9, 0x81), "amber": (0xF5, 0x9E, 0x0B),
    "red":   (0xEF, 0x44, 0x44), "teal":  (0x0E, 0x8C, 0x8B),
    "coral": (0xE7, 0x6F, 0x51), "gold":  (0xE9, 0xC4, 0x6A),
}


def _load_fonts():
    """Returns dict of font sizes -> ImageFont."""
    from PIL import ImageFont
    import os as _os
    sizes = {"xxl": 96, "xl": 64, "lg": 44, "md": 28, "sm": 20, "xs": 16, "xxs": 13}
    families = {"reg": "segoeui.ttf", "bold": "segoeuib.ttf"}
    fonts = {}
    for kind, fam in families.items():
        path = f"C:/Windows/Fonts/{fam}"
        if not _os.path.exists(path):
            path = "C:/Windows/Fonts/arial.ttf"
        for tag, sz in sizes.items():
            try:
                fonts[f"{kind}_{tag}"] = ImageFont.truetype(path, sz)
            except Exception:
                fonts[f"{kind}_{tag}"] = ImageFont.load_default()
    return fonts


def _wrap_lines(draw, text, max_w, font):
    if not text:
        return []
    words = str(text).split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        try:    tw = draw.textlength(test, font=font)
        except: tw = len(test) * 12
        if tw > max_w and cur:
            lines.append(cur); cur = w
        else:
            cur = test
    if cur: lines.append(cur)
    return lines


def _draw_text(draw, text, box, font, color, *, align="left", anchor="top",
               line_gap=6, max_lines=None):
    """Draw word-wrapped text inside box=(x,y,w,h). Returns y after last line."""
    x, y, w, h = box
    lines = _wrap_lines(draw, text, w, font)
    if max_lines:
        lines = lines[:max_lines]
    try:
        lh = draw.textbbox((0, 0), "Ag", font=font)[3] + line_gap
    except Exception:
        lh = 28
    total_h = lh * len(lines)
    if anchor == "middle":
        cy = y + (h - total_h) // 2
    elif anchor == "bottom":
        cy = y + h - total_h
    else:
        cy = y
    for line in lines:
        try:
            lw = draw.textlength(line, font=font)
        except Exception:
            lw = len(line) * 12
        if align == "center":
            lx = x + (w - int(lw)) // 2
        elif align == "right":
            lx = x + w - int(lw)
        else:
            lx = x
        draw.text((lx, cy), line, fill=color, font=font)
        cy += lh
    return cy


def _rrect(draw, box, radius, fill):
    """Rounded rectangle. box=(x0,y0,x1,y1)"""
    try:
        draw.rounded_rectangle(box, radius=radius, fill=fill)
    except Exception:
        draw.rectangle(box, fill=fill)


def _draw_chrome(draw, F, eyebrow, slide_num, total, footer, W, H):
    # Top accent bar
    draw.rectangle([0, 0, W, 12], fill=_BRAND_RGB["accent"])
    if eyebrow:
        _draw_text(draw, eyebrow, (60, 36, W - 120, 32),
                   F["bold_xs"], _BRAND_RGB["accent2"])
    # Footer band
    if footer:
        _draw_text(draw, footer[:80], (60, H - 38, int(W * 0.7), 28),
                   F["bold_xxs"], _BRAND_RGB["muted"])
    if slide_num and total:
        _draw_text(draw, f"{slide_num} / {total}",
                   (W - 220, H - 38, 160, 28),
                   F["bold_xxs"], _BRAND_RGB["muted"], align="right")


def _render_title_img(draw, F, data, deck_meta, length_minutes, W, H):
    # Coral top band
    draw.rectangle([0, 0, W, 56], fill=_BRAND_RGB["accent"])
    _draw_text(draw, data.get("eyebrow", "CLINICAL EDUCATION"),
               (80, 130, W - 160, 36), F["bold_xs"], _BRAND_RGB["muted"])
    title = data.get("title") or deck_meta.get("title", "")
    _draw_text(draw, title, (80, 200, W - 160, 320),
               F["bold_xxl"], _BRAND_RGB["white"], line_gap=10)
    subtitle = data.get("subtitle") or deck_meta.get(
        "subtitle", f"{length_minutes}-Minute Clinical Lecture")
    _draw_text(draw, subtitle, (80, 540, W - 160, 80),
               F["reg_md"], _BRAND_RGB["muted"])
    stats = (data.get("stats") or [])[:3]
    if stats:
        n = len(stats)
        gap = 24
        card_w = (W - 160 - gap * (n - 1)) // n
        x = 80; y = 720; h = 220
        for s in stats:
            _rrect(draw, (x, y, x + card_w, y + h), 18, _BRAND_RGB["bg_dark"])
            _draw_text(draw, s.get("value", ""),
                       (x + 24, y + 30, card_w - 48, 80),
                       F["bold_xl"], _BRAND_RGB["accent2"], align="center")
            _draw_text(draw, s.get("label", ""),
                       (x + 24, y + 130, card_w - 48, 80),
                       F["reg_xs"], _BRAND_RGB["muted"], align="center")
            x += card_w + gap


def _render_stat_cards_img(draw, F, data, W, H):
    _draw_text(draw, data.get("title", ""), (80, 130, W - 160, 80),
               F["bold_lg"], _BRAND_RGB["white"])
    cards = (data.get("cards") or [])[:3]
    if not cards: return
    n = len(cards); gap = 28
    card_w = (W - 160 - gap * (n - 1)) // n
    y = 280; h = 580
    x = 80
    for c in cards:
        _rrect(draw, (x, y, x + card_w, y + h), 24, _BRAND_RGB["card"])
        # Top accent strip
        _rrect(draw, (x, y, x + card_w, y + 28), 0, _BRAND_RGB["accent"])
        _draw_text(draw, c.get("value", ""),
                   (x + 24, y + 90, card_w - 48, 200),
                   F["bold_xxl"], _BRAND_RGB["accent"], align="center")
        _draw_text(draw, c.get("label", ""),
                   (x + 32, y + 320, card_w - 64, h - 360),
                   F["reg_md"], _BRAND_RGB["card_text"], align="center")
        x += card_w + gap


def _render_type_cards_img(draw, F, data, W, H):
    _draw_text(draw, data.get("title", ""), (80, 130, W - 160, 80),
               F["bold_lg"], _BRAND_RGB["white"])
    cards = (data.get("cards") or [])[:4]
    if not cards: return
    n = len(cards); gap = 22
    card_w = (W - 160 - gap * (n - 1)) // n
    y = 240; h = 700
    x = 80
    for c in cards:
        _rrect(draw, (x, y, x + card_w, y + h), 22, _BRAND_RGB["card"])
        # Label strip
        _rrect(draw, (x, y, x + card_w, y + 80), 0, _BRAND_RGB["teal"])
        _draw_text(draw, c.get("label", ""),
                   (x, y + 22, card_w, 40), F["bold_md"],
                   _BRAND_RGB["white"], align="center")
        _draw_text(draw, c.get("heading", ""),
                   (x + 28, y + 110, card_w - 56, 110),
                   F["bold_md"], _BRAND_RGB["card_text"])
        _draw_text(draw, c.get("body", ""),
                   (x + 28, y + 230, card_w - 56, h - 340),
                   F["reg_xs"], _BRAND_RGB["card_text"], line_gap=4)
        badge = c.get("badge")
        if badge:
            bcol = _BADGE_RGB.get((c.get("badge_color") or "teal").lower(),
                                  _BRAND_RGB["teal"])
            bx0, by0 = x + 28, y + h - 70
            bx1, by1 = x + card_w - 28, y + h - 24
            _rrect(draw, (bx0, by0, bx1, by1), 14, bcol)
            _draw_text(draw, badge, (bx0, by0 + 8, bx1 - bx0, 32),
                       F["bold_xxs"], _BRAND_RGB["white"], align="center")
        x += card_w + gap


def _render_numbered_grid_img(draw, F, data, W, H):
    _draw_text(draw, data.get("title", ""), (80, 130, W - 160, 80),
               F["bold_lg"], _BRAND_RGB["white"])
    items = data.get("items") or []
    if not items: return
    cols = 3 if len(items) >= 5 else 2
    rows = (len(items) + cols - 1) // cols
    gap = 22
    card_w = (W - 160 - gap * (cols - 1)) // cols
    card_h = (760 - gap * (rows - 1)) // rows
    x0 = 80; y0 = 240
    for idx, it in enumerate(items[:cols * rows]):
        r, c = divmod(idx, cols)
        x = x0 + (card_w + gap) * c
        y = y0 + (card_h + gap) * r
        _rrect(draw, (x, y, x + card_w, y + card_h), 22, _BRAND_RGB["card"])
        # Number circle
        cx = x + 56; cy = y + 56; rad = 38
        draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                     fill=_BRAND_RGB["accent"])
        _draw_text(draw, str(it.get("n", idx + 1)),
                   (cx - rad, cy - 22, rad * 2, 44),
                   F["bold_md"], _BRAND_RGB["white"], align="center")
        _draw_text(draw, it.get("heading", ""),
                   (x + 120, y + 26, card_w - 140, 70),
                   F["bold_md"], _BRAND_RGB["card_text"])
        _draw_text(draw, it.get("body", ""),
                   (x + 28, y + 130, card_w - 56, card_h - 150),
                   F["reg_xs"], _BRAND_RGB["subtle"], line_gap=4)


def _render_chart_bar_img(draw, F, data, W, H):
    _draw_text(draw, data.get("title", ""), (80, 130, W - 160, 80),
               F["bold_lg"], _BRAND_RGB["white"])
    cats = data.get("categories") or []
    vals = data.get("values") or []
    unit = data.get("unit", "")
    if not cats or not vals: return
    n = min(len(cats), len(vals))
    cats = cats[:n]; vals = [float(v) for v in vals[:n]]
    vmax = max(vals) if vals else 1
    vmax = max(vmax, 1)
    # Plot area
    px, py, pw, ph = 320, 260, W - 380, 660
    # Frame line
    draw.line([(px, py), (px, py + ph)], fill=_BRAND_RGB["muted"], width=2)
    draw.line([(px, py + ph), (px + pw, py + ph)], fill=_BRAND_RGB["muted"], width=2)
    # Bars
    row_h = ph // n
    bar_h = int(row_h * 0.55)
    bar_pad = (row_h - bar_h) // 2
    for i, (cat, v) in enumerate(zip(cats, vals)):
        y = py + i * row_h + bar_pad
        bw = int((v / vmax) * (pw - 80))
        _rrect(draw, (px + 2, y, px + 2 + bw, y + bar_h), 8, _BRAND_RGB["accent"])
        # Category label (left of axis)
        _draw_text(draw, str(cat), (60, y + bar_h // 2 - 16, 240, 40),
                   F["reg_xs"], _BRAND_RGB["white"], align="right")
        # Value at bar end
        _draw_text(draw, f"{v:g}{unit}",
                   (px + 2 + bw + 14, y + bar_h // 2 - 16, 200, 40),
                   F["bold_xs"], _BRAND_RGB["accent2"])


def _render_comparison_table_img(draw, F, data, W, H):
    _draw_text(draw, data.get("title", ""), (80, 130, W - 160, 80),
               F["bold_lg"], _BRAND_RGB["white"])
    headers = data.get("headers") or []
    rows = data.get("rows") or []
    if not headers or not rows: return
    ncols = len(headers)
    table_x = 80; table_y = 260
    table_w = W - 160; table_h = 680
    nrows = len(rows) + 1
    col_w = table_w // ncols
    row_h = table_h // nrows
    # Header row
    _rrect(draw, (table_x, table_y, table_x + table_w, table_y + row_h),
           14, _BRAND_RGB["accent"])
    for c, h in enumerate(headers):
        cx = table_x + c * col_w
        _draw_text(draw, str(h),
                   (cx + 16, table_y + 18, col_w - 32, row_h - 36),
                   F["bold_sm"], _BRAND_RGB["white"], align="center")
    # Body rows
    for r, row in enumerate(rows, start=1):
        y = table_y + r * row_h
        bg = _BRAND_RGB["card"] if r % 2 == 1 else _BRAND_RGB["card_alt"]
        rad = 14 if r == nrows - 1 else 0
        # Use plain rectangle for middle rows; rounded only for last row's bottom
        if r == nrows - 1:
            _rrect(draw, (table_x, y, table_x + table_w, y + row_h), 14, bg)
            # Repaint the top so it's flat (only round bottom corners)
            draw.rectangle([table_x, y, table_x + table_w, y + 14], fill=bg)
        else:
            draw.rectangle([table_x, y, table_x + table_w, y + row_h], fill=bg)
        for c in range(ncols):
            cx = table_x + c * col_w
            cell = str(row[c]) if c < len(row) else ""
            font = F["bold_sm"] if c == 0 else F["reg_sm"]
            _draw_text(draw, cell, (cx + 16, y + 14, col_w - 32, row_h - 28),
                       font, _BRAND_RGB["card_text"])


def _render_bullets_img(draw, F, data, W, H):
    _draw_text(draw, data.get("title", ""), (80, 130, W - 160, 80),
               F["bold_lg"], _BRAND_RGB["white"])
    bullets = data.get("bullets") or []
    if not bullets: return
    y = 260
    for b in bullets[:7]:
        # Coral square bullet
        draw.rectangle([80, y + 14, 104, y + 38], fill=_BRAND_RGB["accent"])
        y_after = _draw_text(draw, b, (130, y, W - 220, 100),
                             F["reg_md"], _BRAND_RGB["white"])
        y = max(y_after, y + 64)
        if y > H - 120:
            break


def _render_summary_img(draw, F, data, W, H):
    # Inset card
    _rrect(draw, (60, 110, W - 60, H - 70), 28, _BRAND_RGB["bg_dark"])
    _draw_text(draw, data.get("eyebrow", "KEY TAKEAWAYS"),
               (110, 150, W - 220, 32), F["bold_xs"], _BRAND_RGB["accent2"])
    _draw_text(draw, data.get("title", "Clinical Pearls"),
               (110, 200, W - 220, 100), F["bold_lg"], _BRAND_RGB["white"])
    bullets = data.get("bullets") or []
    y = 340
    for i, b in enumerate(bullets[:6], start=1):
        # Coral chip
        cx = 140; cy = y + 26
        draw.ellipse([cx - 26, cy - 26, cx + 26, cy + 26],
                     fill=_BRAND_RGB["accent"])
        _draw_text(draw, str(i), (cx - 26, cy - 22, 52, 44),
                   F["bold_md"], _BRAND_RGB["white"], align="center")
        _draw_text(draw, b, (200, y, W - 280, 80),
                   F["reg_md"], _BRAND_RGB["white"])
        y += 90
        if y > H - 110: break


def _render_references_img(draw, F, data, W, H):
    _draw_text(draw, data.get("title", "References"),
               (80, 130, W - 160, 80), F["bold_lg"], _BRAND_RGB["white"])
    items = data.get("items") or data.get("bullets") or []
    if not items: return
    y = 260
    for i, item in enumerate(items[:10], start=1):
        _draw_text(draw, f"{i}.", (90, y, 60, 32), F["bold_xs"],
                   _BRAND_RGB["accent2"])
        y_after = _draw_text(draw, str(item), (150, y, W - 240, 90),
                             F["reg_xs"], _BRAND_RGB["muted"], line_gap=2)
        y = max(y_after, y + 50)
        if y > H - 110: break


_IMG_RENDERERS = {
    "stat_cards":       _render_stat_cards_img,
    "type_cards":       _render_type_cards_img,
    "numbered_grid":    _render_numbered_grid_img,
    "chart_bar":        _render_chart_bar_img,
    "comparison_table": _render_comparison_table_img,
    "bullets":          _render_bullets_img,
    "summary":          _render_summary_img,
    "references":       _render_references_img,
}


def _render_slide_image(slide_data: dict, slide_num: int, total_slides: int,
                         deck_title: str, length_minutes: int,
                         deck_meta: dict = None) -> bytes:
    """Render one slide as a 1920x1080 PNG using Pillow with the brand layouts."""
    import io as _io2
    from PIL import Image, ImageDraw

    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), color=_BRAND_RGB["bg"])
    draw = ImageDraw.Draw(img)
    F = _load_fonts()

    deck_meta = deck_meta or {"title": deck_title}
    stype = (slide_data.get("type") or slide_data.get("slide_type")
             or ("title" if slide_num == 1 else "bullets")).lower()
    footer = (deck_meta.get("footer") or deck_title or "").upper()[:80]

    try:
        if stype == "title" or slide_num == 1:
            _render_title_img(draw, F, slide_data, deck_meta, length_minutes, W, H)
        else:
            renderer = _IMG_RENDERERS.get(stype, _render_bullets_img)
            renderer(draw, F, slide_data, W, H)
            _draw_chrome(draw, F, slide_data.get("eyebrow", ""),
                         slide_num, total_slides, footer, W, H)
    except Exception as e:
        # Fallback: title-only slide so the video isn't blank
        import traceback; traceback.print_exc()
        print(f"  [video] slide {slide_num} render error ({stype}): {e}")
        _draw_text(draw, slide_data.get("title", ""),
                   (80, 80, W - 160, 200), F["bold_lg"], _BRAND_RGB["white"])

    buf = _io2.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Narrated video generation ─────────────────────────────

def run_generate_video(audio_id: str, answer: str, question: str,
                       length_minutes: int, voice: str = "onyx"):
    """Generate a narrated MP4 video: Pillow slide images + OpenAI TTS audio."""
    import os as _os3, tempfile as _tmp3
    try:
        from endo_ai import generate_slides_content

        _apply_random_palette()
        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "generating_content"

        print(f"  [video] Generating {length_minutes}-min slide content...")
        deck = generate_slides_content(answer, question, length_minutes)
        slides     = deck.get("slides", [])
        deck_title = deck.get("title", question)
        total      = len(slides)

        if not slides:
            # Both attempts in generate_slides_content failed. The detailed
            # parse-failure reason was already printed there (look for
            # "[slides] first/retry attempt produced 0 slides"). Surface a
            # user-facing message that points to the most likely cause.
            raise ValueError(
                "Slide generator returned 0 slides after retry. "
                "Most common cause: the JSON exceeded max_tokens and got truncated — "
                "try a shorter length (e.g. 5 min instead of 15 min) or simplify the topic. "
                "Check server log for the parse-failure reason."
            )

        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "building_slides"
            audio_jobs[audio_id]["slides_total"] = total
            audio_jobs[audio_id]["slides_done"]  = 0

        tmpdir = _tmp3.mkdtemp(prefix="endo_vid_")
        img_paths   = [None] * total
        audio_paths = [None] * total

        # ── 1. Render slide images sequentially (Pillow is fast) ──
        for i, slide_data in enumerate(slides):
            slide_num = i + 1
            with audio_jobs_lock:
                if audio_jobs[audio_id].get("cancelled"):
                    print("  [video] Cancelled"); return
            img_bytes = _render_slide_image(slide_data, slide_num, total,
                                            deck_title, length_minutes, deck)
            ip = _os3.path.join(tmpdir, f"slide_{slide_num:03d}.png")
            with open(ip, 'wb') as f: f.write(img_bytes)
            img_paths[i] = ip

        # ── 2. Generate TTS in parallel (OpenAI handles concurrent reqs fine) ──
        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "generating_audio"

        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading as _th

        done_lock = _th.Lock()
        done_count = [0]

        def _tts_one(idx, slide_data):
            slide_num = idx + 1
            notes = (slide_data.get("speaker_notes") or "").strip()
            if not notes:
                return idx, None
            ap = _os3.path.join(tmpdir, f"audio_{slide_num:03d}.mp3")
            # Try OpenAI first
            if OPENAI_TTS_AVAILABLE:
                try:
                    resp = _oai_tts.audio.speech.create(
                        model="tts-1", voice=voice, input=notes[:4096])
                    with open(ap, 'wb') as f: f.write(resp.content)
                    return idx, ap
                except Exception as tts_err:
                    print(f"    [video] slide {slide_num} OpenAI TTS error: {tts_err}")
            # gTTS fallback
            if GTTS_AVAILABLE:
                try:
                    from gtts import gTTS as _gTTS
                    _gTTS(text=notes[:4096], lang='en', slow=False).save(ap)
                    return idx, ap
                except Exception as gtts_err:
                    print(f"    [video] slide {slide_num} gTTS error: {gtts_err}")
            return idx, None

        # OpenAI TTS comfortably handles 6 parallel reqs on default tier.
        # gTTS uses Google's free endpoint -- keep concurrency lower if it kicks in.
        max_workers = 6 if OPENAI_TTS_AVAILABLE else 3
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_tts_one, i, sd) for i, sd in enumerate(slides)]
            for fut in as_completed(futures):
                with audio_jobs_lock:
                    if audio_jobs[audio_id].get("cancelled"):
                        print("  [video] Cancelled mid-TTS"); return
                try:
                    idx, ap = fut.result()
                    audio_paths[idx] = ap
                    if ap:
                        print(f"    [video] slide {idx+1}/{total} TTS OK")
                except Exception as e:
                    print(f"    [video] TTS task failed: {e}")
                with done_lock:
                    done_count[0] += 1
                    with audio_jobs_lock:
                        audio_jobs[audio_id]["slides_done"] = done_count[0]

        # ── Assemble video with moviepy ───────────────────
        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "injecting_audio"

        print("  [video] Assembling video clips with native ffmpeg...")
        out_path = _os3.path.join(tmpdir, f"narrated_{audio_id[:8]}.mp4")

        if _native_ffmpeg:
            # ── Direct ffmpeg path: bypass moviepy entirely ──
            # For each (image, audio) pair, encode a per-slide MP4 (~1-3s/slide
            # for stillimages). Then concat losslessly with -c copy (instant).
            import subprocess as _sp, time as _t
            t0 = _t.time()
            slide_clips = []
            for i, (ip, ap) in enumerate(zip(img_paths, audio_paths)):
                clip_out = _os3.path.join(tmpdir, f"clip_{i+1:03d}.mp4")
                if ap and _os3.path.exists(ap):
                    cmd = [
                        _native_ffmpeg, "-y", "-loglevel", "error",
                        "-loop", "1", "-i", ip,
                        "-i", ap,
                        "-c:v", "libx264", "-tune", "stillimage",
                        "-preset", "ultrafast", "-crf", "23",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k",
                        "-shortest",
                        "-r", "12",
                        clip_out,
                    ]
                else:
                    # Silent 4-second slide
                    cmd = [
                        _native_ffmpeg, "-y", "-loglevel", "error",
                        "-loop", "1", "-i", ip,
                        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                        "-t", "4",
                        "-c:v", "libx264", "-tune", "stillimage",
                        "-preset", "ultrafast", "-crf", "23",
                        "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k",
                        "-r", "12",
                        clip_out,
                    ]
                _sp.run(cmd, check=True, capture_output=True)
                slide_clips.append(clip_out)

            # Concat all slide clips losslessly
            list_path = _os3.path.join(tmpdir, "concat_list.txt")
            with open(list_path, "w", encoding="utf-8") as f:
                for c in slide_clips:
                    f.write(f"file '{c.replace(chr(92), '/')}'\n")
            concat_cmd = [
                _native_ffmpeg, "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                out_path,
            ]
            _sp.run(concat_cmd, check=True, capture_output=True)
            print(f"  [video] OK MP4 saved in {_t.time()-t0:.1f}s: {out_path}")

        else:
            # ── Moviepy fallback (slow on Windows; only if ffmpeg missing) ──
            print("  [video] Native ffmpeg not found, falling back to moviepy...")
            clips = []
            for ip, ap in zip(img_paths, audio_paths):
                if ap and _os3.path.exists(ap):
                    ac   = AudioFileClip(ap)
                    dur  = ac.duration
                    clip = ImageClip(ip, duration=dur).with_audio(ac)
                else:
                    clip = ImageClip(ip, duration=4)
                clips.append(clip)
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(out_path, fps=12, codec='libx264',
                                  audio_codec='aac', logger=None,
                                  ffmpeg_params=['-preset', 'ultrafast',
                                                 '-tune', 'stillimage',
                                                 '-crf', '23', '-pix_fmt', 'yuv420p'],
                                  threads=0)
            for c in clips: c.close()
            final.close()
            print(f"  [video] OK MP4 saved: {out_path}")

        with audio_jobs_lock:
            audio_jobs[audio_id]["status"]    = "complete"
            audio_jobs[audio_id]["file_path"] = out_path
            audio_jobs[audio_id]["file_ext"]  = "mp4"
            q   = audio_jobs[audio_id].get("question", "")
            dur = audio_jobs[audio_id].get("length_minutes", 10)
        _persist_media(out_path, audio_id, "mp4", q, "video", "video", dur)

    except Exception as e:
        import traceback; traceback.print_exc()
        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "error"
            audio_jobs[audio_id]["error"]  = str(e)


# ── PPTX brand palette (mirrors _BRAND_RGB; overwritten per job) ─
def _palette_to_pptx(p):
    """Convert a palette tuple-dict into RGBColor objects for PPTX."""
    keys = ("bg","bg_dark","card","card_text","accent","accent2",
            "teal","white","muted","subtle")
    return {k: RGBColor(*p[k]) for k in keys}

_BRAND = _palette_to_pptx(_PALETTES["warm_clinical"])


def _apply_random_palette():
    """Pick one of the three palettes at random and update both
    _BRAND_RGB (Pillow video) and _BRAND (PPTX) in place. Renderers
    read these module-level dicts so they pick up the new colors."""
    import random as _random_pal
    name = _random_pal.choice(list(_PALETTES.keys()))
    p    = _PALETTES[name]
    _BRAND_RGB.clear(); _BRAND_RGB.update(p)
    new_pptx = _palette_to_pptx(p)
    _BRAND.clear(); _BRAND.update(new_pptx)
    print(f"  [palette] {p['name']}")
    return name

_BADGE_COLORS = {
    "green":   RGBColor(0x10, 0xB9, 0x81),
    "amber":   RGBColor(0xF5, 0x9E, 0x0B),
    "red":     RGBColor(0xEF, 0x44, 0x44),
    "teal":    RGBColor(0x0E, 0x8C, 0x8B),
    "coral":   RGBColor(0xE7, 0x6F, 0x51),
    "gold":    RGBColor(0xE9, 0xC4, 0x6A),
}


def _set_solid(shape, rgb):
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb
    shape.line.fill.background()


def _add_rect(slide, x, y, w, h, rgb, rounded=True):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE,
        x, y, w, h)
    if rounded:
        try:
            shp.adjustments[0] = 0.10
        except Exception:
            pass
    _set_solid(shp, rgb)
    return shp


def _add_text(slide, x, y, w, h, text, *, size=14, bold=False,
              color=None, align="left", anchor="top"):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.02)
    tf.vertical_anchor = {
        "top": MSO_ANCHOR.TOP, "middle": MSO_ANCHOR.MIDDLE, "bottom": MSO_ANCHOR.BOTTOM
    }.get(anchor, MSO_ANCHOR.TOP)
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER,
                   "right": PP_ALIGN.RIGHT}.get(align, PP_ALIGN.LEFT)
    run = p.add_run()
    run.text = str(text or "")
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    return tb


def _slide_bg(slide, rgb):
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.rgb = rgb


def _add_chrome(slide, eyebrow, slide_num, total, footer):
    # Top accent bar
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.33), Inches(0.08))
    _set_solid(bar, _BRAND["accent"])
    # Eyebrow
    if eyebrow:
        _add_text(slide, Inches(0.5), Inches(0.25), Inches(10), Inches(0.4),
                  eyebrow, size=11, bold=True, color=_BRAND["accent2"])
    # Footer
    if footer:
        _add_text(slide, Inches(0.5), Inches(7.05), Inches(10), Inches(0.4),
                  footer, size=9, bold=True, color=_BRAND["muted"])
    # Page number
    if slide_num and total:
        _add_text(slide, Inches(11.5), Inches(7.05), Inches(1.4), Inches(0.4),
                  f"{slide_num} / {total}", size=10, bold=True,
                  color=_BRAND["muted"], align="right")


def _render_title(slide, data, deck, length_minutes):
    _slide_bg(slide, _BRAND["bg"])
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.33), Inches(0.5))
    _set_solid(bar, _BRAND["accent"])
    _add_text(slide, Inches(0.6), Inches(0.7), Inches(12), Inches(0.45),
              data.get("eyebrow", "CLINICAL EDUCATION"),
              size=12, bold=True, color=_BRAND["muted"])
    _add_text(slide, Inches(0.6), Inches(1.3), Inches(12), Inches(2.2),
              data.get("title") or deck.get("title", ""),
              size=54, bold=True, color=_BRAND["white"])
    _add_text(slide, Inches(0.6), Inches(3.5), Inches(12), Inches(1.2),
              data.get("subtitle") or deck.get("subtitle", f"{length_minutes}-Minute Clinical Lecture"),
              size=22, color=_BRAND["muted"])
    # Stat strip across bottom
    stats = data.get("stats") or []
    if stats:
        x = Inches(0.6); top = Inches(5.2); card_w = Inches(4.0); card_h = Inches(1.4)
        gap = Inches(0.15)
        for s in stats[:3]:
            _add_rect(slide, x, top, card_w, card_h, _BRAND["bg_dark"])
            _add_text(slide, x + Inches(0.2), top + Inches(0.15),
                      card_w - Inches(0.4), Inches(0.6),
                      s.get("value", ""), size=28, bold=True, color=_BRAND["accent2"])
            _add_text(slide, x + Inches(0.2), top + Inches(0.75),
                      card_w - Inches(0.4), Inches(0.55),
                      s.get("label", ""), size=11, color=_BRAND["muted"])
            x += card_w + gap


def _render_stat_cards(slide, data):
    _slide_bg(slide, _BRAND["bg"])
    _add_text(slide, Inches(0.6), Inches(0.95), Inches(12), Inches(0.7),
              data.get("title", ""), size=30, bold=True, color=_BRAND["white"])
    cards = (data.get("cards") or [])[:3]
    if not cards: return
    n = len(cards)
    total_w = Inches(12.3); gap = Inches(0.25)
    card_w = (total_w - gap * (n - 1)) / n
    x = Inches(0.5); y = Inches(2.5); h = Inches(3.8)
    for c in cards:
        _add_rect(slide, x, y, card_w, h, _BRAND["card"])
        # Accent strip on top of card
        _add_rect(slide, x, y, card_w, Inches(0.18), _BRAND["accent"], rounded=False)
        _add_text(slide, x + Inches(0.3), y + Inches(0.5),
                  card_w - Inches(0.6), Inches(1.4),
                  c.get("value", ""), size=54, bold=True, color=_BRAND["accent"], align="center")
        _add_text(slide, x + Inches(0.3), y + Inches(2.0),
                  card_w - Inches(0.6), h - Inches(2.2),
                  c.get("label", ""), size=14, color=_BRAND["card_text"], align="center")
        x += card_w + gap


def _render_type_cards(slide, data):
    _slide_bg(slide, _BRAND["bg"])
    _add_text(slide, Inches(0.6), Inches(0.95), Inches(12), Inches(0.7),
              data.get("title", ""), size=28, bold=True, color=_BRAND["white"])
    cards = (data.get("cards") or [])[:4]
    if not cards: return
    n = len(cards)
    total_w = Inches(12.3); gap = Inches(0.2)
    card_w = (total_w - gap * (n - 1)) / n
    x = Inches(0.5); y = Inches(2.2); h = Inches(4.4)
    for c in cards:
        _add_rect(slide, x, y, card_w, h, _BRAND["card"])
        # Label strip
        _add_rect(slide, x, y, card_w, Inches(0.6), _BRAND["teal"], rounded=False)
        _add_text(slide, x, y + Inches(0.05), card_w, Inches(0.5),
                  c.get("label", ""), size=14, bold=True,
                  color=_BRAND["white"], align="center")
        _add_text(slide, x + Inches(0.25), y + Inches(0.85),
                  card_w - Inches(0.5), Inches(0.7),
                  c.get("heading", ""), size=15, bold=True, color=_BRAND["card_text"])
        _add_text(slide, x + Inches(0.25), y + Inches(1.6),
                  card_w - Inches(0.5), h - Inches(2.5),
                  c.get("body", ""), size=11, color=_BRAND["card_text"])
        # Badge
        badge = c.get("badge")
        if badge:
            bcol = _BADGE_COLORS.get((c.get("badge_color") or "teal").lower(),
                                     _BRAND["teal"])
            bw = card_w - Inches(0.6); bh = Inches(0.4)
            _add_rect(slide, x + Inches(0.3), y + h - Inches(0.65),
                      bw, bh, bcol)
            _add_text(slide, x + Inches(0.3), y + h - Inches(0.62),
                      bw, bh, badge, size=11, bold=True,
                      color=_BRAND["white"], align="center")
        x += card_w + gap


def _render_numbered_grid(slide, data):
    _slide_bg(slide, _BRAND["bg"])
    _add_text(slide, Inches(0.6), Inches(0.95), Inches(12), Inches(0.7),
              data.get("title", ""), size=28, bold=True, color=_BRAND["white"])
    items = data.get("items") or []
    if not items: return
    cols = 3 if len(items) >= 5 else 2
    rows = (len(items) + cols - 1) // cols
    total_w = Inches(12.3); total_h = Inches(4.6)
    gap = Inches(0.2)
    card_w = (total_w - gap * (cols - 1)) / cols
    card_h = (total_h - gap * (rows - 1)) / rows
    x0 = Inches(0.5); y0 = Inches(2.2)
    for idx, it in enumerate(items[:cols*rows]):
        r, c = divmod(idx, cols)
        x = x0 + (card_w + gap) * c
        y = y0 + (card_h + gap) * r
        _add_rect(slide, x, y, card_w, card_h, _BRAND["card"])
        # Number circle
        circ = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                       x + Inches(0.2), y + Inches(0.2),
                                       Inches(0.65), Inches(0.65))
        _set_solid(circ, _BRAND["accent"])
        _add_text(slide, x + Inches(0.2), y + Inches(0.22),
                  Inches(0.65), Inches(0.65),
                  str(it.get("n", idx + 1)), size=18, bold=True,
                  color=_BRAND["white"], align="center")
        _add_text(slide, x + Inches(1.0), y + Inches(0.2),
                  card_w - Inches(1.2), Inches(0.6),
                  it.get("heading", ""), size=14, bold=True, color=_BRAND["card_text"])
        _add_text(slide, x + Inches(0.3), y + Inches(0.95),
                  card_w - Inches(0.6), card_h - Inches(1.1),
                  it.get("body", ""), size=10, color=_BRAND["subtle"])


def _render_chart_bar(slide, data):
    _slide_bg(slide, _BRAND["bg"])
    _add_text(slide, Inches(0.6), Inches(0.95), Inches(12), Inches(0.7),
              data.get("title", ""), size=28, bold=True, color=_BRAND["white"])
    cats = data.get("categories") or []
    vals = data.get("values") or []
    if not cats or not vals: return
    cd = CategoryChartData()
    cd.categories = cats
    cd.add_series(data.get("unit", "Value"), vals)
    chart_shape = slide.shapes.add_chart(
        XL_CHART_TYPE.BAR_CLUSTERED,
        Inches(0.6), Inches(2.0), Inches(12.1), Inches(4.6),
        cd)
    chart = chart_shape.chart
    chart.has_legend = False
    plot = chart.plots[0]
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.font.size = Pt(12); dl.font.bold = True
    try: dl.font.color.rgb = _BRAND["white"]
    except Exception: pass
    # Color the bars coral
    try:
        for series in chart.series:
            fill = series.format.fill
            fill.solid()
            fill.fore_color.rgb = _BRAND["accent"]
    except Exception:
        pass
    # Axis text white
    try:
        for ax in (chart.category_axis, chart.value_axis):
            ax.tick_labels.font.size = Pt(11)
            ax.tick_labels.font.color.rgb = _BRAND["white"]
    except Exception:
        pass


def _render_comparison_table(slide, data):
    _slide_bg(slide, _BRAND["bg"])
    _add_text(slide, Inches(0.6), Inches(0.95), Inches(12), Inches(0.7),
              data.get("title", ""), size=28, bold=True, color=_BRAND["white"])
    headers = data.get("headers") or []
    rows    = data.get("rows") or []
    if not headers or not rows: return
    nrows = len(rows) + 1
    ncols = len(headers)
    table_shape = slide.shapes.add_table(
        nrows, ncols,
        Inches(0.6), Inches(2.1), Inches(12.1), Inches(4.4))
    table = table_shape.table
    # Header row
    for c, h in enumerate(headers):
        cell = table.cell(0, c)
        cell.text = ""
        cell.fill.solid(); cell.fill.fore_color.rgb = _BRAND["accent"]
        para = cell.text_frame.paragraphs[0]
        run = para.add_run(); run.text = str(h)
        run.font.size = Pt(13); run.font.bold = True
        run.font.color.rgb = _BRAND["white"]
        para.alignment = PP_ALIGN.CENTER
    # Body rows
    for r, row in enumerate(rows, start=1):
        for c in range(ncols):
            cell = table.cell(r, c)
            cell.text = ""
            cell.fill.solid()
            cell.fill.fore_color.rgb = (_BRAND["card"] if r % 2 == 1
                                         else RGBColor(0xE5, 0xE0, 0xD7))
            para = cell.text_frame.paragraphs[0]
            run = para.add_run()
            run.text = str(row[c]) if c < len(row) else ""
            run.font.size = Pt(12)
            run.font.color.rgb = _BRAND["card_text"]
            run.font.bold = (c == 0)
            para.alignment = PP_ALIGN.LEFT


def _render_bullets(slide, data):
    _slide_bg(slide, _BRAND["bg"])
    _add_text(slide, Inches(0.6), Inches(0.95), Inches(12), Inches(0.7),
              data.get("title", ""), size=28, bold=True, color=_BRAND["white"])
    bullets = data.get("bullets") or []
    if not bullets: return
    y = Inches(2.2)
    for b in bullets[:7]:
        # Coral bullet square
        sq = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                     Inches(0.7), y + Inches(0.18),
                                     Inches(0.18), Inches(0.18))
        _set_solid(sq, _BRAND["accent"])
        _add_text(slide, Inches(1.05), y, Inches(11.5), Inches(0.7),
                  b, size=16, color=_BRAND["white"])
        y += Inches(0.65)


def _render_summary(slide, data):
    _slide_bg(slide, _BRAND["bg"])
    _add_rect(slide, Inches(0.5), Inches(0.9), Inches(12.3), Inches(5.8),
              _BRAND["bg_dark"])
    _add_text(slide, Inches(0.8), Inches(1.1), Inches(12), Inches(0.5),
              data.get("eyebrow", "KEY TAKEAWAYS"), size=12, bold=True,
              color=_BRAND["accent2"])
    _add_text(slide, Inches(0.8), Inches(1.55), Inches(12), Inches(0.9),
              data.get("title", "Clinical Pearls"),
              size=32, bold=True, color=_BRAND["white"])
    bullets = data.get("bullets") or []
    y = Inches(2.7)
    for i, b in enumerate(bullets[:6], start=1):
        # Numbered chip
        chip = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                       Inches(0.9), y + Inches(0.05),
                                       Inches(0.45), Inches(0.45))
        _set_solid(chip, _BRAND["accent"])
        _add_text(slide, Inches(0.9), y + Inches(0.05),
                  Inches(0.45), Inches(0.45),
                  str(i), size=14, bold=True, color=_BRAND["white"], align="center")
        _add_text(slide, Inches(1.6), y, Inches(11), Inches(0.6),
                  b, size=15, color=_BRAND["white"])
        y += Inches(0.6)


def _render_references(slide, data):
    _slide_bg(slide, _BRAND["bg"])
    _add_text(slide, Inches(0.6), Inches(0.95), Inches(12), Inches(0.7),
              data.get("title", "References"), size=28, bold=True, color=_BRAND["white"])
    items = data.get("items") or data.get("bullets") or []
    if not items: return
    y = Inches(2.0)
    for i, item in enumerate(items[:10], start=1):
        _add_text(slide, Inches(0.7), y, Inches(0.5), Inches(0.4),
                  f"{i}.", size=11, bold=True, color=_BRAND["accent2"])
        _add_text(slide, Inches(1.1), y, Inches(11.5), Inches(0.5),
                  item, size=11, color=_BRAND["muted"])
        y += Inches(0.42)


_RENDERERS = {
    "stat_cards":       _render_stat_cards,
    "type_cards":       _render_type_cards,
    "numbered_grid":    _render_numbered_grid,
    "chart_bar":        _render_chart_bar,
    "comparison_table": _render_comparison_table,
    "bullets":          _render_bullets,
    "summary":          _render_summary,
    "references":       _render_references,
}


def run_generate_slides(audio_id: str, answer: str, question: str,
                        length_minutes: int, voice: str = "onyx"):
    try:
        from endo_ai import generate_slides_specs
        from presentations.build_deck import build_deck_from_specs

        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "generating_content"

        print(f"  Generating {length_minutes}-min pattern-based slide specs...")
        deck = generate_slides_specs(answer, question, length_minutes)

        slides_list = deck.get("slides", []) or []
        if not slides_list:
            raise ValueError(
                "Slide generator returned 0 slides after retry. "
                "Try a shorter length or check server log for parse-failure reason."
            )

        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "building_slides"
            audio_jobs[audio_id]["slides_total"] = len(slides_list)
            audio_jobs[audio_id]["slides_done"]  = 0

        print(f"  Building {len(slides_list)}-slide PPTX with design-token patterns...")
        prs, slides_queue = build_deck_from_specs(deck)

        # ── Save base PPTX (no audio yet) ─────────────────────
        tmp_base = tempfile.NamedTemporaryFile(suffix=".pptx", delete=False)
        prs.save(tmp_base.name)
        tmp_base.close()
        print(f"  Base PPTX saved: {len(slides_queue)} slides")

        # ── Generate TTS per slide and inject via ZIP surgery ──
        slide_audios: dict = {}   # {slide_num_1based: mp3_bytes}

        if OPENAI_TTS_AVAILABLE and slides_queue:
            with audio_jobs_lock:
                audio_jobs[audio_id]["status"] = "generating_audio"
                audio_jobs[audio_id]["slides_done"] = 0
            total = len(slides_queue)
            print(f"  Recording narration for {total} slides (voice={voice}) in parallel...")

            from concurrent.futures import ThreadPoolExecutor, as_completed
            import threading as _th_pptx
            done_lock_p = _th_pptx.Lock(); done_count_p = [0]

            def _tts_pptx(slide_num, notes_text):
                narration = (notes_text or "").strip()
                if not narration:
                    return slide_num, None
                try:
                    resp = _oai_tts.audio.speech.create(
                        model="tts-1", voice=voice, input=narration[:4096])
                    return slide_num, resp.content
                except Exception as tts_err:
                    print(f"    slide {slide_num} TTS error: {tts_err}")
                    return slide_num, None

            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = [pool.submit(_tts_pptx, sn, n)
                           for _, n, sn in slides_queue]
                for fut in as_completed(futures):
                    with audio_jobs_lock:
                        if audio_jobs[audio_id].get("cancelled"):
                            print("  Job cancelled by user"); return
                    sn, content = fut.result()
                    if content is not None:
                        slide_audios[sn] = content
                        print(f"    slide {sn}/{total} OK")
                    with done_lock_p:
                        done_count_p[0] += 1
                        with audio_jobs_lock:
                            audio_jobs[audio_id]["slides_done"] = done_count_p[0]

        elif GTTS_AVAILABLE and slides_queue:
            with audio_jobs_lock:
                audio_jobs[audio_id]["status"] = "generating_audio"
            import io as _sysio2
            all_notes = " ".join(n for _, n, _ in slides_queue if (n or "").strip())
            if all_notes:
                try:
                    buf = _sysio2.BytesIO()
                    gTTS(text=all_notes[:5000], lang="en", slow=False).write_to_fp(buf)
                    slide_audios[1] = buf.getvalue()
                    print("  gTTS narration recorded for slide 1")
                except Exception as gtts_err:
                    print(f"  gTTS error: {gtts_err}")
        else:
            print("  No TTS backend -- slides will include text notes only")

        # ── Inject audio into PPTX via ZIP manipulation ────────
        final_path = tmp_base.name
        if slide_audios:
            with audio_jobs_lock:
                audio_jobs[audio_id]["status"] = "injecting_audio"
            print(f"  Injecting audio into {len(slide_audios)} slides...")
            try:
                final_path = _inject_audio_into_pptx(tmp_base.name, slide_audios)
                print(f"  OK Narrated PPTX: {final_path}")
                import os as _os; _os.unlink(tmp_base.name)
            except Exception as inj_err:
                import traceback; traceback.print_exc()
                print(f"  Audio injection failed: {inj_err} -- delivering base PPTX")
                final_path = tmp_base.name

        with audio_jobs_lock:
            audio_jobs[audio_id]["status"]    = "complete"
            audio_jobs[audio_id]["file_path"] = final_path
            q   = audio_jobs[audio_id].get("question", "")
            dur = audio_jobs[audio_id].get("length_minutes", 10)
        _persist_media(final_path, audio_id, "pptx", q, "slides", "slides", dur)
        print(f"  OK Done ({n_slides} slides, {len(slide_audios)} with audio)")

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"  Slides generation error: {e}")
        with audio_jobs_lock:
            audio_jobs[audio_id]["status"] = "error"
            audio_jobs[audio_id]["error"]  = str(e)


# ── Cancel audio/slides job ───────────────────────────────

@app.route("/cancel_audio/<audio_id>", methods=["POST"])
def cancel_audio_job(audio_id: str):
    with audio_jobs_lock:
        job = audio_jobs.get(audio_id)
        if job and job.get("status") not in ("complete", "error", "cancelled"):
            job["status"]    = "cancelled"
            job["cancelled"] = True
    return jsonify({"ok": True})


# ── Media Library (persistent generated files) ───────────

import json as _json_mod, shutil as _shutil

MEDIA_DIR        = os.path.join(os.path.dirname(__file__), "generated_media")
_MEDIA_INDEX_PATH = os.path.join(os.path.dirname(__file__), "media_index.json")
_media_index_lock = threading.Lock()
os.makedirs(MEDIA_DIR, exist_ok=True)

def _load_media_index() -> list:
    if os.path.exists(_MEDIA_INDEX_PATH):
        try:
            with open(_MEDIA_INDEX_PATH, "r", encoding="utf-8") as f:
                return _json_mod.load(f)
        except Exception:
            pass
    return []

def _append_media_item(item: dict):
    """Thread-safe: prepend item to media index JSON (newest first)."""
    with _media_index_lock:
        items = _load_media_index()
        items.insert(0, item)
        with open(_MEDIA_INDEX_PATH, "w", encoding="utf-8") as f:
            _json_mod.dump(items, f, indent=2)

def _remove_media_item(media_id: str) -> bool:
    with _media_index_lock:
        items = _load_media_index()
        target = next((i for i in items if i.get("id") == media_id), None)
        if not target:
            return False
        fpath = os.path.join(MEDIA_DIR, target.get("filename", ""))
        try:
            if os.path.exists(fpath):
                os.unlink(fpath)
        except Exception:
            pass
        items = [i for i in items if i.get("id") != media_id]
        with open(_MEDIA_INDEX_PATH, "w", encoding="utf-8") as f:
            _json_mod.dump(items, f, indent=2)
        return True

def _persist_media(src_path: str, media_id: str, ext: str,
                   question: str, style: str, media_type: str,
                   length_minutes: int):
    """Copy temp file to MEDIA_DIR and record in index."""
    try:
        filename = f"{media_id}.{ext}"
        dst = os.path.join(MEDIA_DIR, filename)
        _shutil.copy2(src_path, dst)
        _append_media_item({
            "id":             media_id,
            "type":           media_type,   # "audio" | "video" | "slides"
            "style":          style,        # "conversation" | "lecture" | "video" | "slides"
            "ext":            ext,
            "filename":       filename,
            "question":       question,
            "length_minutes": length_minutes,
            "created_at":     datetime.now().isoformat(),
        })
        print(f"  [media] Saved {filename}")
    except Exception as e:
        print(f"  [media] Failed to persist: {e}")


@app.route("/api/media")
def list_media():
    """Return all saved media items, newest first."""
    return jsonify(_load_media_index())


@app.route("/api/media/<media_id>/download")
def download_media(media_id: str):
    items = _load_media_index()
    item  = next((i for i in items if i.get("id") == media_id), None)
    if not item:
        return jsonify({"error": "Not found"}), 404
    fpath = os.path.join(MEDIA_DIR, item["filename"])
    if not os.path.exists(fpath):
        return jsonify({"error": "File missing"}), 404
    ext_map = {"mp3": "audio/mpeg", "mp4": "video/mp4",
               "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    mime = ext_map.get(item.get("ext", "mp3"), "application/octet-stream")
    return send_file(fpath, as_attachment=True,
                     download_name=item["filename"], mimetype=mime)


@app.route("/api/media/<media_id>/stream")
def stream_media(media_id: str):
    """Stream audio/video for in-browser playback (no attachment header)."""
    items = _load_media_index()
    item  = next((i for i in items if i.get("id") == media_id), None)
    if not item:
        return jsonify({"error": "Not found"}), 404
    fpath = os.path.join(MEDIA_DIR, item["filename"])
    if not os.path.exists(fpath):
        return jsonify({"error": "File missing"}), 404
    ext_map = {"mp3": "audio/mpeg", "mp4": "video/mp4",
               "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    mime = ext_map.get(item.get("ext", "mp3"), "application/octet-stream")
    return send_file(fpath, mimetype=mime)


@app.route("/api/media/<media_id>", methods=["DELETE"])
def delete_media(media_id: str):
    ok = _remove_media_item(media_id)
    return jsonify({"success": ok})


# ── Case Difficulty Assessment ────────────────────────────

_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "provider_profile.json")

def _load_profile() -> dict:
    if os.path.exists(_PROFILE_PATH):
        try:
            with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
                return _json_mod.load(f)
        except Exception:
            pass
    return {}

def _save_profile(data: dict):
    with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
        _json_mod.dump(data, f, indent=2)


@app.route("/api/profile", methods=["GET"])
def get_profile():
    return jsonify(_load_profile())


@app.route("/api/profile", methods=["POST"])
def save_profile():
    data = request.json or {}
    _save_profile(data)
    return jsonify({"success": True})


@app.route("/api/settings", methods=["GET"])
def get_settings():
    """Return AI-behaviour settings (explanation level, content balance, theme)."""
    profile = _load_profile()
    return jsonify({
        "explanation_level": profile.get("explanation_level", "clinician"),
        "content_balance":   profile.get("content_balance",   "balanced"),
        "theme":             profile.get("theme",             "dark"),
    })


@app.route("/api/settings", methods=["POST"])
def save_settings():
    """Persist AI-behaviour settings into the profile JSON."""
    data    = request.json or {}
    profile = _load_profile()
    for key in ("explanation_level", "content_balance", "theme"):
        if key in data:
            profile[key] = data[key]
    _save_profile(profile)
    return jsonify({"success": True})


# ── X-ray gating (PHI) ───────────────────────────────────
# Patient radiographs are PHI. The vision path ships DISABLED and is enabled
# per-deployment via ENABLE_XRAY=true — a decision recorded in WORKLIST §5:
# enabling it in production requires a BAA with the vision provider
# (Gemini / OpenAI). See HANDOVER.md.

def _xray_enabled() -> bool:
    """Read ENABLE_XRAY at request time so tests/deploys can toggle it."""
    return (os.getenv("ENABLE_XRAY") or "").strip().lower() in ("1", "true", "yes", "on")


def _sanitize_tooth_hint(raw: str) -> str:
    """Reduce the tooth hint to a bare tooth designation (e.g. '14', '#30',
    'B', '4.6'). Anything longer or containing free text is dropped entirely,
    so patient case narrative can never ride along with the image to the
    vision provider."""
    hint = (raw or "").strip()
    if _audit_re.fullmatch(r"#?[A-Ta-t0-9][0-9.]{0,3}", hint):
        return hint.lstrip("#")
    return ""


def _strip_image_metadata(image_bytes: bytes, ext: str) -> bytes:
    """Re-encode the uploaded image with Pillow, dropping ALL ancillary
    metadata: EXIF/GPS/IPTC/XMP on JPEG, tEXt/iTXt/zTXt chunks on PNG.
    Radiograph exports routinely embed patient name/DOB in these fields.
    Raises on any decode failure — the caller fails CLOSED (rejects the
    upload) rather than forwarding un-stripped bytes."""
    from PIL import Image
    import io as _io
    img = Image.open(_io.BytesIO(image_bytes))
    out = _io.BytesIO()
    if ext in ("jpg", "jpeg"):
        img.convert("RGB").save(out, format="JPEG", quality=95)
    else:
        # Pillow drops text chunks unless an explicit pnginfo is passed.
        img.save(out, format="PNG")
    return out.getvalue()


@app.route("/api/analyze-xray", methods=["POST"])
def analyze_xray():
    """Upload a PA radiograph; a vision model pre-fills the assessment form.

    Disabled by default (ENABLE_XRAY unset/false -> 403): radiographs are PHI
    and sending them to a third-party vision API requires a BAA. When enabled,
    the image is re-encoded to strip EXIF/PNG metadata, and only a sanitized
    tooth number — never case text — accompanies it."""
    if not _xray_enabled():
        return jsonify({
            "error": "X-ray analysis is disabled on this deployment. "
                     "Patient radiographs are PHI; enabling the vision path "
                     "requires a BAA with the vision provider. Set "
                     "ENABLE_XRAY=true only once that is in place.",
            "feature": "xray", "enabled": False,
        }), 403
    if "image" not in request.files:
        return jsonify({"error": "No image provided"}), 400
    file = request.files["image"]
    ext  = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg"):
        return jsonify({"error": "Use PNG or JPG"}), 400
    media_type = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    image_bytes = file.read()
    if len(image_bytes) > 12 * 1024 * 1024:
        return jsonify({"error": "Image too large (max 12 MB)"}), 400
    # Strip embedded metadata (EXIF, GPS, PNG text chunks) before the bytes
    # leave this server. Fail closed: an image Pillow cannot decode is
    # rejected, never forwarded raw.
    try:
        image_bytes = _strip_image_metadata(image_bytes, ext)
    except Exception:
        return jsonify({"error": "Could not process image (metadata "
                                 "stripping failed) — upload not sent."}), 400
    tooth_hint = _sanitize_tooth_hint(request.form.get("tooth_hint"))
    provider   = (request.form.get("provider")   or "auto").strip()
    if provider not in ("gemini", "openai"):
        provider = "auto"
    try:
        raw      = analyze_radiograph(image_bytes, media_type, tooth_hint=tooth_hint, provider=provider)
        prefill  = _analysis_to_prefill(raw)
        meta     = raw.get("_meta", {"provider": "unknown", "fallback_reason": None})
        return jsonify({"success": True, "prefill": prefill, "raw": raw,
                        "provider":        meta.get("provider"),
                        "fallback_reason": meta.get("fallback_reason"),
                        "cost_usd":        meta.get("cost_usd", 0.0),
                        "input_tokens":    meta.get("input_tokens", 0),
                        "output_tokens":   meta.get("output_tokens", 0)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e), "fallback": "manual"}), 200


@app.route("/api/assess", methods=["POST"])
def assess_case():
    """Score a case and compare against the provider's profile."""
    data         = request.json or {}
    answers      = data.get("answers", {})
    profile      = data.get("profile") or _load_profile()

    # Build AAE factor scores from questionnaire answers
    scores = _answers_to_aae_scores(answers)
    aae    = calculate_case_difficulty(scores)

    # Personalised match (only if profile exists)
    if profile:
        match = match_case_to_profile(answers, profile)
    else:
        match = {
            "recommendation":    aae["level"],
            "summary":           f"AAE difficulty: {aae['level']}",
            "exceeds_comfort":   aae["high_factors"],
            "within_comfort":    [],
            "equipment_warnings":[]
        }

    # Echo back clinical diagnoses for the result panel
    pulpal_dx     = answers.get("pulpal_diagnosis", "")
    periapical_dx = answers.get("periapical_diagnosis", "")

    # Override recommendation for unusual/conflicting diagnosis combinations
    conflict_msgs = answers.get("_diagnosisConflictMessages", [])
    if answers.get("_diagnosisConflict") and conflict_msgs:
        match["recommendation"] = "REFER"
        match["exceeds_comfort"] = conflict_msgs + match.get("exceeds_comfort", [])
        match["summary"] = (
            "Unusual diagnosis combination — endodontist evaluation required "
            "before proceeding with treatment"
        )

    return jsonify({
        "success": True,
        "aae": aae,
        "match": match,
        "pulpal_diagnosis": pulpal_dx,
        "periapical_diagnosis": periapical_dx,
        "diagnosis_conflict": bool(conflict_msgs),
    })


@app.route("/api/referral-letter", methods=["POST"])
def referral_letter():
    data    = request.json or {}
    profile = data.get("profile") or _load_profile()
    reasons = data.get("reasons", [])
    case    = data.get("case", {})
    try:
        letter = generate_referral_letter(case, profile, reasons)
        return jsonify({"success": True, "letter": letter})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _answers_to_aae_scores(a: dict) -> dict:
    """Convert questionnaire answers to 1-3 AAE factor scores."""

    def curv_score(v):
        return {"straight": 1, "mild": 1, "moderate": 2, "severe": 3}.get(v, 1)

    def calc_score(v):
        return {"open": 1, "mild": 1, "moderate": 2, "severe": 3}.get(v, 1)

    def root_score(v):
        return {"normal": 1, "extra_roots": 2, "dilacerated": 3, "short": 2, "long": 2}.get(v, 1)

    def peri_score(v):
        return {"normal": 1, "small_lesion": 2, "large_lesion": 3}.get(v, 1)

    def retx_score(v):
        return {"none": 1, "simple": 2, "carrier": 2, "posts": 3, "separated": 3}.get(v, 1)

    complications = a.get("complications", ["none"])
    patient_factors = a.get("patient_factors", ["none"])

    def patient_score():
        if any(f in patient_factors for f in ["medical_complex", "bisphosphonates", "anticoagulation"]):
            return 3
        if any(f in patient_factors for f in ["hot_tooth", "limited_opening", "gag_reflex", "anxiety"]):
            return 2
        return 1

    # Clinical findings — percussion/palpation/cold test inform diagnosis clarity
    cold_test  = a.get("cold_test", "not_tested")
    percussion = a.get("percussion", "not_tested")
    palpation  = a.get("palpation", "not_tested")

    # Diagnosis clarity: base on periapical status, boosted if clinical findings confirm
    diag_clarity = peri_score(a.get("periapical_status", "normal"))
    if cold_test == "no_response" and a.get("periapical_status", "normal") == "normal":
        diag_clarity = max(diag_clarity, 2)  # necrosis without radiographic lesion = less clear
    if cold_test == "not_tested" and a.get("periapical_status", "normal") != "normal":
        diag_clarity = max(diag_clarity, 2)  # lesion without pulp testing = incomplete workup

    # Symptomatic irreversible pulpitis with percussion → harder anaesthesia
    is_symptomatic = (cold_test == "exaggerated_lingering" or
                      percussion == "yes" or palpation == "yes")
    anesthesia_score = 3 if "hot_tooth" in patient_factors else (2 if is_symptomatic else 1)

    return {
        "medical_history":        patient_score(),
        "anesthesia_history":     anesthesia_score,
        "patient_disposition":    3 if "anxiety" in patient_factors else 1,
        "mouth_opening":          3 if "limited_opening" in patient_factors else 1,
        "gag_reflex":             3 if "gag_reflex" in patient_factors else 1,
        "diagnosis_clarity":      diag_clarity,
        "radiographic_difficulty":2 if a.get("calcification") in ["moderate", "severe"] else 1,
        "tooth_position":         _tooth_position_score(a.get("tooth_number", 0)),
        "isolation_difficulty":   {"intact": 1, "filling": 1, "full_coverage": 2, "post_crown": 3}.get(a.get("crown_type", "intact"), 1),
        "crown_morphology":       {"easy": 1, "moderate": 2, "difficult": 3}.get(a.get("crown_access", "easy"), 1),
        "canal_morphology":       max(curv_score(a.get("canal_curvature", "mild")), calc_score(a.get("calcification", "open"))),
        "root_morphology":        root_score(a.get("root_anatomy", "normal")),
        "resorption":             3 if "resorption" in complications else 1,
        "trauma_history":         {"uncomplicated_fracture": 2, "complicated_fracture": 2, "luxation": 3, "avulsion": 3}.get(a.get("trauma_type", ""), 1) if "trauma" in complications else 1,
        "previous_endo":          retx_score(a.get("retreatment_complexity", "none") if a.get("is_retreatment") == "yes" else "none"),
        "perio_endo":             2 if "perio" in complications else 1,
    }


def _tooth_position_score(tooth_num: int) -> int:
    if tooth_num in [1, 16, 17, 32]:    return 3  # 3rd molars
    if tooth_num in [2, 15, 18, 31]:    return 3  # 2nd molars
    if tooth_num in [3, 14, 19, 30]:    return 2  # 1st molars
    if tooth_num in [4, 5, 12, 13, 20, 21, 28, 29]: return 1  # premolars
    return 1  # anteriors


# ── Main ─────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
