"""Narration pronunciation dictionary (PRESENTATION_WORKLIST §4.2).

Text-to-speech engines mangle endodontic notation. "Er,Cr:YSGG" comes out as
"er cr ysgg", "NaOCl" as "naockle", "EDTA" as "edta". This module holds the
substitution data and applies it **to the narration script only** — the text a
clinician reads on a slide or in the answer pane must still say "Er:YAG".

Two rules make the substitution safe:

1. **Longest term first.** Terms overlap: "Er,Cr:YSGG" contains "YSGG". If the
   short term were applied first you would get the mangled hybrid
   "Er,Cr:Y-S-G-G" instead of "erbium chromium Y-S-G-G". Every term is sorted
   by length descending and compiled into ONE alternation, so the regex engine
   takes the longest match at each position and never re-reads its own output.

2. **Word guards.** A term that starts or ends with an ASCII alphanumeric gets a
   non-alphanumeric lookaround on that side, so "EDTA" matches in "17% EDTA"
   but not inside "EDTAC", and "PIPS" does not fire inside "PIPSY".

To extend the dictionary, add an entry to PRONUNCIATION_TERMS. Nothing else
needs to change.
"""

import re

# ── The dictionary ────────────────────────────────────────
# term       — what appears in the source text (exact, as written in papers)
# say        — what the TTS engine should receive instead
# ci         — match case-insensitively; the replacement is capitalised when
#              the matched text was (for ordinary words, not acronyms)
# pad_left   — emit a leading space; for terms that abut a number ("500µm")
#
# Order in this list is documentation only — apply_pronunciation() sorts by
# length descending regardless, so a careless insertion cannot break rule 1.
PRONUNCIATION_TERMS = [
    # Laser platforms. Er,Cr:YSGG MUST outrank YSGG (see rule 1 above).
    {"term": "Er,Cr:YSGG", "say": "erbium chromium Y-S-G-G"},
    {"term": "Er:YAG",     "say": "erbium YAG"},
    {"term": "Nd:YAG",     "say": "neodymium YAG"},
    {"term": "YSGG",       "say": "Y-S-G-G"},

    # Irrigants and materials.
    {"term": "NaOCl",      "say": "sodium hypochlorite"},
    {"term": "Ca(OH)2",    "say": "calcium hydroxide"},
    {"term": "EDTA",       "say": "E-D-T-A"},
    {"term": "CHX",        "say": "chlorhexidine"},
    {"term": "MTA",        "say": "M-T-A"},

    # Techniques and units.
    {"term": "PIPS",       "say": "pips"},
    {"term": "µm",         "say": "microns", "pad_left": True},

    # Words the engine stresses wrongly. The respelling is lower-case and
    # hyphen-free of capitals on purpose: capital letters make the engine spell
    # the token out letter by letter.
    {"term": "apexification", "say": "ay-pex-if-i-cation", "ci": True},
]

_ASCII_ALNUM = re.compile(r"[0-9A-Za-z]")

# Runs of spaces/tabs only — never newlines, which carry the script's paragraph
# structure into the section splitter.
_HSPACE_RUN = re.compile(r"[ \t]{2,}")

_compiled_cache = {}


def _entry_pattern(entry: dict) -> str:
    """Regex source for one dictionary entry, with word guards applied."""
    term = entry["term"]
    body = re.escape(term)
    if _ASCII_ALNUM.match(term[0]):
        body = r"(?<![0-9A-Za-z])" + body
    if _ASCII_ALNUM.match(term[-1]):
        body = body + r"(?![0-9A-Za-z])"
    if entry.get("ci"):
        body = "(?i:" + body + ")"
    return body


def _compile(terms: tuple) -> tuple:
    """Return (regex, ordered_entries) for a set of entries, longest term first."""
    ordered = sorted(terms, key=lambda e: len(e["term"]), reverse=True)
    pattern = "|".join(
        f"(?P<t{i}>{_entry_pattern(e)})" for i, e in enumerate(ordered)
    )
    return re.compile(pattern), ordered


def _get_compiled(terms: list) -> tuple:
    key = tuple((e["term"], e["say"], e.get("ci", False), e.get("pad_left", False))
                for e in terms)
    if key not in _compiled_cache:
        _compiled_cache[key] = _compile(tuple(terms))
    return _compiled_cache[key]


def apply_pronunciation(text: str, extra_terms: list = None) -> str:
    """Rewrite `text` for speech synthesis. Never call this on displayed text.

    `extra_terms` — optional list of entries in PRONUNCIATION_TERMS shape,
    merged in for this call only (caller-supplied topic vocabulary).
    """
    if not text:
        return text

    terms = list(PRONUNCIATION_TERMS)
    if extra_terms:
        terms = terms + list(extra_terms)

    regex, ordered = _get_compiled(terms)

    def _sub(m: "re.Match") -> str:
        idx = int(m.lastgroup[1:])
        entry = ordered[idx]
        say = entry["say"]
        if entry.get("ci") and m.group(0)[:1].isupper():
            say = say[:1].upper() + say[1:]
        if entry.get("pad_left"):
            say = " " + say
        return say

    out = regex.sub(_sub, text)
    return _HSPACE_RUN.sub(" ", out)


def pronunciation_pairs(terms: list = None) -> list:
    """(term, say) in the order they are actually applied. For tests/debugging."""
    _, ordered = _get_compiled(list(terms or PRONUNCIATION_TERMS))
    return [(e["term"], e["say"]) for e in ordered]
