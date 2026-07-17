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
import psycopg2
import psycopg2.extras
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
    """Embed a string into a 384-dim vector."""
    model  = get_model()
    vector = model.encode(text[:512], normalize_embeddings=True)
    return vector.tolist()


# ── Database ──────────────────────────────────────────────

def get_conn():
    return psycopg2.connect(DATABASE_URL)


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
                embedding     vector(384),
                added_at      TIMESTAMP DEFAULT NOW()
            );
        """)
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
    Returns papers sorted by similarity × score.
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
                    citations, level_key, score,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM endo_papers_rag
                WHERE level_key = %s
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY (score * 0.6 + (1 - (embedding <=> %s::vector)) * 40) DESC
                LIMIT %s;
            """, (query_vec, level_key, query_vec, similarity_threshold, query_vec, limit))
        else:
            cur.execute("""
                SELECT
                    pmid, title, abstract, authors, year, journal,
                    impact_factor, sample_size, followup_months,
                    citations, level_key, score,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM endo_papers_rag
                WHERE 1 - (embedding <=> %s::vector) >= %s
                ORDER BY (score * 0.6 + (1 - (embedding <=> %s::vector)) * 40) DESC
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
    """Convert RAG DB rows to the same dict format as endo_ai.score_paper output."""
    papers = []
    for r in rows:
        papers.append({
            "pmid":            r.get("pmid", ""),
            "year":            str(r.get("year", "Unknown")),
            "citations":       r.get("citations", 0),
            "authors":         r.get("authors", ""),
            "sample_size":     r.get("sample_size"),
            "followup_months": r.get("followup_months"),
            "journal":         r.get("journal", ""),
            "impact_factor":   r.get("impact_factor"),
            "score":           round(float(r.get("score", 0)), 1),
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
                created_at        TIMESTAMP DEFAULT NOW()
            );
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


def get_cached_answer(question: str, threshold: float = 0.92,
                       max_age_days: int = None) -> dict | None:
    """
    Return a cached answer if a semantically similar question was asked before.
    Returns dict with 'answer', 'papers', 'created_at' (ISO str), and 'age_days'
    on hit, or None on miss.

    `max_age_days` — optional cap. Used by Deep Learning mode (7-day TTL) to
    avoid serving stale cached curricula. Other modes pass None for "no limit".
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
        params     = [q_vec, q_vec, threshold]
        if max_age_days is not None and max_age_days > 0:
            age_filter = " AND created_at >= NOW() - INTERVAL '%s days'"
            params.append(int(max_age_days))

        cur.execute(f"""
            SELECT id, answer, papers, created_at,
                   1 - (question_embedding <=> %s::vector) AS similarity
            FROM query_cache
            WHERE 1 - (question_embedding <=> %s::vector) >= %s{age_filter}
            ORDER BY similarity DESC
            LIMIT 1;
        """, tuple(params))
        row = cur.fetchone()
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


def save_query_cache(question: str, answer: str, papers: list):
    """Store a completed question+answer in the cache."""
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
            INSERT INTO query_cache (question_text, question_embedding, answer, papers)
            VALUES (%s, %s, %s, %s);
        """, (question, q_vec, answer, json.dumps(papers)))
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
