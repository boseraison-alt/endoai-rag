
import anthropic
import requests
import os
import sys
import re
import json
from datetime import datetime

# Force UTF-8 output on Windows so emoji/Unicode in print() never raises UnicodeEncodeError
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── CONFIG ──────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.abspath('.'), '.env'), override=True)

def _get_api_key():
    """Read key at call time so app.py load_dotenv(override=True) takes effect."""
    return os.getenv("ANTHROPIC_API_KEY", "")

ANTHROPIC_API_KEY = _get_api_key()
NUM_PAPERS = 20


# ── NCBI eutils helpers ───────────────────────────────────
# Unauthenticated eutils is rate-limited to 3 req/sec on slow servers.
# Setting NCBI_API_KEY in the env bumps that to 10 req/sec on prioritised
# hardware and substantially reduces tail-latency on abstract pulls.

NCBI_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

def _ncbi_params(extra: dict = None) -> dict:
    """Merge caller params with NCBI tool/email identifiers and api_key (if set)."""
    p = {
        "tool":  "endo-ai-rag",
        "email": os.getenv("NCBI_EMAIL", "endoai@research.local"),
    }
    api_key = (os.getenv("NCBI_API_KEY") or "").strip()
    if api_key:
        p["api_key"] = api_key
    if extra:
        p.update(extra)
    return p


# Parse the batch text returned by efetch (rettype=abstract, retmode=text)
# into per-PMID entries so we can populate the abstract cache as a side
# effect of every PubMed pull.
_EFETCH_ENTRY_SPLIT_RE = re.compile(r"\n\n(?=\d+\.\s+[A-Z])")
_EFETCH_PMID_RE        = re.compile(r"^PMID:\s*(\d+)", re.MULTILINE)


def _parse_efetch_batch(raw_text: str) -> dict:
    """Split an efetch batch text dump into {pmid: {title, abstract}} chunks.

    The format from efetch (rettype=abstract, retmode=text) groups one paper
    per "1. ", "2. ", ... entry. We split on those boundaries, locate the
    `PMID: NNNNNN` line, then extract title + abstract from the entry's
    paragraph structure (longest paragraph ≥ 200 chars is virtually always
    the abstract; the second paragraph is the title).
    """
    if not raw_text or not raw_text.strip():
        return {}
    out = {}
    entries = _EFETCH_ENTRY_SPLIT_RE.split(raw_text)
    for entry in entries:
        m = _EFETCH_PMID_RE.search(entry)
        if not m:
            continue
        pmid = m.group(1).strip()

        # Reuse the same paragraph-collapsing logic the live /api/abstract
        # path uses, so cached and live results look identical to the UI.
        paragraphs, current = [], []
        for line in entry.split("\n"):
            line = line.rstrip()
            if line.strip():
                current.append(line.strip())
            else:
                if current:
                    paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))

        # Title heuristic: 2nd paragraph (1st is the citation line "J Endod. 2024…")
        title = ""
        if len(paragraphs) >= 2 and 10 <= len(paragraphs[1]) <= 400:
            title = paragraphs[1]

        # Abstract heuristic: longest paragraph ≥ 200 chars
        candidates = [p for p in paragraphs if len(p) >= 200]
        abstract = max(candidates, key=len) if candidates else ""

        out[pmid] = {"title": title, "abstract": abstract}
    return out

# ── MODEL ROUTING ─────────────────────────────────────────
# Centralized so re-routing is a one-line change per call site.
# Every client.messages.create() call references MODELS[...] — never a literal.
#
#   reasoning_heavy    — complex multi-tier evidence synthesis
#   reasoning_standard — general reasoning, light synthesis, structural reformat
#   structured_fast    — JSON output, classification, short structured generation
MODELS = {
    "reasoning_heavy":    "claude-opus-4-7",
    "reasoning_standard": "claude-sonnet-4-6",
    "structured_fast":    "claude-haiku-4-5-20251001",
}

# Per-model pricing (USD per million tokens) — used by calc_cost() and the
# upcoming /admin/costs endpoint. Update when Anthropic pricing changes.
MODEL_PRICING = {
    "claude-opus-4-7":            {"input": 15.00, "output": 75.00},
    "claude-opus-4-5":            {"input": 15.00, "output": 75.00},  # legacy fallback
    "claude-sonnet-4-6":          {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5-20251001":  {"input":  1.00, "output":  5.00},
}

# Legacy single-model pricing constants — kept for backwards compat with
# calc_cost() until that function is updated to use MODEL_PRICING.
COST_INPUT_PER_M  = 15.00
COST_OUTPUT_PER_M = 75.00

# ── COST LOGGING ──────────────────────────────────────────
# Append-only JSONL log of every Claude API call. Powers /admin/costs.
import threading as _cost_thread
_COST_LOG_LOCK = _cost_thread.Lock()
_COST_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "cost_log.jsonl")

# ── TIER 2 COMPARISON HARNESS (Sonnet-vs-Opus, flag-gated) ───────
# Two env flags drive behavior:
#   USE_TIER2_SONNET     (default False)  — production model selection
#   LOG_TIER2_COMPARISON (default False)  — run BOTH models in parallel and log
#
# Behavior matrix:
#   USE_TIER2_SONNET=F, LOG=F → Opus only (current production)
#   USE_TIER2_SONNET=T, LOG=F → Sonnet only
#   LOG=T (either flag)       → both models run in parallel, both logged to
#                                tier2_comparison.jsonl; the returned response
#                                obeys USE_TIER2_SONNET.
#
# Flip with env vars:
#   USE_TIER2_SONNET=true python app.py
#   LOG_TIER2_COMPARISON=true python app.py
USE_TIER2_SONNET     = os.getenv("USE_TIER2_SONNET", "true").lower() in ("1", "true", "yes")
LOG_TIER2_COMPARISON = os.getenv("LOG_TIER2_COMPARISON", "false").lower() in ("1", "true", "yes")
_TIER2_LOG_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "tier2_comparison.jsonl")
_TIER2_LOG_LOCK      = _cost_thread.Lock()

import time as _time
import random as _random

# ── Anthropic transient-error retry wrapper ───────────────
# Retries on:
#   - 529 Overloaded   (Anthropic backend saturated)
#   - 503 Service Unavailable
#   - 502 Bad Gateway
#   - 504 Gateway Timeout
#   - 429 Rate Limit (anthropic.RateLimitError)
#   - APIConnectionError (TCP reset, DNS, TLS handshake fail)
# Does NOT retry on 4xx (except 429) — those are caller errors that won't fix themselves.

_RETRYABLE_STATUS  = {502, 503, 504, 529}
_RETRY_BACKOFF_SEC = [2, 5, 12, 30]   # 4 retries → 5 attempts total

def _invoke_claude(client, *, function_name: str = "claude", **kwargs):
    """Wrap client.messages.create with retry-on-transient-error.

    Pass through kwargs identically to client.messages.create. On 529 / 503 /
    504 / 429 / connection error, sleep with exponential backoff + jitter and
    retry. Re-raises the original error after all attempts exhausted.
    """
    last_exc = None
    for attempt in range(len(_RETRY_BACKOFF_SEC) + 1):
        try:
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            last_exc = e
            reason = "rate_limit (429)"
        except anthropic.APIStatusError as e:
            last_exc = e
            status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
            if status not in _RETRYABLE_STATUS:
                # 4xx caller error — no point retrying
                raise
            reason = f"status {status}"
        except anthropic.APIConnectionError as e:
            last_exc = e
            reason = f"connection error ({type(e).__name__})"

        if attempt >= len(_RETRY_BACKOFF_SEC):
            print(f"  [{function_name}] giving up after {attempt+1} attempts ({reason})")
            raise last_exc

        sleep_s = _RETRY_BACKOFF_SEC[attempt] + _random.uniform(0, 1.5)
        print(f"  [{function_name}] {reason} — retry {attempt+1}/{len(_RETRY_BACKOFF_SEC)} in {sleep_s:.1f}s")
        _time.sleep(sleep_s)

    raise last_exc  # unreachable, satisfies linters


def tier2_invoke(function_name: str, mode: str, **create_kwargs):
    """Wrapper for every Tier 2 Claude call. Returns (response, cost).

    Caller passes the same kwargs they'd pass to client.messages.create() —
    EXCEPT `model`, which this wrapper picks based on USE_TIER2_SONNET.

    cost_log.jsonl gets one entry per actual API call (so the comparison mode
    logs two entries — one Opus, one Sonnet).
    """
    client = anthropic.Anthropic(api_key=_get_api_key())

    def _call(model_str):
        t0 = _time.perf_counter()
        resp = _invoke_claude(client, function_name=f"{function_name}({model_str})",
                              model=model_str, **create_kwargs)
        elapsed_ms = int((_time.perf_counter() - t0) * 1000)
        cost = log_llm_call(function_name, model_str, resp.usage, mode=mode)
        return resp, elapsed_ms, cost

    if not LOG_TIER2_COMPARISON:
        # Single-model production path
        chosen = MODELS["reasoning_standard"] if USE_TIER2_SONNET else MODELS["reasoning_heavy"]
        resp, _ms, cost = _call(chosen)
        return resp, cost

    # Parallel-comparison path — both models, both logged
    from concurrent.futures import ThreadPoolExecutor
    opus_resp = sonnet_resp = None
    opus_ms = sonnet_ms = -1
    opus_cost = sonnet_cost = 0.0
    opus_err = sonnet_err = None
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_o = ex.submit(_call, MODELS["reasoning_heavy"])
        f_s = ex.submit(_call, MODELS["reasoning_standard"])
        try:    opus_resp,  opus_ms,  opus_cost  = f_o.result()
        except Exception as e: opus_err  = str(e)
        try:    sonnet_resp, sonnet_ms, sonnet_cost = f_s.result()
        except Exception as e: sonnet_err = str(e)

    # Truncate input for log readability
    msgs_blob = json.dumps(create_kwargs.get("messages", []), ensure_ascii=False)
    sys_blob  = create_kwargs.get("system", "") or ""

    record = {
        "ts":                datetime.now().isoformat(),
        "function":          function_name,
        "mode":              mode,
        "system_truncated":  sys_blob[:1500],
        "input_truncated":   msgs_blob[:2000],
        "opus_output":       opus_resp.content[0].text if opus_resp else None,
        "opus_latency_ms":   opus_ms,
        "opus_cost_usd":     round(opus_cost, 6),
        "opus_error":        opus_err,
        "sonnet_output":     sonnet_resp.content[0].text if sonnet_resp else None,
        "sonnet_latency_ms": sonnet_ms,
        "sonnet_cost_usd":   round(sonnet_cost, 6),
        "sonnet_error":      sonnet_err,
    }
    try:
        with _TIER2_LOG_LOCK:
            with open(_TIER2_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"  [tier2_log] write failed: {e}")

    # Return whichever the flag dictates; fall back if the chosen one errored
    if USE_TIER2_SONNET and sonnet_resp:
        return sonnet_resp, sonnet_cost
    if opus_resp:
        return opus_resp, opus_cost
    return sonnet_resp, sonnet_cost  # last resort


def log_llm_call(function_name: str, model: str, usage, mode: str = "shared",
                 request_id: str = None) -> float:
    """Log a Claude API call to cost_log.jsonl and return its USD cost.

    `function_name`  — caller name (e.g. 'ask_clinical_question')
    `model`          — actual model string (use MODELS[...] at call site)
    `usage`          — the .usage object returned by anthropic SDK
    `mode`           — 'review'|'learn'|'case'|'assessment'|'export'|'shared'
    `request_id`     — optional, groups multi-call requests (e.g. learn pipeline)
    """
    pricing = MODEL_PRICING.get(model) or MODEL_PRICING.get("claude-opus-4-7")
    in_tok  = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0
    cost    = (in_tok / 1_000_000.0 * pricing["input"] +
               out_tok / 1_000_000.0 * pricing["output"])

    record = {
        "ts":            datetime.now().isoformat(),
        "function":      function_name,
        "model":         model,
        "mode":          mode,
        "input_tokens":  in_tok,
        "output_tokens": out_tok,
        "cost_usd":      round(cost, 6),
    }
    if request_id:
        record["request_id"] = request_id

    try:
        with _COST_LOG_LOCK:
            with open(_COST_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
    except Exception as e:
        # Never let logging break a real request
        print(f"  [cost_log] write failed: {e}")

    return cost

def calc_cost(usage) -> float:
    """Return USD cost from a Claude API usage object."""
    return (
        usage.input_tokens  / 1_000_000 * COST_INPUT_PER_M +
        usage.output_tokens / 1_000_000 * COST_OUTPUT_PER_M
    )

# ── COI BLOCKLIST ────────────────────────────────────────
# Known dental industry funders whose papers may be biased
COI_FUNDER_BLOCKLIST = [
    "dentsply", "sirona", "dentsply sirona",
    "kerr", "kerr corporation", "kerr dental",
    "coltene", "coltène", "coltene whaledent",
    "brasseler", "brasseler usa",
    "ultradent",
    "3m espe", "3m oral care",
    "ivoclar", "ivoclar vivadent",
    "voco", "septodont",
    "fkg dentaire", "fkg",
    "vdw gmbh", "vdw dental",
    "micro-mega", "micromega",
    "mani inc", "mani dental",
    "komet dental",
    "maillefer", "dentsply maillefer",
    "ormco", "envista", "solventum",
    "gc corporation", "gc america",
    "shofu", "danaher",
    "henry schein", "patterson dental",
]


def check_coi_blocklist(text: str) -> tuple:
    """Raw blocklist scan: does this text mention an industry name anywhere?

    NOTE: a bare mention is NOT a conflict of interest. In endodontics almost
    every instrumentation / sealer / obturation study names its materials with
    the manufacturer in parentheses ("ProTaper Next (Dentsply Sirona)"), and
    systematic reviews list every product used by their included trials. Use
    detect_coi() for scoring decisions; this helper only answers "is the name
    present", and exists for that narrow purpose.
    """
    text_lower = (text or "").lower()
    for funder in COI_FUNDER_BLOCKLIST:
        if funder in text_lower:
            return True, funder.title()
    return False, ""


# Cue phrases that mark a funding / disclosure statement. A manufacturer name
# only counts as a conflict when it appears INSIDE such a sentence.
_COI_CUE_RE = re.compile(
    r"\b(?:"
    r"fund(?:ed|ing|s)?|financ(?:ed|ial\s+support)|sponsor(?:ed|ship)?|"
    r"support(?:ed)?\s+(?:by|in\s+part\s+by)|grant(?:s|ed)?\s+(?:from|by)|"
    r"conflicts?\s+of\s+interest|competing\s+interests?|disclosur\w*|"
    r"employe(?:e|d)\s+of|consultan\w*\s+(?:for|to)|honorari\w*|"
    r"(?:materials?|instruments?|files?|sealers?|products?)\s+"
    r"(?:were\s+)?(?:donated|provided|supplied|gifted)\s+by|"
    r"in\s+kind|royalt\w*|stock\s+(?:options?|ownership)|patent\s+holder|"
    r"receiv\w*\s+(?:fees|payments?|honorari\w*|grants?|funding|support|"
    r"compensation|reimbursement|equipment|materials?)|"
    r"lecture\s+fees|speaker\s+(?:fees|bureau)|advisory\s+board|"
    r"paid\s+(?:by|consultant|speaker)|financial\s+(?:ties|relationships?)"
    r")\b",
    re.IGNORECASE,
)

# Negative declarations. These patterns were derived from a sample of 120 REAL
# PubMed CoiStatement values in this library, not from imagination — 118 of the
# 120 were denials, and the phrasings below are the ones that actually occur.
# Getting these wrong is the expensive direction: a missed denial becomes a
# false "industry conflict" badge on an independent study.
_COI_NEGATION_RE = re.compile(
    r"(?:"
    # "declare/report/state (that they have) no ..." — the dominant form
    r"\b(?:declar\w*|report\w*|state[sd]?|disclos\w*)\b[^.;]{0,50}?\bno\b"
    # "...absence of any commercial or financial relationships..."
    r"|\babsence\s+of\s+any\b"
    # "deny any conflict", "denies any competing interest"
    r"|\bden(?:y|ies|ied)\b[^.;]{0,30}?\b(?:conflict|competing|interest)"
    # "nothing to disclose / declare"
    r"|\bnothing\s+to\s+(?:disclose|declare|report)\b"
    # "no conflict(s) of interest", "no competing interests", "no potential conflict"
    r"|\bno\s+(?:potential\s+|known\s+|relevant\s+|perceived\s+)?"
    r"(?:conflicts?|competing\s+interests?|financial\s+(?:interests?|relationships?|"
    r"disclosures?)|commercial\s+(?:interests?|relationships?)|funding|disclosures?)\b"
    # "have/has no ...", "there is no ..."
    r"|\b(?:have|has|had|there\s+(?:is|are|was|were))\s+no\b"
    # "received no specific grant from any funding agency" — extremely common
    # boilerplate that the affirmative "received ... grant" pattern would
    # otherwise read as a positive disclosure.
    r"|\breceiv\w+\s+no\b"
    r"|\bno\s+(?:\w+\s+){0,2}(?:grants?|funding|financial\s+support|support)\b"
    # bare "None", "None declared", "Not applicable"
    r"|^\s*(?:none|not\s+applicable|n/?a)\b"
    r"|\bnone\s+(?:declared|to\s+declare|reported)\b"
    r"|\bnot\s+applicable\b"
    r")",
    re.IGNORECASE,
)

# An AFFIRMATIVE disclosure: a party in a stated relationship with a commercial
# entity. Deliberately narrow. The previous version treated any disclosure-ish
# cue word as a conflict, which flagged 9 of every 10 papers whose statement was
# actually a denial ("...absence of any commercial or financial relationships...").
_COI_AFFIRMATIVE_RE = re.compile(
    r"\b(?:is|are|was|were|has|have|had|serves?|served|acts?|acted|works?|worked)\b"
    # Commercial relationships only. "Editorial board member" and similar
    # academic roles are disclosures but not industry conflicts, so generic
    # "board member" / "lecturer" are deliberately excluded.
    r"[^.;]{0,40}?\b(?:paid\s+)?(?:consultant|employee|opinion\s+leader|advisor|"
    r"adviser|advisory\s+board|speaker\s+bureau|shareholder|stockholder)\b"
    r"|\breceiv\w+\b[^.;]{0,40}?\b(?:fees|honorari\w*|grants?|funding|payments?|"
    r"royalt\w*|equipment|materials?|support|compensation)\b"
    r"|\b(?:funded|sponsored|financed)\s+by\b"
    r"|\b(?:materials?|instruments?|files?|sealers?|products?)\s+(?:were\s+)?"
    r"(?:donated|provided|supplied|gifted)\s+by\b",
    re.IGNORECASE,
)


# Tri-state COI outcomes. "No statement" is NOT "no conflict": PubMed only
# carries <CoiStatement> for records indexed since ~2017 whose journal deposits
# one, so treating its absence as a clean bill would silently exonerate every
# older paper. Only DECLARED_CONFLICT is ever penalised.
COI_DECLARED_CONFLICT = "declared_conflict"
COI_DECLARED_NONE     = "declared_none"
COI_NO_STATEMENT      = "no_statement"


def _split_sentences(text: str) -> list:
    """Sentence split that also treats ';' and newlines as boundaries — COI
    statements are frequently semicolon-delimited lists of disclosures."""
    parts = re.split(r"(?<=[.!?])\s+|\s*;\s*|\n+", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def classify_coi(coi_statement: str = "", abstract_text: str = "") -> tuple:
    """Classify a paper's conflict-of-interest position.

    Returns (status, funder) where status is one of COI_DECLARED_CONFLICT,
    COI_DECLARED_NONE, COI_NO_STATEMENT.

    Negation is evaluated PER SENTENCE, not over the whole statement. Real
    declarations routinely open with boilerplate and then disclose:
        "The authors declare no conflict of interest. Dr. Smith has received
         fees from Dentsply Sirona."
    Testing the whole string for a denial would let sentence one mask sentence
    two. A disclosing sentence therefore wins over any denial elsewhere.
    """
    stmt = (coi_statement or "").strip()

    if stmt:
        for sentence in _split_sentences(stmt):
            if _COI_NEGATION_RE.search(sentence):
                continue                      # this sentence is a denial
            named, funder = check_coi_blocklist(sentence)
            if named and _COI_AFFIRMATIVE_RE.search(sentence):
                return COI_DECLARED_CONFLICT, funder
        # A statement exists but names no commercial party in an affirmative
        # disclosure. We deliberately do NOT flag "unnamed" disclosures: in
        # practice those are public grants ("funded by the National Institute
        # for Health Research") and academic roles ("Statistical Editor with
        # Cochrane Oral Health"), which are not industry conflicts. Flagging
        # them put a false INDUSTRY CONFLICT badge on independent Cochrane
        # reviews — worse than missing a manufacturer absent from the
        # blocklist, which is the recall cost we accept here.
        return COI_DECLARED_NONE, ""

    # No declaration on record — fall back to a declaration-scoped abstract
    # scan. A hit here is a genuine disclosure; a miss is UNKNOWN, not clean.
    for sentence in _split_sentences(abstract_text or ""):
        if _COI_NEGATION_RE.search(sentence) or not _COI_AFFIRMATIVE_RE.search(sentence):
            continue
        named, funder = check_coi_blocklist(sentence)
        if named:
            return COI_DECLARED_CONFLICT, funder
    return COI_NO_STATEMENT, ""


def detect_coi(coi_statement: str = "", abstract_text: str = "") -> tuple:
    """Boolean view of classify_coi() for scoring. Returns (has_coi, funder).

    Only a DECLARED conflict is penalised — an absent statement is unknown and
    must not be treated as either clean or conflicted.
    """
    status, funder = classify_coi(coi_statement, abstract_text)
    return status == COI_DECLARED_CONFLICT, funder


# ── CURRENCY FILTER ───────────────────────────────────────
CURRENCY_THRESHOLD_YEARS = 8   # papers older than this are flagged


def apply_currency_tags(scored_papers: list) -> list:
    """Tag each paper with is_old and age_years. Sorts recent papers first within same score band."""
    current_year = datetime.now().year
    for p in scored_papers:
        try:
            age = current_year - int(p.get("year", current_year))
        except (ValueError, TypeError):
            age = 10
        p["is_old"]   = age > CURRENCY_THRESHOLD_YEARS
        p["age_years"] = age
    return scored_papers


def build_currency_warning(scored_papers: list) -> str:
    """Returns a warning string injected into Claude's prompt when evidence is predominantly old."""
    top10     = scored_papers[:10]
    old_count = sum(1 for p in top10 if p.get("is_old"))
    if old_count >= 6:
        oldest = min(
            (int(p["year"]) for p in top10 if str(p.get("year", "")).isdigit()),
            default=2000
        )
        return (
            f"\n⚠️  CURRENCY WARNING: {old_count} of the top 10 papers are over "
            f"{CURRENCY_THRESHOLD_YEARS} years old (oldest: {oldest}). "
            f"Explicitly flag in your answer that some recommendations may have evolved "
            f"and clinicians should consult recent guidelines."
        )
    return ""


# ── OUTLIER DETECTION ─────────────────────────────────────
def detect_outliers(scored_papers: list) -> list:
    """Flag papers whose score deviates >1.5 std from the mean as outliers."""
    if len(scored_papers) < 4:
        return scored_papers
    scores = [p.get("score", 50) for p in scored_papers]
    mean   = sum(scores) / len(scores)
    std    = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5
    for p in scored_papers:
        p["is_outlier"] = abs(p.get("score", 50) - mean) > 1.5 * std
    return scored_papers


# ── PRISMA-STYLE DEDUP ────────────────────────────────────
# Systematic reviews and meta-analyses typically synthesise all primary studies
# published up to ~12-18 months before their own publication date.
# When the evidence base contains a recent SR/MA AND older primary RCTs/cohorts
# on the same topic, those primary studies are likely already counted inside
# the SR — citing both double-counts the same evidence.
#
# Heuristic: any primary study (Level II / IIIa / IIIb / IV) published more than
# PRISMA_BUFFER_YEARS before the newest SR/MA in the evidence base is flagged
# as `superseded_by_review`. We do NOT delete the paper (its methodological detail
# may still be useful) — we just tell Claude to defer to the SR's pooled estimate.
PRISMA_BUFFER_YEARS  = 2     # SRs typically include studies up to N years before pub
SR_TIER_KEYS         = ("cochrane", "level1")
PRIMARY_TIER_KEYS    = ("level2", "level3a", "level3b", "level3", "level4")

def flag_superseded_by_review(evidence: dict) -> dict:
    """Mark primary studies whose evidence is already pooled inside a more
    recent systematic review or meta-analysis. Mutates the passed evidence
    dict in place and returns it."""
    # Find the newest SR/MA year across cochrane + level1
    newest_sr_year = 0
    newest_sr_pmid = ""
    for tier_key in SR_TIER_KEYS:
        for p in (evidence.get(tier_key, {}) or {}).get("scored", []) or []:
            try:
                y = int(p.get("year", 0))
            except (ValueError, TypeError):
                continue
            if y > newest_sr_year:
                newest_sr_year = y
                newest_sr_pmid = p.get("pmid", "")

    if newest_sr_year == 0:
        return evidence  # no SR to compare against

    cutoff = newest_sr_year - PRISMA_BUFFER_YEARS

    flagged = 0
    for tier_key in PRIMARY_TIER_KEYS:
        for p in (evidence.get(tier_key, {}) or {}).get("scored", []) or []:
            try:
                y = int(p.get("year", 0))
            except (ValueError, TypeError):
                p["superseded_by_review"] = False
                continue
            if y > 0 and y <= cutoff:
                p["superseded_by_review"] = True
                p["superseding_sr_pmid"]  = newest_sr_pmid
                p["superseding_sr_year"]  = newest_sr_year
                flagged += 1
            else:
                p["superseded_by_review"] = False

    if flagged:
        print(f"  [PRISMA dedup] flagged {flagged} primary studies as already synthesised "
              f"in newer SR (PMID {newest_sr_pmid}, {newest_sr_year}; cutoff ≤ {cutoff})")
    return evidence


# ── CLINICAL CLARIFYING QUESTIONS ─────────────────────────
def generate_clarifying_questions(question: str) -> list:
    """
    Generate 2-3 targeted clinical clarifying questions before running a full search.
    Returns a list of question strings, or [] if not applicable.
    """
    client = anthropic.Anthropic(api_key=_get_api_key())
    try:
        # Routed to Haiku 2026-04-27 — was Opus. Reason: classification + short JSON output.
        resp = _invoke_claude(client, function_name="generate_clarifying_questions",
            model=MODELS["structured_fast"],
            max_tokens=300,
            messages=[{"role": "user", "content":
                f"""You are an expert endodontist. A clinician asked: "{question}"

Your job: decide whether asking 2-3 clarifying questions BEFORE answering would produce a meaningfully better, more tailored answer.

ALWAYS ask if the question involves ANY of these:
- A specific patient (age, history, symptoms mentioned)
- Treatment decision or prognosis for a case
- Trauma, avulsion, resorption, or pulp status questions
- "Do I treat?", "Should I...?", "What is the prognosis?", "How do I manage?"

Do NOT ask for pure knowledge questions with a fixed answer regardless of context (e.g. "What is the success rate of NiTi files?", "How does MTA work?").

If clarification would help, return a JSON array of 2-3 SHORT, SPECIFIC clinical questions.
Prioritise: type/severity of injury or condition, pulp/periapical status, tooth/root anatomy, patient age/medical factors, prior treatment.
If genuinely no clarification needed, return [].

Return ONLY valid JSON — no markdown, no explanation."""}]
        )
        log_llm_call("generate_clarifying_questions", MODELS["structured_fast"],
                     resp.usage, mode="shared")
        raw = re.sub(r"```json|```", "", resp.content[0].text).strip()
        result = json.loads(raw)
        if isinstance(result, list):
            return [str(q) for q in result[:3]]
    except Exception:
        pass
    return []


# ── MULTI-TERM SEARCH GENERATOR ───────────────────────────
# ── SEARCH-TERM PARSING ──────────────────────────────────
# Search terms coming back from Haiku were parsed with a bare json.loads, and
# any failure fell through `except: pass` to a single term. Measured on ten
# consecutive live calls (2026-08-29): 5/10 parse failures, zero of them
# truncation. The cause is structural: PubMed queries REQUIRE quoted phrases
# ("photodynamic therapy"), the prompt demands them, and Haiku emits them
# unescaped inside JSON strings about half the time — invalid JSON by
# construction. The result was retrieval breadth silently flapping between 1
# and 3 terms for the same question (paper count 43 vs 92), which is why the
# eval baselines had to be recorded as ranges.
#
# The contract is now line-based ("TERM: <query>" per line), which cannot
# collide with the quotes the queries themselves need. The parser below still
# accepts a clean JSON array (legacy) and recovers the quote-mangled JSON shape
# (dominant observed failure) so a model that ignores the format instruction
# degrades gracefully instead of to 1 term.

_TERM_LINE_RE = re.compile(r"^\s*TERM\s*:\s*(.+?)\s*$", re.MULTILINE)


def _looks_like_query(t: str) -> bool:
    """A usable boolean query, not prose and not mangled.

    Unbalanced parens/quotes are dropped rather than repaired: PubMed does not
    reject a malformed query, it silently reinterprets it (see
    tests/test_tier_filter_syntax.py for the bug class), so a damaged term is
    worse than a missing one.
    """
    if not t or len(t) < 10:
        return False
    if " OR " not in t and " AND " not in t:
        return False                      # the spec requires OR-groups
    if t.count("(") != t.count(")"):
        return False
    if t.count('"') % 2:
        return False
    return True


def _parse_term_list(raw: str) -> list:
    """Extract a list of PubMed query strings from an LLM response.

    Tries, in order: TERM: lines (current contract), a strict JSON array
    (legacy contract), then per-line recovery of a JSON-ish array whose string
    elements contain unescaped inner quotes — the failure that hit 5 of 10
    probed calls. Every candidate passes _looks_like_query before it counts.
    """
    text = re.sub(r"```(?:json)?", "", raw or "").strip()

    terms = [m.group(1) for m in _TERM_LINE_RE.finditer(text)]

    if not terms:
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                terms = [str(t).strip() for t in arr]
        except (json.JSONDecodeError, TypeError):
            # JSON-ish with unescaped quotes. The elements still sit one per
            # line between the brackets; strip the array punctuation and the
            # single outer quote pair per line.
            for line in text.splitlines():
                line = line.strip().rstrip(",")
                if line in ("[", "]", ""):
                    continue
                if line.startswith('"'):
                    line = line[1:]
                if line.endswith('"'):
                    line = line[:-1]
                terms.append(line.strip())

    seen, good = set(), []
    for t in terms:
        if _looks_like_query(t) and t not in seen:
            seen.add(t)
            good.append(t)
    return good


MIN_SEARCH_TERMS = 4      # below this after retry, warn loudly — never silent
TARGET_EXTRA_TERMS = 6    # + primary = 7, inside the 6-10 band the eval expects

_MULTI_TERM_FORMAT = (
    f"Return EXACTLY {TARGET_EXTRA_TERMS} lines. Each line starts with "
    '"TERM: " followed by one boolean query. No JSON, no code fences, no '
    "numbering, no commentary — quotes inside the queries are fine."
)


def generate_multi_search_terms(question: str, primary_term: str) -> list:
    """
    Generate additional PubMed queries for broader coverage; the primary_term
    (from generate_search_terms) is always included and always first.

    Never silently returns fewer than MIN_SEARCH_TERMS: one corrective retry,
    then a loud warning. Retrieval breadth flapping with parse luck is what
    made every eval number ±50% noise.
    """
    client = anthropic.Anthropic(api_key=_get_api_key())

    base_prompt = (
        f'Generate {TARGET_EXTRA_TERMS} additional PubMed search queries for this '
        f'endodontic question: "{question}"\n'
        f'The primary search below is already in use — cover DIFFERENT angles: '
        f'alternative vocabulary, adjacent techniques, outcome framings, '
        f'organism/material names.\n'
        f'Primary: {primary_term}\n\n'
        f'Each query: 2-3 concept groups, each an OR-list of synonyms, '
        f'abbreviations, device and brand names, joined by AND. Use * stem '
        f'truncation and quote multi-word phrases. Do NOT add [pt] filters or '
        f'endodontics domain terms — both are appended automatically.\n\n'
        f'{_MULTI_TERM_FORMAT}'
    )

    terms = []
    for attempt, prompt in enumerate((
        base_prompt,
        # Corrective retry: name the failure, restate only the format.
        base_prompt + "\n\nYour previous response could not be parsed. "
                      "Follow the output format EXACTLY: one query per line, "
                      'each line beginning "TERM: ", nothing else.',
    )):
        try:
            resp = _invoke_claude(client, function_name="generate_multi_search_terms",
                model=MODELS["structured_fast"],
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}])
            log_llm_call("generate_multi_search_terms", MODELS["structured_fast"],
                         resp.usage, mode="review")
            terms = _parse_term_list(resp.content[0].text)
        except Exception as e:
            print(f"  [search_terms] generate_multi attempt {attempt + 1} failed: {e}")
            terms = []
        if len(terms) + 1 >= MIN_SEARCH_TERMS:
            break
        if attempt == 0:
            print(f"  [search_terms] got {len(terms)} usable extra terms, retrying with corrective prompt")

    result = [primary_term] + [t for t in terms if t != primary_term][:TARGET_EXTRA_TERMS + 3]
    if len(result) < MIN_SEARCH_TERMS:
        print(f"  [search_terms] WARNING: only {len(result)} search term(s) after retry — "
              f"retrieval breadth is degraded for this run")
    return result


# ── EVIDENCE LEVEL SEARCH TERMS ─────────────────────────
# PubMed has no "Cochrane Review" publication type. It silently translated
# `Cochrane Review[pt]` into ("cochran" OR "cochrane" ...) AND "Review"[pt],
# which matches ANY review mentioning the word Cochrane — i.e. nearly every
# systematic review, since they all say "we searched the Cochrane Library" in
# their methods. That put ordinary journal SRs into the top tier, where the
# prompt tells Claude to let them override everything below.
# The journal is the only reliable identifier of a real Cochrane review.
COCHRANE_TERM = '"Cochrane Database Syst Rev"[jour]'

# Journal-name fragments that identify a genuine Cochrane review, used to
# demote anything that reaches the cochrane tier without belonging there.
_COCHRANE_JOURNAL_HINTS = ("cochrane database", "cochrane db syst")

LEVEL_1_TERMS = [
    "randomized controlled trial[pt]",
    "systematic review[pt]",
    "meta-analysis[pt]"
]

LEVEL_2_TERMS = [
    # "randomized controlled trial[pt] less quality" was a stray annotation that
    # PubMed parsed as `... AND less AND quality`, silently gutting this tier.
    "controlled clinical trial[pt]",
    "prospective studies[mh]",
    "comparative study[pt]"
]

# Level 3 split — retrospective cohort preserves temporal direction
# (exposure → outcome) and carries more prognostic weight than case-control
# (which works backward from outcome and is more vulnerable to recall/selection bias).
LEVEL_3A_TERMS = [
    "retrospective studies[pt]",
    "cohort studies[mh]",
    "longitudinal studies[mh]",
]

LEVEL_3B_TERMS = [
    "case-control studies[pt]",
    "case-control studies[mh]",
]

# Kept for backward compatibility with cached library data tagged "level3"
LEVEL_3_TERMS = LEVEL_3A_TERMS + LEVEL_3B_TERMS

LEVEL_4_TERMS = [
    "case series[pt]",
    "case reports[pt]"
]

LEVEL_5_TERMS = [
    "review[pt]",
    "editorial[pt]",
    # "expert opinion" was untagged, so PubMed searched it across All Fields and
    # ORed in any paper containing the phrase. Same bug class as the Level II
    # "less quality" annotation and the non-existent "Cochrane Review[pt]".
    # PubMed has no expert-opinion publication type; comment and letter are the
    # closest real equivalents.
    "comment[pt]",
    "letter[pt]",
]

# ── EVIDENCE LEVEL SCORES ────────────────────────────────
LEVEL_SCORES = {
    "cochrane": 100,
    "level1":   80,
    "level2":   60,
    "level3a":  50,   # retrospective cohort — preserves temporal direction
    "level3b":  35,   # case-control — works backward from outcome
    "level3":   45,   # legacy alias for older library entries
    "level4":   20,
    "level5":   10,
    # San Antonio Guide / College of Diplomates classics. Heterogeneous study
    # designs (1960s-2000s landmark RCTs, anatomical surveys, microbiology
    # series). Baseline 75 puts them just below Level I evidence on the
    # design axis, AND score_paper() exempts them from the recency penalty
    # below — together this lets foundational papers (Vertucci 1984,
    # Sundqvist 1989, Bystrom 1981) actually surface in semantic retrieval
    # for anatomy / microbiology / pulp-biology questions instead of being
    # buried by 30+ year recency penalties they can never overcome.
    "classic":  75,
    # Terminal tier for rows PubMed marks Retracted Publication. Deliberately
    # NOT in TIER_ORDER: absence from that list is this codebase's mechanism
    # for "never rendered to Claude" (_build_evidence_context iterates it), so
    # a retracted row is invisible to synthesis by construction while admin
    # and bibliography views can still label it honestly.
    "retracted": 0,
}

# Strict tier hierarchy — used to enforce within-tier synthesis.
# Lower index = higher evidentiary weight. Never let a lower tier override
# a finding that a higher tier already addresses.
# Strict synthesis hierarchy. Anything NOT listed here is invisible to
# _build_evidence_context(), so a tier missing from this list never reaches
# Claude. "classic" sits just below Level I: the San Antonio / College of
# Diplomates landmark papers are foundational but heterogeneous in design
# (LEVEL_SCORES puts them at 75 against Level I's 80).
# Ordered strongest-first by LEVEL_SCORES design weight. The legacy "level3"
# bucket (45) previously sat AFTER "level3b" (35), presenting case-control
# studies as the stronger of the two — guarded now by test_tier_banding.py.
TIER_ORDER = ["cochrane", "level1", "classic", "level2", "level3a", "level3",
              "level3b", "level4", "level5"]
TIER_LABEL = {
    "cochrane": "Cochrane Reviews",
    "level1":   "Level I — RCTs and Systematic Reviews",
    "level2":   "Level II — Prospective Studies",
    "level3a":  "Level IIIa — Retrospective Cohort",
    "level3b":  "Level IIIb — Case-Control",
    "level3":   "Level III — Retrospective / Case-Control (legacy)",
    "level4":   "Level IV — Case Series",
    "level5":   "Level V — Expert Opinion / Reviews",
    "classic":  "Classic / Foundational (San Antonio Guide)",
    "retracted": "Retracted — excluded from evidence",
}

# ── JOURNAL IMPACT FACTORS ───────────────────────────────
# Curated list of endodontic and dental journals
# Updated approximate values — will add live lookup in future version
JOURNAL_IMPACT_FACTORS = {
    # Endodontic journals
    "journal of endodontics":                          3.5,
    "j endod":                                         3.5,
    "international endodontic journal":                4.5,
    "int endod j":                                     4.5,
    "endodontic topics":                               2.8,
    "journal of endodontics and restorative dentistry": 2.0,

    # High-impact dental journals
    "journal of dental research":                      7.0,
    "j dent res":                                      7.0,
    "journal of clinical periodontology":              6.5,
    "j clin periodontol":                              6.5,
    "clinical oral investigations":                    4.0,
    "clin oral investig":                              4.0,
    "oral surgery oral medicine oral pathology":       3.0,
    "oral surg oral med oral pathol":                  3.0,
    "journal of the american dental association":      4.5,
    "jada":                                            4.5,
    "journal of oral rehabilitation":                  3.2,
    "j oral rehabil":                                  3.2,
    "dental traumatology":                             3.0,
    "dent traumatol":                                  3.0,
    "journal of dentistry":                            4.0,
    "j dent":                                          4.0,
    "archives of oral biology":                        2.5,
    "arch oral biol":                                  2.5,
    "oral diseases":                                   3.5,
    "bmc oral health":                                 2.5,

    # General medical/evidence journals
    "cochrane database of systematic reviews":         12.0,
    "cochrane database syst rev":                      12.0,
    "bmj":                                             39.0,
    "bmj open":                                        2.9,
    "plos one":                                        3.7,
    "scientific reports":                              4.4,
    "evidence-based dentistry":                        2.0,
}

# ── LOOK UP JOURNAL IMPACT FACTOR ───────────────────────
def get_impact_factor(journal_name):
    """
    Looks up IF from our curated dictionary.
    Tries partial matching if exact match not found.
    Returns IF value and score out of 15.
    """
    if not journal_name:
        return None, 7.5  # neutral placeholder

    journal_lower = journal_name.lower().strip()

    # Exact match first
    if journal_lower in JOURNAL_IMPACT_FACTORS:
        if_val = JOURNAL_IMPACT_FACTORS[journal_lower]
        return if_val, score_impact_factor(if_val)

    # Partial match — check if journal name contains any key
    for key, if_val in JOURNAL_IMPACT_FACTORS.items():
        if key in journal_lower or journal_lower in key:
            return if_val, score_impact_factor(if_val)

    return None, 7.5  # unknown journal — neutral score

def score_impact_factor(if_val):
    """Converts IF value to a score out of 15."""
    if if_val >= 10.0:
        return 15.0
    elif if_val >= 6.0:
        return 13.0
    elif if_val >= 4.0:
        return 11.0
    elif if_val >= 3.0:
        return 9.0
    elif if_val >= 2.0:
        return 7.0
    elif if_val >= 1.0:
        return 5.0
    else:
        return 3.0

# ── EXTRACT JOURNAL NAME FROM ABSTRACT TEXT ──────────────
def extract_journal_name(abstract_text, pmid):
    """
    PubMed abstract text includes journal abbreviation.
    Looks for patterns like 'Int Endod J.' or 'J Endod.'
    """
    if not abstract_text:
        return None

    # PubMed citation line format:
    # "Int Endod J. 2022 Mar;55(3):234-245."
    # Look for lines that match journal citation patterns
    lines = abstract_text.split('\n')
    for line in lines:
        line = line.strip()
        # Journal lines often end with year and volume info
        match = re.match(
            r'^([A-Za-z][A-Za-z\s]+[\.\s])\s*\d{4}',
            line
        )
        if match:
            journal = match.group(1).strip().rstrip('.')
            if len(journal) > 3:  # filter out noise
                return journal

    return None

# ── SPELLED-OUT CARDINAL NUMBERS ─────────────────────────
# Abstracts routinely open a Methods sentence with a spelled-out count
# ("Fourteen patients...", "Fifteen patients were included"). Digit-only
# regexes miss these, so counts are recognised as either digits or words.
_CARDINAL_WORDS = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
    'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
    'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
    'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20,
    'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60, 'seventy': 70,
    'eighty': 80, 'ninety': 90, 'hundred': 100,
}
# Longest-first so 'fourteen' is tried before 'four' in the alternation.
_NUM_WORD_ALT = '|'.join(sorted(_CARDINAL_WORDS, key=len, reverse=True))
# A count token: a 1–6 digit number OR a spelled cardinal, as a whole word.
# Comma-grouped thousands must be matched as ONE token. Without the first
# alternative, "11,971 patients" matched as "11" (or, depending on the pattern,
# as "971") — silently turning a 12,000-patient synthesis into an 11-patient
# one. This affected primary studies as much as reviews.
_COUNT_TOKEN  = r'\b(\d{1,3}(?:,\d{3})+|\d{1,6}|' + _NUM_WORD_ALT + r')\b'


def _count_token_to_int(tok):
    """Convert a digit string or a spelled cardinal ('fourteen') to int, else None.

    Thousands separators are stripped first: "11,971" is one number, not two.
    """
    if tok is None:
        return None
    tok = tok.strip().lower()
    bare = tok.replace(",", "")
    if bare.isdigit():
        return int(bare)
    return _CARDINAL_WORDS.get(tok)


# ── EXTRACT FOLLOW-UP PERIOD FROM ABSTRACT ───────────────
def extract_followup_period(abstract_text):
    """
    Extracts follow-up duration from abstract text.
    Returns (value, unit) tuple or None.
    e.g. (24, 'months') or (5, 'years')

    Within each unit tier the LONGEST duration wins (e.g. "at 6 and 12 mo"
    → 12), because in endodontics longer follow-up = stronger evidence.
    """
    if not abstract_text:
        return None

    year_patterns = [
        r'(\d+)[\s\-]year\s+follow[\s\-]?up',
        r'follow[\s\-]?up\s+(?:of\s+)?(\d+)\s+years?',
        r'followed\s+(?:up\s+)?for\s+(\d+)\s+years?',
        r'(\d+)\s+years?\s+(?:of\s+)?(?:follow[\s\-]?up|observation)',
        r'(?:at|after|over)\s+(\d+)\s+years?',
        # Range, e.g. "follow-up of 5 to 22 years" — take the UPPER bound.
        r'follow[\s\-]?up\s+(?:of\s+|period\s+of\s+|span\s+of\s+)?(?:\d+)\s+to\s+(\d+)\s*years?',
    ]
    month_patterns = [
        r'(\d+)[\s\-]month\s+follow[\s\-]?up',
        r'follow[\s\-]?up\s+(?:of\s+)?(\d+)\s+months?',
        r'followed\s+(?:up\s+)?for\s+(\d+)\s+months?',
        r'(\d+)\s+months?\s+(?:of\s+)?(?:follow[\s\-]?up|observation)',
        r'(?:at|after)\s+(\d+)\s+months?',
        # 'mo'/'mos' abbreviation, e.g. "12-mo follow-up", "After the 12 mo".
        r'(\d+)[\s\-]mos?\b\s*follow[\s\-]?up',
        r'(?:at|after)\s+(?:the\s+)?(\d+)[\s\-]mos?\b',
    ]
    week_patterns = [
        r'(\d+)[\s\-]week\s+follow[\s\-]?up',
        r'follow[\s\-]?up\s+(?:of\s+)?(\d+)\s+weeks?',
        r'followed\s+(?:up\s+)?for\s+(\d+)\s+weeks?',
    ]

    def _max_val(patterns, lo, hi):
        """Largest in-range integer captured by any pattern (last group = value)."""
        vals = []
        for pattern in patterns:
            for m in re.finditer(pattern, abstract_text, re.IGNORECASE):
                groups = [g for g in m.groups() if g is not None]
                if not groups:
                    continue
                try:
                    v = int(groups[-1])
                except ValueError:
                    continue
                if lo <= v <= hi:
                    vals.append(v)
        return max(vals) if vals else None

    # Years first (longest-horizon evidence), then months, then weeks.
    y = _max_val(year_patterns, 1, 30)
    if y is not None:
        return (y * 12, "months")   # normalise to months for uniform scoring

    mo = _max_val(month_patterns, 1, 360)
    if mo is not None:
        return (mo, "months")

    wk = _max_val(week_patterns, 1, 156)
    if wk is not None:
        return (round(wk / 4.3), "months")   # convert to months

    return None

def score_followup(followup_months):
    """
    Scores follow-up period out of 15.
    Longer follow-up = stronger evidence in endodontics.
    """
    if followup_months is None:
        return 5.0  # unknown — partial credit

    if followup_months >= 60:    # 5+ years
        return 15.0
    elif followup_months >= 24:  # 2-5 years
        return 12.0
    elif followup_months >= 12:  # 1-2 years
        return 9.0
    elif followup_months >= 6:   # 6-12 months
        return 6.0
    else:                        # < 6 months
        return 3.0

# ── GENERATE SMART SEARCH TERMS ──────────────────────────
def _clean_single_query(raw: str) -> str:
    """Extract one boolean query from a single-query LLM response.

    The response is a bare string, so JSON quoting is not a risk here, but the
    other observed failure shapes are: code fences, a prose preamble/epilogue
    around the query, and a surrounding quote pair. Pick the line that most
    looks like the query (longest line containing a boolean operator) and
    validate it with _looks_like_query — an unbalanced query must never reach
    PubMed, which reinterprets rather than rejects.
    Returns "" when nothing usable is found, so the caller can retry.
    """
    text = re.sub(r"```(?:json)?", "", raw or "").strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()
    candidates = [ln.strip() for ln in text.splitlines()
                  if " OR " in ln or " AND " in ln]
    if not candidates:
        candidates = [text]
    best = max(candidates, key=len)
    return best if _looks_like_query(best) else ""


def generate_search_terms(question):
    client = anthropic.Anthropic(api_key=_get_api_key())
    # Routed to Haiku 2026-04-27 — was Opus. Reason: single-string structured generation
    # (PubMed query, ≤10 words). Called on EVERY retrieval; the cheapest model is the right one.
    # max_tokens raised 200 → 400: OR-group queries run ~60-80 tokens and a
    # truncated one is an unbalanced-paren query PubMed silently reinterprets.
    message = _invoke_claude(client, function_name="generate_search_terms",
        model=MODELS["structured_fast"],
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": f"""Convert this clinical endodontic question into a PubMed BOOLEAN query.
Return ONLY the query — no explanation, no surrounding quotes, no extra text.

PubMed ANDs bare words together, so a string like "laser irradiation power
settings endodontic disinfection" demands all six words in one record and
returns almost nothing. Write 2-3 concept groups instead, each an OR-list of the
synonyms, abbreviations, device and brand names the field actually uses, joined
by AND. Example for laser disinfection:

  (laser* OR "photodynamic therapy" OR aPDT OR PIPS OR SWEEPS OR Er:YAG OR Nd:YAG OR diode) AND ("root canal" OR endodontic* OR intracanal) AND (disinfect* OR antibacterial OR biofilm OR "E. faecalis")

Rules:
- `*` truncation on stems (disinfect*, endodontic*, irrigat*)
- quote multi-word phrases
- include BOTH abbreviation and expansion for any technique or material
- do NOT add [pt] publication-type filters or endodontics domain terms; both are
  appended automatically and duplicating them only narrows the result set

Question: {question}

PubMed boolean query:"""
        }]
    )
    log_llm_call("generate_search_terms", MODELS["structured_fast"],
                 message.usage, mode="shared")
    search_string = _clean_single_query(message.content[0].text)
    if not search_string:
        # One corrective retry, then fall back to the raw question rather than
        # ship a query we know is mangled. The raw question through PubMed's
        # own term mapping beats an unbalanced boolean string.
        try:
            retry = _invoke_claude(client, function_name="generate_search_terms",
                model=MODELS["structured_fast"], max_tokens=400,
                messages=[{"role": "user", "content":
                    f'Return ONE PubMed boolean query for: "{question}". '
                    f'2-3 OR-groups joined by AND, quoted phrases, * stems. '
                    f'Output the query alone on a single line — no fences, no prose.'}])
            log_llm_call("generate_search_terms", MODELS["structured_fast"],
                         retry.usage, mode="shared")
            search_string = _clean_single_query(retry.content[0].text)
        except Exception as e:
            print(f"  [search_terms] primary-query retry failed: {e}")
    if not search_string:
        print(f"  [search_terms] WARNING: could not parse a usable primary query — "
              f"falling back to the raw question")
        search_string = question
    print(f"  Smart search terms: '{search_string}'")
    return search_string

# ── FETCH METADATA FOR PMIDs ─────────────────────────────
# PROSPERO is a systematic-review registry and is NOT a PubMed DataBank, so it
# only ever appears as free text. Trial registries (ClinicalTrials.gov, ISRCTN,
# IRCT, ...) come from DataBankList instead, which is structured and reliable.
_PROSPERO_RE = re.compile(r"\bPROSPERO\b[^.\n]{0,40}?\bCRD\s*\d{6,}", re.IGNORECASE)

# Designs where pre-registration is a meaningful quality marker. Registration is
# expected for trials and prospective SRs; it is not a norm for case series,
# narrative reviews, or lab work, so absence there must not be penalised.
_REGISTRABLE_LEVELS = {"cochrane", "level1", "level2"}

# PubMed's DataBankList also carries molecular-sequence accessions (GenBank,
# RefSeq, dbSNP, GEO...). Those say nothing about prospective registration, so
# only recognised CLINICAL TRIAL registries count.
_TRIAL_REGISTRIES = {
    "clinicaltrials.gov", "isrctn", "irct", "chictr", "anzctr", "ctri", "drks",
    "eudract", "jprn", "umin-ctr", "ntr", "pactr", "rebec", "rpcec", "slctr",
    "tctr", "cris", "lbctr", "tfda", "who ictrp", "actrn", "nct",
}


def detect_preregistration(level_key: str, registry_ids: list, abstract_text: str) -> tuple:
    """Return (is_registered, source) for THIS paper's own registration.

    Two independent signals, both design-gated:
      1. DataBankList accessions from PubMed (trials) — structured, and populated
         only from the article's own registration, so a review citing other
         trials' NCT numbers cannot trip it.
      2. A PROSPERO CRD number in the abstract (systematic reviews) — free text,
         but the PROSPERO+CRD pairing is specific to the review's own record.

    A bare NCT number in free text is deliberately NOT accepted: reviews and
    meta-analyses routinely quote the registry IDs of their included trials.
    """
    if (level_key or "") not in _REGISTRABLE_LEVELS:
        return False, ""
    for rid in (registry_ids or []):
        name = str(rid).split(":")[0].strip()
        if name.lower() in _TRIAL_REGISTRIES:
            return True, name
    if abstract_text and _PROSPERO_RE.search(abstract_text):
        return True, "PROSPERO"
    return False, ""


# Design tiers only — "classic" is a curation label and "level3" a legacy
# alias, so a demotion must never land on either.
_DEMOTABLE_TIERS = ["cochrane", "level1", "level2", "level3a", "level3b",
                    "level4", "level5"]


def _demote_one_tier(level_key: str) -> str:
    """One step down the design hierarchy; level5 and unknown tiers stay put."""
    try:
        i = _DEMOTABLE_TIERS.index(level_key)
    except ValueError:
        return level_key
    return _DEMOTABLE_TIERS[min(i + 1, len(_DEMOTABLE_TIERS) - 1)]


def _apply_supersession(scored_papers: list) -> list:
    """Live-path twin of the library's superseded_by exclusion.

    Cochrane review updates are new PubMed records; the old versions stay
    indexed, so a live search can retrieve a 2012 version of a review updated
    in 2020. An old version whose replacement is ALSO in this batch adds
    nothing — drop it. One whose replacement was not retrieved still carries
    evidence, but must not sit at the tier its successor earned: demote one
    tier and badge it (format_provenance_badges renders "SUPERSEDED — see
    PMID X" for both retrieval paths), so Claude never treats it as current.

    Note the chain case: the live path does not chain-resolve. In a batch
    holding three generations, the oldest drops only if its DIRECT successor
    is present; the library backfill resolves chains to the terminal version.
    """
    if not scored_papers:
        return scored_papers
    batch_pmids = {p["pmid"] for p in scored_papers}
    kept, dropped = [], 0
    for p in scored_papers:
        succ = p.get("superseded_by") or ""
        if succ and succ in batch_pmids:
            dropped += 1
            continue
        if succ:
            p["level_key"] = _demote_one_tier(p["level_key"])
        kept.append(p)
    if dropped:
        print(f"    [superseded] dropped {dropped} outdated version(s) "
              f"whose current version is in the same batch")
    return kept


def format_provenance_badges(paper: dict) -> str:
    """Render a paper's integrity badges for Claude's evidence context.

    SINGLE source of truth for both retrieval paths — live PubMed
    (fetch_papers) and the stored-column library path (_scored_to_text). Both
    read the same field names, so the two cannot drift apart. Badges are only
    emitted when notable, so their presence carries meaning.
    """
    badges = []
    if paper.get("is_registered"):
        badges.append(f"PRE-REGISTERED ({paper.get('registry') or 'registry'})")
    if paper.get("has_erratum"):
        badges.append("CORRECTION PUBLISHED")
    if paper.get("has_retraction"):
        badges.append("RETRACTION NOTICE — treat with extreme caution")
    if paper.get("superseded_by"):
        badges.append(f"SUPERSEDED — a newer version exists, see PMID "
                      f"{paper['superseded_by']}")
    # Library rows predating the is_reference_text field have journal
    # backfilled to the book title by the migration, so the journal match
    # covers them without a schema change.
    if paper.get("is_reference_text") or \
            "statpearls" in (paper.get("journal") or "").lower():
        badges.append("REFERENCE TEXT — textbook chapter, not primary research")
    if paper.get("medline_indexed") is False:
        badges.append("not MEDLINE-indexed")

    status = paper.get("coi_status")
    if paper.get("has_coi") or status == COI_DECLARED_CONFLICT:
        funder = paper.get("coi_funder") or "undisclosed party"
        badges.append(f"INDUSTRY CONFLICT DECLARED ({funder})")
    elif status == COI_DECLARED_NONE:
        badges.append("authors declared no conflict")
    # COI_NO_STATEMENT is deliberately silent: absence of a declaration is
    # unknown, not clean, and a badge saying so on every pre-2017 paper would
    # be noise rather than signal.
    return (" | " + " | ".join(badges)) if badges else ""


def format_paper_context_line(paper: dict) -> str:
    """One paper's metadata header line for Claude's evidence block.

    Shared by both retrieval paths so the context Claude sees is identical
    whether the evidence came from PubMed or the local library.
    """
    ss   = f"n={paper['sample_size']}" if paper.get("sample_size") else "n=unknown"
    fu   = (f"{paper['followup_months']}mo follow-up"
            if paper.get("followup_months") else "follow-up unknown")
    jif  = f"IF={paper['impact_factor']}" if paper.get("impact_factor") else "IF=unknown"
    auth = paper.get("authors", "") or "Unknown author"
    return (
        f"\nPMID: {paper['pmid']} | Authors: {auth} | Year: {paper.get('year')} | "
        f"Citations: {paper.get('citations', 0)} | {ss} | {fu} | {jif} | "
        f"Evidence Score: {paper.get('score')}/100{format_provenance_badges(paper)}\n"
    )


def _merge_corrections_and_registries(ids: list, metadata: dict) -> None:
    """Populate has_erratum / has_retraction / registry_ids from efetch XML.

    Parsed with defusedxml (XML from a remote source). Mutates `metadata`
    in place; silently leaves defaults on any per-record parse problem.
    """
    if not ids:
        return
    from defusedxml import ElementTree as DET

    fetch_params = _ncbi_params({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    resp = requests.get(f"{NCBI_EUTILS_BASE}/efetch.fcgi", params=fetch_params, timeout=25)
    if resp.status_code != 200:
        return
    root = DET.fromstring(resp.text)

    n_err = n_reg = 0
    for article in root.iter("PubmedArticle"):
        pmid_el = article.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()
        entry = metadata.get(pmid)
        if entry is None:
            continue

        # Corrections / retractions attached to THIS article.
        # "ErratumIn"/"CorrectedandRepublishedIn" => this paper was corrected.
        # "ErratumFor" means this paper IS the correction notice — not a defect.
        # An expression of concern is an unresolved integrity signal and is
        # treated as a correction, not a retraction.
        for cc in article.iter("CommentsCorrections"):
            ref = (cc.get("RefType") or "").lower()
            if ref in ("erratumin", "correctedandrepublishedin", "expressionofconcernin"):
                entry["has_erratum"] = True
            elif ref in ("retractionin", "retractedandrepublishedin"):
                entry["has_retraction"] = True
            elif ref == "updatein":
                # Cochrane versioning: every review update is a NEW PubMed
                # record and the old versions stay indexed. UpdateIn sits on
                # the OLDER record and names its successor (UpdateOf points
                # backwards — confusing the two inverts the feature; verified
                # against raw XML for the CD005296 chain, PMIDs 27905673 /
                # 36512807). The successor PMID is a plain <PMID> CHILD of
                # CommentsCorrections, not a RefPMID attribute.
                succ = cc.find("PMID")
                if succ is not None and (succ.text or "").strip():
                    entry["superseded_by"] = succ.text.strip()

        # Publication types — feeds the level_key backfill from the same pass.
        ptypes = [(pt.text or "").strip() for pt in article.iter("PublicationType")]
        if ptypes:
            entry["pubtypes"] = [p for p in ptypes if p]

        # Indexing status lives on MedlineCitation.
        mc = article.find(".//MedlineCitation")
        if mc is not None and mc.get("Status"):
            entry["medline_indexed"] = mc.get("Status").upper() == "MEDLINE"

        # Authors' own conflict-of-interest declaration (PubMed <CoiStatement>,
        # populated for most records since ~2017). This is the authoritative
        # signal — far better than scanning an abstract for company names,
        # which in endodontics mostly detects product mentions in the methods.
        coi_el = article.find(".//CoiStatement")
        if coi_el is not None and (coi_el.text or "").strip():
            entry["coi_statement"] = " ".join((coi_el.text or "").split())[:1000]

        # Trial / review registry accessions (the article's own registration)
        regs = []
        for db in article.iter("DataBank"):
            name_el = db.find("DataBankName")
            name = (name_el.text or "").strip() if name_el is not None else ""
            for acc in db.iter("AccessionNumber"):
                if acc.text and acc.text.strip():
                    regs.append(f"{name}:{acc.text.strip()}" if name else acc.text.strip())
        if regs:
            entry["registry_ids"] = regs

        if entry["has_erratum"] or entry["has_retraction"]:
            n_err += 1
        if entry["registry_ids"]:
            n_reg += 1

    # Book records (StatPearls chapters, NBK ids) come back as
    # PubmedBookArticle, which the loop above never sees — so they used to get
    # NO provenance at all (no pubtypes, no MEDLINE status, no COI, no
    # corrections) and sailed through at whatever tier the search ran under;
    # three sat at Level I scoring 67. Their PMID lives at BookDocument/PMID,
    # not MedlineCitation/PMID.
    for book in root.iter("PubmedBookArticle"):
        pmid_el = book.find(".//BookDocument/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        entry = metadata.get(pmid_el.text.strip())
        if entry is None:
            continue
        entry["is_book"] = True
        title_el = book.find(".//BookDocument/Book/BookTitle")
        if title_el is not None and (title_el.text or "").strip():
            entry["book_title"] = title_el.text.strip()
        ptypes = [(pt.text or "").strip() for pt in book.iter("PublicationType")]
        if ptypes:
            entry["pubtypes"] = [p for p in ptypes if p]
        # Books are not MEDLINE-indexed journal articles.
        entry["medline_indexed"] = False
        coi_el = book.find(".//CoiStatement")
        if coi_el is not None and (coi_el.text or "").strip():
            entry["coi_statement"] = " ".join((coi_el.text or "").split())[:1000]

    if n_err or n_reg:
        print(f"    [pubmed_xml] {n_err} paper(s) with corrections, "
              f"{n_reg} with registry entries")


def fetch_metadata(ids):
    if not ids:
        return {}

    metadata = {}

    try:
        summary_url = f"{NCBI_EUTILS_BASE}/esummary.fcgi"
        summary_params = _ncbi_params({
            "db":      "pubmed",
            "id":      ",".join(ids),
            "retmode": "json",
        })
        r    = requests.get(summary_url, params=summary_params, timeout=10)
        data = r.json().get("result", {})

        for pmid in ids:
            entry    = data.get(pmid, {})
            pub_date = entry.get("pubdate", "")
            year     = pub_date[:4] if pub_date else "Unknown"
            journal  = entry.get("fulljournalname", "") or entry.get("source", "")

            # Authors — esummary returns a list of {name, authtype, clusterid}
            raw_authors = entry.get("authors", [])
            author_names = [a.get("name", "") for a in raw_authors if a.get("name")]
            # Format: "Smith AB, Jones CD, et al." (cap at 3 then et al.)
            if len(author_names) > 3:
                authors_str = ", ".join(author_names[:3]) + " et al."
            else:
                authors_str = ", ".join(author_names)

            metadata[pmid] = {
                "year":     year,
                "citations": 0,
                "journal":  journal,
                # Short journal abbreviation (e.g. "J Endod") for compact citations
                "journal_abbrev": entry.get("source", "") or journal,
                "authors":  authors_str,
                "volume":   entry.get("volume", "") or "",
                "issue":    entry.get("issue", "") or "",
                "pages":    entry.get("pages", "") or "",
                # Indexing status — "PubMed - indexed for MEDLINE" means the
                # record passed NLM's journal-selection review. Non-indexed
                # records (ahead-of-print, PMC-only deposits) are weaker.
                "medline_indexed": "medline" in (entry.get("recordstatus", "") or "").lower(),
                "pubtypes":  entry.get("pubtype", []) or [],
                # Filled in by the efetch-XML pass below
                "has_erratum":  False,
                "has_retraction": False,
                "registry_ids": [],
                "coi_statement": "",
                "superseded_by": "",
            }

    except Exception as e:
        print(f"    Metadata fetch error: {e}")
        for pmid in ids:
            metadata[pmid] = {"year": "Unknown", "citations": 0, "journal": "",
                              "journal_abbrev": "", "authors": "",
                              "volume": "", "issue": "", "pages": "",
                              "medline_indexed": True, "pubtypes": [],
                              "has_erratum": False, "has_retraction": False,
                              "registry_ids": [], "coi_statement": "",
                              "superseded_by": ""}

    # ── Corrections + trial-registry pass (efetch XML) ────────────────────
    # esummary carries neither CommentsCorrections nor DataBankList, so one XML
    # call per batch supplies both. DataBankList is the AUTHORITATIVE
    # pre-registration signal: PubMed populates it from the article's OWN
    # registration, so a systematic review that merely cites other trials'
    # NCT numbers cannot be mistaken for a registered study.
    try:
        _merge_corrections_and_registries(ids, metadata)
    except Exception as e:
        print(f"    Corrections/registry fetch error (non-critical): {e}")

    try:
        elink_url = f"{NCBI_EUTILS_BASE}/elink.fcgi"
        elink_params = _ncbi_params({
            "dbfrom":   "pubmed",
            "db":       "pubmed",
            "id":       ids,
            "linkname": "pubmed_pubmed_citedin",
            "retmode":  "json",
        })
        r         = requests.get(elink_url, params=elink_params, timeout=10)
        link_data = r.json()

        linksets = link_data.get("linksets", [])
        for linkset in linksets:
            source_ids   = linkset.get("ids", [])
            link_set_dbs = linkset.get("linksetdbs", [])
            for lsdb in link_set_dbs:
                if lsdb.get("linkname") == "pubmed_pubmed_citedin":
                    citing_ids = lsdb.get("links", [])
                    for pmid in source_ids:
                        if pmid in metadata:
                            metadata[pmid]["citations"] = len(citing_ids)

    except Exception as e:
        print(f"    Citation fetch error (non-critical): {e}")

    return metadata

# ── EXTRACT SAMPLE SIZE ───────────────────────────────────
# Units that count STUDIES, not people. In a systematic review "we included 12
# studies" and "n=12 trials" are counts of included papers; reading either as a
# sample size scores a meta-analysis of 1,300 patients like a 12-person pilot.
_STUDY_UNIT_RE = re.compile(
    r"^\s*(?:included\s+|eligible\s+|relevant\s+|primary\s+|randomi[sz]ed\s+)?"
    r"(?:stud(?:y|ies)|trials?|rcts?|articles?|publications?|papers?|reports?|"
    r"investigations?|reviews?|databases?|records?|citations?|comparisons?|"
    r"meta-analys[ie]s|abstracts?)\b",
    re.IGNORECASE,
)

# In a review abstract a bare number is usually NOT the pooled participant
# count. It is a search yield ("a total of 2098 reports"), an eligibility
# threshold ("articles including at least 10 patients"), or a subgroup
# ("cerebral palsy (n = 5)"). For reviews we therefore accept a count only when
# it is explicitly framed as the pooled total across included studies, and
# exempt the paper otherwise — an exemption is honest about not knowing,
# whereas a subgroup or threshold silently understates a synthesis.
_REVIEW_TOTAL_RE = re.compile(
    r"(?:total(?:ling|ing)?\s+(?:of\s+)?|pooled\s+|comprising\s+|combined\s+|"
    r"cumulative\s+|overall\s+|involving\s+|encompass\w*\s+|across\s+)"
    r"[^.;]{0,30}?\b(\d{1,3}(?:,\d{3})+|\d{2,6})\b[^.;]{0,20}?"
    r"\b(?:patients?|participants?|subjects?|teeth|tooth|canals?|cases?|children|adults?)\b"
    r"|\b(\d{1,3}(?:,\d{3})+|\d{2,6})\b\s+(?:patients?|participants?|subjects?|teeth|tooth|canals?)\s+"
    r"(?:were\s+)?(?:included|analy[sz]ed|pooled|evaluated|assessed)\b"
    # "29 trials (4341 patients) were included" — a study count immediately
    # followed by a parenthesised participant total. Very common in review
    # abstracts, and unambiguous: the parenthetical qualifies the study count.
    r"|\b\d{1,4}\s+(?:trials?|studies|rcts?|articles?)\s*\(\s*"
    r"(?:n\s*=\s*)?(\d{1,3}(?:,\d{3})+|\d{2,6})\s*"
    r"(?:patients?|participants?|subjects?|teeth|tooth|canals?)\s*\)",
    re.IGNORECASE,
)

# Eligibility thresholds and subgroup labels — never a pooled total.
_THRESHOLD_RE = re.compile(
    r"\b(?:at\s+least|minimum\s+of|fewer\s+than|less\s+than|more\s+than|"
    r"greater\s+than|over|under|>=?|<=?)\s*$",
    re.IGNORECASE,
)

_REVIEW_DESIGN_RE = re.compile(
    r"\b(?:systematic\s+review|meta-?analys[ie]s|scoping\s+review|"
    r"umbrella\s+review|network\s+meta-?analysis|pooled\s+analysis)\b",
    re.IGNORECASE,
)


def is_review_design(level_key: str = "", abstract_text: str = "") -> bool:
    """Is this an evidence-synthesis paper rather than a primary study?

    Cochrane entries always are. Level I mixes RCTs with SRs/meta-analyses, so
    for those the abstract text decides.
    """
    if (level_key or "").strip() == "cochrane":
        return True
    if (level_key or "").strip() in ("level1", "classic"):
        return bool(_REVIEW_DESIGN_RE.search(abstract_text or ""))
    return False


def extract_sample_size(abstract_text, level_key: str = ""):
    """Participant count for this paper, or None when it cannot be read.

    For reviews the count of INCLUDED STUDIES is rejected: only participant
    counts qualify. Returning None for a review is deliberate — score_paper()
    exempts reviews from the sample-size term rather than penalising them,
    the same way classics are exempt from the recency term.
    """
    if not abstract_text:
        return None

    # Reviews take a stricter path: only an explicitly-pooled total counts.
    if is_review_design(level_key, abstract_text):
        best = None
        for m in _REVIEW_TOTAL_RE.finditer(abstract_text):
            # Alternatives contribute different capture groups; take whichever
            # one fired rather than hard-coding indices (a third alternative was
            # added later and silently never read).
            raw = next((g for g in m.groups() if g), None)
            n = _count_token_to_int(raw) if raw else None
            if n is None or not (5 <= n <= 1000000):
                continue
            if _THRESHOLD_RE.search(abstract_text[max(0, m.start() - 25):m.start()]):
                continue                      # "at least 10 patients"
            best = n if best is None else max(best, n)
        return best

    # High-priority idiom: attrition/analysis cohorts, e.g. "Fourteen of 24
    # patients were available", "150 of 200 patients completed the trial".
    # The FIRST number is the analysable sample size for THIS study — the
    # bare max() below would otherwise grab the larger enrolled-pool figure.
    attrition = re.search(
        _COUNT_TOKEN + r'\s+of\s+\d+\s+(?:patients|subjects|participants)'
        r'[\s\w,]{0,25}?(?:available|analy[sz]ed|evaluated|assessed|'
        r'completed|recalled|retained|included)',
        abstract_text, re.IGNORECASE)
    if attrition:
        n = _count_token_to_int(attrition.group(1))
        if n is not None and 1 <= n <= 100000:
            return n

    patterns = [
        r'\bn\s*=\s*(\d+)',
        _COUNT_TOKEN + r'\s+patients',
        _COUNT_TOKEN + r'\s+teeth',
        _COUNT_TOKEN + r'\s+subjects',
        _COUNT_TOKEN + r'\s+participants',
        _COUNT_TOKEN + r'\s+cases',
        r'total\s+of\s+' + _COUNT_TOKEN,
        r'included\s+' + _COUNT_TOKEN,
        r'enrolled\s+' + _COUNT_TOKEN,
        r'comprised\s+' + _COUNT_TOKEN,
        _COUNT_TOKEN + r'\s+root\s+canals?',
        _COUNT_TOKEN + r'\s+molars',
        _COUNT_TOKEN + r'\s+premolars',
    ]

    found_sizes = []
    for pattern in patterns:
        for m in re.finditer(pattern, abstract_text, re.IGNORECASE):
            n = _count_token_to_int(m.group(1))
            if n is None or not (5 <= n <= 100000):
                continue
            # Reject counts of studies rather than of people. "n=12 studies",
            # "included 12 trials", "12 RCTs" are review bookkeeping, not a
            # sample size — and the max() below would otherwise happily take
            # them when no participant count is stated.
            if _STUDY_UNIT_RE.match(abstract_text[m.end():m.end() + 40]):
                continue
            found_sizes.append(n)

    if found_sizes:
        return max(found_sizes)

    # A review with no stated participant count: report unknown rather than
    # guessing. score_paper() exempts reviews from the sample-size term.
    return None

# ── SCORE A PAPER ────────────────────────────────────────
CITATION_GRACE_PERIOD_YEARS = 2   # papers ≤ 2 yrs old get a flat baseline citation score

# ── IMPACT-FACTOR TOGGLE ──────────────────────────────────
# When off (default), journal impact factor is EXCLUDED from paper scoring and
# the remaining five factors are renormalised so scores stay on the 0-100
# scale. The IF value is still looked up and displayed as reference metadata.
# Re-enable with USE_IMPACT_FACTOR=true in the environment.
USE_IMPACT_FACTOR = os.getenv("USE_IMPACT_FACTOR", "false").lower() in ("1", "true", "yes")

_SCORE_WEIGHTS_DESC = (
    """- Study design (35%)
- Sample size (15%)
- Recency (15%)
- Citation velocity / citations per year (15%) — papers ≤2 years old receive a baseline score and are NOT penalised for being new
- Follow-up period (10%)
- Journal impact factor (10%)"""
    if USE_IMPACT_FACTOR else
    """- Study design (39%)
- Sample size (17%)
- Recency (17%)
- Citation velocity / citations per year (16%) — papers ≤2 years old receive a baseline score and are NOT penalised for being new
- Follow-up period (11%)
(Journal impact factor is shown for reference only — it is EXCLUDED from the score.)"""
)


def score_citations_velocity(citations: int, year) -> float:
    """
    Citation velocity = citations per year since publication.
    Papers ≤ 2 years old receive a flat baseline (9 pts) so newly-published work
    isn't penalised for not having had time to accrue citations.
    """
    current_year = datetime.now().year
    try:
        age = current_year - int(year)
    except (ValueError, TypeError):
        age = 5

    if age <= CITATION_GRACE_PERIOD_YEARS:
        return 9.0  # baseline for fresh papers — neither bonus nor penalty

    velocity = (citations or 0) / max(age, 1)
    if   velocity >= 30: return 15.0
    elif velocity >= 15: return 13.0
    elif velocity >= 7:  return 11.0
    elif velocity >= 3:  return 8.0
    elif velocity >= 1:  return 5.0
    elif velocity > 0:   return 3.0
    else:                return 1.0

def score_paper(level_key, year, citations, sample_size,
                followup_months, if_score, is_review: bool = False):
    """
    Scores a paper 0-100:
      Study design       35%
      Sample size        15%
      Recency            15%
      Citation velocity  15%  ← citations/year, 2-yr grace period
      Follow-up          10%
      Impact factor      10%  ← only when USE_IMPACT_FACTOR=true; otherwise
                                excluded and the other five renormalised to 100
    """
    design_score = LEVEL_SCORES.get(level_key, 10) * 0.35

    # Sample size (15 pts)
    if sample_size is None and is_review:
        # A review with no stated participant count is exempt rather than
        # penalised — same precedent as classics being exempt from recency.
        # A synthesis pooling multiple trials is presumptively better powered
        # than any single one of them, so the 5.0 "unknown" penalty is exactly
        # backwards for this design.
        sample_score = 12.0
    elif sample_size is None:
        sample_score = 5.0
    elif sample_size >= 200:
        sample_score = 15.0
    elif sample_size >= 100:
        sample_score = 12.0
    elif sample_size >= 50:
        sample_score = 9.0
    elif sample_size >= 20:
        sample_score = 6.0
    else:
        sample_score = 3.0

    # Recency (15 pts) — classics are explicitly exempted (the whole point of
    # the tier is that these foundational papers are valuable BECAUSE they're
    # old; penalising age would defeat the purpose).
    current_year = datetime.now().year
    try:
        age = current_year - int(year)
    except:
        age = 10

    if level_key == "classic":
        recency_score = 12.0   # near-max, but slightly below truly recent (15)
    elif age <= 3:
        recency_score = 15.0
    elif age <= 7:
        recency_score = 12.0
    elif age <= 12:
        recency_score = 8.0
    elif age <= 20:
        recency_score = 4.0
    else:
        recency_score = 1.0

    # Citation velocity (15 pts) — citations / years since pub, with grace period.
    # Classics get a baseline 10/15 instead since we don't fetch citation
    # counts during ingestion (extra elink call per paper would 4x the runtime).
    if level_key == "classic":
        citation_score = 10.0
    else:
        citation_score = score_citations_velocity(citations or 0, year)

    # Follow-up (10 pts) — scale from 15-pt score
    fu_score = score_followup(followup_months) * (10.0 / 15.0)

    # Impact factor (10 pts) — scale from 15-pt score.
    # With USE_IMPACT_FACTOR off, IF contributes nothing and the other five
    # factors (max 90 pts) are renormalised back onto the 0-100 scale, so the
    # quality floor (50) and RAG score bands keep their meaning.
    if USE_IMPACT_FACTOR:
        if_pts = if_score * (10.0 / 15.0)
        total  = design_score + sample_score + recency_score + citation_score + fu_score + if_pts
    else:
        if_pts = 0.0
        total  = (design_score + sample_score + recency_score + citation_score + fu_score) / 0.90

    return round(total, 1), {
        "design":        round(design_score, 1),
        "sample":        round(sample_score, 1),
        "recency":       round(recency_score, 1),
        "citations":     round(citation_score, 1),
        "followup":      round(fu_score, 1),
        "impact_factor": round(if_pts, 1)
    }

# ── FETCH COCHRANE ────────────────────────────────────────
def fetch_cochrane(topic, max_results=3):
    print(f"  Searching Cochrane for: '{topic}'...")
    try:
        url = "https://www.cochranelibrary.com/api/search/searchresults"
        params  = {"q": topic, "p": "1", "n": max_results, "t": "1"}
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data    = response.json()
            results = data.get("results", [])
            if not results:
                print("  OK Cochrane: No results found, using PubMed fallback")
                return ""
            text = ""
            for r in results:
                title    = r.get("title", "No title")
                abstract = r.get("abstract", "No abstract available")
                doi      = r.get("doi", "")
                year     = r.get("publicationDate", "")[:4] if r.get("publicationDate") else ""
                text += f"\nTitle: {title}\nYear: {year}\nDOI: {doi}\nAbstract: {abstract}\n"
                text += "-" * 40 + "\n"
            print(f"  OK Cochrane:{len(results)} reviews found")
            return text
        else:
            print(f"  OKCochrane API unavailable (status {response.status_code}), using PubMed fallback")
            return ""

    except Exception as e:
        print(f"  OK Cochrane:Using PubMed fallback ({e})")
        return ""

# ── FETCH FROM PUBMED ────────────────────────────────────
# Hybrid endodontic constraint — MeSH OR Title/Abstract free-text.
# MeSH-only excludes 6-18 months of newly-indexed papers; the [tiab] terms
# pull those in until PubMed catches up with curation.
ENDO_DOMAIN_FILTER = (
    '(endodontics[MeSH] OR "dental pulp"[MeSH] OR "periapical diseases"[MeSH] '
    'OR endodontic*[tiab] OR "root canal"[tiab] OR "root canals"[tiab] '
    'OR "dental pulp"[tiab] OR pulpitis[tiab] OR "periapical"[tiab] '
    'OR "pulp therapy"[tiab] OR "pulp capping"[tiab])'
)

_PMID_FORMAT_RE = re.compile(r"^\d{1,9}$")


def _pubmed_audit_log(label: str, level_key: str, search_term: str,
                       returned_pmids: list, http_status: int, ms: int) -> None:
    """Append-only proof-of-fetch log: every esearch call we make against NCBI
    is recorded with the exact search term, returned PMIDs, HTTP status, and
    latency. This is the audit trail showing PMIDs came from a live NCBI
    response — not synthesised. Stored in pubmed_audit.jsonl."""
    rec = {
        "ts":           datetime.now().isoformat(),
        "label":        label,
        "level_key":    level_key,
        "search_term":  search_term[:600],
        "n_returned":   len(returned_pmids),
        "pmid_sample":  returned_pmids[:10],
        "http_status":  http_status,
        "latency_ms":   ms,
    }
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "pubmed_audit.jsonl")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except Exception as e:
        print(f"    [pubmed_audit] write failed: {e}")


def fetch_papers(topic, filter_term, label, level_key, max_results=50, mode="review"):
    # Exclude retracted papers at the search level — free, no extra API call
    search_term = (
        f"({topic}) AND ({filter_term}) AND {ENDO_DOMAIN_FILTER} "
        f'NOT "Retracted Publication"[pt] NOT "Retraction of Publication"[pt]'
    )

    search_url    = f"{NCBI_EUTILS_BASE}/esearch.fcgi"
    search_params = _ncbi_params({
        "db":      "pubmed",
        "term":    search_term,
        "retmax":  max_results,
        "retmode": "json",
        "sort":    "relevance",
    })

    try:
        # ── LIVE NCBI esearch — never fakes results ──
        # Explicit logging makes the live-fetch nature visible and the audit
        # log records every call so we can prove later that any PMID we
        # showed Claude came from a real NCBI response at a known timestamp.
        t0 = _time.perf_counter()
        search_response = requests.get(search_url, params=search_params, timeout=20)
        latency_ms = int((_time.perf_counter() - t0) * 1000)

        if search_response.status_code != 200:
            print(f"  XX {label}: NCBI esearch HTTP {search_response.status_code} — abandoning tier")
            _pubmed_audit_log(label, level_key, search_term, [],
                              search_response.status_code, latency_ms)
            return "", [], []

        try:
            raw_ids = search_response.json()["esearchresult"]["idlist"] or []
        except (ValueError, KeyError):
            print(f"  XX {label}: NCBI esearch returned malformed JSON — abandoning tier")
            _pubmed_audit_log(label, level_key, search_term, [],
                              search_response.status_code, latency_ms)
            return "", [], []

        # PMID format guard — reject anything that isn't well-formed numeric.
        # NCBI should never return malformed IDs, but if some upstream layer
        # ever injected fake-looking IDs, this catches them before they hit
        # Claude's evidence context.
        ids = [pid for pid in raw_ids if _PMID_FORMAT_RE.match(str(pid))]
        rejected = len(raw_ids) - len(ids)
        if rejected:
            print(f"    [pmid_guard] rejected {rejected} malformed ID(s) from NCBI response")

        print(f"  [NCBI_LIVE] {label}: esearch returned {len(ids)} PMIDs in {latency_ms}ms (HTTP 200)")
        _pubmed_audit_log(label, level_key, search_term, ids,
                          search_response.status_code, latency_ms)

        if not ids:
            print(f"  -- {label}: 0 results found")
            return "", [], []

        fetch_url    = f"{NCBI_EUTILS_BASE}/efetch.fcgi"
        fetch_params = _ncbi_params({
            "db":      "pubmed",
            "id":      ",".join(ids),
            "rettype": "abstract",
            "retmode": "text",
        })
        fetch_response = requests.get(fetch_url, params=fetch_params, timeout=20)
        abstract_text  = fetch_response.text

        print(f"    Fetching metadata for {len(ids)} papers...")
        metadata = fetch_metadata(ids)

        # Parse per-PMID abstracts once — used for three purposes:
        #   1. Postgres abstract cache population (provenance panel)
        #   2. Per-paper sample_size / followup extraction (fixes metadata broadcast bug
        #      where the old code passed the full batch text to extract_sample_size /
        #      extract_followup_period, broadcasting one paper's n= to every paper)
        #   3. Selective abstract inclusion in annotated_text (only kept papers)
        _per_pmid = _parse_efetch_batch(abstract_text)

        try:
            from rag import bulk_cache_abstracts
            cache_entries = []
            for pmid, parts in _per_pmid.items():
                m = metadata.get(pmid, {}) or {}
                cache_entries.append({
                    "pmid":     pmid,
                    "title":    parts.get("title") or "",
                    "abstract": parts.get("abstract") or "",
                    "journal":  m.get("journal") or "",
                    "year":     m.get("year")    or "",
                    "authors":  m.get("authors") or "",
                    "source":   "efetch_batch",
                })
            n_cached = bulk_cache_abstracts(cache_entries) if cache_entries else 0
            if n_cached:
                print(f"    [abstract_cache] persisted {n_cached} abstracts from this batch")
        except Exception as _ce:
            print(f"    [abstract_cache] write skipped: {_ce}")

        # COI is evaluated PER PAPER below (title + its own abstract). A batch-wide
        # scan is only used for the tier log line, never for scoring: one paper
        # naming an industry funder must not penalise the other 49 in the batch.
        _batch_has_coi, _batch_funder = check_coi_blocklist(abstract_text)
        if _batch_has_coi:
            print(f"    [COI] '{_batch_funder}' mentioned somewhere in {label} — "
                  f"evaluating per paper")

        n_coi_papers = n_registered = n_corrected = 0
        scored_papers = []
        for pmid in ids:
            meta    = metadata.get(pmid, {"year": "Unknown", "citations": 0, "journal": "", "authors": ""})

            # Use this paper's own abstract for metadata extraction — NOT the full
            # batch text. The old code passed abstract_text (all 50 papers) to both
            # functions, so the regex found the largest n= in the batch (typically a
            # meta-analysis) and stamped it on every unrelated paper.
            _parts      = _per_pmid.get(pmid, {})
            paper_text  = _parts.get('abstract', '') or ''

            # Reference-text chapters (StatPearls etc., PubmedBookArticle
            # records) are narrative summaries, not studies of the design this
            # tier searched for. The tier override has to happen BEFORE
            # scoring, or the book keeps the design premium of the tier it was
            # retrieved under — which is exactly how three textbook chapters
            # ended up at Level I scoring 67.
            is_book   = bool(meta.get("is_book"))
            eff_level = "level5" if is_book else level_key

            paper_is_review = is_review_design(eff_level, paper_text)
            sample_size     = extract_sample_size(paper_text, eff_level)
            followup        = extract_followup_period(paper_text)
            followup_months = followup[0] if followup else None
            journal_name    = meta.get("journal", "") or meta.get("book_title", "")
            if_val, if_pts  = get_impact_factor(journal_name)

            score, breakdown = score_paper(
                eff_level,
                meta["year"],
                meta["citations"],
                sample_size,
                followup_months,
                if_pts,
                is_review=paper_is_review,
            )

            # COI (15% penalty) from the authors' own PubMed declaration, else
            # a declaration-scoped abstract scan. Deliberately NOT a bare
            # company-name match: endodontic papers name their materials'
            # manufacturers in the methods, which is a product mention, not a
            # conflict. Also per-paper, not per-batch (an earlier version
            # penalised every paper in a tier when any one named a funder).
            coi_status, coi_funder = classify_coi(
                meta.get("coi_statement", "") or "", paper_text
            )
            has_coi = coi_status == COI_DECLARED_CONFLICT
            if has_coi:
                score = round(score * 0.85, 1)
                n_coi_papers += 1

            # ── Provenance-quality adjustments ──
            # Deliberately modest: these are integrity signals, not design
            # quality, and none should outweigh study design (39%). Each is
            # also surfaced as a badge so the clinician sees the reason.
            is_registered, reg_source = detect_preregistration(
                eff_level, meta.get("registry_ids") or [], paper_text
            )
            if is_registered:
                score = round(min(score * 1.05, 100.0), 1)   # pre-registered trial/SR
                n_registered += 1
            if meta.get("has_erratum"):
                score = round(score * 0.97, 1)               # corrected post-publication
                n_corrected += 1
            if meta.get("has_retraction"):
                score = round(score * 0.50, 1)               # slipped past the [pt] filter
                n_corrected += 1
            if meta.get("medline_indexed") is False:
                score = round(score * 0.97, 1)               # not NLM-indexed

            # Currency tagging
            try:
                age = datetime.now().year - int(meta["year"])
            except (ValueError, TypeError):
                age = 10

            scored_papers.append({
                "pmid":            pmid,
                # The tier this paper was retrieved under. Previously omitted,
                # so write-back inserted live results with an empty level_key —
                # they were then banded to the weakest tier on every later
                # query, quietly burying good RCTs as Level V evidence.
                # (eff_level, not level_key: book records are overridden to
                # level5 regardless of the tier the search ran under.)
                "level_key":       eff_level,
                "is_reference_text": is_book,
                "year":            meta["year"],
                "citations":       meta["citations"],
                "authors":         meta.get("authors", ""),
                "sample_size":     sample_size,
                "followup_months": followup_months,
                "journal":         journal_name,
                "journal_abbrev":  meta.get("journal_abbrev", "") or journal_name,
                "volume":          meta.get("volume", ""),
                "issue":           meta.get("issue", ""),
                "pages":           meta.get("pages", ""),
                "impact_factor":   if_val,
                "score":           score,
                "breakdown":       breakdown,
                "has_coi":         has_coi,
                "coi_funder":      coi_funder if has_coi else "",
                "coi_status":      coi_status,
                "is_registered":   is_registered,
                "registry":        reg_source,
                "has_erratum":     bool(meta.get("has_erratum")),
                "has_retraction":  bool(meta.get("has_retraction")),
                "superseded_by":   meta.get("superseded_by", "") or "",
                "medline_indexed": meta.get("medline_indexed", True),
                "is_old":          age > CURRENCY_THRESHOLD_YEARS,
                "age_years":       age,
                "is_outlier":      False,  # set later by detect_outliers()
            })

        # A paper only belongs in the cochrane tier if it was published in the
        # Cochrane Database. Anything else that lands here is a systematic
        # review in an ordinary journal and is demoted to Level I, which is
        # where it genuinely sits. Guards against a filter regression putting
        # journal SRs where the prompt grants overriding authority.
        if level_key == "cochrane":
            demoted = 0
            for p in scored_papers:
                jl = (p.get("journal") or "").lower()
                if not any(h in jl for h in _COCHRANE_JOURNAL_HINTS):
                    p["level_key"] = "level1"
                    demoted += 1
            if demoted:
                print(f"    [tier] demoted {demoted} non-Cochrane review(s) "
                      f"from the cochrane tier to level1")

        scored_papers = _apply_supersession(scored_papers)

        if n_coi_papers:
            print(f"    [COI] {n_coi_papers} of {len(ids)} papers carry an industry-funder "
                  f"mention — 15% penalty applied to those only")
        if n_registered or n_corrected:
            print(f"    [provenance] {n_registered} pre-registered, "
                  f"{n_corrected} with corrections/retractions")

        scored_papers.sort(key=lambda x: x["score"], reverse=True)

        # ── Dynamic retrieval limits ──
        # Mode-aware per-tier cap. Review biases Tiers I-III; Learn promotes Tier V.
        kept = _apply_quality_threshold(scored_papers, mode=mode, tier_key=level_key)
        if len(kept) < len(scored_papers):
            print(f"    [quality] kept {len(kept)} of {len(scored_papers)} papers above threshold (mode={mode}, tier={level_key})")
        scored_papers = kept

        # Build annotated text block — only include abstracts for kept papers.
        # Reuses _per_pmid parsed above; no second call to _parse_efetch_batch.
        annotated_text = f"\n[{label}]\n"
        for p in scored_papers:
            annotated_text += format_paper_context_line(p)
            ab = _per_pmid.get(p['pmid'], {})
            if ab.get('abstract'):
                annotated_text += ab['abstract'] + "\n"
            elif ab.get('title'):
                annotated_text += ab['title'] + "\n"

        print(f"  OK{label}: {len(ids)} papers -- top score {scored_papers[0]['score']}/100")

        # Write good papers back into the library so it learns from the topics
        # clinicians actually ask about, instead of staying frozen at its
        # ingestion date while the coverage gate keeps preferring it.
        if LIBRARY_WRITE_BACK:
            try:
                from rag import learn_from_live_results
                learn_from_live_results(scored_papers, _per_pmid)
            except Exception as _we:
                print(f"    [learn] write-back skipped: {_we}")

        return annotated_text, ids, scored_papers

    except Exception as e:
        print(f"  XX{label}: Could not fetch ({e})")
        return "", [], []

# ── DYNAMIC QUALITY THRESHOLD ─────────────────────────────
# Live results above the quality floor are added to the local library, so the
# corpus tracks what clinicians actually ask about. Disable with
# LIBRARY_WRITE_BACK=false if the library must stay a curated, fixed set.
LIBRARY_WRITE_BACK = os.getenv("LIBRARY_WRITE_BACK", "true").lower() in ("1", "true", "yes")

QUALITY_FLOOR    = 50   # min score to count as "quality" evidence
MIN_PAPERS_KEPT  = 3    # keep at least this many even if low-quality (avoid empty tier)
MAX_PAPERS_KEPT  = 25   # default hard cap so one tier can't drown out others

# Mode-specific per-tier paper caps.
#   review  — chairside literature review: bias toward Tiers I-III primary evidence
#   learn   — deep-learning lecture: over-index on Tier V reviews/editorials/guidelines
#             (they supply the narrative scaffolding a 20-min teaching module needs)
MODE_TIER_QUOTAS = {
    "review": {
        "cochrane": 10, "level1": 18, "level2": 14,
        "level3a": 10, "level3b": 6, "level3": 8,
        "level4": 4,   "level5": 4,
    },
    "learn": {
        "cochrane": 8,  "level1": 10, "level2": 8,
        "level3a": 6,  "level3b": 4,  "level3": 6,
        "level4": 6,   "level5": 25,   # narrative-rich tier promoted
    },
    # case discussion uses the same balance as review
    "case": {
        "cochrane": 10, "level1": 18, "level2": 14,
        "level3a": 10, "level3b": 6, "level3": 8,
        "level4": 4,   "level5": 4,
    },
}

def _tier_cap(mode: str, tier_key: str) -> int:
    """Look up the per-tier paper cap for a given mode. Falls back to MAX_PAPERS_KEPT."""
    table = MODE_TIER_QUOTAS.get(mode) or MODE_TIER_QUOTAS["review"]
    return table.get(tier_key, MAX_PAPERS_KEPT)

def _apply_quality_threshold(scored_papers: list, mode: str = "review",
                              tier_key: str = "") -> list:
    """
    Quality-driven cut with mode-aware per-tier caps:
      - retain every paper scoring >= QUALITY_FLOOR
      - if fewer than MIN_PAPERS_KEPT survive, top up with the next-best
      - never keep more than the per-tier cap for the active mode
    Caller is responsible for sorting by score before calling.
    """
    if not scored_papers:
        return scored_papers

    cap = _tier_cap(mode, tier_key) if tier_key else MAX_PAPERS_KEPT
    above = [p for p in scored_papers if p.get("score", 0) >= QUALITY_FLOOR]

    if len(above) >= MIN_PAPERS_KEPT:
        return above[:cap]

    # Sparse tier — top up to MIN_PAPERS_KEPT with the best remaining
    return scored_papers[:max(MIN_PAPERS_KEPT, len(above))][:cap]


# ── WITHIN-TIER SYNTHESIS ORDER ──────────────────────────
# Strict tier hierarchy means a Tier 4 paper that scored 90 must NEVER outrank
# a Tier 1 paper that scored 70 in the synthesis order Claude sees.
def build_synthesis_order(evidence: dict) -> list:
    """
    Returns a single flattened list of papers with strict tier hierarchy:
    every cochrane paper, then every level1 paper, etc. Within each tier,
    papers are sorted by score descending.
    """
    ordered = []
    for tier_key in TIER_ORDER:
        tier_block = evidence.get(tier_key, {})
        scored = tier_block.get("scored", []) or []
        scored = sorted(scored, key=lambda p: p.get("score", 0), reverse=True)
        for p in scored:
            p_copy = dict(p)
            p_copy["tier_key"]   = tier_key
            p_copy["tier_label"] = TIER_LABEL.get(tier_key, tier_key)
            ordered.append(p_copy)
    return ordered


# ── BUILD EVIDENCE BASE ───────────────────────────────────
def build_evidence_base(topic, mode: str = "review"):
    """Build a tier-organised evidence base. `mode` controls per-tier paper caps:
    'review' biases primary evidence, 'learn' promotes Tier V narrative sources."""
    print(f"\nBuilding evidence base for: '{topic}' (mode={mode})")
    print("-" * 50)

    evidence   = {}
    all_scored = []

    smart_topic = generate_search_terms(topic)

    # Cochrane
    cochrane_direct = fetch_cochrane(smart_topic)
    if cochrane_direct:
        evidence["cochrane"] = {"text": cochrane_direct, "ids": [], "scored": []}
    else:
        text, ids, scored = fetch_papers(smart_topic, COCHRANE_TERM,
                                         "Cochrane Reviews (PubMed)", "cochrane",
                                         mode=mode)
        evidence["cochrane"] = {"text": text, "ids": ids, "scored": scored}
        all_scored.extend(scored)

    # Levels 1-5 (Tier 3 split into 3a retrospective cohort + 3b case-control)
    levels = [
        ("level1",  LEVEL_1_TERMS,  TIER_LABEL["level1"]),
        ("level2",  LEVEL_2_TERMS,  TIER_LABEL["level2"]),
        ("level3a", LEVEL_3A_TERMS, TIER_LABEL["level3a"]),
        ("level3b", LEVEL_3B_TERMS, TIER_LABEL["level3b"]),
        ("level4",  LEVEL_4_TERMS,  TIER_LABEL["level4"]),
        ("level5",  LEVEL_5_TERMS,  TIER_LABEL["level5"]),
    ]

    for level_key, terms, label in levels:
        text, ids, scored = fetch_papers(
            smart_topic, " OR ".join(terms), label, level_key, mode=mode
        )
        evidence[level_key] = {"text": text, "ids": ids, "scored": scored}
        all_scored.extend(scored)

    # Summary
    avg_score = 0
    if all_scored:
        avg_score = sum(p["score"] for p in all_scored) / len(all_scored)
        top_paper = max(all_scored, key=lambda x: x["score"])
        print(f"\n  Evidence base summary:")
        print(f"  Total papers scored: {len(all_scored)}")
        print(f"  Average score:       {avg_score:.1f}/100")
        print(f"  Top paper:           PMID {top_paper['pmid']} -- {top_paper['score']}/100")
        if top_paper.get("journal"):
            print(f"  Top journal:         {top_paper['journal']} (IF={top_paper.get('impact_factor', 'unknown')})")

    # PRISMA-style dedup — flag primary studies already synthesised in a newer SR
    flag_superseded_by_review(evidence)

    # synthesis_order = strict tier hierarchy (Cochrane → L1 → L2 → L3a → L3b → L4 → L5)
    # all_scored      = legacy flat-by-score list (retained for status panels / downstream code)
    evidence["_summary"] = {
        "total_scored":    len(all_scored),
        "avg_score":       round(avg_score, 1),
        "all_scored":      sorted(all_scored, key=lambda x: x["score"], reverse=True),
        "synthesis_order": build_synthesis_order(evidence),
    }

    return evidence

# ── BUILD EVIDENCE CONTEXT (TIER-ORDERED) ─────────────────
def _build_evidence_context(evidence: dict) -> str:
    """
    Assemble the evidence block sent to Claude.

    Two principles enforced here:
      1. Tier order is strict (Cochrane → L1 → L2 → L3a → L3b → L3 → L4 → L5).
         The Claude prompt sees tiers in this order regardless of within-tier scores.
      2. The "key papers" panel is now per-tier (top paper from each tier),
         not "top 3 across all tiers" — the old approach let a Tier 4 paper
         outrank a Tier 1 paper just because it scored numerically higher.
    """
    context = ""

    # Per-tier evidence blocks in strict hierarchy order
    for key in TIER_ORDER:
        block = evidence.get(key, {}) or {}
        if block.get("text"):
            label = TIER_LABEL.get(key, key.upper())
            context += f"\n\n=== {label} ===\n" + block["text"]

    summary    = evidence.get("_summary", {}) or {}
    all_scored = summary.get("all_scored", []) or []
    synthesis  = summary.get("synthesis_order", []) or []

    if not all_scored:
        return context

    context += "\n\n=== EVIDENCE QUALITY SUMMARY ===\n"
    context += f"Total papers: {summary.get('total_scored', len(all_scored))} | Avg score: {summary.get('avg_score', 0)}/100\n"

    # COI warning
    coi_papers = [p for p in all_scored if p.get("has_coi")]
    if coi_papers:
        funders = sorted({p.get("coi_funder", "") for p in coi_papers if p.get("coi_funder")})
        context += (
            f"\n⚠️  INDUSTRY FUNDING WARNING: Some papers in this evidence base mention "
            f"industry funders ({', '.join(funders)}). These papers have had their "
            f"evidence scores reduced by 15%. Acknowledge this in your answer where relevant.\n"
        )

    # Outlier warning
    outliers = [p for p in all_scored if p.get("is_outlier")]
    if outliers:
        context += f"\n📊 OUTLIER PAPERS: {len(outliers)} paper(s) have unusually high or low scores compared to peers.\n"

    # Currency warning
    currency_warning = build_currency_warning(all_scored)
    if currency_warning:
        context += currency_warning + "\n"

    # PRISMA-style dedup notice — primary studies already pooled in a newer SR
    superseded = [p for p in all_scored if p.get("superseded_by_review")]
    if superseded:
        sr_pmid = superseded[0].get("superseding_sr_pmid", "")
        sr_year = superseded[0].get("superseding_sr_year", "")
        pmid_list = ", ".join(p.get("pmid", "?") for p in superseded[:10])
        more = "" if len(superseded) <= 10 else f" (and {len(superseded)-10} more)"
        context += (
            f"\n📚 PRISMA DEDUP NOTICE: {len(superseded)} primary studies in this evidence base "
            f"are likely already synthesised inside the newer systematic review/meta-analysis "
            f"PMID {sr_pmid} ({sr_year}). To avoid double-counting evidence, defer to the SR's "
            f"pooled estimate when discussing those findings, and only cite the primary study "
            f"independently if you need a methodological detail (e.g., specific instrumentation, "
            f"sample characteristics) that the SR does not capture.\n"
            f"  Affected PMIDs: {pmid_list}{more}\n"
        )

    # ── Top paper PER TIER (replaces cross-tier "top 3 by score") ──
    if synthesis:
        seen_tiers = []
        per_tier_top = {}
        for p in synthesis:
            tk = p.get("tier_key")
            if tk and tk not in per_tier_top:
                per_tier_top[tk] = p
                seen_tiers.append(tk)

        context += "\nTop paper per tier (use in this order — never let a lower tier override a higher one):\n"
        for tk in seen_tiers:
            p = per_tier_top[tk]
            ss   = f", n={p['sample_size']}" if p.get('sample_size') else ""
            fu   = f", {p['followup_months']}mo follow-up" if p.get('followup_months') else ""
            jif  = f", IF={p['impact_factor']}" if p.get('impact_factor') else ""
            tags = []
            if p.get("has_coi"):    tags.append("INDUSTRY FUNDED")
            if p.get("is_old"):     tags.append(f"{p.get('age_years', '?')}yr old")
            if p.get("is_outlier"): tags.append("OUTLIER")
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            context += (
                f"  [{TIER_LABEL.get(tk, tk)}] PMID {p['pmid']} — {p['score']}/100 "
                f"(Year: {p['year']}, Citations: {p['citations']}{ss}{fu}{jif}){tag_str}\n"
            )

    return context


# ──────────────────────────────────────────────────────────
# INTENT ROUTER + EVIDENCE-MAPPING VALIDATOR
# ──────────────────────────────────────────────────────────
# Two safety/efficiency layers wrapping every Claude synthesis call:
#
# 1. classify_question_intent() — Haiku-powered triage. Decides per-query
#    whether to run the full 7-tier synthesis, a quick definition lookup,
#    or solicit clarification first. Also decides retrieval strategy
#    (local RAG only / live PubMed / both). One Haiku call per question.
#
# 2. validate_evidence_mapping() — pure-Python validator that runs AFTER
#    every synthesis call. Detects:
#      - Fabricated PMIDs (cited but not in evidence base) → HARD FAIL
#      - Unattributed clinical claims (numeric/comparative sentences with
#        no [[PMID:N]] marker)
#      - Gap sections (subsections with zero PMID attribution)
#    Failed validations trigger a single retry with a corrective prompt
#    that names the specific failures. Second-attempt failures are
#    surfaced to the clinician with a [VALIDATION WARNING] prefix.
#
# Logging: every validation appends a JSON line to evidence_mapping.jsonl.

_EVMAP_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "evidence_mapping.jsonl")
_EVMAP_LOG_LOCK = _cost_thread.Lock()

# Validation thresholds — tune from logs once we have a week of data.
_EVMAP_MAX_UNATTRIBUTED = 3        # hard fail above this many unattributed claims
_EVMAP_MAX_GAP_RATIO    = 0.50     # hard fail if >50% of cite-required sections have no PMIDs
_EVMAP_RETRY_LIMIT      = 1        # one retry max — don't burn context on infinite loops

# Sections that legitimately have no PMIDs (per existing prompt rules).
# Matched case-insensitively against subsection headings.
_EVMAP_EXEMPT_SECTIONS = {
    # NOTE: "clinical recommendation" is deliberately NOT exempt. It is the
    # text a clinician acts on and was previously the least-verified part of
    # the answer — no citations required, and skipped by the unattributed-claim
    # detector. It now must name its evidence tier and carry a citation, and
    # _check_recommendation() enforces that.
    "assessment",                # ask_case_question prompt: assessment is interpretation
    "key takeaways",             # stitcher closing
    "references",                # final reference list (uses single-bracket [PMID: N])
    "table of contents",
    "summary",
}

# Patterns that mark a sentence as a "clinical claim" requiring attribution.
# Conservative — only flag sentences that clearly assert a fact derivable from
# literature, not transitions or background prose.
_CLAIM_PATTERNS = [
    re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%"),                         # "85.3%", "85 %"
    re.compile(r"\bn\s*=\s*\d+", re.IGNORECASE),                    # "n=42"
    re.compile(r"\bp\s*[<>=]\s*0?\.\d+", re.IGNORECASE),            # "p<0.05"
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|ml|mm|µm|um|s|sec|min|months|years|weeks|days|hours)\b",
               re.IGNORECASE),                                       # "5 mm", "60 sec"
    re.compile(r"\b(?:success rate|failure rate|survival rate|recurrence rate|incidence|prevalence|"
               r"odds ratio|relative risk|hazard ratio|confidence interval|CI)\b", re.IGNORECASE),
    re.compile(r"\b(?:superior to|inferior to|outperforms?|outperformed|better than|worse than|"
               r"more effective|less effective|equivalent to|non-inferior)\b", re.IGNORECASE),
    re.compile(r"\b(?:is recommended|are recommended|is indicated|is contraindicated|"
               r"should be used|must be used|is the standard|is the gold standard|"
               r"is preferred over)\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}(?:\.\d+)?\s*%\s+(?:NaOCl|EDTA|chlorhexidine|sodium hypochlorite)\b",
               re.IGNORECASE),                                       # specific concentrations
]

_PMID_RE          = re.compile(r"\[\[PMID:\s*(\d+)\s*\]\]")
_HEADING_RE       = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\d])")


def _extract_evidence_pmids(evidence: dict) -> set:
    """Collect every PMID present in the evidence base across all tiers."""
    pmids = set()
    if not isinstance(evidence, dict):
        return pmids
    for key, block in evidence.items():
        if key.startswith("_"):
            continue
        if isinstance(block, dict):
            for pid in (block.get("ids") or []):
                if pid:
                    pmids.add(str(pid).strip())
            for paper in (block.get("scored") or []):
                pid = (paper or {}).get("pmid")
                if pid:
                    pmids.add(str(pid).strip())
    summary = (evidence.get("_summary") or {})
    for paper in (summary.get("all_scored") or []):
        pid = (paper or {}).get("pmid")
        if pid:
            pmids.add(str(pid).strip())
    return pmids


def _extract_cited_pmids(answer: str) -> list:
    """Return every PMID inside [[PMID:N]] markers in order, with duplicates."""
    return [m.group(1).strip() for m in _PMID_RE.finditer(answer or "")]


def _split_sections(answer: str) -> list:
    """Split a markdown answer into [(heading, body), ...] subsections.

    Pre-heading content is returned with heading="(intro)".
    """
    if not answer:
        return []
    matches = list(_HEADING_RE.finditer(answer))
    if not matches:
        return [("(intro)", answer)]
    sections = []
    if matches[0].start() > 0:
        intro = answer[:matches[0].start()].strip()
        if intro:
            sections.append(("(intro)", intro))
    for i, m in enumerate(matches):
        title = m.group(2).strip()
        start = m.end()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(answer)
        body  = answer[start:end].strip()
        sections.append((title, body))
    return sections


def _is_exempt_section(title: str) -> bool:
    t = (title or "").strip().lower()
    # Strip leading bold markers and trailing dashes
    t = re.sub(r"^[*_\s]+|[*_\s—–-]+$", "", t)
    if t in _EVMAP_EXEMPT_SECTIONS:
        return True
    for ex in _EVMAP_EXEMPT_SECTIONS:
        if t.startswith(ex):
            return True
    return False


def _detect_unattributed_claims(answer: str) -> list:
    """Find sentences that look like clinical claims but carry no [[PMID:N]] marker.

    Conservative — pattern-matches numeric/comparative/recommendation language.
    Returns a list of {sentence, section} dicts.
    """
    flagged = []
    for title, body in _split_sections(answer):
        if _is_exempt_section(title):
            continue
        # Strip markdown bullets/headings before splitting into sentences
        cleaned = re.sub(r"^\s*[-*•]\s+", "", body, flags=re.MULTILINE)
        for sent in _SENTENCE_SPLIT_RE.split(cleaned):
            s = sent.strip()
            if len(s) < 20:
                continue
            # Skip sentences that already have a marker
            if _PMID_RE.search(s):
                continue
            # Does this sentence look like a clinical claim?
            for pat in _CLAIM_PATTERNS:
                if pat.search(s):
                    flagged.append({"sentence": s[:240], "section": title})
                    break
    return flagged


def _detect_gap_sections(answer: str) -> list:
    """Subsections with zero [[PMID:N]] markers in their body, excluding exempt ones."""
    gaps = []
    for title, body in _split_sections(answer):
        if _is_exempt_section(title) or title == "(intro)":
            continue
        if not body or len(body) < 80:
            continue  # Trivial / placeholder section
        if not _PMID_RE.search(body):
            gaps.append(title)
    return gaps


_TIER_CLAIM_RE = re.compile(
    r"\b(?:cochrane|level\s*(?:I{1,3}|IV|V|[1-5])\b|systematic\s+review|"
    r"meta-?analys[ie]s|randomi[sz]ed\s+controlled\s+trial|rct|"
    r"case\s+(?:series|report)|expert\s+opinion|cohort|case-control)\b",
    re.IGNORECASE,
)


def _check_recommendation(answer: str) -> dict:
    """The Clinical Recommendation must be traceable.

    It is the 2-4 sentences a clinician acts on, and it was previously the only
    part of the answer nothing verified: citations were forbidden there by
    prompt, and the unattributed-claim detector skipped the section entirely.
    So the most consequential text was the least checked.

    Returns {present, has_citation, names_tier, issues[]}.
    """
    out = {"present": False, "has_citation": False, "names_tier": False, "issues": []}
    for title, body in _split_sections(answer or ""):
        if not title.strip().lower().startswith("clinical recommendation"):
            continue
        out["present"] = True
        out["has_citation"] = bool(_PMID_RE.search(body or ""))
        out["names_tier"]   = bool(_TIER_CLAIM_RE.search(body or ""))
        if not out["has_citation"]:
            out["issues"].append(
                "CLINICAL RECOMMENDATION has no [[PMID:N]] citation — the clinician "
                "cannot trace the advice they are being asked to act on"
            )
        if not out["names_tier"]:
            out["issues"].append(
                "CLINICAL RECOMMENDATION does not state the strength of evidence it "
                "rests on (e.g. \"Based on Level I evidence\")"
            )
        break
    return out


def validate_evidence_mapping(answer: str, evidence: dict) -> dict:
    """Validate a synthesised answer against its evidence base.

    Returns a dict with keys:
      passed (bool), score (0-100), evidence_pmids, cited_pmids,
      fabricated_pmids, valid_pmids, unattributed_claims, gap_sections,
      failure_reason (str|None)
    """
    evidence_pmids = _extract_evidence_pmids(evidence)
    cited          = _extract_cited_pmids(answer)
    cited_set      = set(cited)
    fabricated     = sorted(p for p in cited_set if p not in evidence_pmids)
    valid          = sorted(p for p in cited_set if p in evidence_pmids)

    # Non-numeric markers, e.g. "[[PMID:AAE-PS-obturation]]". The numeric
    # _PMID_RE cannot see these, so they bypass the check above. They are NOT
    # automatically fabrications: hand-ingested authority documents (the AAE
    # position statements) legitimately carry synthetic identifiers. The test
    # is the same as for any citation — is it in the evidence base?
    non_numeric = {m.group(1).strip()
                   for m in re.finditer(r"\[\[PMID:\s*([^\]]+?)\s*\]\]", answer or "")
                   if not m.group(1).strip().isdigit()}
    if non_numeric:
        cited_set |= non_numeric
        invented = {p for p in non_numeric if p not in evidence_pmids}
        if invented:
            fabricated = sorted(set(fabricated) | invented)
        valid = sorted(set(valid) | (non_numeric - invented))

    unattributed = _detect_unattributed_claims(answer)
    gaps         = _detect_gap_sections(answer)

    # Total cite-required sections (everything non-exempt with body)
    total_cite_required = 0
    for title, body in _split_sections(answer):
        if _is_exempt_section(title) or title == "(intro)":
            continue
        if body and len(body) >= 80:
            total_cite_required += 1
    gap_ratio = (len(gaps) / total_cite_required) if total_cite_required else 0.0

    rec = _check_recommendation(answer)

    # Decide pass/fail
    failure_reason = None
    if fabricated:
        failure_reason = f"FABRICATED_PMIDS: {len(fabricated)} cited PMID(s) not in evidence base ({', '.join(fabricated[:5])})"
    elif len(unattributed) > _EVMAP_MAX_UNATTRIBUTED:
        failure_reason = f"UNATTRIBUTED_CLAIMS: {len(unattributed)} clinical claim(s) lack [[PMID:N]] markers (limit {_EVMAP_MAX_UNATTRIBUTED})"
    elif gap_ratio > _EVMAP_MAX_GAP_RATIO and total_cite_required >= 2:
        failure_reason = f"GAP_SECTIONS: {len(gaps)}/{total_cite_required} sections have zero PMID attribution (limit {int(_EVMAP_MAX_GAP_RATIO*100)}%)"
    elif rec["present"] and rec["issues"]:
        failure_reason = "UNTRACEABLE_RECOMMENDATION: " + "; ".join(rec["issues"])

    # Score: fabrication is dominant penalty
    score = 100
    score -= 30 * len(fabricated)
    score -= 5  * max(0, len(unattributed) - 1)
    score -= 10 * len(gaps)
    score -= 10 * len(rec["issues"])
    score = max(0, min(100, score))

    return {
        "passed":               failure_reason is None,
        "score":                score,
        "evidence_pmids":       evidence_pmids,
        "cited_pmids":          cited_set,
        "fabricated_pmids":     fabricated,
        "valid_pmids":          valid,
        "unattributed_claims":  unattributed,
        "gap_sections":         gaps,
        "total_cite_required":  total_cite_required,
        "recommendation":       rec,
        "failure_reason":       failure_reason,
    }


def _log_evidence_mapping(function_name: str, mode: str, attempt: int,
                           result: dict, request_id: str = None) -> None:
    """Append a single validation result to evidence_mapping.jsonl."""
    record = {
        "ts":                  datetime.now().isoformat(),
        "function":            function_name,
        "mode":                mode,
        "attempt":             attempt,
        "passed":              result.get("passed"),
        "score":               result.get("score"),
        "n_evidence_pmids":    len(result.get("evidence_pmids") or []),
        "n_cited_pmids":       len(result.get("cited_pmids") or []),
        "n_fabricated":        len(result.get("fabricated_pmids") or []),
        "fabricated_pmids":    result.get("fabricated_pmids") or [],
        "n_unattributed":      len(result.get("unattributed_claims") or []),
        "unattributed_sample": [c.get("sentence") for c in (result.get("unattributed_claims") or [])[:3]],
        "n_gap_sections":      len(result.get("gap_sections") or []),
        "gap_sections":        result.get("gap_sections") or [],
        "failure_reason":      result.get("failure_reason"),
    }
    if request_id:
        record["request_id"] = request_id
    try:
        with _EVMAP_LOG_LOCK:
            with open(_EVMAP_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"  [evmap_log] write failed: {e}")


def _build_corrective_message(result: dict) -> str:
    """Build a stern follow-up user message that names the specific validation
    failures and demands a re-write using ONLY evidence-base PMIDs."""
    parts = ["Your previous response failed evidence-mapping validation. Re-write it, fixing these specific issues:\n"]

    if result.get("fabricated_pmids"):
        fab = result["fabricated_pmids"]
        parts.append(
            f"\n1. **FABRICATED PMIDS** — you cited {len(fab)} PMID(s) that are NOT in the evidence base "
            f"provided to you: {', '.join(fab[:10])}. You MUST only cite PMIDs that appear in the evidence "
            f"block of the original prompt. Remove any [[PMID:N]] markers for PMIDs not in the evidence base. "
            f"If a claim cannot be supported by an evidence-base PMID, either remove the claim or replace it "
            f"with explicit acknowledgement: \"The evidence base does not address this point.\""
        )

    if result.get("unattributed_claims"):
        ua = result["unattributed_claims"]
        sample = "\n   - ".join(c["sentence"] for c in ua[:5])
        parts.append(
            f"\n2. **UNATTRIBUTED CLAIMS** — {len(ua)} sentence(s) make clinical/numeric claims with no "
            f"[[PMID:N]] marker. Add markers from the evidence base, OR rephrase the sentence so it does not "
            f"assert an evidence-derived fact (avoid percentages, success rates, comparative claims like "
            f"'superior to', or recommendations like 'is indicated' without attribution). Examples:\n   - {sample}"
        )

    rec = result.get("recommendation") or {}
    if rec.get("issues"):
        parts.append(
            "\n**CLINICAL RECOMMENDATION NOT TRACEABLE** — " + "; ".join(rec["issues"]) +
            ". This is the text the clinician acts on. Rewrite it to state the evidence "
            "tier it rests on (e.g. \"Based on Level I evidence\") and to carry at least "
            "one [[PMID:N]] marker on the load-bearing claim. Do not add citations you "
            "cannot support from the evidence block."
        )

    if result.get("gap_sections"):
        gs = result["gap_sections"]
        parts.append(
            f"\n3. **GAP SECTIONS** — these subsections have zero [[PMID:N]] attribution: "
            f"{', '.join(gs[:8])}. Either add citations from the evidence base, or shorten these sections "
            f"and explicitly state that the evidence base provides limited coverage on this aspect."
        )

    parts.append(
        "\n\nReturn the FULL corrected response in the same format as before. Do not include this critique in "
        "your output. Do not invent PMIDs to satisfy the markers — only use PMIDs you can see in the evidence "
        "block. If the evidence base genuinely lacks coverage for a point, say so explicitly."
    )
    return "".join(parts)


# ──────────────────────────────────────────────────────────
# CITATION-SUPPORT VERIFIER (v2 guardrail)
#
# validate_evidence_mapping() guarantees every cited PMID is REAL (it was
# actually retrieved from PubMed this run). This second gate goes further:
# for each claim sentence, does the cited paper's abstract actually SUPPORT
# the claim? Catches real-but-irrelevant citations that the set-difference
# check cannot see.
# ──────────────────────────────────────────────────────────

CITATION_SUPPORT_CHECK = os.getenv("CITATION_SUPPORT_CHECK", "true").lower() in ("1", "true", "yes")
_SUPPORT_MAX_PAIRS     = 30     # cap Haiku payload size
_SUPPORT_ABSTRACT_CHARS = 1200  # abstract excerpt length per pair


def _extract_claim_citation_pairs(answer: str) -> list:
    """Return [(claim_sentence_without_markers, pmid), ...] in document order.

    A sentence citing two papers yields two pairs (each pmid is checked against
    the claim independently). Exempt sections (References, Clinical
    Recommendation, ...) are skipped — same exemption set as the validator.
    """
    pairs = []
    for title, body in _split_sections(answer or ""):
        if _is_exempt_section(title):
            continue
        cleaned = re.sub(r"^\s*[-*•]\s+", "", body or "", flags=re.MULTILINE)
        for sent in _SENTENCE_SPLIT_RE.split(cleaned):
            s = sent.strip()
            if len(s) < 20:
                continue
            pmids = [m.group(1) for m in _PMID_RE.finditer(s)]
            if not pmids:
                continue
            claim = _PMID_RE.sub("", s).strip()
            claim = re.sub(r"\s{2,}", " ", claim)
            for pid in pmids:
                pairs.append((claim, pid))
    return pairs


def verify_citation_support(answer: str, evidence: dict) -> dict:
    """Check each (claim, cited paper) pair against the paper's cached abstract.

    Returns {"flags": [{pmid, claim, verdict}], "checked": int, "cost": float}.
    Fail-open by design: any error returns zero flags — this gate must never
    block an answer, only annotate it.
    """
    # status is surfaced to the clinician: silence from a fail-open check must
    # never be mistaken for a pass.
    out = {"flags": [], "checked": 0, "cost": 0.0,
           "status": "not_run", "detail": ""}
    if not CITATION_SUPPORT_CHECK:
        out["detail"] = "disabled by configuration"
        return out
    if not answer:
        out["detail"] = "no answer text"
        return out
    try:
        pairs = _extract_claim_citation_pairs(answer)[:_SUPPORT_MAX_PAIRS]
        if not pairs:
            out["detail"] = "no cited claims to check"
            return out

        from rag import get_cached_abstracts_bulk
        abstracts = get_cached_abstracts_bulk(sorted({p for _, p in pairs}))

        items = []
        for i, (claim, pmid) in enumerate(pairs):
            ab = (abstracts.get(pmid) or {}).get("abstract") or ""
            if not ab.strip():
                continue   # nothing cached to judge against — cannot assess
            items.append({
                "i":        i,
                "pmid":     pmid,
                "claim":    claim[:400],
                "abstract": ab[:_SUPPORT_ABSTRACT_CHARS],
            })
        if not items:
            out["detail"] = "source abstracts unavailable"
            print(f"  [citation_support] no abstracts available for {len(pairs)} "
                  f"claim-citation pairs — check skipped")
            return out

        client = anthropic.Anthropic(api_key=_get_api_key())
        payload = json.dumps([{k: it[k] for k in ("i", "claim", "abstract")} for it in items],
                             ensure_ascii=False)
        resp = _invoke_claude(client, function_name="verify_citation_support",
            model      = MODELS["structured_fast"],
            max_tokens = 1000,
            messages   = [{"role": "user", "content":
                f"""You are auditing citations in a clinical document. For each item, decide whether the
ABSTRACT supports the CLAIM made in the sentence that cites it.

Verdicts:
- "supports"      — the abstract states or directly implies the claim
- "partial"       — related and consistent, but the claim goes beyond what the abstract states
  (different numbers, stronger wording, different population)
- "not_supported" — the abstract is about something else, or contradicts the claim

Be conservative: only use "not_supported" when the abstract clearly does not back the claim.
Statistical values need not match verbatim — same finding in different words is "supports".

ITEMS (JSON):
{payload}

Return ONLY a JSON array, no prose, no markdown fence:
[{{"i": 0, "verdict": "supports"}}, ...]"""
            }]
        )
        out["cost"] = log_llm_call("verify_citation_support", MODELS["structured_fast"],
                                   resp.usage, mode="guardrail")
        raw = re.sub(r"```json|```", "", resp.content[0].text).strip()
        verdicts = {int(v["i"]): str(v.get("verdict", "")).strip().lower()
                    for v in json.loads(raw) if "i" in v}

        by_index = {it["i"]: it for it in items}
        out["checked"] = len(items)
        out["status"]  = "verified"
        for i, verdict in verdicts.items():
            if verdict == "not_supported" and i in by_index:
                out["flags"].append({
                    "pmid":    by_index[i]["pmid"],
                    "claim":   by_index[i]["claim"],
                    "verdict": verdict,
                })

        # Audit trail — same JSONL stream as the fabrication validator
        try:
            record = {
                "ts":        datetime.now().isoformat(),
                "function":  "verify_citation_support",
                "checked":   out["checked"],
                "n_flagged": len(out["flags"]),
                "flags":     [{"pmid": f["pmid"], "claim": f["claim"][:160]} for f in out["flags"]],
            }
            with _EVMAP_LOG_LOCK:
                with open(_EVMAP_LOG_PATH, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
        except Exception:
            pass

        if out["flags"]:
            print(f"  [citation_support] {len(out['flags'])} of {out['checked']} "
                  f"claim-citation pairs flagged as not supported")
        else:
            print(f"  [citation_support] all {out['checked']} claim-citation pairs OK")
        return out

    except Exception as e:
        out["status"] = "not_run"
        out["detail"] = "check unavailable"
        print(f"  [citation_support] check skipped: {e}")
        return out


def _append_support_warnings(answer: str, support: dict) -> str:
    """Append the citation-support outcome — including when it did NOT run.

    A fail-open check that stays silent is indistinguishable from a check that
    passed, so the clinician would read "no warning" as "verified". Every
    outcome is stated explicitly.
    """
    support = support or {}
    flags   = support.get("flags") or []
    status  = support.get("status", "not_run")
    checked = support.get("checked", 0)

    if flags:
        lines = [
            "\n\n---\n",
            f"> ⚠ **Citation support: {len(flags)} of {checked} flagged.** An automated "
            "review of each cited abstract found these may not directly support the "
            "claim they are attached to. Verify before relying on them:\n>",
        ]
        for f in flags[:5]:
            lines.append(f"> - [[PMID:{f['pmid']}]] cited for: \"{f['claim'][:140]}\"")
        return answer + "\n".join(lines)

    if status == "verified":
        return answer + (
            f"\n\n---\n\n> ✓ **Citation support: verified.** Each of the {checked} cited "
            "claims was checked against its source abstract."
        )

    detail = support.get("detail") or "check unavailable"
    return answer + (
        f"\n\n---\n\n> ○ **Citation support: not available** ({detail}). Citations were "
        "confirmed to exist in the retrieved evidence, but whether each source supports "
        "its claim was not verified for this answer."
    )


# ──────────────────────────────────────────────────────────
# INTENT ROUTER (Haiku)
# ──────────────────────────────────────────────────────────

_INTENT_KINDS     = {"simple", "standard", "complex"}
_INTENT_RETRIEVAL = {"local", "pubmed", "both"}


def classify_question_intent(question: str) -> dict:
    """Triage a clinician's question into a routing decision.

    Returns dict with keys:
      kind          — "simple"   (definition / single-fact)
                    | "standard" (typical comparative / clinical question)
                    | "complex"  (multi-faceted, multi-system)
      needs_clarify — True if key clinical context appears missing
      retrieval     — "local" (RAG library suffices)
                    | "pubmed" (need fresh PubMed pull)
                    | "both"  (use local + supplement with PubMed)
      reason        — one short sentence explaining the routing
      cost          — USD cost of this Haiku call

    On any failure, returns a safe default that runs the full pipeline.
    """
    safe_default = {
        "kind":          "standard",
        "needs_clarify": False,
        "retrieval":     "both",
        "reason":        "router unavailable — defaulting to full pipeline",
        "cost":          0.0,
    }

    if not question or not question.strip():
        return safe_default

    client = anthropic.Anthropic(api_key=_get_api_key())
    try:
        resp = _invoke_claude(client, function_name="classify_question_intent",
            model      = MODELS["structured_fast"],
            max_tokens = 200,
            messages   = [{"role": "user", "content":
                f"""You are routing an endodontic clinical question to the right pipeline.

QUESTION: "{question}"

Classify it on three axes and return ONLY a JSON object (no prose, no markdown fence):

1. "kind":
   - "simple"   — a definition, single-fact lookup, or terminology question (e.g. "what is apexification?", "define ledge")
   - "standard" — a typical evidence-based clinical question with a few comparators or outcome metrics (e.g. "MTA vs CaOH for vital pulp therapy success rate")
   - "complex"  — multi-faceted, multi-system, or requires combining several distinct evidence streams (e.g. "manage a separated NiTi instrument with periapical pathology in a diabetic patient")

2. "needs_clarify": true if the question is missing key clinical context that would change the answer (tooth/vitality/history/age unspecified for what is clearly a case question), false otherwise. Definition-style questions never need clarify.

3. "retrieval":
   - "local"  — common, well-studied topic almost certainly covered by a curated endodontic library
   - "pubmed" — niche, very recent (last 12 months), or unusual — likely needs fresh PubMed pull
   - "both"   — standard topic but worth supplementing local results with fresh PubMed (default for most clinical questions)

4. "reason": one short sentence (max 20 words) explaining your routing choice.

Output JSON only:
{{"kind":"...","needs_clarify":false,"retrieval":"...","reason":"..."}}"""
            }]
        )
        cost = log_llm_call("classify_question_intent", MODELS["structured_fast"],
                            resp.usage, mode="router")
        raw = re.sub(r"```json|```", "", resp.content[0].text).strip()
        data = json.loads(raw)

        kind          = str(data.get("kind", "standard")).strip().lower()
        retrieval     = str(data.get("retrieval", "both")).strip().lower()
        needs_clarify = bool(data.get("needs_clarify", False))
        reason        = str(data.get("reason", "")).strip()[:200]

        if kind not in _INTENT_KINDS:           kind      = "standard"
        if retrieval not in _INTENT_RETRIEVAL:  retrieval = "both"

        return {
            "kind":          kind,
            "needs_clarify": needs_clarify,
            "retrieval":     retrieval,
            "reason":        reason,
            "cost":          cost,
        }
    except Exception as e:
        print(f"  [intent_router] failed: {e} — defaulting to full pipeline")
        return safe_default


# ── ASK CLAUDE ───────────────────────────────────────────
def ask_clinical_question(question, evidence):
    client = anthropic.Anthropic(api_key=_get_api_key())

    system_prompt = """═══════════════════════════════════════════════════════════════
MANDATORY CITATION FORMAT — NON-NEGOTIABLE
═══════════════════════════════════════════════════════════════
You MUST NEVER output a bare PMID number anywhere in the body of your response (no "PMID 12345678", no "(12345678)", no "Smith 2024 [12345678]"). Every time you reference a paper INLINE — in the CLINICAL RECOMMENDATION (no, see below — that section forbids citations), the EVIDENCE SUMMARY, or any other prose — you MUST wrap the PMID EXACTLY like this:

    [[PMID:12345678]]

Double brackets, the literal prefix "PMID:" (uppercase, no space), the digit string immediately after the colon, double brackets to close. Multiple co-citations are space-separated, each fully wrapped: [[PMID:12345678]] [[PMID:23456789]].

This is a clinical-safety requirement: the UI parses these markers to render click-through citation pills so the clinician can verify each source. Any other format — bare numbers, single brackets like [PMID: 12345], parentheses, superscripts, "ref 1", "Smith et al. 2024 (12345678)" — will fail to render as a verifiable pill. The clinician will not be able to inspect the evidence behind your claim and your response is unsafe.

EXCEPTION (and ONLY this exception): the final numbered REFERENCES list at the bottom of the response uses single brackets `[PMID: 12345678]` as a bibliographic key. This is intentional and the parser distinguishes it from inline markers. Do not use `[PMID: N]` anywhere except inside that final numbered list.
═══════════════════════════════════════════════════════════════

You are a world-class endodontist and clinical researcher with deep expertise in evidence-based dentistry.

Each paper has been pre-scored 0-100 based on:
__SCORE_WEIGHTS__

CRITICAL — STRICT TIER HIERARCHY (read this carefully):
Synthesise the evidence in tier order: Cochrane → Level I → Level II → Level IIIa (retrospective cohort) → Level IIIb (case-control) → Level IV → Level V.
A high-scoring lower-tier paper must NEVER override a finding that a higher tier already addresses, even if its 0-100 score is numerically higher. Scores rank papers WITHIN a tier — they do not promote a tier. If Level I evidence answers the question, use it; only fall through to lower tiers when higher tiers are silent or genuinely insufficient.

CONTRADICTION SURFACING:
Before writing the recommendation, check the top 3 systematic reviews / RCTs in the evidence below. If they reach OPPOSING conclusions (e.g., one favours treatment A, another favours treatment B; one finds no difference, another finds significant effect), you MUST begin your CLINICAL RECOMMENDATION with the literal phrase: "**The literature is currently divided on this topic.**" — and then explain both sides in 2-3 sentences before stating which position the better-designed / more recent / larger studies favour. Do not paper over genuine disagreement among high-quality sources.

INLINE PROVENANCE (REQUIRED for clinician verifiability):
Every standalone clinical claim — a recommendation, statistic, treatment success rate, comparative finding, or factual statement supported by literature — MUST be followed immediately by `[[PMID:nnnnnnn]]` markers, one per supporting paper. Use the EXACT format `[[PMID:12345678]]` (double brackets, no space after the colon). Place markers at the END of the sentence the claim appears in.
- Example: "MTA outperforms calcium hydroxide in vital pulp therapy [[PMID:31543236]] [[PMID:34234567]]."
- Multiple supporting papers can be cited (space-separated markers).
- If a claim summarises a systematic review's pooled estimate, cite the SR's PMID, not the underlying primary trials (per the PRISMA dedup rule above).
- Do NOT add markers to introductory sentences, transitions, or general background statements that are NOT specific evidence-derived claims.
- This INLINE format is DIFFERENT from the final REFERENCES list which uses single brackets `[PMID: 12345]` — do not confuse the two.

When referencing key papers in the evidence summary, use author surnames only — not PMIDs or scores.

Structure every answer exactly like this:

---

## CLINICAL RECOMMENDATION

2-4 concise, actionable sentences — the bottom line.

This section is what the clinician acts on, so it MUST be traceable:
- State the strength of evidence it rests on, using the literal tier name — e.g. "Based on Level I evidence," / "Cochrane-level evidence supports..." / "Only Level IV evidence addresses this, so treat as provisional:".
- Carry at least one `[[PMID:N]]` marker on the load-bearing clinical claim. Keep it to the one or two papers the recommendation actually rests on; the full argument belongs in the EVIDENCE SUMMARY below.
- If the evidence base cannot support a recommendation, say so plainly and name what is missing, still citing the closest available evidence.

---

## EVIDENCE SUMMARY

Organized by evidence level, top-down. For each level write a short paragraph (3-6 sentences) summarising what the evidence shows — do not use terse bullet points. Cite authors inline as (Author et al.) or (Author Surname). Include study design, sample size, and follow-up where relevant. Discuss agreements and disagreements between studies. Skip levels with no relevant evidence.

**Cochrane Reviews**
**Level I — RCTs and Systematic Reviews**
**Level II — Prospective Studies**
**Level IIIa — Retrospective Cohort Studies**
**Level IIIb — Case-Control Studies**
**Level IV — Case Series**
**Level V — Expert Opinion**

---

## REFERENCES

List the papers you cited in the text above. Numbered list:
1. [PMID: 12345678] Author AB, Author CD et al. — Brief description. Journal (IF: X.X), Year. Follow-up: X months. n=XX. (Score: XX/100)

---

Rules:
- Never fabricate PMIDs
- Flag conflicts between studies
- Note when follow-up is too short to draw conclusions
- Note when sample sizes are underpowered
- Note when evidence base is weak overall
- Keep recommendation concise
- NEVER end your response with a question. NEVER ask the clinician for more information. If key clinical details are missing, state what information would change the recommendation — but do not pose questions."""

    # Splice in the active scoring-weight description (impact factor on/off)
    system_prompt = system_prompt.replace("__SCORE_WEIGHTS__", _SCORE_WEIGHTS_DESC)

    # Build context — feed papers in strict tier order (Cochrane → L5),
    # not cross-tier sorted by score
    context = _build_evidence_context(evidence)

    user_message = f"""Peer-reviewed endodontic literature with evidence scores:

{context}

Clinical Question: {question}"""

    print(f"\nAsking Claude: '{question}'")
    print("=" * 60)

    # INTENTIONALLY OPUS (Tier 3) — Literature Review primary path. 7-tier evidence
    # synthesis with strict tier hierarchy, contradiction surfacing, PRISMA dedup,
    # inline [[PMID:N]] provenance. Quality regression here is most user-visible.
    # Revisit only after eval infrastructure exists.
    convo = [{"role": "user", "content": user_message}]
    message = _invoke_claude(client, function_name="ask_clinical_question",
        model=MODELS["reasoning_heavy"],
        max_tokens=8000,
        system=system_prompt,
        messages=convo,
    )

    cost = log_llm_call("ask_clinical_question", MODELS["reasoning_heavy"],
                        message.usage, mode="review")
    print(f"  Cost: ${cost:.4f} ({message.usage.input_tokens} in / {message.usage.output_tokens} out)")

    answer = message.content[0].text

    # Validate-and-retry against evidence base
    result = validate_evidence_mapping(answer, evidence)
    _log_evidence_mapping("ask_clinical_question", "review", attempt=1, result=result)
    print(f"  Evidence mapping: passed={result['passed']} score={result['score']} "
          f"cited={len(result['cited_pmids'])} fabricated={len(result['fabricated_pmids'])} "
          f"unattributed={len(result['unattributed_claims'])} gaps={len(result['gap_sections'])}")

    if not result["passed"]:
        print(f"  RETRY — validation failed: {result['failure_reason']}")
        convo.append({"role": "assistant", "content": answer})
        convo.append({"role": "user", "content": _build_corrective_message(result)})
        retry = _invoke_claude(client, function_name="ask_clinical_question_retry",
            model=MODELS["reasoning_heavy"],
            max_tokens=8000,
            system=system_prompt,
            messages=convo,
        )
        retry_cost = log_llm_call("ask_clinical_question_retry", MODELS["reasoning_heavy"],
                                  retry.usage, mode="review")
        cost += retry_cost
        retry_answer = retry.content[0].text
        retry_result = validate_evidence_mapping(retry_answer, evidence)
        _log_evidence_mapping("ask_clinical_question", "review", attempt=2, result=retry_result)
        print(f"  Retry mapping:    passed={retry_result['passed']} score={retry_result['score']} "
              f"cited={len(retry_result['cited_pmids'])} fabricated={len(retry_result['fabricated_pmids'])} "
              f"unattributed={len(retry_result['unattributed_claims'])} gaps={len(retry_result['gap_sections'])}")

        # Pick the better attempt; warn the clinician if neither passed
        if retry_result["passed"] or retry_result["score"] >= result["score"]:
            answer, result = retry_answer, retry_result
        if not result["passed"]:
            warning = (
                f"> ⚠ **VALIDATION WARNING** — this answer did not fully pass evidence-mapping checks "
                f"after one retry. Issue: {result['failure_reason']}. Verify clinical claims against "
                f"the linked PMIDs before acting on this recommendation.\n\n"
            )
            answer = warning + answer

    # v2 guardrail — do the cited abstracts actually SUPPORT the claims?
    # (Fabrication is already impossible past validate_evidence_mapping; this
    # catches real-but-irrelevant citations. Fail-open, advisory only.)
    support = verify_citation_support(answer, evidence)
    cost += support.get("cost", 0.0)
    answer = _append_support_warnings(answer, support)

    return answer, cost


# ── LEARN MODE ────────────────────────────────────────────
def ask_learn_question(question, evidence):
    """Educational/procedural mode: teaches the topic with step-by-step guidance."""
    client = anthropic.Anthropic(api_key=_get_api_key())

    system_prompt = """You are a master endodontist and dental educator with 20+ years of clinical and teaching experience. You write clear, structured educational content that bridges textbook knowledge with clinical practice.

You have been given peer-reviewed papers as reference material. Your task is to answer the learner's question as a comprehensive educational guide.

CRITICAL — STRICT TIER HIERARCHY:
The literature is presented in tier order: Cochrane → Level I → Level II → Level IIIa (retrospective cohort) → Level IIIb (case-control) → Level IV → Level V. When evidence at multiple tiers addresses the same point, teach from the higher tier first. A high-scoring lower-tier paper must NEVER override a finding that a higher tier already addresses — paper scores rank evidence WITHIN a tier, they do not promote a tier.

DENSITY OVER DURATION:
Target ~20 minutes of dense, high-yield teaching (≈ 3,000 words total). Do NOT pad to fill an hour-long lecture format. Every sentence should teach something concrete. Evidence-based dentistry does not stretch well — a tight, accurate synthesis beats a long, diluted one.

PROCEDURAL SPECIFICITY:
When describing any clinical technique, extract and explicitly state the exact chemical concentrations (e.g., "5.25% NaOCl", "17% EDTA"), exposure times (e.g., "60 seconds", "5 minutes"), instrument sizes / tapers, temperatures, and material handling steps (mixing ratios, working time, setting time) used in the cited studies. Vague verbs like "gently irrigate", "appropriately disinfect", or "use enough" are forbidden — replace them with the numeric value from the source. If a cited study did not report a parameter, state that explicitly rather than inventing one.

CONSENSUS CHECKING:
If a single recent study contradicts widely-accepted endodontic guidelines (AAE / ESE / Cochrane consensus — e.g., disagreement on hemostasis time, cold-test thresholds, working-length determination, irrigant activation protocols), frame it as a "**Recent Development**" or "**Emerging Debate**" subheading and explicitly state that current standard-of-care still follows the established guideline. Never present an outlier finding as established fact.

VISUAL SCANNABILITY:
Use bulleted lists (3-7 items) specifically when listing inclusion / exclusion criteria, diagnostic indicators or red flags, step-by-step procedural sequences, decision-tree branch points, or comparative material properties. Reserve continuous prose for mechanism, rationale, and evidence synthesis — bullets are for enumerable clinical content only.

CONTRADICTION SURFACING:
Before drafting the OVERVIEW, check the top 3 systematic reviews / RCTs in the evidence below. If they reach OPPOSING conclusions (e.g., one favours treatment A, another favours treatment B; one finds no difference, another finds significant effect), you MUST begin the OVERVIEW with the literal phrase: "**The literature is currently divided on this topic.**" — then explain both sides in the BACKGROUND section before recommending which position the better-designed / more recent / larger studies favour. Do not paper over genuine disagreement among high-quality sources.

INLINE PROVENANCE (REQUIRED for clinician verifiability):
Every standalone clinical claim, statistic, success rate, or evidence-derived factual statement MUST be followed immediately by `[[PMID:nnnnnnn]]` markers (double brackets, no space). Multiple papers space-separated. Place at end of the sentence. Example: "Calcium silicate cements show a 95% success rate at 36 months [[PMID:31543236]]." This INLINE format is DIFFERENT from the REFERENCES list (which uses single brackets `[PMID: 12345]`). Do NOT add markers to background prose, transitions, or general teaching statements that are not specific evidence-derived claims.

Citation scoring note: papers ≤2 years old receive a baseline citation-velocity score and are NOT penalised for being new — treat fresh well-designed work as on equal footing with older highly-cited work in the same tier.

Structure your answer exactly like this:

---

## OVERVIEW

2-3 sentences introducing the topic: what it is, when it is used, and why it matters clinically.

---

## BACKGROUND & CONCEPTS

Key anatomy, pathophysiology, materials science, or theoretical concepts a dentist needs to understand. Use **bold subheadings** for sub-topics. Write each sub-topic as a short paragraph (3-5 sentences) that explains not just what but why — include clinical rationale, consequences of not understanding this concept, and any nuance from the literature. Do not use terse bullet points.

---

## CLINICAL PROCEDURE

[Include this section ONLY if the question involves a clinical technique or hands-on procedure. Omit entirely for purely conceptual questions.]

Numbered step-by-step instructions a clinician can follow chairside:
1. Patient preparation / consent points
2. Instruments and materials required
3. Each procedural step in order
4. Critical checkpoints and decision points
5. Common pitfalls and how to avoid them

---

## EVIDENCE & BEST PRACTICES

Write 3-6 paragraphs summarising what the peer-reviewed literature says about this topic. Each paragraph should cover a distinct aspect or debate (e.g., one technique vs another, short-term vs long-term outcomes, a specific material or instrument). Cite authors inline (Author et al., year) with study design and sample size where relevant. Do not use bullet points — write in connected, explanatory prose that helps the reader understand not just what the evidence says but what it means clinically.

---

## CLINICAL CASES

Present 2-3 brief clinical vignettes drawn from cases described in the provided literature (or synthesised from the evidence where explicit cases are not reported). Format each as:

**Case [N] — [Brief descriptor, e.g. "Irreversible pulpitis in mandibular molar"]**
- **Presentation:** Patient age/sex, chief complaint, clinical and radiographic findings
- **Diagnosis:** Pulp and periapical diagnosis using AAE classification
- **Management:** Step-by-step approach taken, materials used, any complications
- **Outcome:** Result at follow-up (duration), lessons learned

---

## KEY TAKEAWAYS

Write 3-5 short paragraphs (2-3 sentences each), each covering one key point. Start each with a bold heading. Do not use bare bullet points — each takeaway should explain the point and its clinical implication.

---

## REFERENCES

List the papers you cited in the text above. Numbered list:
1. [PMID: 12345678] Author AB et al. — Brief description. Journal (IF: X.X), Year. n=XX. (Score: XX/100)

---

Rules:
- Write for a dental graduate or general dentist who wants to learn or refresh on this topic
- Be practical and clinically oriented
- Never fabricate PMIDs or invent studies
- If the evidence base is limited, say so
- Present both sides when the literature is genuinely divided
- Clinical cases must be realistic and consistent with the evidence provided
- NEVER end your response with a question. NEVER ask the learner for more information."""

    # Build context — strict tier order, same builder as review mode
    context = _build_evidence_context(evidence)

    user_message = f"""Peer-reviewed endodontic literature with evidence scores:

{context}

Learning question: {question}"""

    print(f"\nLearn mode -- asking Claude: '{question}'")
    print("=" * 60)

    # INTENTIONALLY OPUS (Tier 3) — legacy single-shot fallback for Deep Learning.
    # Only fires if the curriculum builder pipeline (build_deep_learning_module)
    # is bypassed; same synthesis complexity as ask_clinical_question.
    message = _invoke_claude(client, function_name="ask_learn_question",
        model=MODELS["reasoning_heavy"],
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )

    cost = log_llm_call("ask_learn_question", MODELS["reasoning_heavy"],
                        message.usage, mode="learn")
    print(f"  Cost: ${cost:.4f} ({message.usage.input_tokens} in / {message.usage.output_tokens} out)")
    return message.content[0].text, cost


# ═════════════════════════════════════════════════════════════════════════
# DEEP-LEARNING CURRICULUM BUILDER (agentic, multi-stage)
#
# Instead of one Claude call writing an hour of content from a single
# evidence base, we run:
#   A. Syllabus  — Claude breaks the topic into 4-5 modules
#   B. Retrieval — separate evidence build per module (mode="learn")
#   C. Writing   — short Claude call writes a dense ~4 min script per module
#   D. Stitching — Claude writes intro / transitions / closing / refs
#
# Density target: ~20 minutes of high-yield teaching, not a 60-min lecture.
# (~150 wpm × 20 min ≈ 3,000 words total; 4 modules × ~600 words + intro/outro)
# ═════════════════════════════════════════════════════════════════════════

CURRICULUM_MODULE_COUNT      = 4      # default modules per curriculum
CURRICULUM_WORDS_PER_MODULE  = 650    # ~4 min at 150 wpm
CURRICULUM_INTRO_OUTRO_WORDS = 600    # intro + transitions + closing + takeaways
CURRICULUM_TOTAL_TARGET_MIN  = 20     # density-over-duration cap

_MODULE_LINE_RE = re.compile(
    r"^\s*(?:MODULE\s*:\s*)?(.+?)\s*\|\|\|\s*(.+?)\s*$", re.MULTILINE)


def _parse_module_lines(raw: str, n_modules: int) -> list:
    """Parse 'MODULE: <title> ||| <query>' lines from an LLM response.

    Also accepts the legacy JSON-array-of-objects shape, and recovers
    title/search_query pairs from quote-mangled JSON via regex. Queries are
    validated with _looks_like_query; a module whose query fails validation is
    dropped (the caller retries), because an unbalanced query reaching PubMed
    is silently reinterpreted, not rejected.
    """
    text = re.sub(r"```(?:json)?", "", raw or "").strip()
    pairs = [(m.group(1), m.group(2)) for m in _MODULE_LINE_RE.finditer(text)]

    if not pairs:
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                pairs = [(str(m.get("title", "")), str(m.get("search_query", "")))
                         for m in arr if isinstance(m, dict)]
        except (json.JSONDecodeError, TypeError):
            # Quote-mangled JSON: pull the field values line-wise.
            titles  = re.findall(r'"title"\s*:\s*"([^"]+)"', text)
            queries = re.findall(r'"search_query"\s*:\s*"(.+?)"\s*[,}]\s*$',
                                 text, re.MULTILINE)
            pairs = list(zip(titles, queries))

    cleaned = []
    for title, query in pairs[:n_modules]:
        title, query = title.strip().strip('"'), query.strip()
        if title and _looks_like_query(query):
            cleaned.append({"title": title, "search_query": query})
    return cleaned


def generate_curriculum_syllabus(question: str, n_modules: int = CURRICULUM_MODULE_COUNT) -> list:
    """
    STEP A — ask Claude to break the user's topic into a coherent teaching syllabus.
    Returns: [{"title": "...", "search_query": "..."}, ...]
    Each module's search_query is what we'll feed PubMed in step B.
    """
    client = anthropic.Anthropic(api_key=_get_api_key())
    print(f"\n[curriculum] Step A — generating {n_modules}-module syllabus for: '{question}'")

    try:
        # Routed to Haiku 2026-04-27 — was Opus. Pure structural task.
        # Line format, not JSON: the queries contain quoted PubMed phrases,
        # which Haiku emits unescaped inside JSON strings ~half the time
        # (measured 5/10 on the multi-term generator). max_tokens 600 → 1500:
        # four OR-group queries plus titles ran right up against 600.
        resp = _invoke_claude(client, function_name="generate_curriculum_syllabus",
            model=MODELS["structured_fast"],
            max_tokens=1500,
            messages=[{"role": "user", "content":
                f"""You are a senior endodontic educator designing a tight, dense ~{CURRICULUM_TOTAL_TARGET_MIN}-minute teaching module on:

"{question}"

Break the topic into exactly {n_modules} sequential learning modules that together form a coherent narrative arc — typical structure for endodontic teaching:
  1. Background / pathophysiology / classification
  2. Diagnosis & clinical presentation
  3. Treatment options / technique
  4. Prognosis, outcomes, complications
(Adapt these headings to fit the specific topic.)

For EACH module, return:
- "title":        a short module heading (5-8 words)
- "search_query": a PubMed BOOLEAN query for THIS module. It is combined with a
                   study-design filter and an endodontics domain filter at search time,
                   so query the CONCEPT broadly here.

CRITICAL — the query must be OR-expanded, not a list of words. PubMed ANDs bare
words together, so "laser irradiation power settings endodontic disinfection"
requires all six words in one record and returns almost nothing. Write 2-3
concept groups, each an OR-list of the synonyms, abbreviations, brand and device
names the field actually uses, joined by AND:

  (laser* OR "photodynamic therapy" OR aPDT OR PIPS OR SWEEPS OR "laser-activated irrigation" OR Er:YAG OR Nd:YAG OR diode)
  AND ("root canal" OR endodontic* OR intracanal)
  AND (disinfect* OR antibacterial OR antimicrobial OR biofilm OR "E. faecalis")

Rules: use `*` truncation on word stems; quote multi-word phrases; include
abbreviations AND expansions for any technique; never write a bare multi-word
string. Do NOT add [pt] design filters or endodontic domain terms — those are
appended automatically, and duplicating them narrows the search.

Return EXACTLY {n_modules} lines, one per module, in this format:
MODULE: <title> ||| <boolean query>
No JSON, no fences, no numbering, no other text. Quotes inside the query are fine."""
            }]
        )
        cost = log_llm_call("generate_curriculum_syllabus", MODELS["structured_fast"],
                            resp.usage, mode="learn")
        cleaned = _parse_module_lines(resp.content[0].text, n_modules)
        if len(cleaned) < n_modules:
            # Corrective retry — the old bare json.loads fell straight through
            # to the bag-of-words fallback below on any parse hiccup, which is
            # the exact query shape that caused the 5-PMID laser regression.
            print(f"  [curriculum] parsed {len(cleaned)}/{n_modules} modules, retrying")
            resp = _invoke_claude(client, function_name="generate_curriculum_syllabus",
                model=MODELS["structured_fast"], max_tokens=1500,
                messages=[{"role": "user", "content":
                    f'Design {n_modules} sequential teaching modules for the endodontic '
                    f'topic "{question}" (background → diagnosis → treatment → outcomes). '
                    f'For each, output ONE line: MODULE: <5-8 word title> ||| <PubMed '
                    f'boolean query, 2-3 OR-groups of synonyms/abbreviations/device names '
                    f'joined by AND, quoted phrases, * stems>. Exactly {n_modules} lines, '
                    f'nothing else.'}])
            cost += log_llm_call("generate_curriculum_syllabus", MODELS["structured_fast"],
                                 resp.usage, mode="learn")
            cleaned = _parse_module_lines(resp.content[0].text, n_modules)
        if cleaned:
            print(f"  syllabus: {[c['title'] for c in cleaned]}")
            print(f"  Cost: ${cost:.4f}")
            return cleaned, cost
    except Exception as e:
        print(f"  [curriculum] syllabus generation failed: {e}")
    print("  [curriculum] WARNING: using generic fallback syllabus — module "
          "structure is not topic-specific for this run")

    # Fallback — generic 4-module syllabus. These look like bag-of-words
    # queries, but they never reach PubMed raw: build_evidence_base() passes
    # every module search_query through generate_search_terms(), which
    # OR-expands it. The real cost of landing here is generic module structure,
    # hence the WARNING above.
    fallback = [
        {"title": "Background & Pathophysiology",  "search_query": f"{question} pathophysiology"},
        {"title": "Diagnosis & Clinical Findings", "search_query": f"{question} diagnosis"},
        {"title": "Treatment & Technique",         "search_query": f"{question} treatment management"},
        {"title": "Prognosis & Outcomes",          "search_query": f"{question} outcomes prognosis"},
    ]
    return fallback, 0.0


# A module with no retrieved evidence must not produce a protocol. The failure
# this guards: a laser-disinfection module retrieved ZERO papers and still
# emitted "Er:YAG 20 mJ, 15 Hz", "5.25% NaOCl, 2 mL, 60 s", "ISO #30/.04" — a
# fully specified numeric clinical protocol invented from nothing and shipped
# behind a disclaimer. A disclaimer does not make invented parameters safe.
MIN_MODULE_PAPERS = 2

_NUMERIC_PARAM_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|mm|mJ|Hz|W|mW|J/cm|mL|ml|µm|um|sec|s\b|seconds?|min\b|"
    r"minutes?|mo\b|months?|ISO|#\d|N·?cm|Ncm|rpm|°C)"
    r"|\bISO\s*#?\d+"
    r"|\b#\d{2}/\.?\d{2}\b",
    re.IGNORECASE,
)


def module_has_usable_evidence(evidence: dict) -> tuple:
    """(ok, n_papers) — is there enough retrieved evidence to write a module?"""
    summary = (evidence or {}).get("_summary", {}) or {}
    n = len(summary.get("all_scored") or [])
    return n >= MIN_MODULE_PAPERS, n


def _module_not_generated_block(title: str, n_papers: int, query: str = "") -> str:
    """Rendered in place of a module when retrieval came back empty."""
    return (
        f"## Module — {title}\n\n"
        f"> **Module not generated — insufficient evidence retrieved.**\n>\n"
        f"> A literature search for this module returned "
        f"{'no papers' if not n_papers else f'only {n_papers} paper(s)'}, which is "
        f"below the minimum required to write evidence-based clinical content.\n>\n"
        f"> No protocol, parameters or decision rules are given here. Any numeric "
        f"values presented for this topic would be unsourced.\n>\n"
        f"> This usually means the topic is genuinely sparse in the indexed "
        f"literature, or that it is described using terminology the search did not "
        f"cover. Consider narrowing the parent question or consulting a specialist "
        f"review directly.\n"
        + (f">\n> *Search used:* `{query[:220]}`\n" if query else "")
    )


def validate_module_output(text: str, evidence: dict) -> dict:
    """Reject a module that states numeric clinical parameters with no citations.

    Returns {"ok": bool, "reason": str}. This is the last line of defence: even
    with evidence present, a module that specifies irrigant concentrations or
    laser settings while citing nothing is asserting parameters it cannot
    support.
    """
    cited = _extract_cited_pmids(text or "")
    if cited:
        return {"ok": True, "reason": ""}
    params = _NUMERIC_PARAM_RE.findall(text or "")
    if params:
        return {"ok": False,
                "reason": (f"module states {len(params)} numeric clinical parameter(s) "
                           f"with zero [[PMID:N]] citations")}
    return {"ok": True, "reason": ""}


def write_curriculum_module(module: dict, evidence: dict, parent_question: str,
                             idx: int, total: int) -> tuple:
    """
    STEP C — Claude writes a single dense ~{CURRICULUM_WORDS_PER_MODULE}-word
    module script using ONLY the evidence retrieved for this module's sub-topic.
    Returns: (markdown_text, cost)
    """
    client = anthropic.Anthropic(api_key=_get_api_key())
    title  = module.get("title", f"Module {idx}")

    system_prompt = f"""═══════════════════════════════════════════════════════════════
MANDATORY CITATION FORMAT — NON-NEGOTIABLE
═══════════════════════════════════════════════════════════════
You MUST NEVER output a bare PMID number anywhere in this module. Every time you reference a paper, you MUST wrap the PMID EXACTLY like this:

    [[PMID:12345678]]

Double brackets, the literal prefix "PMID:", the digit string, double brackets to close. Multiple co-citations are space-separated, each fully wrapped: [[PMID:12345678]] [[PMID:23456789]]. Forbidden formats include bare numbers, single brackets, parentheses, superscripts, footnote refs, or "ref 1". The downstream stitcher and the UI both parse the [[PMID:N]] markers — any other format will fail to render as a clickable verifiability pill.
═══════════════════════════════════════════════════════════════

You are a master endodontist writing module {idx} of {total} in a dense {CURRICULUM_TOTAL_TARGET_MIN}-minute teaching curriculum on "{parent_question}".

This module: **{title}**

Hard rules:
- Target length: {CURRICULUM_WORDS_PER_MODULE} words (≈ 4 minutes spoken). Density over duration — every sentence should teach something.
- Use ONLY the papers provided in the evidence block below. Never invent PMIDs or studies.
- Cite authors inline (Author et al., Year). Do not write a separate references list — the stitcher will compile that at the end.
- Strict tier hierarchy: when multiple tiers address a point, lead with the higher tier; never let a high-scoring lower-tier paper override a higher tier.
- EVIDENCE ANCHORING (REQUIRED): every conclusion in this module MUST be explicitly anchored to the highest-available level of evidence in the evidence base for that point. Where the evidence base contains a Cochrane review or Level I RCT/SR addressing the question, that is the lead citation and the conclusion must reflect its finding. If you find yourself drawing a conclusion from a Level IV case report or Level V expert review WHEN higher-tier evidence on the same point exists, stop and re-lead from the higher tier. When a conclusion genuinely rests on case-level evidence ONLY (no Level I/II/III source addresses it), you MUST include a one-sentence justification that names the limitation explicitly — example: "This recommendation rests on a single case series of 14 teeth (Heithersay 1999 [[PMID:NNNNN]]) — no RCT or prospective cohort has yet evaluated this approach; treat as provisional pending higher-tier confirmation." Generic disclaimers like "more research is needed" are insufficient — you must name the design (case series), the n, the author, and what specifically is missing (RCT, cohort, longer follow-up).
- PROCEDURAL SPECIFICITY: when describing any clinical technique, you MUST extract and explicitly state from the cited studies the exact chemical concentrations (e.g., "5.25% NaOCl" not "sodium hypochlorite"), exposure times (e.g., "irrigate for 60 seconds" not "irrigate adequately"), instrument sizes / tapers, temperatures, and material handling steps (mixing ratios, working time, setting time). Vague verbs like "gently irrigate", "appropriately disinfect", or "use enough" are forbidden — replace them with the numeric value from the source paper. If a cited study does not specify a parameter, state that explicitly ("Author et al. did not report exposure time").
- CONSENSUS CHECKING: if a single recent study contradicts widely-accepted endodontic guidelines (AAE / ESE position statements, Cochrane consensus — e.g., disagreement on hemostasis time in vital pulp therapy, cold-test interpretation, working-length determination, irrigant activation), you MUST frame it as a "**Recent Development**" or "**Emerging Debate**" subheading and explicitly state that current standard-of-care still follows the established guideline. Never present an outlier finding as established fact.
- VISUAL SCANNABILITY: use bulleted lists (3-7 items) specifically when listing inclusion / exclusion criteria, diagnostic indicators or red flags, step-by-step procedural sequences, decision-tree branch points, or comparative material properties. Continuous prose is still required for mechanism, rationale, and evidence synthesis — bullets are for enumerable clinical content only.
- CONTRADICTION SURFACING: if the top 3 systematic reviews / RCTs in the evidence block for THIS module reach opposing conclusions on the same clinical question, do not paper over the disagreement. Open the relevant subsection with the literal phrase "**The literature is currently divided on this topic.**" and explain both positions before stating which the higher-quality / more recent / larger studies favour. Genuine disagreement among high-quality sources must be flagged, not flattened.
- INLINE PROVENANCE (REQUIRED): every standalone clinical claim, statistic, or evidence-derived statement MUST be followed by `[[PMID:nnnnnnn]]` markers (double brackets, no space, multiple space-separated). Place at end of sentence. Example: "MTA outperforms calcium hydroxide [[PMID:31543236]] [[PMID:34234567]]." Do NOT mark transitions, background prose, or general teaching statements. The stitcher will compile the final REFERENCES list separately — your job is just inline `[[PMID:N]]` markers on claims.
- Use **bold subheadings** for sub-points. Mix prose paragraphs with bulleted lists per the rule above.
- Do NOT write an introduction, conclusion, or transition to the next module — those are added later by the stitcher.
- NEVER end with a question.

═══════════════════════════════════════════════════════════════
CLINICAL APPLICATION SECTION — REQUIRED IN EVERY MODULE
═══════════════════════════════════════════════════════════════
After your evidence-summary prose and BEFORE the Clinical Protocol Summary table, you MUST include a section headed `## Clinical Application` with exactly these three subsections in this order:

**### 4a. Procedural Protocol**
A numbered, executable sequence (5-12 steps). Each step has:
- A short imperative header (e.g., "1. Establish working length")
- 1-3 sentences of clinical detail with SPECIFIC values — concentrations, sizes, times, torques
- `[[PMID:N]]` citations for any step where the detail is drawn from a specific paper

Forbidden: vague verbs — "appropriately", "adequately", "as needed", "gently", "sufficient". Replace with numeric values from the evidence. If two acceptable protocols exist (e.g., single vs multi-visit), state both with evidence grades and a clear default: "Most evidence favors X [[PMID:N]]. Choose Y when [criterion]." Do not paper over real clinical disagreement — surface it inside the protocol.

**### 4b. Decision Tree**
3-6 branch points using this exact format for each branch:
  IF [observable clinical or radiographic finding]
  THEN [action or pathway]
  BECAUSE [1-line rationale; include [[PMID:N]] if literature-derived]

Cover all three decision types: (1) inclusion criteria — when this technique applies, (2) exclusion criteria — when to take a different pathway, (3) modification criteria — when to alter the standard protocol (immature apex, retreatment, medical complexity). Branch conditions must be mutually exclusive — if a clinician could satisfy two branches simultaneously, rewrite to eliminate the overlap.

**### 4c. Materials & Instrumentation**
A compact bullet list or Markdown table — NOT prose. Clinicians will scan this section at chairside. Include every category that applies to this module's topic:
- **Irrigants:** solution name · concentration · volume per canal · contact time · delivery method
- **Medicaments:** name · vehicle/carrier · placement technique · duration between visits
- **Obturation/sealer:** generic chemistry first (e.g., "calcium silicate-based bioceramic"), brand examples in parentheses if widely used (e.g., "(BC Sealer, TotalFill)")
- **Instruments:** file system type · recommended size range/taper · motion type (continuous rotation / reciprocating) · recommended sequence
- **Imaging:** modality · FOV for CBCT · exposure parameters where relevant

Lead with generic chemistry; never brand-only. Omit categories irrelevant to this module's topic.

This section serves a MIXED audience — students building foundational understanding AND clinicians executing the technique this week. Be explicit enough that a student understands every term; specific enough that a clinician can execute without additional research.

A module missing any of the three Clinical Application subsections, or with vague verbs inside the Procedural Protocol, WILL BE REJECTED and re-prompted.
═══════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════
MANDATORY CLINICAL PROTOCOL TABLE — END OF EVERY MODULE
═══════════════════════════════════════════════════════════════
Every module MUST end with a GitHub-flavored Markdown table titled `### Clinical Protocol Summary` that operationalises this module's content into a one-glance chairside reference. The columns and rows depend on the module's clinical focus — pick the format that gives the highest decision-support value for THIS topic:

  • **Comparing two treatments** (e.g. Re-RCT vs MTA Apexification, MTA vs Biodentine, conventional RCT vs surgery)
    Columns: `| Criterion | Option A | Option B |`
    REQUIRED rows (include all that apply to the topic — never skip a row that the evidence base could fill):
      - Indications (case selection: tooth type, age, periapical status, restorability)
      - Contraindications (absolute and relative)
      - Disinfection protocol (irrigant, concentration, exposure time)
      - Working / treatment time per visit (minutes; chair-time)
      - Number of visits required
      - Maturogenesis / continued root development potential
      - Short-term success rate (≤24 mo) — % with PMID
      - Long-term success / survival rate (≥5 yr) — % with PMID
      - Predictability / outcome variability (range, IQR, or qualitative)
      - Cost (relative — material + chair time)
      - Re-treatability if it fails

  • **Single-technique procedural breakdown** (e.g. obturation, irrigation protocol, working-length determination)
    Columns: `| Step | Parameter | Evidence-Based Value |`
    Rows = each procedural step with the specific concentration / time / size / temperature taken from the cited papers

  • **Diagnostic decision tree** (e.g. pulpal-status assessment, trauma classification, root-fracture detection)
    Columns: `| Finding | Diagnostic Implication | Action | Evidence Level |`
    Rows = each clinical/radiographic finding with what it means, what to do next, and the tier of evidence supporting that action

  • **Material / instrument selection** (e.g. file system choice, sealer comparison)
    Columns: `| Material | Indications | Setting/Working time | Outcome (short-term) | Outcome (long-term) | Best use case |`

Hard rules for the table:
1. Cells MUST contain concrete values (concentrations, times, percentages, success rates) — never vague verbs like "appropriate" or "adequate".
2. Wherever a cell asserts an evidence-derived value (success rate, time, concentration, comparative claim), append the supporting `[[PMID:N]]` marker INSIDE the cell. Example cell: `92.4% at 24 mo [[PMID:31543236]]`.
3. If the evidence base lacks data for a cell, write `Not reported in evidence base` rather than estimating or guessing. Empty cells are forbidden.
4. For comparative-treatment tables: the `Long-term success / survival rate (≥5 yr)` row is mandatory if ANY paper in the evidence base reports follow-up of 60 months or longer — explicitly check the followup_months metadata in the evidence block before deciding the cell content.
5. The table comes AFTER the Clinical Application section and AFTER the module's last prose paragraph.
═══════════════════════════════════════════════════════════════

Output format:

## Module {idx} — {title}

[~{CURRICULUM_WORDS_PER_MODULE} words of background, pathophysiology, and evidence synthesis — evidence-heavy prose with [[PMID:N]] citations throughout]

## Clinical Application

### 4a. Procedural Protocol

[numbered steps with specific values per the rules above]

### 4b. Decision Tree

[3-6 IF/THEN/BECAUSE branch points per the rules above]

### 4c. Materials & Instrumentation

[compact bullet list or table — NOT prose — per the rules above]

### Clinical Protocol Summary

[mandatory Markdown table per the rules above]

HARD LENGTH CAP: Your entire response must not exceed 2,000 words. Budget approximately: evidence prose ~{CURRICULUM_WORDS_PER_MODULE} words · Clinical Application ~900 words (protocol ~400, decision tree ~200, materials ~250) · Clinical Protocol Summary table ~200 words. If over budget, cut background prose and verbose table cells first — never cut the Clinical Application section, numeric specifics, or [[PMID:N]] markers.
"""

    context = _build_evidence_context(evidence)
    user_message = f"""Evidence retrieved specifically for this module ({title}):

{context}

Write the module content now."""

    print(f"\n[curriculum] Step C.{idx}/{total} — writing module: '{title}'")
    # Routed to Sonnet — evidence context is now per-PMID filtered (< 25K tokens)
    # so Opus's extra context window isn't needed. Validation+retry provides the
    # quality safety net. 5× cheaper than Opus with equivalent synthesis quality
    # at the density targets here (~650 words + evidence table).
    convo = [{"role": "user", "content": user_message}]
    resp = _invoke_claude(client, function_name=f"write_curriculum_module[{idx}/{total}]",
        model=MODELS["reasoning_standard"],
        max_tokens=3200,
        system=system_prompt,
        messages=convo,
    )
    cost = log_llm_call("write_curriculum_module", MODELS["reasoning_standard"],
                        resp.usage, mode="learn")
    print(f"  Cost: ${cost:.4f} ({resp.usage.input_tokens} in / {resp.usage.output_tokens} out)")

    answer = resp.content[0].text

    # Validate-and-retry — curriculum modules are dense and most prone to
    # gap-filling with statistical guesswork.
    result = validate_evidence_mapping(answer, evidence)
    _log_evidence_mapping(f"write_curriculum_module[{idx}/{total}]", "learn",
                          attempt=1, result=result)
    print(f"  Evidence mapping: passed={result['passed']} score={result['score']} "
          f"cited={len(result['cited_pmids'])} fabricated={len(result['fabricated_pmids'])} "
          f"unattributed={len(result['unattributed_claims'])} gaps={len(result['gap_sections'])}")

    if not result["passed"]:
        print(f"  RETRY — validation failed: {result['failure_reason']}")
        convo.append({"role": "assistant", "content": answer})
        convo.append({"role": "user", "content": _build_corrective_message(result)})
        retry = _invoke_claude(client, function_name=f"write_curriculum_module_retry[{idx}/{total}]",
            model=MODELS["reasoning_standard"],
            max_tokens=3200,
            system=system_prompt,
            messages=convo,
        )
        retry_cost = log_llm_call("write_curriculum_module_retry", MODELS["reasoning_standard"],
                                  retry.usage, mode="learn")
        cost += retry_cost
        retry_answer = retry.content[0].text
        retry_result = validate_evidence_mapping(retry_answer, evidence)
        _log_evidence_mapping(f"write_curriculum_module[{idx}/{total}]", "learn",
                              attempt=2, result=retry_result)
        print(f"  Retry mapping:    passed={retry_result['passed']} score={retry_result['score']} "
              f"cited={len(retry_result['cited_pmids'])} fabricated={len(retry_result['fabricated_pmids'])} "
              f"unattributed={len(retry_result['unattributed_claims'])} gaps={len(retry_result['gap_sections'])}")

        if retry_result["passed"] or retry_result["score"] >= result["score"]:
            answer, result = retry_answer, retry_result
        # Don't prepend a banner inside a curriculum module — the stitcher
        # would propagate it awkwardly. Failure is logged for review instead.

    return answer, cost


def stitch_curriculum(parent_question: str, modules_with_scripts: list,
                      all_evidence: dict) -> tuple:
    """
    STEP D — write intro, smooth transitions between modules, closing
    "Key Takeaways", and a single deduplicated REFERENCES list spanning
    every module's evidence. Returns: (final_markdown, cost)

    `modules_with_scripts` = [{"title": str, "search_query": str, "script": str}, ...]
    `all_evidence`         = combined evidence block (for the references list)
    """
    client = anthropic.Anthropic(api_key=_get_api_key())

    # Build a compact reference list from every module's evidence.
    # Include tier_key so the Case Diversity rule can identify Tier IV/V
    # case reports that need rebalancing against higher-tier studies.
    seen = {}
    pmid_to_tier = {}
    for tier_key in TIER_ORDER:
        tier_block = (all_evidence.get(tier_key) or {})
        for p in (tier_block.get("scored") or []):
            pmid = p.get("pmid")
            if pmid:
                pmid_to_tier.setdefault(pmid, tier_key)
    for p in (all_evidence.get("_summary", {}) or {}).get("all_scored", []):
        pmid = p.get("pmid")
        if pmid and pmid not in seen:
            seen[pmid] = p

    refs_block = ""
    for p in seen.values():
        pmid = p.get("pmid", "")
        tier_key = pmid_to_tier.get(pmid, "")
        tier_lbl = TIER_LABEL.get(tier_key, tier_key) if tier_key else "—"
        refs_block += (
            f"PMID {pmid} | TIER: {tier_lbl} | {p.get('authors','')} | "
            f"Year: {p.get('year','')} | Score: {p.get('score','?')}/100 | "
            f"Journal: {p.get('journal','')}\n"
        )

    syllabus_str = "\n".join(f"  {i+1}. {m['title']}" for i, m in enumerate(modules_with_scripts))
    module_blocks = "\n\n---\n\n".join(m["script"] for m in modules_with_scripts)

    system_prompt = f"""You are the editor finalising a {CURRICULUM_TOTAL_TARGET_MIN}-minute endodontic teaching curriculum on "{parent_question}".

Module bodies have already been written by subject-matter authors. Your job is to wrap them with:
  1. A short **OVERVIEW** (3-4 sentences, ~{CURRICULUM_INTRO_OUTRO_WORDS // 4} words) — what the learner will master and why it matters.
  2. A 1-2 sentence **transition** between consecutive modules (insert before module 2, 3, 4 …) — keep them tight, narrative, no headings.
  3. A **KEY TAKEAWAYS** section — 4-5 short bold-headed paragraphs (2-3 sentences each), each an actionable clinical pearl.
  4. **THE FINAL VERDICT** — a decisive synthesis section (see mandatory structure below).
  5. A clean **REFERENCES** list at the very end — numbered, deduplicated, format:
     `1. [PMID: 12345678] Author AB et al. — Brief description. Journal, Year. (Score: XX/100)`

Do NOT rewrite the module bodies. Reproduce them verbatim, just inserting your overview/transitions/takeaways/references around them. The module authors have been instructed to use specific concentrations / times / sizes, to flag emerging-vs-established findings, and to attach `[[PMID:nnnnnnn]]` inline provenance markers to every clinical claim — preserve ALL of these details verbatim. Never soften a numeric value to a vague verb. Never strip or alter the `[[PMID:N]]` markers (they power the clinician verifiability side panel in the UI).

Your own additions (OVERVIEW, transitions, KEY TAKEAWAYS) should also use `[[PMID:nnnnnnn]]` inline markers when you make a specific clinical claim, using the same double-bracket format. Use the single-bracket format `[PMID: 12345]` ONLY in the final REFERENCES list — never inline.

KEY TAKEAWAYS formatting: each takeaway should be an actionable clinical pearl with concrete numbers where applicable (e.g., "Irrigate with 5.25% NaOCl for 60 s after final shaping" not "Irrigate adequately"). Where the takeaway concerns an emerging-evidence area, prefix it with "**Emerging:**" so the reader can distinguish from established standard-of-care. Where the takeaway concerns an area where high-quality literature genuinely disagrees, prefix it with "**Divided:**" and briefly state both positions.

═══════════════════════════════════════════════════════════════
THE FINAL VERDICT — MANDATORY DECISION-RULE SECTION
═══════════════════════════════════════════════════════════════
After KEY TAKEAWAYS and BEFORE the REFERENCES list, write a section titled `## The Final Verdict` containing four numbered subsections in this exact order:

**1. Decision Rule.** Give a chairside if/then rule for the central treatment question of "{parent_question}". Be operational — not "consider the patient" but: "If [tooth has X] AND [age band Y] AND [periapical status Z] → choose Treatment A. If [other condition] → choose Treatment B." Use named treatment options drawn from the curriculum, not abstract categories. If the central question is diagnostic rather than treatment-based, frame the rule as: "If [finding] → diagnosis A → action X. If [other finding] → diagnosis B → action Y."

**2. Evidence Anchor.** For each branch of the decision rule above, name the highest tier of evidence supporting it (Cochrane / Level I RCT / Level II prospective cohort / Level III retrospective / Level IV case series / Level V expert opinion) and cite the strongest paper inline as `[[PMID:N]]`. Use the literal phrase "**Anchored in:**" prefixing each branch. Example: "**Anchored in:** Level I systematic review of 12 RCTs (n=842) [[PMID:31543236]]." If a branch rests on case-level evidence only, say so explicitly: "**Anchored in:** case series only — no RCT or prospective cohort has yet evaluated this branch."

**3. Where Uncertainty Remains.** Three to five bulleted points naming the SPECIFIC unresolved questions in the evidence base for "{parent_question}". Each bullet must name (a) the specific clinical sub-question that's unresolved, (b) why current evidence is insufficient (e.g., "longest follow-up is 24 months — survival beyond 5 years unknown", "all RCTs to date are single-centre", "no head-to-head trial of A vs B in the indication of interest"), and (c) what study design would resolve it. Generic uncertainty disclaimers like "more research is needed" are forbidden — every bullet must be specific to a named gap.

**4. When NOT to Apply This Rule.** Two to three bulleted scenarios in which the decision rule above should be set aside in favour of patient-specific judgement, referral, or specialist opinion (e.g., "vertical root fracture confirmed", "active sinus tract with systemic symptoms", "non-compliant patient with abandoned recall history", "complex medical co-morbidity altering prognosis"). Each bullet ends with the alternative action (refer, monitor, etc.), not just the contraindication.

The Final Verdict is the section the clinician will re-read in the operatory at 3 p.m. before deciding what to do. It must be decisive, anchored, honest about gaps, and operational. Vague hedging ("the evidence is mixed", "consider individual factors") is forbidden in this section — those phrasings belong in KEY TAKEAWAYS where appropriate, not here.
═══════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════
CASE DIVERSITY RULE — REBALANCE IMBALANCED EVIDENCE
═══════════════════════════════════════════════════════════════
Before finalising, count the [[PMID:N]] markers across all module bodies + your additions:

1. Identify any single Tier IV / V source (case report, case series, expert opinion, narrative review) that accounts for **more than 20% of all inline citations** in the curriculum. The reference metadata block below tells you each paper's tier-equivalent score (≤45/100 = treat as Tier IV/V case-grade).

2. For any paper that exceeds the 20% threshold, you must **rebalance**: replace some of its citations with a higher-tier prospective study, RCT, or systematic review covering the same point — drawn from the reference metadata block below. The narrative content stays the same; only the inline `[[PMID:N]]` marker changes to a stronger source. If no higher-tier source in the evidence covers that point, leave the case-report citation in place but add an explicit phrase: "(supported only by case-level evidence; higher-tier confirmation pending)".

3. Aim for a healthy mix — when both case-level and prospective-cohort/RCT evidence exists for the same claim, the prospective source is the lead citation; the case report becomes a secondary/illustrative co-citation only if it adds a specific clinical detail the prospective study lacks.

This rule prevents a single anecdotal case report from looking like settled evidence by sheer repetition. The aim is balanced citation pressure across the evidence pyramid, weighted toward higher tiers wherever they exist.
═══════════════════════════════════════════════════════════════

Density rule: keep total length ≈ 3,000 words. Cut transitions before cutting teaching content."""

    user_message = f"""Curriculum syllabus:
{syllabus_str}

═══════════════════════════════════════════════════════════════
MODULE BODIES (reproduce verbatim with your wrapper text added):
═══════════════════════════════════════════════════════════════

{module_blocks}

═══════════════════════════════════════════════════════════════
REFERENCE METADATA (compile the final REFERENCES list from these — only include papers actually cited in module bodies above):
═══════════════════════════════════════════════════════════════

{refs_block}

Now produce the final stitched curriculum."""

    # Compute a token budget for the stitcher: each module is capped at 1800 tokens
    # by write_curriculum_module; with N modules + ~2500 tokens of additions
    # (overview, transitions, takeaways, verdict, references), we need at least
    # N*1800 + 2500. Add 20% headroom and clamp to Sonnet's 64K output limit.
    n_modules = len(modules_with_scripts)
    stitch_budget = min(int((n_modules * 1800 + 2500) * 1.2), 32000)

    print(f"\n[curriculum] Step D — stitching {n_modules} modules (budget={stitch_budget} tokens)")
    # TIER 2 (flag-gated) — Sonnet candidate; reproduces module bodies verbatim
    # and only writes overview/transitions/takeaways/refs (light synthesis).
    resp, cost = tier2_invoke(
        "stitch_curriculum",
        mode="learn",
        max_tokens=stitch_budget,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    print(f"  Cost: ${cost:.4f} ({resp.usage.input_tokens} in / {resp.usage.output_tokens} out)")
    return resp.content[0].text, cost


def merge_evidence_bases(per_module_evidence: list) -> dict:
    """
    Combine N tier-organised evidence dicts into one. Used by the curriculum
    builder to give the stitcher a single deduplicated _summary for references.
    """
    combined = {key: {"text": "", "ids": [], "scored": []} for key in TIER_ORDER}
    seen_pmids = set()
    for ev in per_module_evidence:
        for tier_key in TIER_ORDER:
            block = ev.get(tier_key, {}) or {}
            for p in (block.get("scored") or []):
                pmid = p.get("pmid")
                if pmid and pmid not in seen_pmids:
                    seen_pmids.add(pmid)
                    combined[tier_key]["scored"].append(p)
                    combined[tier_key]["ids"].append(pmid)
            if block.get("text"):
                combined[tier_key]["text"] += "\n" + block["text"]

    all_scored = []
    for tk in TIER_ORDER:
        all_scored.extend(combined[tk]["scored"])
    avg = (sum(p.get("score", 0) for p in all_scored) / len(all_scored)) if all_scored else 0
    combined["_summary"] = {
        "total_scored":    len(all_scored),
        "avg_score":       round(avg, 1),
        "all_scored":      sorted(all_scored, key=lambda x: x.get("score", 0), reverse=True),
        "synthesis_order": build_synthesis_order(combined),
    }
    return combined


def build_deep_learning_module(question: str, progress_cb=None) -> tuple:
    """
    Top-level orchestrator for the agentic curriculum builder.
    Returns: (final_markdown, total_cost, combined_evidence)

    `progress_cb(percent: int, message: str)` — optional, called between stages
    so the Flask job tracker can update the UI.
    """
    def _tick(pct, msg):
        if progress_cb:
            try: progress_cb(pct, msg)
            except Exception: pass

    total_cost = 0.0

    # Step A — Syllabus
    _tick(8, "Generating curriculum syllabus...")
    syllabus, c = generate_curriculum_syllabus(question)
    total_cost += c

    # Step B — per-module retrieval
    n = len(syllabus)
    per_module_evidence = []
    modules_with_scripts = []

    # Reserve 30-65% of progress bar for retrieval (the slow PubMed bit)
    retrieval_span = 35
    retrieval_base = 15
    for i, mod in enumerate(syllabus):
        pct = retrieval_base + int((i / max(n, 1)) * retrieval_span)
        _tick(pct, f"Searching evidence for module {i+1}/{n}: {mod['title']}")
        ev = build_evidence_base(mod["search_query"], mode="learn")
        per_module_evidence.append(ev)

    # Step C — per-module writing
    writing_span = 20
    writing_base = 55
    for i, (mod, ev) in enumerate(zip(syllabus, per_module_evidence)):
        pct = writing_base + int((i / max(n, 1)) * writing_span)
        _tick(pct, f"Writing module {i+1}/{n}: {mod['title']}")
        ok, n_papers = module_has_usable_evidence(ev)

        # Retrieval came back empty or near-empty. Broaden the query once before
        # giving up — a narrow or over-specified query is the usual cause.
        if not ok:
            print(f"  [module {i+1}] only {n_papers} paper(s) — broadening and retrying")
            try:
                broadened = generate_search_terms(
                    f"{mod['title']} (broad concept search; use OR-groups of "
                    f"synonyms, abbreviations and device names)"
                )
                ev_retry = build_evidence_base(broadened, mode="learn")
                ok_retry, n_retry = module_has_usable_evidence(ev_retry)
                if n_retry > n_papers:
                    ev, ok, n_papers = ev_retry, ok_retry, n_retry
                    print(f"  [module {i+1}] broadened search found {n_retry} paper(s)")
            except Exception as e:
                print(f"  [module {i+1}] broadened retry failed: {e}")

        if not ok:
            # Still nothing. Emit an explicit gap rather than a module: a
            # numeric protocol written from no sources is the worst output
            # this system can produce, and a disclaimer does not redeem it.
            print(f"  [module {i+1}] SKIPPED — {n_papers} paper(s), below minimum "
                  f"{MIN_MODULE_PAPERS}")
            modules_with_scripts.append({
                **mod,
                "script": _module_not_generated_block(
                    mod.get("title", f"Module {i+1}"), n_papers,
                    mod.get("search_query", "")),
                "not_generated": True,
            })
            continue

        script, c = write_curriculum_module(mod, ev, question, idx=i+1, total=n)
        total_cost += c

        # Even with evidence present, refuse a module that specifies clinical
        # parameters while citing nothing.
        verdict = validate_module_output(script, ev)
        if not verdict["ok"]:
            print(f"  [module {i+1}] REJECTED — {verdict['reason']}")
            script = _module_not_generated_block(
                mod.get("title", f"Module {i+1}"), n_papers,
                mod.get("search_query", ""))
            modules_with_scripts.append({**mod, "script": script, "not_generated": True})
            continue

        modules_with_scripts.append({**mod, "script": script})

    # Step D — Stitch
    _tick(82, "Stitching curriculum...")
    combined = merge_evidence_bases(per_module_evidence)
    final, c = stitch_curriculum(question, modules_with_scripts, combined)
    total_cost += c

    _tick(95, "Finalising...")
    return final, total_cost, combined


# ── CASE DISCUSSION ───────────────────────────────────────
def ask_case_question(messages: list, evidence: dict) -> tuple:
    """
    Clinical case discussion / chat mode.
    messages: conversation history [{"role": "user"|"assistant", "content": str}]
    Returns (answer, cost).
    """
    client = anthropic.Anthropic(api_key=_get_api_key())

    system_prompt = """═══════════════════════════════════════════════════════════════
MANDATORY CITATION FORMAT — NON-NEGOTIABLE
═══════════════════════════════════════════════════════════════
You MUST NEVER output a bare PMID number anywhere in your response. Every time you reference a paper, you MUST wrap the PMID EXACTLY like this:

    [[PMID:12345678]]

Double brackets, the literal prefix "PMID:", the digit string, double brackets to close. Multiple co-citations are space-separated, each fully wrapped: [[PMID:12345678]] [[PMID:23456789]]. Forbidden formats include bare numbers ("PMID 12345678"), single brackets ("[PMID: 12345]"), parentheses ("(12345678)"), superscripts, footnotes, or "ref 1".

This is a clinical-safety requirement: the chairside UI parses these markers to render click-through citation pills so the clinician can verify each source before acting on your advice. Any other format will fail to render and the clinician cannot inspect the evidence — that makes your response unsafe to act on.
═══════════════════════════════════════════════════════════════

You are a senior endodontist providing real-time clinical consultation on a case.

The clinician has described their case. Use the peer-reviewed evidence to give direct, practical advice.

Format every response exactly like this:

**Assessment:** 1-2 sentences on your clinical interpretation.

**Recommendation:** Clear, actionable recommendation with rationale.

**Evidence:** 1-2 key studies cited as Author et al. (Year) [[PMID:XXXXXXXX]].

**Key Considerations:** Any caveats, red flags, alternative approaches, or follow-up plan.

INLINE PROVENANCE (REQUIRED for clinician verifiability):
Every standalone clinical claim — a recommendation, statistic, treatment success rate, comparative finding, or factual statement supported by literature — MUST be followed immediately by `[[PMID:nnnnnnn]]` markers, one per supporting paper. Use the EXACT format `[[PMID:12345678]]` (double brackets, no space after the colon). Place markers at the END of the sentence the claim appears in.
- Example: "MTA outperforms calcium hydroxide in vital pulp therapy [[PMID:31543236]] [[PMID:34234567]]."
- Multiple supporting papers can be cited (space-separated markers).
- If a claim summarises a systematic review's pooled estimate, cite the SR's PMID, not the underlying primary trials.
- Do NOT add markers to the **Assessment** sentence (which is your interpretation, not an evidence-derived claim) or to general transitions. Markers belong on **Recommendation**, **Evidence**, and any **Key Considerations** that cite literature.
- The double-bracket format `[[PMID:N]]` is what powers the click-through source-abstract side panel in the UI. Do NOT use the single-bracket form `[PMID: N]` anywhere in your response — the UI will not recognise it as a verifiability marker.

Keep responses concise and focused. Build naturally on prior messages in the conversation.
Never fabricate PMIDs or invent studies.
NEVER end your response with a question to the clinician. NEVER ask for more information. If missing details would change your recommendation, list what those details are — but do not pose questions.

UNIVERSAL NUMBERING SYSTEM — always use the correct tooth name when a number is mentioned:
Upper (R→L): 1=Mx R 3rd molar, 2=Mx R 2nd molar, 3=Mx R 1st molar, 4=Mx R 2nd premolar, 5=Mx R 1st premolar, 6=Mx R canine, 7=Mx R lateral incisor, 8=Mx R central incisor, 9=Mx L central incisor, 10=Mx L lateral incisor, 11=Mx L canine, 12=Mx L 1st premolar, 13=Mx L 2nd premolar, 14=Mx L 1st molar, 15=Mx L 2nd molar, 16=Mx L 3rd molar
Lower (L→R): 17=Mn L 3rd molar, 18=Mn L 2nd molar, 19=Mn L 1st molar, 20=Mn L 2nd premolar, 21=Mn L 1st premolar, 22=Mn L canine, 23=Mn L lateral incisor, 24=Mn L central incisor, 25=Mn R central incisor, 26=Mn R lateral incisor, 27=Mn R canine, 28=Mn R 1st premolar, 29=Mn R 2nd premolar, 30=Mn R 1st molar, 31=Mn R 2nd molar, 32=Mn R 3rd molar
(Mx=Maxillary, Mn=Mandibular)"""

    # Build evidence context — strict tier order (Cochrane → L5),
    # same builder as review/learn modes
    context = _build_evidence_context(evidence)

    # Inject evidence only into the first user message
    api_messages = []
    for i, msg in enumerate(messages):
        if i == 0 and msg["role"] == "user":
            api_messages.append({
                "role": "user",
                "content": (
                    f"Evidence base for this consultation:\n{context}\n\n"
                    f"---\n\nCase: {msg['content']}"
                )
            })
        else:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

    print(f"\nCase consultation -- asking Claude...")
    print("=" * 60)

    # TIER 2 (flag-gated) — Sonnet candidate; 2K tok chat-friendly responses
    # with conversation memory, no fresh evidence synthesis required.
    resp, cost = tier2_invoke(
        "ask_case_question",
        mode       = "case",
        max_tokens = 2000,
        system     = system_prompt,
        messages   = api_messages,
    )
    print(f"  Cost: ${cost:.4f} ({resp.usage.input_tokens} in / {resp.usage.output_tokens} out)")

    answer = resp.content[0].text

    # Validate-and-retry — case answers are short, validation is cheap and
    # mis-cited PMIDs in case advice are particularly dangerous chairside.
    result = validate_evidence_mapping(answer, evidence)
    _log_evidence_mapping("ask_case_question", "case", attempt=1, result=result)
    print(f"  Evidence mapping: passed={result['passed']} score={result['score']} "
          f"cited={len(result['cited_pmids'])} fabricated={len(result['fabricated_pmids'])} "
          f"unattributed={len(result['unattributed_claims'])} gaps={len(result['gap_sections'])}")

    if not result["passed"]:
        print(f"  RETRY — validation failed: {result['failure_reason']}")
        retry_messages = list(api_messages)
        retry_messages.append({"role": "assistant", "content": answer})
        retry_messages.append({"role": "user", "content": _build_corrective_message(result)})
        retry_resp, retry_cost = tier2_invoke(
            "ask_case_question_retry",
            mode       = "case",
            max_tokens = 2000,
            system     = system_prompt,
            messages   = retry_messages,
        )
        cost += retry_cost
        retry_answer = retry_resp.content[0].text
        retry_result = validate_evidence_mapping(retry_answer, evidence)
        _log_evidence_mapping("ask_case_question", "case", attempt=2, result=retry_result)
        print(f"  Retry mapping:    passed={retry_result['passed']} score={retry_result['score']} "
              f"cited={len(retry_result['cited_pmids'])} fabricated={len(retry_result['fabricated_pmids'])} "
              f"unattributed={len(retry_result['unattributed_claims'])} gaps={len(retry_result['gap_sections'])}")

        if retry_result["passed"] or retry_result["score"] >= result["score"]:
            answer, result = retry_answer, retry_result
        if not result["passed"]:
            warning = (
                f"> ⚠ **VALIDATION WARNING** — {result['failure_reason']}. Verify any cited PMIDs "
                f"before acting clinically.\n\n"
            )
            answer = warning + answer

    return answer, cost


# ── SLIDES CONTENT GENERATOR ──────────────────────────────
def generate_slides_content(answer: str, question: str, length_minutes: int) -> dict:
    """
    Ask Claude to produce a richly typed JSON slide deck.
    Slide types: title, stat_cards, type_cards, numbered_grid, chart_bar,
                 comparison_table, bullets, summary, references.
    """
    client     = anthropic.Anthropic(api_key=_get_api_key())
    slide_count = max(8, min(55, length_minutes * 2))
    words_per_slide = round(length_minutes * 145 / slide_count)

    prompt = f"""You are designing a {length_minutes}-minute narrated, professional clinical endodontic slide deck on: "{question}"

Generate exactly {slide_count} slides as a colorful, varied, magazine-style presentation. Vary the layout types so the deck is visually engaging — do NOT use only bullet slides.

Return ONLY valid JSON (no markdown fence, no commentary):
{{
  "title": "Short presentation title (2-5 words)",
  "subtitle": "One-line tagline",
  "footer": "BRAND FOOTER LINE - SHORT TOPIC",
  "slides": [ ... ]
}}

Each slide is one of these types — pick the BEST fit for the content. Required fields per type:

1. title slide (always slide 1)
   {{"type":"title","eyebrow":"CLINICAL EDUCATION - ENDODONTICS","title":"Main title","subtitle":"Subtitle line","stats":[{{"value":"85%","label":"Maxillary lateral incisors"}}, ...up to 3], "speaker_notes":"..."}}

2. stat_cards (3 big-number callouts in a row)
   {{"type":"stat_cards","eyebrow":"EPIDEMIOLOGY","title":"Where Does It Occur?","cards":[{{"value":"85%","label":"Description"}}, ...exactly 3], "speaker_notes":"..."}}

3. type_cards (2-4 categorized cards in a row, each with a colored badge)
   {{"type":"type_cards","eyebrow":"CLASSIFICATION","title":"Oehlers Classification","cards":[{{"label":"TYPE I","heading":"Confined to crown","body":"1-2 sentence description","badge":"EXCELLENT","badge_color":"green"}}, ...], "speaker_notes":"..."}}
   badge_color: green, amber, red, teal, coral

4. numbered_grid (2-6 numbered items in a 2- or 3-column grid)
   {{"type":"numbered_grid","eyebrow":"CLINICAL SIGNS","title":"Recognising the Anomaly","items":[{{"n":1,"heading":"Enlarged cingulum","body":"Palpable bump on palatal surface"}}, ...], "speaker_notes":"..."}}

5. chart_bar (horizontal bar chart with real data)
   {{"type":"chart_bar","eyebrow":"DISTRIBUTION","title":"By Tooth Type","categories":["Maxillary lateral","Maxillary central","Mandibular incisor","Other"], "values":[85,8,4,3], "unit":"%", "speaker_notes":"..."}}
   Use ONLY real numbers from the report. If no chart-worthy data exists, do not generate a chart_bar slide.

6. comparison_table (2-5 rows, 2-4 columns)
   {{"type":"comparison_table","eyebrow":"MANAGEMENT","title":"Treatment Pathway","headers":["Type","Pulp Status","Treatment","Prognosis"], "rows":[["I","Vital","Sealant","Excellent"], ["II","Necrotic","Endo","Good"]], "speaker_notes":"..."}}

7. bullets (use sparingly — only when no other type fits)
   {{"type":"bullets","eyebrow":"BACKGROUND","title":"Definition","bullets":["Bullet 1","Bullet 2","Bullet 3"], "speaker_notes":"..."}}

8. summary (final takeaways)
   {{"type":"summary","eyebrow":"KEY TAKEAWAYS","title":"Clinical Pearls","bullets":["Pearl 1","Pearl 2","Pearl 3","Pearl 4"], "speaker_notes":"..."}}

9. references (bibliography)
   {{"type":"references","title":"References","items":["Author et al. (2023). Title. Journal.","..."], "speaker_notes":"..."}}

LAYOUT REQUIREMENTS for a {slide_count}-slide deck:
- Slide 1: MUST be type="title"
- Last slide: MUST be type="references" with 5-10 citations
- Second-to-last slide: SHOULD be type="summary"
- Among the middle slides, REQUIRED variety: at least 1 stat_cards, at least 1 type_cards OR numbered_grid, at least 1 comparison_table, at least 1 chart_bar (only if real data supports it). Use bullets for AT MOST 2 slides.

Content rules:
- speaker_notes per slide: ~{words_per_slide} words, natural spoken English, no markdown, no headers
- Total spoken narration: ~{length_minutes * 145} words across all slides
- Eyebrow text: ALL CAPS, 2-5 words, acts as section label
- Card body / table cell text: terse, max ~15 words

Report (your evidence base):
{answer[:6000]}"""

    # Length-aware token budget — long decks need more headroom or the JSON
    # truncates mid-slide and the parser silently fails. Empirically each
    # slide costs ~250-400 tokens (speaker_notes dominate); plus the JSON
    # scaffolding. Cap at the model's safe limit.
    token_budget = max(8000, min(20000, slide_count * 500 + 2000))

    # TIER 2 (flag-gated) — Sonnet candidate; structural reformat (answer → JSON deck).
    def _generate(extra_msg: str = "", budget: int = token_budget):
        msgs = [{"role": "user", "content": prompt + extra_msg}]
        return tier2_invoke(
            "generate_slides_content",
            mode       = "export",
            max_tokens = budget,
            messages   = msgs,
        )

    resp, cost = _generate()
    print(f"  Slides content cost: ${cost:.4f} ({resp.usage.input_tokens} in / {resp.usage.output_tokens} out, max_tokens={token_budget})")

    deck, parse_err = _parse_slides_response(resp.content[0].text, question, length_minutes)

    # If the first attempt produced no slides, retry once with explicit
    # diagnostic feedback so Claude knows what to fix.
    if not deck.get("slides"):
        sample = (resp.content[0].text or "")[:400].replace("\n", " ")
        print(f"  [slides] first attempt produced 0 slides — parse_err={parse_err!r}")
        print(f"  [slides] response sample: {sample!r}")
        retry_msg = (
            "\n\nIMPORTANT: your previous response could not be parsed into a slide deck "
            f"(reason: {parse_err}). Return ONLY a single valid JSON object with the structure "
            '{"title":"...", "subtitle":"...", "footer":"...", "slides":[{...},{...},...]}. '
            "No prose, no markdown fence, no commentary. The JSON must be syntactically complete; "
            "if you cannot fit all slides within the token limit, reduce slide count rather than truncating."
        )
        resp2, cost2 = _generate(extra_msg=retry_msg, budget=min(token_budget + 4000, 24000))
        cost += cost2
        print(f"  Slides retry cost: ${cost2:.4f}")
        deck2, parse_err2 = _parse_slides_response(resp2.content[0].text, question, length_minutes)
        if deck2.get("slides"):
            deck = deck2
        else:
            sample2 = (resp2.content[0].text or "")[:400].replace("\n", " ")
            print(f"  [slides] retry also produced 0 slides — parse_err={parse_err2!r}")
            print(f"  [slides] retry sample: {sample2!r}")

    deck.setdefault("title", question)
    deck.setdefault("subtitle", f"{length_minutes}-Minute Clinical Lecture")
    deck.setdefault("footer", question.upper()[:60])
    return deck


def generate_slides_specs(answer: str, question: str, length_minutes: int) -> dict:
    """
    Pattern-based slide-deck generator — returns structured specs for
    presentations/build_deck.py rather than the legacy type-keyed dict.

    Each slide in `deck["slides"]` has a "pattern" key matching one of the 10
    layout functions in slide_patterns.py, plus all required fields for that
    pattern, plus "speaker_notes" for the TTS pipeline.

    Falls back to generate_slides_content() if parsing fails.
    """
    client      = anthropic.Anthropic(api_key=_get_api_key())
    slide_count = max(8, min(24, length_minutes * 2))
    words_per_slide = round(length_minutes * 145 / slide_count)
    token_budget    = max(10000, min(24000, slide_count * 600 + 3000))

    pattern_guide = """
AVAILABLE PATTERNS — use the one whose structure best matches the content:

1. title_slide  (slide 1 only)
   {"pattern":"title_slide","eyebrow":"TOPIC · SUBTOPIC","title":"Main title (can use \\n for line break)","subtitle":"One-line tagline","tagline":"Optional italic callout sentence","footer_metadata":"Source tier · Guideline · Version","speaker_notes":"..."}

2. section_divider  (module/chapter breaks)
   {"pattern":"section_divider","module_label":"MODULE 01","module_title":"Section Title","module_subtitle":"Optional subtitle — italic, muted","footer":"MODULE 1 · LABEL","speaker_notes":"..."}

3. objectives_slide  (learning goals — use near start of each module)
   {"pattern":"objectives_slide","eyebrow":"MODULE X · OBJECTIVES","title":"Short framing statement","items":[{"icon":"microscope","number":"01","header":"Bold goal","body":"One sentence elaboration."}],"closing_callout":"Optional italics punch line.","speaker_notes":"..."}
   icon options: microscope, tooth, alert, chart_bar, book, check, clipboard, flag, search, star, info, stethoscope

4. two_column_compare  (two competing approaches, drugs, protocols)
   {"pattern":"two_column_compare","eyebrow":"MODULE X · COMPARISON","title":"Short comparison title","left_card":{"label":"LEFT LABEL","headline":"Headline","lines":["Line 1","Line 2","Line 3"],"verdict":{"icon":"x_circle","text":"Verdict text","color":"accent_red"}},"right_card":{"label":"RIGHT LABEL","headline":"Headline","lines":["Line 1","Line 2","Line 3"],"verdict":{"icon":"check_circle","text":"Verdict text","color":"accent_teal"}},"center_chip":"arrow_both","caption":"Optional italic caption below.","speaker_notes":"..."}
   verdict color options: accent_red, accent_teal, accent_gold, accent_coral

5. cascade_slide  (3–5 sequential steps, cause-effect chains)
   {"pattern":"cascade_slide","eyebrow":"MODULE X · SEQUENCE","title":"Short title","steps":[{"number":"01","header":"Step header","body":"1-2 sentence explanation."}],"footer_callout":"Optional clinical implication.","speaker_notes":"..."}

6. decision_table  (findings → implication → action, up to 6 rows)
   {"pattern":"decision_table","eyebrow":"MODULE X · DECISION FRAMEWORK","title":"Short title","rows":[{"finding":"Bold finding","implication":"What it means","path":"Italic action","severity_color":"accent_red"}],"footer_caption":"Optional citation/note.","speaker_notes":"..."}
   severity_color options: accent_red, accent_teal, accent_gold, accent_coral, ink_secondary

7. three_route_grid  (exactly 3 parallel options or treatment routes)
   {"pattern":"three_route_grid","eyebrow":"MODULE X · OPTIONS","title":"Short title","routes":[{"color":"accent_teal","icon":"repeat","name":"Route Name","tagline":"When to use","when":"Indication sentence.","how":"Technique sentence.","citation":"Author, Journal Year"}],"speaker_notes":"..."}
   color options: accent_teal, accent_coral, accent_gold

8. stat_panel  (1–2 big numbers with context)
   {"pattern":"stat_panel","eyebrow":"MODULE X · OUTCOMES","title":"Short title","primary_stat":"96.1%","primary_label":"What it measures and source","secondary_stat":"61%","secondary_label":"What it measures","callout":"Insight sentence bridging the two numbers.","citation":"Full citations.","speaker_notes":"..."}
   secondary_stat and secondary_label are optional.

9. evidence_summary  (evidence hierarchy + insight callout)
   {"pattern":"evidence_summary","eyebrow":"MODULE X · EVIDENCE","title":"Short title","hierarchy_rows":[{"tier_label":"PRIMARY","description":"What studies","stat":"96.1%","color":"accent_teal"}],"trap_callout":{"heading":"THE TRAP","body":"Why headline figure misleads.","stat":"61%","stat_label":"What the real number is","color":"accent_coral"},"speaker_notes":"..."}
   color options: accent_teal, accent_gold, accent_coral, ink_secondary, ink_muted

10. takeaways_slide  (final summary, always last or second-to-last)
    {"pattern":"takeaways_slide","eyebrow":"MODULE X · KEY TAKEAWAYS","title":"Short serif italic title","items":[{"number":"01","header":"Bold takeaway","body":"Supporting sentence."}],"speaker_notes":"..."}
"""

    pattern_rules = f"""
PATTERN SELECTION RULES:
- Slide 1: MUST be title_slide
- Last content slide: MUST be takeaways_slide
- Use section_divider to open each new module/topic block
- Comparing two things → two_column_compare
- Sequence of 3-5 steps → cascade_slide
- Decision rules (finding → action) → decision_table
- Exactly 3 parallel paths → three_route_grid
- Big numbers / success rates → stat_panel
- Evidence quality hierarchy → evidence_summary
- Learning goals → objectives_slide
- NEVER use the same pattern twice in a row
- Aim for at least 6 different patterns across the {slide_count}-slide deck
- NO full-width colored bars — those are handled inside each pattern
- Keep eyebrow text ALL-CAPS, 3-6 words, format: "MODULE X · TOPIC"
"""

    prompt = f"""You are a clinical endodontic educator designing a {length_minutes}-minute narrated presentation on:
"{question}"

Generate exactly {slide_count} slides using the pattern system below. Return ONLY valid JSON — no markdown fence, no commentary, no trailing text.

Top-level format:
{{"title":"Deck title (2-5 words)","subtitle":"One-line tagline","footer":"SECTION LABEL","slides":[...]}}

{pattern_guide}

{pattern_rules}

CONTENT RULES:
- speaker_notes per slide: ~{words_per_slide} words, natural spoken English, no markdown, no headers. This is the narration track the clinician will hear.
- Card body / table cell / step body: terse, max 20 words each
- All statistics must come from the evidence report below — do not fabricate numbers
- Use [[PMID:N]] citations within speaker_notes only, never in card body text
- Vary the deck: at minimum use title_slide + takeaways_slide + at least 4 other distinct patterns

Evidence report (your only source):
{answer[:7000]}"""

    def _try_generate(extra: str = "", budget: int = token_budget):
        msgs = [{"role": "user", "content": prompt + extra}]
        return tier2_invoke(
            "generate_slides_specs",
            mode       = "export",
            max_tokens = budget,
            messages   = msgs,
        )

    resp, cost = _try_generate()
    print(f"  [specs] cost: ${cost:.4f} ({resp.usage.input_tokens}in/{resp.usage.output_tokens}out)")

    deck, err = _parse_slides_response(resp.content[0].text, question, length_minutes)

    if not deck.get("slides"):
        sample = (resp.content[0].text or "")[:400].replace("\n", " ")
        print(f"  [specs] parse failed ({err}) — retrying. sample: {sample!r}")
        retry_msg = (
            f"\n\nYour previous response failed to parse ({err}). "
            "Return ONLY a single valid JSON object starting with { and ending with }. "
            "No prose, no markdown fences. Reduce slide count if needed to stay within token limit."
        )
        resp2, cost2 = _try_generate(extra=retry_msg, budget=min(token_budget + 4000, 28000))
        cost += cost2
        deck2, err2 = _parse_slides_response(resp2.content[0].text, question, length_minutes)
        if deck2.get("slides"):
            deck = deck2
        else:
            print(f"  [specs] retry also failed ({err2}) — falling back to generate_slides_content")
            return generate_slides_content(answer, question, length_minutes)

    deck.setdefault("title", question)
    deck.setdefault("subtitle", f"{length_minutes}-Minute Clinical Lecture")
    deck.setdefault("footer", question.upper()[:60])
    print(f"  [specs] {len(deck.get('slides', []))} slides, total cost ${cost:.4f}")
    return deck


def _parse_slides_response(raw_text: str, fallback_title: str,
                            length_minutes: int) -> tuple[dict, str | None]:
    """Robust JSON extractor for the slide-deck response.

    Returns (deck_dict, error_reason). On failure deck_dict is the fallback
    skeleton (with an empty slides list) and error_reason names the failure
    mode so the caller can log it and trigger a retry.

    Handles three known failure modes:
      1. Markdown ```json fence wrapping
      2. Commentary text before or after the JSON
      3. Top-level array (when the model forgets the {title, slides} wrapper)
    """
    if not raw_text or not raw_text.strip():
        return {"title": fallback_title, "slides": []}, "empty response"

    raw = re.sub(r"```json|```", "", raw_text).strip()

    # Find the first { or [ and brace-match to its closing partner so a
    # trailing comment after the JSON doesn't trip us up.
    open_idx = -1
    open_char = ""
    for i, ch in enumerate(raw):
        if ch in "{[":
            open_idx = i
            open_char = ch
            break
    if open_idx < 0:
        return {"title": fallback_title, "slides": []}, "no JSON object/array found in response"

    close_char = "}" if open_char == "{" else "]"
    depth = 0
    in_str = False
    esc    = False
    end_idx = -1
    for i in range(open_idx, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:    esc = False
            elif ch == "\\": esc = True
            elif ch == '"':  in_str = False
            continue
        if ch == '"':
            in_str = True; continue
        if ch == open_char:  depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break

    if end_idx < 0:
        # Unmatched braces — almost certainly truncated mid-output
        return ({"title": fallback_title, "slides": []},
                f"truncated JSON (unmatched {open_char}, response cut mid-output — increase max_tokens)")

    blob = raw[open_idx:end_idx]
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError as e:
        return ({"title": fallback_title, "slides": []},
                f"JSONDecodeError: {e.msg} at line {e.lineno} col {e.colno}")

    # Accept either {title, slides:[...]} or a top-level [...] of slide dicts.
    if isinstance(parsed, list):
        return ({"title": fallback_title,
                 "subtitle": f"{length_minutes}-Minute Clinical Lecture",
                 "slides": parsed}, None)
    if isinstance(parsed, dict):
        if isinstance(parsed.get("slides"), list):
            return parsed, None
        # Some Claude outputs use 'deck' or 'content' as the key
        for alt in ("deck", "content", "presentation"):
            v = parsed.get(alt)
            if isinstance(v, list):
                parsed["slides"] = v
                return parsed, None
        return parsed, "JSON object has no 'slides' array (found keys: " + ",".join(parsed.keys()) + ")"
    return {"title": fallback_title, "slides": []}, f"unexpected JSON top-level type: {type(parsed).__name__}"


# ── TWO-HOST PODCAST SCRIPT ───────────────────────────────
def generate_podcast_script(answer: str, question: str, length_minutes: int,
                             host1: str = "DR. CHEN", host2: str = "ALEX") -> list:
    """
    Generate a two-host conversational podcast script.
    host1 = expert endodontist (voice: onyx)
    host2 = curious resident/student (voice: nova)
    Returns list of {"host": str, "text": str} dicts.
    ~130 words/min for natural conversation.
    """
    client = anthropic.Anthropic(api_key=_get_api_key())
    word_target = length_minutes * 130
    turns_estimate = max(12, length_minutes * 4)

    prompt = f"""You are writing a {length_minutes}-minute educational podcast script for endodontists.

TWO HOSTS:
- {host1}: Senior endodontist and researcher. Authoritative, precise, cites evidence naturally.
- {host2}: Enthusiastic dental resident. Asks great clinical questions, relates concepts to practice.

TOPIC: {question}

TARGET: approximately {word_target} words total across ~{turns_estimate} exchanges.

RULES:
- Write ONLY dialogue — no stage directions, no narration, no asterisks
- Start with {host2} welcoming the listener and introducing the topic naturally
- {host1} should cite evidence as: "Chen and colleagues found that..." (never say PMID)
- Include 2-3 realistic clinical scenarios or cases woven into the conversation
- {host2} should ask at least 3 clarifying "but what about..." or "so in practice..." questions
- End with {host1} giving 2-3 clear takeaways and {host2} closing the episode
- Keep each speaking turn 1-4 sentences — natural conversational rhythm
- Total script should fill exactly {length_minutes} minutes when spoken aloud

RETURN FORMAT — return ONLY a JSON array, no other text:
[
  {{"host": "{host1}", "text": "..."}},
  {{"host": "{host2}", "text": "..."}},
  ...
]

SOURCE MATERIAL:
{answer[:6000]}"""

    import json as _json
    # TIER 2 (flag-gated) — Sonnet candidate; reformat (answer → dialogue script).
    resp, cost = tier2_invoke(
        "generate_podcast_script",
        mode="export",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    print(f"  Podcast script cost: ${cost:.4f} ({resp.usage.input_tokens} in / {resp.usage.output_tokens} out)")

    raw = resp.content[0].text.strip()
    import re as _re
    raw = _re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    try:
        lines = _json.loads(raw)
        if isinstance(lines, list):
            return [l for l in lines if isinstance(l, dict) and "host" in l and "text" in l]
    except Exception:
        pass
    # Fallback: parse plain PROF:/ALEX: format
    result = []
    for line in raw.splitlines():
        for host in [host1, host2]:
            if line.startswith(f"{host}:"):
                result.append({"host": host, "text": line[len(host)+1:].strip()})
    return result


# ── AUDIO SCRIPT GENERATOR (lecture / single-voice) ───────
def generate_audio_script(answer: str, question: str, length_minutes: int) -> str:
    """
    Use Claude to reformat the Deep Learning answer into a natural-speech audio
    lecture script of approximately `length_minutes` minutes.
    ~145 words/min for clear educational speech.
    """
    client     = anthropic.Anthropic(api_key=_get_api_key())
    word_target = length_minutes * 145

    prompt = f"""You are converting an endodontic educational report into a {length_minutes}-minute audio lecture script.

Target: approximately {word_target} words.

Rules:
- Write entirely in spoken language — NO markdown, NO headers, NO bullet points, NO asterisks
- Use verbal transitions: "Let's begin with...", "Moving on to...", "Importantly...", "As we consider...", "Now let's turn to..."
- For citations say: "[Author] and colleagues, in [Year], demonstrated that..." (never say "PMID")
- Open with: "Welcome to this {length_minutes}-minute lecture on {question}."
- Close with: "In summary..." followed by 2-3 key takeaways spoken naturally
- Speak in a clear, authoritative tone appropriate for a continuing education lecture
- If content is longer than {word_target} words, prioritise clinical recommendations and key evidence
- If shorter, expand on clinical implications and chairside applications

Report to convert:
{answer[:7000]}"""

    # TIER 2 (flag-gated) — Sonnet candidate; reformat (answer → TTS narration).
    resp, cost = tier2_invoke(
        "generate_audio_script",
        mode="export",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    print(f"  Audio script cost: ${cost:.4f} ({resp.usage.input_tokens} in / {resp.usage.output_tokens} out)")
    return resp.content[0].text


# ── EDUCATIONAL IMAGES ────────────────────────────────────
def fetch_topic_images(topic: str, limit: int = 3) -> list:
    """
    Fetch educational images combining:
    - Option 1: Wikipedia REST API thumbnails (anatomy/procedure diagrams)
    - Option 2: Wikimedia Commons category search (clinical radiographs & photos)
    """

    HEADERS = {"User-Agent": "EndoAI/1.0 (educational endodontic assistant)"}
    topic_lower = topic.lower()

    # ── Option 1: Wikipedia article thumbnails ────────────
    TOPIC_ARTICLES = [
        (["root canal", "rct", "perform", "endodontic treatment"],
         ["Root_canal_treatment", "Dental_pulp", "Apical_periodontitis", "Endodontics"]),
        (["pulp cap", "vital pulp", "mta", "biodentine"],
         ["Pulp_capping", "Mineral_trioxide_aggregate", "Dental_pulp", "Endodontics"]),
        (["apical", "periapical", "abscess", "periodontitis"],
         ["Apical_periodontitis", "Dental_abscess", "Root_canal_treatment", "Endodontics"]),
        (["instrument", "rotary", "reciproc", "glide path", "niti"],
         ["Root_canal_treatment", "Nickel_titanium", "Endodontics", "Dental_pulp"]),
        (["irrigat", "sodium hypochlorite", "edta", "disinfect"],
         ["Root_canal_treatment", "Sodium_hypochlorite", "Dental_pulp", "Endodontics"]),
        (["obturat", "gutta-percha", "sealer", "fill"],
         ["Gutta-percha", "Root_canal_treatment", "Endodontics", "Dental_pulp"]),
        (["retreatment", "failed", "revision"],
         ["Root_canal_treatment", "Apical_periodontitis", "Endodontics", "Dental_pulp"]),
        (["apex locator", "working length"],
         ["Root_canal_treatment", "Endodontics", "Dental_pulp", "Apical_periodontitis"]),
        (["crack", "fracture", "split"],
         ["Cracked_tooth_syndrome", "Root_canal_treatment", "Endodontics", "Dental_pulp"]),
        (["crown", "restoration", "coronal seal"],
         ["Dental_crown", "Root_canal_treatment", "Endodontics", "Dental_pulp"]),
        (["anaesthes", "anesthes", "pain", "local"],
         ["Dental_anesthesia", "Root_canal_treatment", "Endodontics", "Dental_pulp"]),
        (["apexif", "apexogen", "immature"],
         ["Apexification", "Dental_pulp", "Endodontics", "Root_canal_treatment"]),
    ]
    DEFAULT_ARTICLES = ["Endodontics", "Root_canal_treatment", "Dental_pulp", "Apical_periodontitis"]

    matched_articles = DEFAULT_ARTICLES
    for keywords, articles in TOPIC_ARTICLES:
        if any(kw in topic_lower for kw in keywords):
            matched_articles = articles
            break

    educational = []
    for article in matched_articles:
        if len(educational) >= 2:
            break
        try:
            resp = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{article}",
                headers=HEADERS, timeout=6,
            )
            if resp.status_code != 200:
                continue
            data  = resp.json()
            thumb = data.get("thumbnail", {}).get("source", "")
            if not thumb:
                continue
            educational.append({
                "url":        thumb,
                "title":      data.get("title", article.replace("_", " ")),
                "label":      "Educational",
                "source":     "Wikipedia",
                "source_url": data.get("content_urls", {}).get("desktop", {}).get("page",
                              f"https://en.wikipedia.org/wiki/{article}"),
            })
            print(f"  Wikipedia image OK: {article}")
        except Exception as e:
            print(f"  Wikipedia image error ({article}): {e}")

    # ── Option 2: Wikipedia article images (clinical/procedural photos) ──
    # Fetch images embedded in Wikipedia articles — more reliable than Commons categories
    TOPIC_CLINICAL_ARTICLES = [
        (["root canal", "rct", "perform", "endodontic treatment"],
         ["Root_canal_treatment", "Endodontics"]),
        (["pulp cap", "vital pulp", "mta", "biodentine"],
         ["Pulp_capping", "Mineral_trioxide_aggregate"]),
        (["apical", "periapical", "abscess"],
         ["Apical_periodontitis", "Dental_abscess"]),
        (["crack", "fracture"],
         ["Cracked_tooth_syndrome", "Root_canal_treatment"]),
        (["retreatment", "failed"],
         ["Root_canal_treatment", "Apical_periodontitis"]),
        (["irrigat", "sodium hypochlorite"],
         ["Root_canal_treatment", "Sodium_hypochlorite"]),
        (["obturat", "gutta-percha"],
         ["Gutta-percha", "Root_canal_treatment"]),
        (["perforation"],
         ["Root_canal_treatment", "Endodontics"]),
    ]
    DEFAULT_CLINICAL_ARTICLES = ["Root_canal_treatment", "Apical_periodontitis"]

    matched_clinical = DEFAULT_CLINICAL_ARTICLES
    for keywords, articles in TOPIC_CLINICAL_ARTICLES:
        if any(kw in topic_lower for kw in keywords):
            matched_clinical = articles
            break

    clinical = []
    seen_titles = set()
    for article in matched_clinical:
        if len(clinical) >= 2:
            break
        try:
            # Step 1: get list of image file names used in this article
            resp = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action":  "query",
                    "titles":  article,
                    "prop":    "images",
                    "imlimit": 20,
                    "format":  "json",
                },
                headers=HEADERS, timeout=6,
            )
            pages      = resp.json().get("query", {}).get("pages", {})
            img_titles = []
            for page in pages.values():
                for img in page.get("images", []):
                    t = img.get("title", "")
                    tl = t.lower()
                    # Skip icons, logos, flags, audio, SVGs
                    if (t not in seen_titles and not tl.endswith(".svg")
                            and not tl.endswith(".ogg") and not tl.endswith(".ogv")
                            and "flag" not in tl and "logo" not in tl
                            and "icon" not in tl and "commons" not in tl
                            and "wikip" not in tl):
                        img_titles.append(t)

            if not img_titles:
                continue

            # Step 2: get thumbnail URLs for up to 5 candidate images
            resp2 = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action":    "query",
                    "titles":    "|".join(img_titles[:8]),
                    "prop":      "imageinfo",
                    "iiprop":    "url|thumburl|mime",
                    "iiurlwidth": 480,
                    "format":    "json",
                },
                headers=HEADERS, timeout=6,
            )
            img_pages = resp2.json().get("query", {}).get("pages", {})
            print(f"  Wikipedia article images for '{article}': {len(img_pages)} candidates")
            for pg in img_pages.values():
                if len(clinical) >= 2:
                    break
                file_title = pg.get("title", "")
                if file_title in seen_titles:
                    continue
                info_list = pg.get("imageinfo", [])
                if not info_list:
                    continue
                info  = info_list[0]
                mime  = info.get("mime", "")
                if not mime.startswith("image/") or mime == "image/svg+xml":
                    continue
                thumb = info.get("thumburl", "") or info.get("url", "")
                if not thumb:
                    continue
                seen_titles.add(file_title)
                label = file_title.replace("File:", "").rsplit(".", 1)[0]
                clinical.append({
                    "url":        thumb,
                    "title":      label,
                    "label":      "Clinical",
                    "source":     "Wikipedia",
                    "source_url": f"https://en.wikipedia.org/wiki/{article}",
                })
                print(f"  Wikipedia article image OK: {label}")
        except Exception as e:
            print(f"  Wikipedia article image error ({article}): {e}")

    images = (educational + clinical)[:limit]
    print(f"  Total images: {len(images)} ({len(educational)} educational, {len(clinical)} clinical)")
    return images


# ── CASE DIFFICULTY ASSESSMENT ───────────────────────────

_RADIOGRAPH_SYSTEM_PROMPT = """You are an endodontic case assessment assistant analyzing periapical radiographs.
This is for EDUCATIONAL and DECISION SUPPORT purposes only -- the clinician verifies all findings.

Analyze the radiograph and return ONLY a valid JSON object with this exact structure -- no extra text:

{
  "narrative": "3-5 sentence radiographic report describing everything visible: tooth identity, number of roots and canals, curvature, calcification level, crown/restoration type, periapical status, any retreatment material, and all complications. Write as a clinician would dictate findings. Be specific about what you see and what you cannot see due to image limitations.",
  "image_quality": {"adequate": true, "issues": []},
  "tooth": {"number": 19, "name": "Mandibular left first molar", "confidence": "high"},
  "canal_curvature": {"rating": "straight|mild|moderate|severe", "description": "...", "confidence": "high|medium|low"},
  "calcification": {"rating": "open|mild|moderate|severe", "description": "...", "confidence": "high|medium|low"},
  "root_anatomy": {"rating": "normal|extra_roots|dilacerated|short|long", "description": "...", "confidence": "high|medium|low"},
  "periapical": {"lesion": false, "size": "none|small|large", "confidence": "high|medium|low"},
  "crown": {"type": "intact|filling|full_coverage|post_crown", "access": "easy|moderate|difficult"},
  "retreatment": {
    "present": false,
    "material": "none|gp|carrier|paste|silver_points",
    "posts": false,
    "separated_instrument": false,
    "confidence": "high|medium|low"
  },
  "complications": {
    "resorption": {"present": false, "type": "none|apical|internal|cervical"},
    "open_apex": {"present": false, "description": "..."},
    "perforation": {"suspected": false, "location": "none|coronal|furcal|apical"},
    "fracture_suspected": false,
    "perio_involvement": {"suspected": false, "description": "..."}
  },
  "overall": {"estimated_difficulty": "minimal|moderate|high", "key_challenges": [], "limitations": []}
}

Curvature: straight <5deg, mild 5-15deg, moderate 15-30deg, severe >30deg or S-curve.
Calcification: open=clearly visible, mild=visible but narrowed, moderate=difficult to trace, severe=not visible.
Be conservative -- if uncertain, rate difficulty HIGHER. Note confidence for each finding.

UNIVERSAL NUMBERING SYSTEM — use this exact mapping for tooth.number → tooth.name:
Upper arch (patient's right → left):  1 Mx R 3rd molar | 2 Mx R 2nd molar | 3 Mx R 1st molar | 4 Mx R 2nd premolar | 5 Mx R 1st premolar | 6 Mx R canine | 7 Mx R lateral incisor | 8 Mx R central incisor | 9 Mx L central incisor | 10 Mx L lateral incisor | 11 Mx L canine | 12 Mx L 1st premolar | 13 Mx L 2nd premolar | 14 Mx L 1st molar | 15 Mx L 2nd molar | 16 Mx L 3rd molar
Lower arch (patient's left → right): 17 Mn L 3rd molar | 18 Mn L 2nd molar | 19 Mn L 1st molar | 20 Mn L 2nd premolar | 21 Mn L 1st premolar | 22 Mn L canine | 23 Mn L lateral incisor | 24 Mn L central incisor | 25 Mn R central incisor | 26 Mn R lateral incisor | 27 Mn R canine | 28 Mn R 1st premolar | 29 Mn R 2nd premolar | 30 Mn R 1st molar | 31 Mn R 2nd molar | 32 Mn R 3rd molar
(Mx = Maxillary, Mn = Mandibular, L = Left, R = Right)"""


def _strip_json_fence(raw: str) -> str:
    import re as _re
    raw = raw.strip()
    raw = _re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
    # Some models add a trailing prose comment; trim to the outermost {...}
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    return raw[start:end] if start >= 0 and end > start else raw


# Universal Numbering System lookup table
_UNS = {
     1: "Maxillary right third molar",    2: "Maxillary right second molar",
     3: "Maxillary right first molar",    4: "Maxillary right second premolar",
     5: "Maxillary right first premolar", 6: "Maxillary right canine",
     7: "Maxillary right lateral incisor",8: "Maxillary right central incisor",
     9: "Maxillary left central incisor", 10: "Maxillary left lateral incisor",
    11: "Maxillary left canine",          12: "Maxillary left first premolar",
    13: "Maxillary left second premolar", 14: "Maxillary left first molar",
    15: "Maxillary left second molar",    16: "Maxillary left third molar",
    17: "Mandibular left third molar",    18: "Mandibular left second molar",
    19: "Mandibular left first molar",    20: "Mandibular left second premolar",
    21: "Mandibular left first premolar", 22: "Mandibular left canine",
    23: "Mandibular left lateral incisor",24: "Mandibular left central incisor",
    25: "Mandibular right central incisor",26: "Mandibular right lateral incisor",
    27: "Mandibular right canine",        28: "Mandibular right first premolar",
    29: "Mandibular right second premolar",30: "Mandibular right first molar",
    31: "Mandibular right second molar",  32: "Mandibular right third molar",
}


def _apply_tooth_hint(raw: dict, tooth_hint: str) -> dict:
    """
    Override Gemini/GPT-4o tooth detection with the clinician-supplied number.
    Patches tooth.number, tooth.name, and all references inside the narrative.
    Saves the AI's original detection under raw['_ai_tooth'] for display.
    """
    import re as _re
    try:
        num = int(tooth_hint.strip().lstrip("#"))
    except (ValueError, TypeError):
        return raw  # non-numeric hint — leave untouched
    if not (1 <= num <= 32):
        return raw

    correct_name = _UNS.get(num, f"tooth #{num}")
    ai_tooth = raw.get("tooth") or {}

    # Preserve AI detection so the UI can show "AI detected: #N"
    raw["_ai_tooth"] = {
        "number": ai_tooth.get("number"),
        "name":   ai_tooth.get("name", ""),
    }

    # Override tooth identity
    raw.setdefault("tooth", {})
    raw["tooth"]["number"] = num
    raw["tooth"]["name"]   = correct_name

    # Patch narrative — replace AI's tooth number and name with correct ones
    narrative = raw.get("narrative", "")
    if narrative:
        ai_num  = ai_tooth.get("number")
        ai_name = ai_tooth.get("name", "")
        if ai_num:
            for pat in [
                r'tooth\s+#' + str(ai_num) + r'\b',
                r'tooth\s+number\s+' + str(ai_num) + r'\b',
                r'#' + str(ai_num) + r'\b',
                r'\bNumber\s+' + str(ai_num) + r'\b',
            ]:
                narrative = _re.sub(pat, f'tooth #{num}', narrative, flags=_re.IGNORECASE)
        if ai_name and ai_name != correct_name:
            narrative = narrative.replace(ai_name, correct_name)
        raw["narrative"] = narrative

    return raw


# Pricing per 1M tokens (USD), as of late 2025 / early 2026.
# Update if Google or OpenAI changes their rates.
_VISION_PRICING = {
    "gemini-2.5-pro": {"input": 1.25,  "output": 10.00},
    "gpt-4o":         {"input": 2.50,  "output": 10.00},
}


def _calc_vision_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    p = _VISION_PRICING.get(model)
    if not p: return 0.0
    return (in_tokens * p["input"] + out_tokens * p["output"]) / 1_000_000.0


def _build_xray_prompt(tooth_hint: str = "") -> str:
    base = "Analyze this periapical radiograph for endodontic case difficulty assessment. Return only the JSON object."
    if tooth_hint:
        return (
            f"The clinician has identified tooth #{tooth_hint} as the tooth of concern. "
            f"Use that number for tooth.number, look up the correct name from the UNS table in your instructions, "
            f"and write the narrative about tooth #{tooth_hint}. "
            f"Do not override the clinician's tooth identification with your own detection. "
            + base
        )
    return base


def _analyze_with_gemini(image_bytes: bytes, media_type: str, tooth_hint: str = "") -> dict:
    """Gemini 2.5 Pro Vision analysis. Attaches `_usage` for cost tracking."""
    import os, json as _json
    from google import genai
    from google.genai import types as _gtypes
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[
            _gtypes.Part.from_bytes(data=image_bytes, mime_type=media_type),
            _build_xray_prompt(tooth_hint),
        ],
        config=_gtypes.GenerateContentConfig(
            system_instruction=_RADIOGRAPH_SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.2,
            max_output_tokens=2000,
        ),
    )
    raw = (resp.text or "").strip()
    if not raw:
        raise RuntimeError("Gemini returned empty response")
    parsed = _json.loads(_strip_json_fence(raw))
    um = getattr(resp, "usage_metadata", None)
    in_t  = getattr(um, "prompt_token_count", 0) if um else 0
    out_t = getattr(um, "candidates_token_count", 0) if um else 0
    parsed["_usage"] = {"input_tokens": in_t, "output_tokens": out_t,
                        "cost_usd": _calc_vision_cost("gemini-2.5-pro", in_t, out_t)}
    return parsed


def _analyze_with_openai(image_bytes: bytes, media_type: str, tooth_hint: str = "") -> dict:
    """OpenAI GPT-4o Vision fallback."""
    import base64, json as _json, os
    from openai import OpenAI as _OpenAI
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    client = _OpenAI(api_key=api_key)
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{media_type};base64,{image_b64}"
    resp = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=2000,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _RADIOGRAPH_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                {"type": "text", "text": _build_xray_prompt(tooth_hint)},
            ]},
        ],
    )
    raw = resp.choices[0].message.content or ""
    parsed = _json.loads(_strip_json_fence(raw))
    u = resp.usage
    in_t  = getattr(u, "prompt_tokens", 0) if u else 0
    out_t = getattr(u, "completion_tokens", 0) if u else 0
    parsed["_usage"] = {"input_tokens": in_t, "output_tokens": out_t,
                        "cost_usd": _calc_vision_cost("gpt-4o", in_t, out_t)}
    return parsed


def analyze_radiograph(image_bytes: bytes, media_type: str,
                        tooth_hint: str = "", provider: str = "auto") -> dict:
    """
    Analyze a PA radiograph and return structured difficulty factors.
    provider: 'gemini' | 'openai' | 'auto' (Gemini first, GPT-4o fallback).
    tooth_hint: clinician tooth number — overrides AI detection in post-processing.
    """
    import os

    def _finish(result: dict, provider_name: str, fallback_reason=None) -> dict:
        usage = result.get("_usage", {})
        result["_meta"] = {
            "provider":       provider_name,
            "fallback_reason": fallback_reason,
            "cost_usd":       usage.get("cost_usd", 0.0),
            "input_tokens":   usage.get("input_tokens", 0),
            "output_tokens":  usage.get("output_tokens", 0),
        }
        print(f"  [radiograph] {provider_name} -- "
              f"${usage.get('cost_usd', 0):.4f} "
              f"({usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)} out)")
        if tooth_hint:
            result = _apply_tooth_hint(result, tooth_hint)
        return result

    # ── Explicit provider selection ───────────────────────
    if provider == "gemini":
        result = _analyze_with_gemini(image_bytes, media_type, tooth_hint)
        return _finish(result, "gemini-2.5-pro")

    if provider == "openai":
        result = _analyze_with_openai(image_bytes, media_type, tooth_hint)
        return _finish(result, "gpt-4o")

    # ── Auto: Gemini → GPT-4o fallback ───────────────────
    fallback_reason = None
    if os.getenv("GEMINI_API_KEY"):
        try:
            result = _analyze_with_gemini(image_bytes, media_type, tooth_hint)
            return _finish(result, "gemini-2.5-pro")
        except Exception as e:
            fallback_reason = f"Gemini error: {e}"
            print(f"  [radiograph] Gemini failed ({e}); falling back to OpenAI GPT-4o")
    else:
        fallback_reason = "GEMINI_API_KEY not set"
        print("  [radiograph] GEMINI_API_KEY not set; using OpenAI GPT-4o Vision")

    result = _analyze_with_openai(image_bytes, media_type, tooth_hint)
    return _finish(result, "gpt-4o", fallback_reason)


# Map analysis JSON to questionnaire pre-fill format
def _analysis_to_prefill(analysis: dict) -> dict:
    answers = {}
    flags = []

    tooth = analysis.get("tooth", {})
    if tooth.get("number"):
        answers["tooth_number"] = tooth["number"]
        if tooth.get("confidence") == "low":
            flags.append("Verify tooth identification")

    cc = analysis.get("canal_curvature", {})
    if cc.get("rating"):
        answers["canal_curvature"] = cc["rating"]
    if cc.get("confidence") == "low":
        flags.append("Verify curvature — low confidence on radiograph")

    calc = analysis.get("calcification", {})
    if calc.get("rating"):
        answers["calcification"] = calc["rating"]

    root = analysis.get("root_anatomy", {})
    if root.get("rating"):
        answers["root_anatomy"] = root["rating"]

    peri = analysis.get("periapical", {})
    if peri.get("lesion"):
        answers["periapical_status"] = "large_lesion" if peri.get("size") == "large" else "small_lesion"
    else:
        answers["periapical_status"] = "normal"

    retx = analysis.get("retreatment", {})
    if retx.get("present"):
        answers["is_retreatment"] = "yes"
        if retx.get("separated_instrument"):
            answers["retreatment_complexity"] = "separated"
            flags.append("Possible separated instrument detected — verify")
        elif retx.get("posts"):
            answers["retreatment_complexity"] = "posts"
        else:
            mat = retx.get("material", "gp")
            answers["retreatment_complexity"] = "carrier" if mat == "carrier" else "simple"
        if retx.get("confidence") == "low":
            flags.append("Retreatment status — verify on radiograph")
    else:
        answers["is_retreatment"] = "no"

    comp = analysis.get("complications", {})
    complications = []
    res = comp.get("resorption", {})
    if res.get("present"):
        complications.append("resorption")
        answers["resorption_type"] = res.get("type", "apical")
        flags.append(f"Resorption detected ({res.get('type','apical')}) — verify type and extent")
    oa = comp.get("open_apex", {})
    if oa.get("present"):
        complications.append("open_apex")
        flags.append("Open apex / immature tooth detected — apexification or MTA apical plug may be required")
    perf = comp.get("perforation", {})
    if perf.get("suspected"):
        complications.append("perforation")
        answers["perforation_location"] = perf.get("location", "furcal")
        flags.append("Possible perforation — verify clinically")
    if comp.get("fracture_suspected"):
        complications.append("cracked")
        flags.append("Possible vertical root fracture — consider CBCT")
    perio = comp.get("perio_involvement", {})
    if perio.get("suspected"):
        complications.append("perio")
        flags.append("Possible perio-endo involvement — probe depths and periodontal evaluation required")
    answers["complications"] = complications if complications else ["none"]

    overall = analysis.get("overall", {})
    return {
        "answers": answers,
        "estimated_difficulty": overall.get("estimated_difficulty", "moderate"),
        "key_challenges": overall.get("key_challenges", []),
        "limitations": overall.get("limitations", []),
        "flags": flags,
        "source": "ai_analysis"
    }


# ── Difficulty scoring (AAE framework) ───────────────────
DIFFICULTY_WEIGHTS = {
    "medical_history":        0.06,
    "anesthesia_history":     0.04,
    "patient_disposition":    0.04,
    "mouth_opening":          0.03,
    "gag_reflex":             0.03,
    "diagnosis_clarity":      0.08,
    "radiographic_difficulty":0.06,
    "tooth_position":         0.08,
    "isolation_difficulty":   0.06,
    "crown_morphology":       0.08,
    "canal_morphology":       0.15,   # highest — most predictive
    "root_morphology":        0.10,
    "resorption":             0.06,
    "trauma_history":         0.05,
    "previous_endo":          0.10,
    "perio_endo":             0.08,
}

FACTOR_LABELS = {
    "medical_history": "Complex medical history",
    "anesthesia_history": "Anesthesia challenges",
    "patient_disposition": "Patient management",
    "mouth_opening": "Limited opening",
    "gag_reflex": "Severe gag reflex",
    "diagnosis_clarity": "Diagnostic complexity",
    "radiographic_difficulty": "Radiographic difficulty",
    "tooth_position": "Difficult tooth position",
    "isolation_difficulty": "Isolation challenges",
    "crown_morphology": "Access / crown complexity",
    "canal_morphology": "Complex canal anatomy",
    "root_morphology": "Complex root anatomy",
    "resorption": "Resorption present",
    "trauma_history": "Trauma-related complexity",
    "previous_endo": "Retreatment complexity",
    "perio_endo": "Perio-endo involvement",
}


def calculate_case_difficulty(scores: dict) -> dict:
    """
    Calculate AAE-based overall difficulty from factor scores (1=minimal, 2=moderate, 3=high).
    AAE rule: ANY single HIGH factor = HIGH case overall.
    Returns score 0-100 plus high/moderate factor lists and recommendation.
    """
    weighted = sum(scores.get(k, 1) * w for k, w in DIFFICULTY_WEIGHTS.items())
    max_w = sum(3 * w for w in DIFFICULTY_WEIGHTS.values())
    min_w = sum(1 * w for w in DIFFICULTY_WEIGHTS.values())
    normalized = round((weighted - min_w) / (max_w - min_w) * 100, 1)

    high_factors    = [k for k, v in scores.items() if v == 3 and k in DIFFICULTY_WEIGHTS]
    moderate_factors = [k for k, v in scores.items() if v == 2 and k in DIFFICULTY_WEIGHTS]

    if high_factors:
        level = "HIGH"
    elif len(moderate_factors) >= 3 or normalized > 50:
        level = "MODERATE"
    else:
        level = "MINIMAL"

    return {
        "score":           normalized,
        "level":           level,
        "high_factors":    [FACTOR_LABELS[f] for f in high_factors if f in FACTOR_LABELS],
        "moderate_factors":[FACTOR_LABELS[f] for f in moderate_factors if f in FACTOR_LABELS],
    }


def match_case_to_profile(case_answers: dict, profile: dict) -> dict:
    """
    Compare case factors against the GP's comfort profile.
    Returns personalised treat/refer recommendation with reasons.
    """
    exceeds = []
    within  = []

    # ── Tooth type comfort ───────────────────────────────
    tooth_type = _get_tooth_type(case_answers.get("tooth_number", 0))
    comfort = profile.get("tooth_comfort", {}).get(tooth_type, 2)
    if comfort <= 1:
        exceeds.append(f"{_tooth_type_label(tooth_type)} — you indicated you prefer to refer these")
    else:
        within.append("Tooth type")

    # ── Curvature threshold ──────────────────────────────
    curv_levels = ["straight", "mild", "moderate", "severe"]
    case_curv  = case_answers.get("canal_curvature", "mild")
    prof_curv  = profile.get("max_curvature", "mild")
    if _level_index(curv_levels, case_curv) > _level_index(curv_levels, prof_curv):
        exceeds.append(f"Canal curvature ({case_curv}) exceeds your limit ({prof_curv})")
    else:
        within.append("Canal curvature")

    # ── Calcification threshold ──────────────────────────
    calc_levels = ["open", "mild", "moderate", "severe"]
    case_calc  = case_answers.get("calcification", "open")
    prof_calc  = profile.get("max_calcification", "mild")
    if _level_index(calc_levels, case_calc) > _level_index(calc_levels, prof_calc):
        exceeds.append(f"Calcification ({case_calc}) exceeds your limit ({prof_calc})")
    else:
        within.append("Calcification")

    # ── Retreatment threshold ────────────────────────────
    if case_answers.get("is_retreatment") == "yes":
        retx_levels = ["none", "simple", "carrier", "posts", "separated"]
        case_retx = case_answers.get("retreatment_complexity", "simple")
        prof_retx = profile.get("retreatment_level", "none")
        if _level_index(retx_levels, case_retx) > _level_index(retx_levels, prof_retx):
            exceeds.append(f"Retreatment complexity ({case_retx}) exceeds your limit ({prof_retx})")
        else:
            within.append("Retreatment complexity")

    # ── Complication thresholds ──────────────────────────
    complications = case_answers.get("complications", ["none"])

    if "resorption" in complications:
        res_levels = ["none", "apical", "internal", "cervical"]
        case_res = case_answers.get("resorption_type", "apical")
        prof_res = profile.get("resorption_level", "none")
        if _level_index(res_levels, case_res) > _level_index(res_levels, prof_res):
            exceeds.append(f"Resorption ({case_res}) — you indicated you refer these")
        else:
            within.append("Resorption type")

    if "open_apex" in complications and not profile.get("open_apex_comfort", False):
        exceeds.append("Open apex / immature tooth — you indicated you refer these")

    if "perforation" in complications:
        perf_levels = ["none", "coronal", "furcal", "lateral", "apical"]
        case_perf = case_answers.get("perforation_location", "furcal")
        prof_perf = profile.get("perforation_level", "none")
        if _level_index(perf_levels, case_perf) > _level_index(perf_levels, prof_perf):
            exceeds.append(f"Perforation ({case_perf}) — you indicated you refer these")
        else:
            within.append("Perforation management")

    if "trauma" in complications:
        trauma_levels = ["none", "uncomplicated_fracture", "complicated_fracture", "luxation", "avulsion"]
        case_trauma = case_answers.get("trauma_type", "uncomplicated_fracture")
        prof_trauma = profile.get("trauma_level", "none")
        if _level_index(trauma_levels, case_trauma) > _level_index(trauma_levels, prof_trauma):
            exceeds.append(f"Trauma type ({case_trauma.replace('_',' ')}) — beyond your indicated comfort")
        else:
            within.append("Trauma management")

    # ── Patient factor triggers ──────────────────────────
    patient_factors = case_answers.get("patient_factors", ["none"])
    prof_triggers   = set(profile.get("refer_triggers", []))
    for factor in patient_factors:
        if factor in prof_triggers:
            exceeds.append(f"{_patient_factor_label(factor)} — you indicated this triggers referral")

    # ── Equipment warnings ───────────────────────────────
    equipment_warnings = []
    if case_answers.get("calcification") in ["moderate", "severe"] and not profile.get("has_microscope", False):
        equipment_warnings.append("Microscope recommended for calcified canals — not listed in your equipment")
    if case_answers.get("is_retreatment") == "yes" and not profile.get("has_ultrasonic", False):
        equipment_warnings.append("Ultrasonic tips helpful for retreatment — not listed in your equipment")

    # ── Final verdict ────────────────────────────────────
    if exceeds:
        recommendation = "REFER"
        summary = f"This case exceeds your comfort profile in {len(exceeds)} area(s)"
    elif equipment_warnings:
        recommendation = "CONSIDER_REFERRING"
        summary = "Within your comfort zone, but equipment limitations may affect outcomes"
    else:
        recommendation = "TREAT"
        summary = "This case is within your stated comfort profile"

    return {
        "recommendation":   recommendation,
        "summary":          summary,
        "exceeds_comfort":  exceeds,
        "within_comfort":   within,
        "equipment_warnings": equipment_warnings,
    }


def _get_tooth_type(tooth_num: int) -> str:
    if tooth_num <= 0:
        return "max_anterior"
    if tooth_num in [1, 16]:
        return "max_2nd_molar"
    if tooth_num in [2, 15]:
        return "max_2nd_molar"
    if tooth_num in [3, 14]:
        return "max_molar"
    if tooth_num in [4, 5, 12, 13]:
        return "max_premolar"
    if tooth_num in [6, 7, 8, 9, 10, 11]:
        return "max_anterior"
    if tooth_num in [17, 32]:
        return "mand_2nd_molar"
    if tooth_num in [18, 31]:
        return "mand_2nd_molar"
    if tooth_num in [19, 30]:
        return "mand_molar"
    if tooth_num in [20, 21, 28, 29]:
        return "mand_premolar"
    return "mand_anterior"


def _tooth_type_label(t: str) -> str:
    return {
        "max_anterior": "Maxillary anteriors",
        "max_premolar": "Maxillary premolars",
        "max_molar":    "Maxillary molars",
        "max_2nd_molar":"Maxillary 2nd/3rd molars",
        "mand_anterior":"Mandibular anteriors",
        "mand_premolar":"Mandibular premolars",
        "mand_molar":   "Mandibular molars",
        "mand_2nd_molar":"Mandibular 2nd/3rd molars",
    }.get(t, t)


def _patient_factor_label(f: str) -> str:
    return {
        "medical_complex":  "Complex medical history (ASA III+)",
        "bisphosphonates":  "Bisphosphonate therapy",
        "anticoagulation":  "Anticoagulation requiring management",
        "hot_tooth":        "Hot tooth / difficult to anaesthetize",
        "limited_opening":  "Limited opening (<30 mm)",
        "gag_reflex":       "Severe gag reflex",
        "anxiety":          "Extreme dental anxiety",
    }.get(f, f)


def _level_index(levels: list, value: str) -> int:
    try:
        return levels.index(value)
    except ValueError:
        return 0


def generate_referral_letter(case_info: dict, profile: dict, reasons: list) -> str:
    """Generate a professional endodontic referral letter using Claude."""
    client = anthropic.Anthropic(api_key=_get_api_key())

    tooth_num   = case_info.get("tooth_number", "?")
    tooth_name  = case_info.get("tooth_name", f"tooth #{tooth_num}")
    complaint   = case_info.get("chief_complaint", "")
    pulpal_dx   = case_info.get("pulpal_diagnosis", "")
    periap_dx   = case_info.get("periapical_diagnosis", "")
    aae_score   = case_info.get("aae_score")
    aae_level   = case_info.get("aae_level", "")
    dr_name     = profile.get("dr_name", "")
    practice    = profile.get("practice_name", "")

    # Build diagnosis block
    diag_lines = []
    if pulpal_dx:
        diag_lines.append(f"Pulpal diagnosis: {pulpal_dx}")
    if periap_dx:
        diag_lines.append(f"Periapical diagnosis: {periap_dx}")
    diag_block = "\n".join(diag_lines) if diag_lines else "Endodontic pathology (diagnosis pending further evaluation)"

    # Build reasons block — numbered list
    if reasons:
        reasons_block = "\n".join(f"{i+1}. {r}" for i, r in enumerate(reasons))
    else:
        reasons_block = "1. Complex case beyond referring provider's comfort level"

    # AAE difficulty note
    difficulty_note = ""
    if aae_score is not None:
        difficulty_note = f"AAE Difficulty Score: {aae_score}/100 ({aae_level})"

    prompt = f"""Write a professional endodontic referral letter using the clinical details below.

REFERRING PROVIDER: {dr_name or 'Dr. [Name]'}, {practice or '[Practice Name]'}
TOOTH: #{tooth_num} ({tooth_name})
CHIEF COMPLAINT: {complaint or 'Endodontic pathology requiring specialist management'}

DIAGNOSIS:
{diag_block}
{('\\n' + difficulty_note) if difficulty_note else ''}

REASONS FOR REFERRAL:
{reasons_block}

Instructions:
- 200–280 words, formal but warm tone
- Open with patient presentation and diagnosis (pulpal and periapical by name)
- List every referral reason clearly — do not summarise or omit any
- State you are requesting specialist evaluation and definitive endodontic management
- Close with: "I appreciate your expertise in managing this case."
- Use [Patient Name] and [Patient DOB] as placeholders for patient-specific fields
- Sign off as "{dr_name or 'Dr. [Name]'}"

Return only the letter text, no extra commentary."""

    # TIER 2 (flag-gated) — Sonnet candidate; formatted clinical letter from
    # structured input (case + reasons). Pattern-following, light reasoning.
    resp, _cost = tier2_invoke(
        "generate_referral_letter",
        mode="assessment",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


# ── SAVE ANSWERS ─────────────────────────────────────────
def save_answer(question, answer, evidence):
    if not os.path.exists("answers"):
        os.makedirs("answers")

    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename     = f"answers/answer_{timestamp}.txt"
    total_papers = sum(len(v["ids"]) for k, v in evidence.items()
                       if k != "_summary" and "ids" in v)
    summary      = evidence.get("_summary", {})

    with open(filename, "w", encoding="utf-8") as f:
        f.write("ENDO AI — Clinical Answer\n")
        f.write("=" * 60 + "\n")
        f.write(f"Date:             {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Question:         {question}\n")
        f.write(f"Papers Retrieved: {total_papers}\n")
        if summary:
            f.write(f"Avg Score:        {summary.get('avg_score', 0)}/100\n")
        f.write("=" * 60 + "\n\n")
        f.write(answer)
        f.write("\n\n" + "=" * 60 + "\n")

    print(f"  Answer saved to: {filename}")

# ── MAIN ─────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  ENDO AI -- Evidence-Based Clinical Assistant")
    print("  Powered by PubMed + Cochrane + Claude")
    print("=" * 60)
    print("\nType your clinical question and press Enter.")
    print("Type 'quit' to exit.\n")

    while True:
        QUESTION = input("Your Question: ").strip()

        if QUESTION.lower() in ["quit", "exit", "q"]:
            print("\nGoodbye!")
            break

        if not QUESTION:
            print("Please enter a question.\n")
            continue

        evidence = build_evidence_base(QUESTION)
        answer   = ask_clinical_question(QUESTION, evidence)

        print(answer)
        print("=" * 60)

        save_answer(QUESTION, answer, evidence)

        print("\nReady for your next question.\n")