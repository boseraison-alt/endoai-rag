"""Rule 42 — code and data are written with the file tools, never a heredoc.

TWO INCIDENTS, ONE CAUSE. Writing source through a shell heredoc silently ate
backslashes on 2026-09-08 and again on 2026-09-09:

  `r"\\b%s\\b"` became `r"\x08%s\x08"` — two literal BACKSPACE bytes. `grep`
  could not see them, `inspect.getsource` rendered the line as an innocuous
  substring match, and `species_from_reason` returned "unspecified" for every
  input while looking correct in every view of it. It was found only by dumping
  the code object's constants.

  `"\\n"` became a real newline inside a string literal, three times, breaking
  `ingest_guideline_text_files.py` and `app.py` at parse time. Those were cheap
  because Python refused to run them. The backspace was expensive because it
  ran fine.

This file makes the cheap failure the only possible one. A control byte in a
tracked text file fails the suite; a corpus file whose bytes drifted from its
sidecar fails it too.

THE CRLF HALF is the second finding of 2026-09-08. Every one of the thirteen
browser-fetched guideline files failed its sidecar hash on a clean
`git status`, with nothing edited: git stores them LF and had checked them out
CRLF on a Windows tree. `.gitattributes` now marks that corpus `-text`, and
this test is what notices if that protection is ever removed.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Tab, newline and carriage return are the legitimate ones. Everything else in
# C0 — backspace, form feed, vertical tab, the escape byte, NUL — has no place
# in source or in prose, and every instance this repo has seen arrived by
# accident.
FORBIDDEN = {c for c in range(0x00, 0x20)} - {0x09, 0x0A, 0x0D}
FORBIDDEN.add(0x7F)                       # DEL

EXTENSIONS = (".py", ".md", ".json", ".txt")


def _tracked_text_files():
    """Files git tracks, filtered to the text kinds this rule covers.

    Read from git rather than the filesystem so a stray file in a scratch
    directory cannot fail the suite, and so the set is the one that actually
    ships.
    """
    try:
        out = subprocess.run(["git", "ls-files"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=60)
    except Exception as ex:                      # pragma: no cover
        pytest.skip("git not available: %s" % ex)
    if out.returncode != 0:                      # pragma: no cover
        pytest.skip("git ls-files failed")
    files = []
    for line in out.stdout.splitlines():
        name = line.strip()
        if not name or not name.endswith(EXTENSIONS):
            continue
        p = ROOT / name
        if p.is_file():
            files.append(p)
    return files


class TestNoControlBytes:

    def test_the_input_is_not_empty(self):
        """A zero is only meaningful beside the size of the input that produced
        it (rule 34). If `git ls-files` ever returns nothing, the test below
        passes vacuously and this is what says so."""
        files = _tracked_text_files()
        assert len(files) > 200, (
            "only %d tracked text files found — the scan is not covering the "
            "repository" % len(files))

    def test_no_tracked_text_file_contains_a_control_byte(self):
        offenders = []
        for p in _tracked_text_files():
            try:
                raw = p.read_bytes()
            except OSError:                      # pragma: no cover
                continue
            bad = FORBIDDEN & set(raw)
            if bad:
                # Report the byte AND where, because "there is a backspace
                # somewhere in a 14,000-line file" is not actionable.
                idx = next(i for i, b in enumerate(raw) if b in FORBIDDEN)
                line = raw[:idx].count(b"\n") + 1
                offenders.append("%s:%d contains %s"
                                 % (p.relative_to(ROOT), line,
                                    ", ".join("0x%02x" % b
                                              for b in sorted(bad))))
        assert not offenders, (
            "control bytes in tracked text files (rule 42 — written through a "
            "shell heredoc?):\n  " + "\n  ".join(offenders[:20]))

    def test_the_detector_finds_a_planted_byte(self, tmp_path):
        """MUTATION CHECK. Plant a backspace — the exact byte that broke
        `species_from_reason` — and confirm the scan would catch it."""
        p = tmp_path / "planted.py"
        p.write_bytes(b'PATTERN = r"\x08word\x08"\n')
        raw = p.read_bytes()
        assert FORBIDDEN & set(raw), (
            "the scan does not treat a backspace byte as forbidden, which is "
            "the byte the rule exists for")

    def test_tab_newline_and_cr_are_allowed(self):
        """The control bytes that legitimately appear in text must NOT fire,
        or the test above is unusable and will be deleted rather than fixed."""
        assert not (FORBIDDEN & set(b"a\tb\nc\r\n"))


@pytest.mark.skipif(not (ROOT / "data" / "guideline_text").exists(),
                    reason="no browser-fetched corpus in this checkout")
class TestTheGuidelineCorpusMatchesItsSidecars:

    def _pairs(self):
        d = ROOT / "data" / "guideline_text"
        return [(j, j.with_suffix(".txt")) for j in sorted(d.glob("*.json"))]

    def test_there_are_files_to_check(self):
        pairs = self._pairs()
        assert pairs, "no sidecars — this class would pass vacuously"
        assert all(t.exists() for _j, t in pairs), (
            "a sidecar with no .txt beside it")

    def test_every_file_hashes_to_its_sidecar_on_this_checkout(self):
        """The bytes on disk, not normalised. Normalising before hashing is the
        tempting fix and it would silently weaken the one check that makes
        "the library quotes what the publisher published" verifiable."""
        bad = []
        for j, t in self._pairs():
            meta = json.loads(j.read_text(encoding="utf-8"))
            raw = t.read_bytes()
            got = hashlib.sha256(raw).hexdigest()
            if got != (meta.get("sha256") or ""):
                crlf = (hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
                        == meta.get("sha256"))
                bad.append("%s: %s" % (
                    t.name,
                    "CRLF line endings — git rewrote it on checkout; "
                    ".gitattributes must mark data/guideline_text/* as -text"
                    if crlf else "content differs from the sidecar"))
        assert not bad, "\n  ".join(bad)

    def test_no_corpus_file_has_crlf_line_endings(self):
        """The direct form of the same property, so the failure names the cause
        rather than two hex strings."""
        crlf = [t.name for _j, t in self._pairs()
                if b"\r\n" in t.read_bytes()]
        assert not crlf, (
            "CRLF in the content-addressed corpus, which breaks every sidecar "
            "hash: %s" % crlf)

    def test_the_crlf_detector_would_catch_a_converted_file(self, tmp_path):
        """MUTATION CHECK: convert a copy to CRLF and confirm both the hash
        check and the line-ending check would fire."""
        j, t = self._pairs()[0]
        meta = json.loads(j.read_text(encoding="utf-8"))
        converted = t.read_bytes().replace(b"\n", b"\r\n")
        assert b"\r\n" in converted
        assert hashlib.sha256(converted).hexdigest() != meta["sha256"], (
            "converting a corpus file to CRLF did not change its hash — the "
            "sidecar check cannot detect the 2026-09-08 failure")


class TestTheProtectionIsDeclared:

    def test_gitattributes_marks_the_corpus_as_binary(self):
        p = ROOT / ".gitattributes"
        assert p.exists(), (
            ".gitattributes is gone; git will convert the content-addressed "
            "corpus to CRLF on the next Windows checkout")
        text = p.read_text(encoding="utf-8")
        assert "data/guideline_text/*.txt -text" in text
        assert "data/guideline_text/*.json -text" in text
