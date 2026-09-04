"""Run the SHIPPED JavaScript out of `templates/index.html` under node.

WHY THIS IS SHARED. Three test files pulled named declarations out of the
template with their own copy of the same extractor, each carrying its own list
of names. That list is a dependency graph maintained by hand, and it drifted
twice inside one batch: `trust-surface-v1` Q4 gave `renderAnswer` two new
helpers and `test_streaming.py` went red with a ReferenceError; Q2 gave it
three more and the same thing happened to a second file. Neither failure was
about the behaviour under test.

`RENDER_DEPS` is now the single list of everything `renderAnswer` and
`renderAnswerWithBox` need, in dependency order. A test that wants more names
passes `extra=[...]`.

The extraction rules come from the template's own formatting: every
declaration in that script block starts at column 0, a function ends at the
first line that is exactly `}`, and a `var` at the first line ending in `;`.
Brace counting is not usable — the renderers are full of regex literals like
/\\n{2,}/ that would unbalance it.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).parent.parent / "templates" / "index.html"

# Everything the answer renderer touches, in dependency order.
RENDER_DEPS = [
    # citation keys and metadata (`trust-surface-v1` Q4)
    "PMID_KEY_SRC", "isNumericPmid", "pmidRefHtml",
    "_citeEsc", "pmidMeta", "formatCite",
    # headings
    "deShout",
    # the unverified block (`trust-surface-v1` Q2). A22c added a SECOND
    # pattern — stored answers carry the pre-A22f header and footer, and A16b
    # re-renders the archive on every read — so both regexes and the shared
    # `_stashOne` are dependencies now.
    "_QUARANTINE_BLOCK_RE_JS", "_QUARANTINE_LEGACY_RE_JS",
    # Invariant 3 — the citation replacer is shared by `renderAnswer` and
    # `_unverifiedInline` now, because a quarantine block was the one rendered
    # surface where `[[PMID:N]]` survived raw (30 of them on one stored
    # curriculum). It must be extracted before both of them.
    "_citeMarkersToPills",
    "_unverifiedInline", "_stashOne", "_stashUnverifiedBlocks",
    # the renderers themselves
    "renderAnswer", "_recommendationTier", "renderAnswerWithBox",
    # A3c — the flagged claims are marked in the rendered answer
    "_uncitedClaimQuotes", "_reEscape", "markUncitedClaims",
]

# The trust banner and the blockquote it is built from.
CHIP_DEPS = ["CHIPS_CHECKING", "buildTrustChips",
             "_SUPPORT_BLOCKQUOTE_RE", "_stripSupportBlockquote"]


def extract_js(names):
    """Pull named top-level declarations out of index.html, in the order given."""
    src = INDEX_HTML.read_text(encoding="utf-8").split("\n")
    out = []
    for name in names:
        start, is_fn = None, False
        for i, line in enumerate(src):
            if line.startswith("function %s(" % name):
                start, is_fn = i, True
                break
            if line.startswith("var %s " % name) or line.startswith("var %s=" % name):
                start, is_fn = i, False
                break
        assert start is not None, "%s not found as a top-level declaration" % name
        j = start
        while j < len(src):
            if is_fn and j > start and src[j] == "}":
                break
            if not is_fn and src[j].rstrip().endswith(";"):
                break
            j += 1
        assert j < len(src), "could not find the end of %s" % name
        out.append("\n".join(src[start:j + 1]))
    return "\n\n".join(out)


def run_node(js_body, names=None, mode="review", preamble=""):
    """Evaluate `js_body` against the shipped declarations; parse its last line
    of stdout as JSON."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available - cannot exercise the shipped JS")
    prog = ("var mode = %s;\nvar trunc = function(s){return s;};\n" % json.dumps(mode)
            + preamble + extract_js(names or RENDER_DEPS) + "\n" + js_body)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(prog)
        path = f.name
    try:
        r = subprocess.run([node, path], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        os.unlink(path)
