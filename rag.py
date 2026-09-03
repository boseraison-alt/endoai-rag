"""
Endo AI — RAG System
Semantic search over a local Neon Postgres + pgvector library of endodontic papers.
Embedding: sentence-transformers all-MiniLM-L6-v2 (free, local, 384-dim)
Falls back to live PubMed when local results are insufficient.
"""

import os
import json
import hashlib
import threading
import time
import psycopg2
import psycopg2.extras
import psycopg2.extensions
import psycopg2.pool
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.abspath('.'), '.env'))

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ── Embedding model (lazy-loaded on first use) ────────────
_model       = None
_model_lock  = threading.Lock()


def get_model():
    """Load sentence-transformer model once and reuse."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                print("  Loading embedding model (first run only)...")
                _model = SentenceTransformer("all-MiniLM-L6-v2")
                print("  Embedding model ready.")
    return _model


def embed(text: str) -> list[float]:
    """Embed a string into a 384-dim vector.

    all-MiniLM-L6-v2 works on TOKENS and truncates internally at its
    max_seq_length (256 word-piece tokens ≈ 1,500-2,000 characters). The old
    code pre-sliced text[:512] CHARACTERS — only ~120 tokens — silently
    discarding the back half of most abstracts before they ever reached the
    tokenizer, so retrieval was scoring on roughly half of each paper. We now
    pass enough characters to fill the model's real token window and let the
    tokenizer do the truncation at its true 256-token limit.
    """
    model  = get_model()
    vector = model.encode(text[:2000], normalize_embeddings=True)
    return vector.tolist()


# ── Database ──────────────────────────────────────────────
#
# A single ThreadedConnectionPool is shared process-wide. Every request used to
# open a brand-new TCP+TLS connection to Neon and tear it down again — under the
# Deep-Learning pipeline (dozens of queries per run) and concurrent Flask
# workers that is both slow and a good way to exhaust Neon's connection cap.
#
# The pool is transparent to callers: get_conn() hands back a proxy whose
# .close() RETURNS the connection to the pool instead of closing the socket, so
# the existing `conn = get_conn() ... conn.close()` contract works unchanged
# across rag.py, app.py, and the one-shot ingest scripts.

_pool      = None
_pool_lock = threading.Lock()


def _init_pool():
    """Lazily build the shared connection pool (thread-safe, double-checked)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                minc = int(os.getenv("DB_POOL_MIN", "1"))
                # Default raised 10 -> 32 (2026-08-30). Three parallelism features landed in
                # one batch: 6 tier-fetch workers, 4 curriculum workers, and streaming.
                # 4 modules x 6 workers = 24 potential concurrent borrowers, and
                # ThreadedConnectionPool RAISES on exhaustion rather than blocking, so the
                # only combination that could hard-fail is priced out here. Neon's
                # connection cap is far above 32; idle pooled connections cost nothing.
                maxc = int(os.getenv("DB_POOL_MAX", "32"))
                _pool = psycopg2.pool.ThreadedConnectionPool(
                    minc, maxc, dsn=DATABASE_URL,
                    # Survive Neon dropping idle connections between borrows.
                    keepalives=1, keepalives_idle=30,
                    keepalives_interval=10, keepalives_count=5,
                )
    return _pool


class _PooledConnection:
    """Transparent proxy over a pooled psycopg2 connection.

    Callers keep the old contract — `conn = get_conn(); ...; conn.close()` — but
    .close() returns the connection to the pool rather than tearing down the
    session. Every other attribute/method delegates to the real connection, and
    `with conn:` still gives psycopg2 transaction semantics (commit/rollback,
    NOT close).
    """
    __slots__ = ("_conn", "_pool", "_returned")

    def __init__(self, conn, pool):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_returned", False)

    def close(self):
        if object.__getattribute__(self, "_returned"):
            return
        object.__setattr__(self, "_returned", True)
        conn = object.__getattribute__(self, "_conn")
        pool = object.__getattribute__(self, "_pool")
        try:
            # Never hand the next borrower an open or aborted transaction.
            if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
        except Exception:
            pass
        try:
            pool.putconn(conn, close=bool(conn.closed))
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    def __enter__(self):
        object.__getattribute__(self, "_conn").__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return object.__getattribute__(self, "_conn").__exit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_conn"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_conn"), name, value)


def get_conn():
    """Borrow a connection from the shared pool.

    Returns a proxy whose .close() returns the connection to the pool, so every
    existing caller gets pooling with no code change. Stale connections (Neon
    dropped them while idle) are discarded and replaced.
    """
    pool = _init_pool()
    for _ in range(3):
        conn = pool.getconn()
        # `conn.closed` only reports what THIS process did. When the server
        # drops an idle connection — routine on Neon, and certain during a
        # 20-minute Deep Learning run — the socket looks open until a query
        # fails with "connection already closed". Validate before handing it
        # out, so that failure lands here (recoverable) rather than mid-write.
        try:
            if conn.closed:
                raise psycopg2.InterfaceError("connection closed")
            with conn.cursor() as probe:
                probe.execute("SELECT 1;")
            if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
            return _PooledConnection(conn, pool)
        except Exception:
            try:
                pool.putconn(conn, close=True)   # discard, don't recycle
            except Exception:
                pass
            continue
    # Pool exhausted of usable connections — open a direct one rather than
    # leaving the caller empty-handed.
    return _PooledConnection(psycopg2.connect(DATABASE_URL), pool)


def close_pool():
    """Close every pooled connection. Call on graceful shutdown if desired."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            finally:
                _pool = None


def setup_table():
    """Create endo_papers_rag table and ivfflat index. Safe to run multiple times."""
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS endo_papers_rag (
                id            SERIAL PRIMARY KEY,
                pmid          TEXT UNIQUE NOT NULL,
                title         TEXT,
                abstract      TEXT,
                authors       TEXT,
                year          INTEGER,
                journal       TEXT,
                impact_factor REAL,
                sample_size   INTEGER,
                followup_months INTEGER,
                citations     INTEGER DEFAULT 0,
                level_key     TEXT,
                score         REAL DEFAULT 0,
                is_curated    BOOLEAN DEFAULT FALSE,
                embedding     vector(384),
                added_at      TIMESTAMP DEFAULT NOW()
            );
        """)
        # Migration for libraries created before is_curated existed. Papers with
        # this flag carry a hand-assigned authority score (AAE/ESE position
        # statements, guidelines) and must never be overwritten by the formula-
        # based rescorer.
        cur.execute("""
            ALTER TABLE endo_papers_rag
            ADD COLUMN IF NOT EXISTS is_curated BOOLEAN DEFAULT FALSE;
        """)
        # Provenance-quality signals, backfilled from PubMed by
        # scripts/backfill_provenance.py. has_retraction matters most: the live
        # search filters retractions at query time, but library-served papers
        # bypass that filter, so a paper retracted AFTER ingestion would
        # otherwise still reach the clinician.
        for _col, _type in (
            ("medline_indexed", "BOOLEAN DEFAULT TRUE"),
            ("has_erratum",     "BOOLEAN DEFAULT FALSE"),
            ("has_retraction",  "BOOLEAN DEFAULT FALSE"),
            ("registry",        "TEXT DEFAULT ''"),
            # COI is decided ONCE at ingest/backfill time and stored here; the
            # stored `score` already carries the penalty. The read path only
            # displays these — never re-scans abstracts, never re-penalises.
            ("coi_flag",        "BOOLEAN DEFAULT FALSE"),
            ("coi_funder",      "TEXT DEFAULT ''"),
            # Tri-state: 'declared_conflict' | 'declared_none' | 'no_statement'.
            # PubMed only carries <CoiStatement> for records indexed since ~2017
            # whose journal deposits one, so "no statement" must stay distinct
            # from "declared none" — otherwise every older paper gets an
            # implicit clean bill it never earned.
            ("coi_status",      "TEXT DEFAULT 'no_statement'"),
            # PMID of the newer version that replaces this record, or '' when
            # this record is current. Cochrane reviews are VERSIONED: every
            # update is a new PubMed record and the older ones stay indexed, so
            # a library ingested once can hold three versions of the same review
            # and cite the 2007 one as current. PubMed links them through
            # CommentsCorrectionsList RefType="UpdateIn" on the OLDER record.
            # Stored as the successor's PMID rather than a bare boolean so the
            # answer can name the version the clinician should read instead.
            ("superseded_by",   "TEXT DEFAULT ''"),
        ):
            cur.execute(f"ALTER TABLE endo_papers_rag ADD COLUMN IF NOT EXISTS {_col} {_type};")
        cur.execute("""
            CREATE INDEX IF NOT EXISTS endo_papers_rag_emb_idx
            ON endo_papers_rag
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 50);
        """)
        conn.commit()
        print("RAG table ready.")
    except Exception as e:
        conn.rollback()
        print(f"Setup warning: {e}")
    finally:
        cur.close()
        conn.close()


# ── Store a paper ─────────────────────────────────────────

def learn_from_live_results(scored_papers: list, per_pmid: dict = None,
                            min_score: float = 50.0,
                            query_text: str = None) -> int:
    """Add good papers found on the live PubMed path into the local library.

    Without this the library is frozen at its ingestion date while the coverage
    gate keeps preferring it — the evidence base ages while the system keeps
    answering "I've got this". Scheduled re-ingest only refreshes topics someone
    thought to schedule; writing back refreshes the topics clinicians actually
    ask about.

    Papers land with their provenance already known (level_key, COI, registry,
    corrections) because the live path just computed all of it. Only papers at
    or above the quality floor are kept, and only ones carrying an abstract —
    a row without one is useless for both retrieval and the support check.

    `query_text` is the query this write-back came from, and doubles as the
    identity of the QUESTION for cache invalidation. Once the write-backs
    carrying that query have added CACHE_INVALIDATION_MIN_PAPERS papers in
    total — across however many tier-by-tier calls it takes — the cached
    answers sitting near that query are dropped, once. They were synthesised
    from the thinner evidence base those calls just replaced. It is OPTIONAL:
    a caller that has no query degrades to "write back, invalidate nothing",
    never to an exception.

    Returns the number of papers written. Never raises: a failure here must not
    break the answer that is already being returned to the clinician.
    """
    per_pmid = per_pmid or {}
    written = 0
    try:
        candidates = []
        for p in scored_papers or []:
            pmid = str(p.get("pmid") or "").strip()
            if not pmid or float(p.get("score") or 0) < min_score:
                continue
            if p.get("has_retraction"):
                continue                      # never seed a retracted paper
            if (p.get("superseded_by") or "").strip():
                continue                      # nor an outdated review version
            parts = per_pmid.get(pmid) or {}
            if not (parts.get("abstract") or "").strip():
                continue
            candidates.append((pmid, p, parts))
        if not candidates:
            return 0

        # Only embed papers the library does not already hold — embedding is
        # the expensive step and this runs on the request path. Refreshing
        # existing rows' citation counts and provenance is the nightly job's
        # concern, not this one's.
        conn = get_conn()
        cur  = conn.cursor()
        try:
            cur.execute("SELECT pmid FROM endo_papers_rag WHERE pmid = ANY(%s);",
                        ([c[0] for c in candidates],))
            known = {r[0] for r in cur.fetchall()}
        finally:
            cur.close(); conn.close()

        for pmid, p, parts in candidates:
            if pmid in known:
                continue
            abstract = (parts.get("abstract") or "").strip()
            title    = (parts.get("title") or "").strip()
            try:
                vec = embed(f"{title}\n{abstract}")
            except Exception:
                continue

            conn = get_conn()
            cur  = conn.cursor()
            try:
                cur.execute("""
                    INSERT INTO endo_papers_rag
                        (pmid, title, abstract, authors, year, journal,
                         impact_factor, sample_size, followup_months,
                         citations, level_key, score, embedding,
                         medline_indexed, has_erratum, has_retraction,
                         registry, coi_flag, coi_funder, coi_status,
                         superseded_by)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (pmid) DO UPDATE SET
                        citations       = EXCLUDED.citations,
                        score           = EXCLUDED.score,
                        level_key       = COALESCE(NULLIF(EXCLUDED.level_key,''),
                                                   endo_papers_rag.level_key),
                        medline_indexed = EXCLUDED.medline_indexed,
                        has_erratum     = EXCLUDED.has_erratum,
                        has_retraction  = EXCLUDED.has_retraction,
                        registry        = EXCLUDED.registry,
                        coi_flag        = EXCLUDED.coi_flag,
                        coi_funder      = EXCLUDED.coi_funder,
                        coi_status      = EXCLUDED.coi_status,
                        -- Never CLEAR a supersession the backfill established.
                        -- The live PubMed path does not parse UpdateIn, so it
                        -- always arrives empty; overwriting blindly would
                        -- un-flag a stale review on every re-ingest.
                        superseded_by   = COALESCE(NULLIF(EXCLUDED.superseded_by, ''),
                                                   endo_papers_rag.superseded_by)
                    WHERE NOT COALESCE(endo_papers_rag.is_curated, FALSE);
                """, (
                    pmid, title, abstract, p.get("authors", ""),
                    _safe_year(p.get("year")), p.get("journal", ""),
                    p.get("impact_factor"), p.get("sample_size"),
                    p.get("followup_months"), p.get("citations", 0),
                    p.get("level_key", "") or "", float(p.get("score") or 0), vec,
                    p.get("medline_indexed", True), bool(p.get("has_erratum")),
                    bool(p.get("has_retraction")), p.get("registry", "") or "",
                    bool(p.get("has_coi")), p.get("coi_funder", "") or "",
                    p.get("coi_status", "no_statement") or "no_statement",
                    p.get("superseded_by", "") or "",
                ))
                conn.commit()
                written += 1
            except Exception as e:
                conn.rollback()
                print(f"  [learn] skip {pmid}: {e}")
            finally:
                cur.close(); conn.close()
    except Exception as e:
        print(f"  [learn] write-back aborted: {e}")

    # A write-back big enough to change a topic's evidence base invalidates the
    # answers cached on that topic: they were synthesised before these papers
    # existed locally and would keep being served, at $0, until their TTL
    # expired. Deliberately OUTSIDE the try above, so a partial write-back that
    # aborted halfway still clears the answers its completed rows outdated —
    # and inside its own guard, because invalidation is a cache optimisation
    # and must never cost the caller either the papers it just wrote or the
    # answer already on its way to the clinician.
    #
    # The threshold is on the QUESTION's total, not this call's: fetch_papers()
    # calls this once per tier, so a question writing 4 papers into each of 7
    # tiers is a 28-paper topic change that no single call could ever report.
    # _note_writeback() accumulates and returns True exactly once per question.
    try:
        _should = _note_writeback(query_text, written)
    except Exception as e:                     # accounting must never break
        print(f"  [learn] write-back tally skipped: {e}")
        _should = written >= CACHE_INVALIDATION_MIN_PAPERS
    if _should:
        try:
            invalidate_cache_near_query(query_text)
        except Exception as e:
            print(f"  [learn] cache invalidation skipped: {e}")

    if written:
        print(f"  [learn] library grew by {written} paper(s) from this search")
    return written


def _safe_year(v):
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def upsert_paper(paper: dict, embedding: list[float]):
    """Insert or update a paper in the RAG library."""
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO endo_papers_rag
                (pmid, title, abstract, authors, year, journal,
                 impact_factor, sample_size, followup_months,
                 citations, level_key, score, embedding)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (pmid) DO UPDATE SET
                title           = EXCLUDED.title,
                abstract        = EXCLUDED.abstract,
                authors         = EXCLUDED.authors,
                year            = EXCLUDED.year,
                citations       = EXCLUDED.citations,
                sample_size     = EXCLUDED.sample_size,
                followup_months = EXCLUDED.followup_months,
                score           = EXCLUDED.score,
                embedding       = EXCLUDED.embedding;
        """, (
            paper.get("pmid"),
            paper.get("title", ""),
            # Stored WHOLE and deliberately so — never slice the abstract on
            # its way into the library. Every ingest script used to cap this
            # field ([:1000]/[:1200]) and left 1,342 rows ending mid-paper,
            # with the CONCLUSIONS gone; the synthesis prompt reads this column
            # back verbatim. Length limits belong on EMBEDDING text only.
            paper.get("abstract", ""),
            paper.get("authors", ""),
            paper.get("year"),
            paper.get("journal", ""),
            paper.get("impact_factor"),
            paper.get("sample_size"),
            paper.get("followup_months"),
            paper.get("citations", 0),
            paper.get("level_key", ""),
            paper.get("score", 0),
            embedding,
        ))
        conn.commit()
    finally:
        cur.close()
        conn.close()


# ── Search ────────────────────────────────────────────────

def search(
    query: str,
    level_key: str = None,
    limit: int = 20,
    similarity_threshold: float = 0.30,
) -> list[dict]:
    """
    Semantic search against local library.
    Optionally filter by evidence level (level_key).
    Returns papers ordered by SIMILARITY. The limit decides membership of
    the candidate pool, and membership is a relevance question
    (standing rule 19); quality ranks later, within a tier.
    """
    if not DATABASE_URL:
        return []

    try:
        query_vec = embed(query)
    except Exception as e:
        print(f"  Embed error: {e}")
        return []

    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if level_key:
            cur.execute("""
                SELECT
                    pmid, title, abstract, authors, year, journal,
                    impact_factor, sample_size, followup_months,
                    citations, level_key, score, is_curated,
                    medline_indexed, has_erratum, has_retraction, registry,
                    coi_flag, coi_funder, coi_status, superseded_by,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM endo_papers_rag
                WHERE level_key = %s
                  AND NOT COALESCE(has_retraction, FALSE)
                  AND title NOT ILIKE 'WITHDRAWN:%%'
                  -- Superseded: a newer version of this same review exists.
                  -- (Same reasoning as the unfiltered branch below — keep both
                  -- in step.)
                  AND COALESCE(superseded_by, '') = ''
                  AND 1 - (embedding <=> %s::vector) >= %s
                -- A30/rule 19. This LIMIT decides MEMBERSHIP of the
                -- candidate pool, so it is ordered by relevance alone. It
                -- used to blend `score * 0.6 + similarity * 40` — score is
                -- 0-100 and similarity 0-1, so the score carried 60 of the
                -- 100 available weight and decided who got in.
                --
                -- Measured on "retreatment in one visit versus two visits":
                -- Schwendicke 2017 sits at similarity 0.635, rank 40 in the
                -- library by pure relevance and comfortably above the 0.55
                -- floor — and the blend pushed it out of the top 100
                -- ENTIRELY, which is why it reached no query and looked like
                -- a vocabulary miss. Karaoglan moved 95 -> 32 and Toia
                -- 63 -> 15 on the same change.
                --
                -- Ranking by quality still happens; it happens later, within
                -- a tier, where invariant 1 puts it.
                ORDER BY (1 - (embedding <=> %s::vector)) DESC
                LIMIT %s;
            """, (query_vec, level_key, query_vec, similarity_threshold, query_vec, limit))
        else:
            cur.execute("""
                SELECT
                    pmid, title, abstract, authors, year, journal,
                    impact_factor, sample_size, followup_months,
                    citations, level_key, score, is_curated,
                    medline_indexed, has_erratum, has_retraction, registry,
                    coi_flag, coi_funder, coi_status, superseded_by,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM endo_papers_rag
                WHERE NOT COALESCE(has_retraction, FALSE)
                  -- Cochrane withdraws a review when it is no longer reliable
                  -- (superseded methods, unresolved concerns). PubMed does not
                  -- mark these as retracted, so has_retraction misses them,
                  -- and they sit in the cochrane tier at ~70 score. The
                  -- withdrawal notice replaces the title verbatim.
                  AND title NOT ILIKE 'WITHDRAWN:%%'
                  -- Cochrane reviews are versioned: each update is a NEW PubMed
                  -- record and the older versions stay indexed, so the library
                  -- can hold a 2007, a 2016 and a 2022 edition of the same
                  -- review side by side. Nothing in the older record's title,
                  -- level or score says it is out of date — only PubMed's
                  -- CommentsCorrections RefType="UpdateIn" does — so without
                  -- this filter the ranker can hand a clinician a decade-old
                  -- conclusion the authors have since revised.
                  AND COALESCE(superseded_by, '') = ''
                  AND 1 - (embedding <=> %s::vector) >= %s
                -- A30/rule 19. This LIMIT decides MEMBERSHIP of the
                -- candidate pool, so it is ordered by relevance alone. It
                -- used to blend `score * 0.6 + similarity * 40` — score is
                -- 0-100 and similarity 0-1, so the score carried 60 of the
                -- 100 available weight and decided who got in.
                --
                -- Measured on "retreatment in one visit versus two visits":
                -- Schwendicke 2017 sits at similarity 0.635, rank 40 in the
                -- library by pure relevance and comfortably above the 0.55
                -- floor — and the blend pushed it out of the top 100
                -- ENTIRELY, which is why it reached no query and looked like
                -- a vocabulary miss. Karaoglan moved 95 -> 32 and Toia
                -- 63 -> 15 on the same change.
                --
                -- Ranking by quality still happens; it happens later, within
                -- a tier, where invariant 1 puts it.
                ORDER BY (1 - (embedding <=> %s::vector)) DESC
                LIMIT %s;
            """, (query_vec, query_vec, similarity_threshold, query_vec, limit))

        rows = cur.fetchall()
        return [dict(r) for r in rows]

    except Exception as e:
        print(f"  RAG search error: {e}")
        return []
    finally:
        cur.close()
        conn.close()


def search_by_pmids(query: str, pmids: list) -> list[dict]:
    """Fetch specific library rows WITH their cosine similarity to `query`.

    Used to seed a follow-up question's candidate set with the papers the
    previous answer cited. It returns candidates, never results: the rows come
    back in exactly the shape search() produces, carrying a real similarity
    against the NEW question, so every downstream gate — the similarity floor,
    tier banding, the per-tier quality floors — judges them on this question
    rather than on the last one.

    The exclusion clause is a copy of search()'s and must stay one: retracted,
    WITHDRAWN: and superseded rows are unfit to serve whatever route reaches
    them, and a seeding path that quietly re-admitted them would be the worst
    kind of bypass — invisible, and only on follow-ups.
    """
    pmids = [str(p).strip() for p in (pmids or []) if str(p).strip()]
    if not DATABASE_URL or not pmids:
        return []
    try:
        query_vec = embed(query)
    except Exception as e:
        print(f"  Embed error: {e}")
        return []

    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT
                pmid, title, abstract, authors, year, journal,
                impact_factor, sample_size, followup_months,
                citations, level_key, score, is_curated,
                medline_indexed, has_erratum, has_retraction, registry,
                coi_flag, coi_funder, coi_status, superseded_by,
                1 - (embedding <=> %s::vector) AS similarity
            FROM endo_papers_rag
            WHERE pmid = ANY(%s)
              AND NOT COALESCE(has_retraction, FALSE)
              AND title NOT ILIKE 'WITHDRAWN:%%'
              AND COALESCE(superseded_by, '') = ''
              AND embedding IS NOT NULL;
        """, (query_vec, pmids))
        return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"  RAG pmid-seed error: {e}")
        return []
    finally:
        cur.close()
        conn.close()


def has_enough_results(
    query: str,
    level_key: str,
    min_results: int = 5,
) -> bool:
    """Quick check: does the library have enough papers for this query + level?"""
    results = search(query, level_key=level_key, limit=min_results)
    return len(results) >= min_results


# ── Convert RAG results to scored_papers format ───────────

def rag_results_to_scored(rows: list[dict]) -> list[dict]:
    """Convert RAG DB rows to the same dict format as endo_ai.score_paper output.

    Provenance signals (COI, corrections, registry, indexing) are READ from
    stored columns — they are decided once at ingest/backfill time by
    scripts/backfill_provenance.py, and the stored `score` already carries any
    COI penalty. Nothing is re-derived per query here: re-scanning abstracts at
    read time both double-counted the penalty and, because RAG ranks on the
    stored score, left the penalty unable to influence retrieval order.
    """
    papers = []
    for r in rows:
        has_coi    = bool(r.get("coi_flag"))
        coi_funder = r.get("coi_funder") or ""

        papers.append({
            "has_coi":         has_coi,
            "coi_funder":      coi_funder if has_coi else "",
            "coi_status":      r.get("coi_status") or "no_statement",
            "level_key":       r.get("level_key", "") or "",
            "pmid":            r.get("pmid", ""),
            # THE PAPER ITSELF. `search()` selects both columns and this
            # function used to drop them, so `app._scored_to_text` had nothing
            # to render but the metadata line: a library-served paper reached
            # Claude as authors, year, citations, n, follow-up, IF and a score,
            # with not one word of what it says. Asked for a paragraph on what
            # the evidence shows, the model got the author, the year and the
            # sample size right and invented the finding — 16 of 20 flagged
            # claim-citation pairs, hand-judged 2026-08-31.
            #
            # `_safe_papers` whitelists what leaves the server, so the abstract
            # stops at the prompt and never reaches the browser.
            "title":           r.get("title", "") or "",
            "abstract":        r.get("abstract", "") or "",
            "year":            str(r.get("year", "Unknown")),
            "citations":       r.get("citations", 0),
            "authors":         r.get("authors", ""),
            "sample_size":     r.get("sample_size"),
            "followup_months": r.get("followup_months"),
            "journal":         r.get("journal", ""),
            "journal_abbrev":  r.get("journal", ""),
            "volume":          "",
            "issue":           "",
            "pages":           "",
            "impact_factor":   r.get("impact_factor"),
            # Stored score already includes every provenance adjustment.
            "score":           round(float(r.get("score", 0)), 1),
            "is_registered":   bool(r.get("registry")),
            "registry":        r.get("registry") or "",
            "has_erratum":     bool(r.get("has_erratum")),
            "has_retraction":  bool(r.get("has_retraction")),
            # PMID of the newer version of this review, '' when current.
            # search() already filters these out, so a non-empty value reaching
            # here means the caller bypassed search — carry it so the row can
            # still round-trip through learn_from_live_results() without the
            # flag being silently dropped.
            "superseded_by":   r.get("superseded_by") or "",
            "medline_indexed": r.get("medline_indexed", True),
            "is_curated":      bool(r.get("is_curated")),
            "breakdown":       {},
            "similarity":      round(float(r.get("similarity", 0)), 3),
        })
    return papers


# ── Query cache ───────────────────────────────────────────

def setup_query_cache():
    """Create query_cache table. Safe to run multiple times."""
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS query_cache (
                id                SERIAL PRIMARY KEY,
                question_text     TEXT NOT NULL,
                question_embedding vector(384),
                answer            TEXT,
                papers            JSONB,
                hit_count         INTEGER DEFAULT 0,
                created_at        TIMESTAMP DEFAULT NOW(),
                context_hash      TEXT DEFAULT ''
            );
        """)
        # Existing installations predate the column. An answer written under a
        # conversation context is a DIFFERENT cache entry from the same question
        # asked cold, and the partition has to exist before the first follow-up
        # is served — see context_fingerprint().
        cur.execute("""
            ALTER TABLE query_cache
            ADD COLUMN IF NOT EXISTS context_hash TEXT DEFAULT '';
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS query_cache_emb_idx
            ON query_cache
            USING ivfflat (question_embedding vector_cosine_ops)
            WITH (lists = 10);
        """)
        conn.commit()
        print("Query cache table ready.")
    except Exception as e:
        conn.rollback()
        print(f"Query cache setup warning: {e}")
    finally:
        cur.close()
        conn.close()


# ── The conversation-context half of the cache key ───────────────────────
# The cache matches on an EMBEDDING of the question text, and a follow-up's
# text is often near-identical to the same words asked cold: "what about in
# immature teeth?" embeds at cosine ~1.0 against itself regardless of which
# conversation it belongs to, and even a fully-spelled-out follow-up sits well
# inside 0.92 of the standalone version. Nothing in the question text records
# that the answer was synthesised under a prior exchange — so without this the
# first follow-up in any thread would be served the context-free answer to a
# similar-looking question, which is the exact failure the whole feature exists
# to avoid.
#
# The fingerprint is therefore a HARD PARTITION of the table, not another
# similarity term: rows are only ever compared within one context. "" is the
# no-context partition, which is where every row written before this change
# lives (the column defaults to '' and the lookup COALESCEs NULL to ''), so
# ordinary standalone questions keep hitting their existing cache entries.
def context_fingerprint(context_block: str) -> str:
    """Stable short hash of a conversation-context block. "" (no context) maps
    to "" so a context-free question keys exactly as it always did."""
    text = " ".join((context_block or "").split())
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


# Above this cosine the two questions are effectively the same string and the
# equivalence check is skipped. Between the match threshold and this, a cheap
# model confirms they are the same CLINICAL question before the cached answer
# is served.
CACHE_EXACT_THRESHOLD    = 0.985
CACHE_EQUIVALENCE_CHECK  = os.getenv("CACHE_EQUIVALENCE_CHECK", "true").lower() in ("1", "true", "yes")

# ── Write-back cache invalidation (WORKLIST 4.6) ─────────────────────────
# How many papers one write-back must add before the topic counts as having
# materially changed. Below this the library gained a few rows it probably
# already had neighbours for; above it, answers cached on the topic were
# synthesised from a measurably thinner evidence base.
CACHE_INVALIDATION_MIN_PAPERS = 5

# ── Per-QUESTION accumulation of the write-back count (WORKLIST C1) ──────
# CACHE_INVALIDATION_MIN_PAPERS is a threshold on ONE QUESTION's write-back,
# but learn_from_live_results() is called once per TIER inside fetch_papers()
# — seven times for a single question. A question that writes 4 papers into
# each of 7 tiers adds 28 papers to the library, a large topic change, and
# under a per-call test invalidated NOTHING: no single call reached 5.
#
# The counter therefore lives here, keyed by the query the write-back came
# from, and the threshold is applied to the RUNNING TOTAL for that question.
# Invalidation fires exactly once per question, on the tier whose write
# crosses the threshold — which is still before the answer is synthesised and
# cached, so this question's own fresh cache row is never the one deleted.
#
# Why keyed here rather than threaded through fetch_papers(): the call site
# is one line inside a function this workstream does not own, and threading a
# per-question counter through build_evidence_base -> fetch_papers -> rag
# would put the correctness of the invalidation in the hands of every future
# caller (`learn_from_live_results` has three). Keying on the query text that
# the caller ALREADY passes keeps the whole rule in one place, and a caller
# that passes no query still degrades to "write back, invalidate nothing".
#
# A question re-asked later must be able to invalidate again, so a tally is
# only continued while writes keep arriving: a gap longer than
# WRITEBACK_SESSION_GAP_SECONDS starts a fresh tally for the same query. The
# seven tier calls of one question arrive within seconds of each other.
_WRITEBACK_SESSION_GAP_SECONDS = float(
    os.getenv("WRITEBACK_SESSION_GAP_SECONDS", "300"))
# Bound the dict — a long-lived server answers thousands of questions.
_WRITEBACK_TALLY_MAX = 64

_writeback_tally = {}          # query key -> {"written", "invalidated", "last"}
_writeback_lock  = threading.Lock()


def _reset_writeback_tally():
    """Drop every accumulated per-question count. Tests use this; nothing on
    the request path needs it (entries expire by idle gap)."""
    with _writeback_lock:
        _writeback_tally.clear()


def _writeback_total(query_text: str) -> int:
    """Papers written so far for this question. Read-only; for tests/logging."""
    key = " ".join((query_text or "").lower().split())
    with _writeback_lock:
        return int((_writeback_tally.get(key) or {}).get("written", 0))


def _note_writeback(query_text: str, written: int) -> bool:
    """Add `written` to this question's running total.

    Returns True on the ONE call whose write pushes the question's total to
    CACHE_INVALIDATION_MIN_PAPERS or beyond; False every other time, including
    every later tier of the same question (the neighbourhood has already been
    cleared — clearing it again would only delete rows cached since).
    """
    key = " ".join((query_text or "").lower().split())
    if not key or written <= 0:
        return False
    now = time.monotonic()
    with _writeback_lock:
        entry = _writeback_tally.get(key)
        if entry is None or (now - entry["last"]) > _WRITEBACK_SESSION_GAP_SECONDS:
            entry = {"written": 0, "invalidated": False, "last": now}
            _writeback_tally[key] = entry
        entry["written"] += int(written)
        entry["last"] = now

        if len(_writeback_tally) > _WRITEBACK_TALLY_MAX:
            for stale, _ in sorted(_writeback_tally.items(),
                                   key=lambda kv: kv[1]["last"]
                                   )[:len(_writeback_tally) - _WRITEBACK_TALLY_MAX]:
                if stale != key:
                    _writeback_tally.pop(stale, None)

        if entry["invalidated"]:
            return False
        if entry["written"] >= CACHE_INVALIDATION_MIN_PAPERS:
            entry["invalidated"] = True
            return True
        return False


# Cosine above which a cached question counts as "on the written-back topic".
# LOOSER than the 0.92 serve threshold in get_cached_answer() on purpose: that
# one asks "is this the same question?", this one asks "is this the same
# topic?", and a topic-level change to the evidence should clear a wider
# neighbourhood than an exact-question match. Measured on real eval questions
# (MiniLM, 2026-08-30): paraphrases of one question score 0.87-0.97, while two
# genuinely different endodontic questions top out at 0.55 — so 0.85 clears
# the rephrasings of the written-back question and nothing else.
CACHE_INVALIDATION_SIMILARITY = 0.85


def _same_clinical_question(a: str, b: str) -> bool:
    """Would these two questions have the same evidence-based answer?

    Fails CLOSED: any error returns False, which degrades to a cache miss and a
    freshly generated answer. Serving a stale-but-wrong clinical answer is far
    worse than paying to regenerate one.
    """
    if not a or not b:
        return False
    a_s, b_s = a.strip(), b.strip()
    if a_s.lower() == b_s.lower():
        return True
    try:
        from endo_ai import _invoke_claude, MODELS, log_llm_call, _get_api_key
        import anthropic, re as _re
        client = anthropic.Anthropic(api_key=_get_api_key())
        resp = _invoke_claude(client, function_name="cache_equivalence_check",
            model=MODELS["structured_fast"], max_tokens=10,
            messages=[{"role": "user", "content":
                f"""Two clinical questions from an endodontics tool. Would the SAME
evidence-based answer serve both? Differences in tooth type (primary vs permanent),
pulp status (vital vs necrotic), presence of periapical pathology, patient age group,
or the specific material/technique compared mean they are DIFFERENT questions.

A: {a_s[:400]}
B: {b_s[:400]}

Answer with exactly one word: SAME or DIFFERENT."""}])
        log_llm_call("cache_equivalence_check", MODELS["structured_fast"],
                     resp.usage, mode="cache")
        return "same" in resp.content[0].text.strip().lower()[:10]
    except Exception as e:
        print(f"  [cache] equivalence check unavailable ({e}) — treating as MISS")
        return False


def invalidate_cache_near_query(query_text: str,
                                threshold: float = CACHE_INVALIDATION_SIMILARITY,
                                dry_run: bool = False) -> int:
    """Drop cached answers whose question sits within `threshold` cosine of
    `query_text`.

    The rescore and tier-migration scripts invalidate by truncating the whole
    table, because a rescore moves every paper. A write-back moves one topic,
    so it clears one neighbourhood instead — see CACHE_INVALIDATION_SIMILARITY
    for why that neighbourhood is wider than the serve threshold.

    Rows with a NULL `question_embedding` are never touched. `NULL >= x` is
    NULL rather than true in SQL, so they would survive incidentally, but the
    guard is written out: "we cannot tell what this row is about" must resolve
    to keeping it, not to whatever the comparison happens to do.

    Returns the number of rows deleted, or under `dry_run` the number that
    would have been. Never raises — every caller is on the request path behind
    an answer that has already been generated.
    """
    if not (query_text or "").strip():
        return 0                      # no query — invalidate nothing
    if not DATABASE_URL:
        return 0

    conn = cur = None
    try:
        q_vec = embed(query_text.strip())
        conn  = get_conn()
        cur   = conn.cursor()
        cur.execute("""
            SELECT id, question_text,
                   1 - (question_embedding <=> %s::vector) AS similarity
            FROM query_cache
            WHERE question_embedding IS NOT NULL
              AND 1 - (question_embedding <=> %s::vector) >= %s
            ORDER BY similarity DESC;
        """, (q_vec, q_vec, threshold))
        doomed = cur.fetchall() or []
        if not doomed:
            return 0

        verb = "would invalidate" if dry_run else "invalidating"
        for row_id, qtext, sim in doomed:
            print(f"  [cache] {verb} #{row_id} (cos {float(sim):.3f}): "
                  f"{(qtext or '')[:70]}")
        if dry_run:
            return len(doomed)

        # Delete by the ids just listed rather than re-running the predicate,
        # so what is removed is exactly what was reported.
        cur.execute("DELETE FROM query_cache WHERE id = ANY(%s);",
                    ([int(r[0]) for r in doomed],))
        deleted = cur.rowcount
        conn.commit()
        print(f"  [cache] invalidated {deleted} cached answer(s) within cos "
              f"{threshold} of the written-back query")
        return deleted
    except Exception as e:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        print(f"  [cache] invalidation skipped: {e}")
        return 0
    finally:
        try:
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()
        except Exception:
            pass


def get_cached_answer(question: str, threshold: float = 0.92,
                       max_age_days: int = None,
                       context_hash: str = "") -> dict | None:
    """
    Return a cached answer if a semantically similar question was asked before.
    Returns dict with 'answer', 'papers', 'created_at' (ISO str), and 'age_days'
    on hit, or None on miss.

    `max_age_days` — optional cap. Used by Deep Learning mode (7-day TTL) to
    avoid serving stale cached curricula. Other modes pass None for "no limit".

    `context_hash` — context_fingerprint() of the conversation context this
    question is being asked under, "" for a standalone question. It is an
    EQUALITY term in the WHERE clause, not part of the similarity: a follow-up
    can never be served the answer that was generated without its context, at
    any cosine, and vice versa.
    """
    if not DATABASE_URL:
        return None
    try:
        q_vec = embed(question)
    except Exception:
        return None

    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        # Build age filter: PostgreSQL `created_at >= NOW() - INTERVAL` if age cap set
        age_filter = ""
        params     = [q_vec, q_vec, threshold, (context_hash or "")]
        if max_age_days is not None and max_age_days > 0:
            age_filter = " AND created_at >= NOW() - INTERVAL '%s days'"
            params.append(int(max_age_days))

        # `question_text` is the column; this selected `question` and so raised
        # on EVERY lookup, was swallowed by the except below, and returned None.
        # The answer cache had therefore never served a single hit since the
        # table was created — silently, because a permanent miss is
        # indistinguishable from a cold cache. The alias keeps the row key the
        # equivalence gate and the return block already use.
        cur.execute(f"""
            SELECT id, question_text AS question, answer, papers, created_at,
                   1 - (question_embedding <=> %s::vector) AS similarity
            FROM query_cache
            WHERE 1 - (question_embedding <=> %s::vector) >= %s
              -- Hard partition, not a soft signal. Rows written before the
              -- column existed are NULL and COALESCE to '', the same partition
              -- a standalone question asks from.
              AND COALESCE(context_hash, '') = %s{age_filter}
            ORDER BY similarity DESC
            LIMIT 1;
        """, tuple(params))
        row = cur.fetchone()

        # Clinical-equivalence gate. MiniLM cosine is a lexical proxy: "MTA
        # pulpotomy in PRIMARY molars" vs "...in PERMANENT molars", or vital vs
        # necrotic, or with vs without a periapical lesion, can all clear 0.92
        # while being different clinical questions with different answers.
        # Serving the wrong cached answer costs nothing to detect and is the
        # worst failure this system can have, so confirm before serving.
        if row and CACHE_EQUIVALENCE_CHECK and row["similarity"] < CACHE_EXACT_THRESHOLD:
            if not _same_clinical_question(question, row.get("question") or ""):
                print(f"  [cache] similar ({row['similarity']:.3f}) but clinically "
                      f"different — treating as MISS")
                return None

        if row:
            # Increment hit counter
            cur.execute("UPDATE query_cache SET hit_count = hit_count + 1 WHERE id = %s;", (row["id"],))
            conn.commit()

            created_at = row.get("created_at")
            age_days = None
            created_iso = None
            if created_at:
                try:
                    from datetime import datetime as _dt
                    age_days = (_dt.now() - created_at).days
                    created_iso = created_at.isoformat()
                except Exception:
                    pass

            return {
                "answer":     row["answer"],
                "papers":     row["papers"] or [],
                "created_at": created_iso,
                "age_days":   age_days,
            }
        return None
    except Exception as e:
        print(f"  Cache lookup error: {e}")
        return None
    finally:
        cur.close()
        conn.close()


# ── Abstract cache (PMID → title/abstract/meta) ──────────
# Populated for free during build_evidence_base() — every paper that gets
# scored has its abstract parsed from the efetch batch and stored here.
# When the UI clicks a [[PMID:N]] pill, /api/abstract serves from this
# table instantly instead of waiting on a live eutils round-trip.

def setup_abstract_cache():
    """Create abstract_cache table. Safe to run multiple times."""
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS abstract_cache (
                pmid       TEXT PRIMARY KEY,
                title      TEXT,
                abstract   TEXT,
                journal    TEXT,
                year       TEXT,
                authors    TEXT,
                source     TEXT DEFAULT 'efetch_batch',
                cached_at  TIMESTAMP DEFAULT NOW(),
                hit_count  INTEGER DEFAULT 0
            );
        """)
        conn.commit()
        print("Abstract cache table ready.")
    except Exception as e:
        conn.rollback()
        print(f"Abstract cache setup warning: {e}")
    finally:
        cur.close()
        conn.close()


def get_cached_abstract(pmid: str) -> dict | None:
    """Return cached abstract dict or None. Increments hit_count on hit."""
    if not DATABASE_URL or not pmid:
        return None
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, title, abstract, journal, year, authors, source, cached_at, hit_count
            FROM abstract_cache
            WHERE pmid = %s;
        """, (str(pmid),))
        row = cur.fetchone()
        if not row:
            return None
        # Increment hit counter — best-effort, don't fail the read on it
        try:
            cur.execute("UPDATE abstract_cache SET hit_count = hit_count + 1 WHERE pmid = %s;", (str(pmid),))
            conn.commit()
        except Exception:
            conn.rollback()
        return dict(row)
    except Exception as e:
        print(f"  Abstract cache lookup error: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def get_cached_abstracts_bulk(pmids: list) -> dict:
    """Return {pmid: {title, abstract, ...}} for every requested PMID found in
    the abstract cache. One query, no hit-count updates — used by the
    citation-support verifier, which reads many abstracts at once."""
    pmids = [str(p) for p in (pmids or []) if p]
    if not DATABASE_URL or not pmids:
        return {}
    conn = get_conn()
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("""
            SELECT pmid, title, abstract, journal, year, authors
            FROM abstract_cache
            WHERE pmid = ANY(%s);
        """, (pmids,))
        found = {row["pmid"]: dict(row) for row in cur.fetchall()}

        # Fall back to the curated RAG library for PMIDs the abstract cache
        # doesn't have — library papers were ingested offline and never pass
        # through the live-fetch cache, but their abstracts are just as usable
        # for the citation-support check.
        missing = [p for p in pmids if p not in found]
        if missing:
            cur.execute("""
                SELECT pmid, title, abstract, journal, year::text AS year, authors
                FROM endo_papers_rag
                WHERE pmid = ANY(%s);
            """, (missing,))
            for row in cur.fetchall():
                found.setdefault(row["pmid"], dict(row))
        return found
    except Exception as e:
        print(f"  Abstract cache bulk lookup error: {e}")
        return {}
    finally:
        cur.close()
        conn.close()


def cache_abstract(pmid: str, title: str = "", abstract: str = "",
                    journal: str = "", year: str = "", authors: str = "",
                    source: str = "efetch_batch") -> None:
    """Insert or update one abstract. Existing rows are updated only if the
    new payload has a non-empty abstract (we never overwrite a real abstract
    with a placeholder)."""
    if not DATABASE_URL or not pmid:
        return
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO abstract_cache (pmid, title, abstract, journal, year, authors, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (pmid) DO UPDATE SET
                title    = COALESCE(NULLIF(EXCLUDED.title,    ''), abstract_cache.title),
                abstract = CASE WHEN EXCLUDED.abstract IS NOT NULL AND length(EXCLUDED.abstract) >= 100
                                THEN EXCLUDED.abstract ELSE abstract_cache.abstract END,
                journal  = COALESCE(NULLIF(EXCLUDED.journal,  ''), abstract_cache.journal),
                year     = COALESCE(NULLIF(EXCLUDED.year,     ''), abstract_cache.year),
                authors  = COALESCE(NULLIF(EXCLUDED.authors,  ''), abstract_cache.authors),
                source   = EXCLUDED.source;
        """, (str(pmid), title or "", abstract or "", journal or "",
              year or "", authors or "", source))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  Abstract cache write error (pmid={pmid}): {e}")
    finally:
        cur.close()
        conn.close()


def bulk_cache_abstracts(entries: list) -> int:
    """Bulk-insert a list of {pmid, title, abstract, journal, year, authors}
    dicts. Returns number of rows touched.

    Used by fetch_papers() so every PubMed pull populates the cache as a
    side-effect — the user never sees a cache miss for papers we've already
    scored into an evidence base.
    """
    if not DATABASE_URL or not entries:
        return 0
    conn = get_conn()
    cur  = conn.cursor()
    n = 0
    try:
        for e in entries:
            pmid = (e.get("pmid") or "").strip()
            if not pmid:
                continue
            cur.execute("""
                INSERT INTO abstract_cache (pmid, title, abstract, journal, year, authors, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (pmid) DO UPDATE SET
                    title    = COALESCE(NULLIF(EXCLUDED.title,    ''), abstract_cache.title),
                    abstract = CASE WHEN EXCLUDED.abstract IS NOT NULL AND length(EXCLUDED.abstract) >= 100
                                    THEN EXCLUDED.abstract ELSE abstract_cache.abstract END,
                    journal  = COALESCE(NULLIF(EXCLUDED.journal,  ''), abstract_cache.journal),
                    year     = COALESCE(NULLIF(EXCLUDED.year,     ''), abstract_cache.year),
                    authors  = COALESCE(NULLIF(EXCLUDED.authors,  ''), abstract_cache.authors),
                    source   = EXCLUDED.source;
            """, (pmid, e.get("title") or "", e.get("abstract") or "",
                  e.get("journal") or "", e.get("year") or "",
                  e.get("authors") or "", e.get("source") or "efetch_batch"))
            n += 1
        conn.commit()
    except Exception as ex:
        conn.rollback()
        print(f"  Bulk abstract cache write error: {ex}")
    finally:
        cur.close()
        conn.close()
    return n


def save_query_cache(question: str, answer: str, papers: list,
                     context_hash: str = ""):
    """Store a completed question+answer in the cache.

    `context_hash` must be the SAME fingerprint the lookup will present — an
    answer stored under a context and looked up without one (or under a
    different one) is simply never found again, which is the safe direction but
    also a permanently cold cache. app.py computes it once per job.
    """
    if not DATABASE_URL:
        return
    try:
        q_vec = embed(question)
    except Exception:
        return

    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO query_cache (question_text, question_embedding, answer,
                                     papers, context_hash)
            VALUES (%s, %s, %s, %s, %s);
        """, (question, q_vec, answer, json.dumps(papers), (context_hash or "")))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  Cache save error: {e}")
    finally:
        cur.close()
        conn.close()


# ── Library stats ─────────────────────────────────────────

def library_stats() -> dict:
    """Return stats about what's in the library."""
    conn = get_conn()
    cur  = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM endo_papers_rag;")
        total = cur.fetchone()[0]

        cur.execute("""
            SELECT level_key, COUNT(*)
            FROM endo_papers_rag
            GROUP BY level_key
            ORDER BY level_key;
        """)
        by_level = dict(cur.fetchall())

        cur.execute("SELECT MIN(year), MAX(year) FROM endo_papers_rag;")
        row = cur.fetchone()
        year_range = f"{row[0]}–{row[1]}" if row[0] else "empty"

        return {
            "total":      total,
            "by_level":   by_level,
            "year_range": year_range,
        }
    finally:
        cur.close()
        conn.close()
