"""Item E precondition 1 (2026-09-07) — retracted and quarantined are terminal.

THE ROW THIS EXISTS FOR. The 2026-09-06 reband dry run would have moved TWO
rows `retracted -> level1`, because their publication types say "Randomized
Controlled Trial" and the derivation believed them. A retracted paper is
retracted whatever its publication types say, and promoting one to the top of
the evidence ladder is the worst single move this script could make.

A quarantined row is terminal for the mirror-image reason: it was taken out of
retrieval on purpose, and rebanding it would re-band a row somebody removed
deliberately.

The two retracted rows are real, from the live library.
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rag import get_conn


def _q(sql, args=None):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, args or ())
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


class TestTheScriptCannotMoveATerminalRow:

    def test_the_script_has_no_apply_flag_at_all(self):
        """Rebanding changes level_key across the corpus, level_key carries
        39% of the score, and the score orders every pool. RB decides.

        THE ASSERTION IS ON THE FLAG, NOT THE STRING. A bare
        `"--apply" not in src` fails on the script's own prose, which says
        "No `--apply` exists on this script" and "DRY RUN. NO --apply." —
        the documentation of the absence would have been read as the presence.
        """
        src = open(os.path.join(ROOT, "scripts", "reband_from_pubtype.py"),
                   encoding="utf-8").read()
        assert 'add_argument("--apply"' not in src, (
            "an --apply flag was added to the reband script")
        assert "args.apply" not in src, (
            "the reband script reads an apply flag")
        assert "UPDATE endo_papers_rag" not in src, (
            "the reband script contains a write")

    def test_retracted_is_skipped_before_any_derivation(self):
        src = open(os.path.join(ROOT, "scripts", "reband_from_pubtype.py"),
                   encoding="utf-8").read()
        i = src.index('if stored == "retracted":')
        j = src.index("tier_from_pubtypes(", i)
        assert j > i, (
            "the retracted check must come BEFORE the derivation, or a "
            "retracted row is derived and only then discarded")

    def test_the_query_excludes_quarantined_rows(self):
        src = open(os.path.join(ROOT, "scripts", "reband_from_pubtype.py"),
                   encoding="utf-8").read()
        assert "COALESCE(quarantine_reason,'') = ''" in src

    def test_the_library_really_holds_retracted_rows_to_skip(self):
        """Rule 34. If the corpus had no retracted rows, every assertion above
        would pass over an empty set and prove nothing."""
        rows = _q("SELECT COUNT(*) FROM endo_papers_rag "
                  "WHERE level_key = 'retracted'")
        assert rows[0][0] > 0, (
            "no retracted rows in the library — this guard is untested")


class TestTheGuardActuallyRuns:
    """Behavioural, not source-shape. The tests above read the file; this one
    runs it over a slice that contains a retracted row and checks the output."""

    def test_a_retracted_row_appears_as_terminal_never_as_a_change(self):
        rows = _q("""SELECT pmid FROM endo_papers_rag
                     WHERE level_key = 'retracted'
                       AND pmid ~ '^[0-9]+$'
                     ORDER BY pmid LIMIT 1""")
        if not rows:
            pytest.skip("no numeric-PMID retracted row")
        pmid = rows[0][0]
        # A handful of rows, not 3,323: the guard is per-row, so exercising it
        # on the retracted row plus a control proves the same thing in seconds.
        control = _q("""SELECT pmid FROM endo_papers_rag
                        WHERE level_key = 'level5' AND pmid ~ '^[0-9]+$'
                          AND COALESCE(quarantine_reason,'') = ''
                          AND NOT COALESCE(is_curated, FALSE)
                        ORDER BY pmid LIMIT 3""")
        out = subprocess.run(
            [sys.executable, os.path.join("scripts", "reband_from_pubtype.py"),
             "--pmids", ",".join([pmid] + [c[0] for c in control]),
             "--out", os.path.join("eval", "reports", "_reband_probe.md")],
            cwd=ROOT, capture_output=True, text=True, timeout=3600,
            encoding="utf-8", errors="replace")
        assert out.returncode == 0, out.stderr[-2000:]
        text = out.stdout
        assert "TERMINAL, never moved" in text
        # the retracted row must be listed as terminal...
        term_block = text.split("TERMINAL, never moved")[1].split(
            "derived == stored")[0]
        assert pmid in term_block, (
            "%s is retracted but not listed as terminal" % pmid)
        # ...and must NOT appear in the change list
        change_block = text.split("EVERY ROW THAT WOULD CHANGE")[-1]
        assert pmid not in change_block, (
            "%s is retracted and would still be moved" % pmid)
