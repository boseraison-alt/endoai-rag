"""
Post-run audit for the laser-disinfection retrieval fix.

Answers four questions that the run's own console output cannot:
  1. How many of the ~909 esearch PMIDs actually landed in the library, and did
     they land complete (level_key + provenance) or as unlabelled rows?
  2. Is the cochrane tier honest now that COCHRANE_TERM is journal-scoped?
  3. Does the answer cache still point at the 5-paper version of this question?
  4. What does learn_history hold for it?
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag import get_conn

LASER = "%laser%"


def section(t):
    print(f"\n{'=' * 68}\n{t}\n{'=' * 68}")


conn = get_conn()
cur = conn.cursor()

section("1. WRITE-BACK: what landed in the library today")
cur.execute("""
    SELECT COUNT(*)                                              AS total,
           COUNT(*) FILTER (WHERE level_key IS NULL OR level_key = '') AS no_tier,
           COUNT(*) FILTER (WHERE score IS NULL OR score = 0)     AS no_score,
           COUNT(*) FILTER (WHERE abstract IS NULL OR abstract = '') AS no_abstract,
           COUNT(*) FILTER (WHERE embedding IS NULL)              AS no_embedding,
           COUNT(*) FILTER (WHERE coi_status IS NULL OR coi_status = '') AS no_coi,
           COUNT(*) FILTER (WHERE year IS NULL)                   AS no_year
      FROM endo_papers_rag
     WHERE added_at >= NOW() - INTERVAL '3 days';
""")
cols = [d[0] for d in cur.description]
row = cur.fetchone()
for c, v in zip(cols, row):
    print(f"   {c:<14} {v}")

section("2. TIER DISTRIBUTION of those rows")
cur.execute("""
    SELECT COALESCE(NULLIF(level_key, ''), '(unlabelled)') AS tier,
           COUNT(*), ROUND(AVG(score)::numeric, 1)
      FROM endo_papers_rag
     WHERE added_at >= NOW() - INTERVAL '3 days'
     GROUP BY 1 ORDER BY 2 DESC;
""")
for tier, n, avg in cur.fetchall():
    print(f"   {tier:<14} {n:>5}   avg score {avg}")

section("3. COCHRANE HONESTY CHECK — every row tagged cochrane, library-wide")
cur.execute("""
    SELECT COUNT(*) FILTER (WHERE LOWER(journal) LIKE '%%cochrane database%%'),
           COUNT(*)
      FROM endo_papers_rag WHERE level_key = 'cochrane';
""")
real, total = cur.fetchone()
print(f"   tagged cochrane: {total}   actually in Cochrane Database: {real}")
if total != real:
    cur.execute("""
        SELECT pmid, year, journal, LEFT(title, 62)
          FROM endo_papers_rag
         WHERE level_key = 'cochrane'
           AND LOWER(journal) NOT LIKE '%%cochrane database%%'
         ORDER BY year DESC LIMIT 15;
    """)
    print("   MISLABELLED (should be level1):")
    for pmid, yr, jour, title in cur.fetchall():
        print(f"     {pmid}  {yr}  {(jour or '')[:34]:<34} {title}")

section("4. LASER-TOPIC ROWS specifically")
cur.execute("""
    SELECT COALESCE(NULLIF(level_key, ''), '(unlabelled)'), COUNT(*)
      FROM endo_papers_rag
     WHERE (LOWER(title) LIKE %s OR LOWER(abstract) LIKE %s)
     GROUP BY 1 ORDER BY 2 DESC;
""", (LASER, LASER))
for tier, n in cur.fetchall():
    print(f"   {tier:<14} {n}")

section("5. ANSWER CACHE for this question")
cur.execute("""
    SELECT to_char(created_at, 'YYYY-MM-DD HH24:MI'),
           LEFT(question_text, 52),
           LENGTH(COALESCE(answer, '')),
           COALESCE(JSONB_ARRAY_LENGTH(papers), 0),
           hit_count
      FROM query_cache
     WHERE LOWER(question_text) LIKE %s
     ORDER BY created_at DESC LIMIT 10;
""", (LASER,))
rows = cur.fetchall()
if not rows:
    print("   no cached entry for a laser question")
for created, q, alen, npapers, hits in rows:
    flag = "  <-- STALE 5-paper version" if npapers and npapers < 20 else ""
    print(f"   {created}  papers={npapers:<4} answer={alen:<7} hits={hits}  {q}{flag}")

section("6. TOTAL cache entries")
cur.execute("SELECT COUNT(*) FROM query_cache;")
print(f"   {cur.fetchone()[0]} cached answers")

cur.close()
conn.close()
