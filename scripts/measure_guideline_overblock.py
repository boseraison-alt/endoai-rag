"""Item D finding — item 3's guard is blocking CURRENT guidelines.

WHAT THE BASELINE FOUND. Across the three v8 runs the guard logged drops of
`AAE-MRONJ-2026`, `COCHRANE-CD005296`, `COCHRANE-CD004969` and `AAE-VPT-2021`.
All four documents are `current`, unquarantined and unsuperseded. One of them,
`COCHRANE-CD005296`, is PMID 36512807 — the row `single-vs-multiple-visit`
pins with `must_include_pmid`, and the one the batch said to leave alone
because it is a real criterion.

THE MECHANISM, which is the redirect story wearing a new hat. When a document
is re-keyed from its manifest slug to its real PMID, the old slug-keyed row
stays behind as a forwarding stub:

    pmid='COCHRANE-CD005296'  status='current'
    quarantine_reason='re-keyed: this document is 36512807'

`non_current_guideline_keys()` disqualifies on `quarantine_reason <> ''`, so
the stub qualifies; the loop then adds the stub's `pmid` column, which holds
the SLUG. The guard drops anything whose `guideline_id` is that slug — and the
only row that carries it is the current, re-keyed document itself.

A POINTER IS NOT A DOCUMENT. `re-keyed:` and `duplicate_of:` are forwarding
addresses, not judgements about content. Whether the target may be served is
decided by the target's own row, which is in the set on its own facts when it
deserves to be — `ESE-QG-2006`'s stub says `duplicate_of:17180780`, and 17180780
is independently `superseded`, so that slug stays blocked either way.

    python scripts/measure_guideline_overblock.py
"""
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import endo_ai as E  # noqa: E402
import rag  # noqa: E402

DROP = re.compile(
    r"\[guideline_status\] dropped (\d+) non-current guideline\(s\) "
    r"from ([\w-]+): (.+)$")
# The two quarantine reasons that are FORWARDING ADDRESSES rather than verdicts.
POINTER = re.compile(r"^\s*(re-keyed|duplicate_of)\b", re.I)


def target_state(conn):
    """For every key in the block set, what the document itself actually is."""
    cur = conn.cursor()
    cur.execute("""
        SELECT pmid, COALESCE(guideline_id,''), COALESCE(guideline_status,''),
               COALESCE(quarantine_reason,''), COALESCE(superseded_by,'')
        FROM endo_papers_rag
        WHERE level_key = 'guideline'
    """)
    rows = cur.fetchall()
    # A re-keyed guideline can land on any ladder — COCHRANE-CD005296 re-keys
    # onto `cochrane` — so a guideline-only lookup cannot see the document a
    # stub points at, and reports an over-block it cannot explain.
    targets = sorted({t for t in (E._pointer_target(r[3]) for r in rows) if t})
    if targets:
        cur.execute("""
            SELECT pmid, COALESCE(guideline_id,''),
                   COALESCE(guideline_status,''),
                   COALESCE(quarantine_reason,''), COALESCE(superseded_by,'')
            FROM endo_papers_rag
            WHERE level_key <> 'guideline'
              AND (pmid = ANY(%s) OR guideline_id = ANY(%s))
        """, (targets, targets))
        rows = rows + list(cur.fetchall())
    cur.close()
    by_key = {}
    for pmid, gid, status, quar, sup in rows:
        for k in (str(pmid or "").strip(), str(gid or "").strip()):
            if k:
                by_key.setdefault(k, []).append(
                    {"pmid": pmid, "gid": gid, "status": status,
                     "quar": quar, "sup": sup})
    return by_key


def verdict(key, by_key):
    """Is blocking `key` correct? Decided on the documents that carry it.

    A key is correctly blocked if ANY row carrying it is genuinely unservable
    — bad status, a real quarantine, or a supersession. A key whose only
    disqualifying row is a forwarding stub is an OVER-BLOCK: the stub is a
    pointer, and the document it points at is fine.
    """
    rows = by_key.get(key, [])
    if not rows:
        return "unknown", "no row carries this key"
    real, stubs = [], []
    for r in rows:
        pointer = bool(POINTER.match(r["quar"] or ""))
        bad_status = (r["status"] or "").lower() not in E.CURRENT_GUIDELINE_STATUSES
        if bad_status or r["sup"] or ((r["quar"] or "") and not pointer):
            real.append(r)
        elif pointer:
            stubs.append(r)
    if real:
        return "correct", "%s" % (real[0]["status"] or real[0]["quar"][:40])
    if stubs:
        return "OVER-BLOCK", "forwarding stub only: %s" % stubs[0]["quar"][:60]
    return "OVER-BLOCK", "no disqualifying fact on any row"


def main():
    # NOT "/tmp/...": Git Bash rewrites POSIX paths in ARGUMENTS when it calls
    # a Windows program, but a string hardcoded in Python gets none of that and
    # resolves to C:\tmp, which does not exist. The first version of this
    # script read three missing files, reported 0 drop events, and looked like
    # a clean result. A default that cannot be found must not read as a zero.
    tmp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")
    logs = sys.argv[1:] or [str(tmp / ("v8_run%d.log" % i)) for i in (1, 2, 3)]
    missing = [p for p in logs if not Path(p).exists()]
    if missing:
        print("  MISSING LOG(S): %s" % ", ".join(missing))
        print("  Refusing to report drop counts from logs that were not read.")
        return 1
    conn = rag.get_conn()
    by_key = target_state(conn)

    print("=" * 78)
    print("ITEM D FINDING — IS THE GUARD BLOCKING CURRENT GUIDELINES?")
    print("=" * 78)
    keys = E.non_current_guideline_keys()
    print("  block-set size          : %d" % len(keys))
    over = {k: verdict(k, by_key) for k in sorted(keys)}
    bad = {k: v for k, v in over.items() if v[0] == "OVER-BLOCK"}
    unk = {k: v for k, v in over.items() if v[0] == "unknown"}
    print("  correctly blocked       : %d"
          % sum(1 for v in over.values() if v[0] == "correct"))
    print("  OVER-BLOCKED (current)  : %d" % len(bad))
    print("  no row carries the key  : %d" % len(unk))
    print()
    if bad:
        print("  THE OVER-BLOCKED KEYS")
        for k, (_, why) in sorted(bad.items()):
            tgt = [r for r in by_key.get(k, [])
                   if not POINTER.match(r["quar"] or "")]
            served = ("; document lives at PMID %s, status %s"
                      % (tgt[0]["pmid"], tgt[0]["status"])) if tgt else ""
            print("    %-28s %s%s" % (k, why, served))
        print()

    # ── what it cost the baseline ───────────────────────────────────────────
    events, rows_dropped = Counter(), Counter()
    lanes = Counter()
    for lg in logs:
        p = Path(lg)
        if not p.exists():
            continue
        for ln in p.read_text(encoding="utf-8", errors="replace").split("\n"):
            m = DROP.search(ln)
            if not m:
                continue
            n, lane, ids = int(m.group(1)), m.group(2), m.group(3)
            for gid in [s.strip() for s in ids.split(",") if s.strip()]:
                events[gid] += 1
                lanes[(lane, gid)] += 1
            rows_dropped[lane] += n

    print("  DROPS LOGGED ACROSS THE THREE V8 RUNS")
    print("  %-34s %-8s %s" % ("key", "events", "verdict"))
    tot_ok = tot_bad = 0
    for gid, n in events.most_common():
        v = over.get(gid, verdict(gid, by_key))
        print("  %-34s %-8d %s" % (gid, n, v[0]))
        if v[0] == "correct":
            tot_ok += n
        else:
            tot_bad += n
    print()
    print("  drop events, correct    : %d" % tot_ok)
    print("  drop events, OVER-BLOCK : %d" % tot_bad)
    print()
    print("  BY LANE (which pool lost a current guideline)")
    for (lane, gid), n in sorted(lanes.items()):
        if over.get(gid, ("", ""))[0] == "OVER-BLOCK":
            print("    %-16s %-30s %d event(s)" % (lane, gid, n))
    print()
    print("  Live lanes are unaffected: a PubMed row carries no `guideline_id`,")
    print("  so only its PMID is checked and the PMID was never in the set. The")
    print("  rows lost are the LIBRARY's own copies — the curated documents the")
    print("  union exists to contribute.")

    Path("eval/reports").mkdir(parents=True, exist_ok=True)
    json.dump({"block_set": len(keys),
               "over_blocked": {k: v[1] for k, v in bad.items()},
               "unknown": {k: v[1] for k, v in unk.items()},
               "drop_events": dict(events),
               "events_correct": tot_ok, "events_overblock": tot_bad},
              open("eval/reports/item_d_guideline_overblock.json", "w",
                   encoding="utf-8"), indent=1)
    print("\n  wrote eval/reports/item_d_guideline_overblock.json")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
