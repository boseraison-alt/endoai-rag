"""Dump every public table to CSV and VERIFY the dump against a live count.

`pg_dump` is not on this machine's PATH, so the dump goes through psycopg2's
`COPY ... TO STDOUT WITH CSV HEADER`.

The verification is the point. A dump whose row count is not checked is a
belief, not a backup — and line-counting the file is NOT a row count here:
abstracts contain embedded newlines, so a 3,164-row table can be 40,000 lines.
Every file is re-read with the `csv` module, which is the only reader that
agrees with the writer about where a row ends.

Usage:  python scripts/dump_db.py <outdir>
Exit 1 if ANY table's dumped row count differs from its live count.
"""
import csv
import gzip
import os
import sys

sys.path.insert(0, os.getcwd())
csv.field_size_limit(1024 * 1024 * 64)

import rag  # noqa: E402


def tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename")
        return [r[0] for r in cur.fetchall()]


def live_count(conn, t):
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM "%s"' % t)
        return cur.fetchone()[0]


def dump_one(conn, t, outdir):
    path = os.path.join(outdir, "%s.csv.gz" % t)
    with conn.cursor() as cur, gzip.open(path, "wt", encoding="utf-8",
                                         newline="") as fh:
        cur.copy_expert('COPY (SELECT * FROM "%s") TO STDOUT WITH CSV HEADER' % t,
                        fh)
    return path


def dumped_count(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        r = csv.reader(fh)
        next(r, None)                      # header
        return sum(1 for _ in r)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "db_dump"
    os.makedirs(outdir, exist_ok=True)
    conn = rag.get_conn()

    print("%-42s %10s %10s %8s %s" % ("table", "live", "dumped", "MB", "ok"))
    bad = []
    total_live = total_dumped = 0
    for t in tables(conn):
        live = live_count(conn, t)
        path = dump_one(conn, t, outdir)
        got = dumped_count(path)
        mb = os.path.getsize(path) / 1e6
        ok = (live == got)
        if not ok:
            bad.append((t, live, got))
        total_live += live
        total_dumped += got
        print("%-42s %10d %10d %8.1f %s"
              % (t, live, got, mb, "OK" if ok else "MISMATCH"))

    print("%-42s %10d %10d" % ("TOTAL", total_live, total_dumped))
    if bad:
        print("\nFAILED BACKUP — %d table(s) disagree:" % len(bad))
        for t, live, got in bad:
            print("  %s: live=%d dumped=%d" % (t, live, got))
        return 1
    print("\nall %d tables verified, %d rows" % (len(tables(conn)), total_live))
    return 0


if __name__ == "__main__":
    sys.exit(main())
