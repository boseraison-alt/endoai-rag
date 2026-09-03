
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

# ── NCBI RATE LIMITER ────────────────────────────────────
# NCBI allows 3 requests/second without an API key and 10 with one. There was
# no limiter at all: ten call sites fired as fast as the code reached them,
# which was survivable only because everything ran sequentially. B2 parallelises
# the tier fetches, so a shared limiter is the prerequisite — without it,
# parallelism turns a working pipeline into a 429 generator.
#
# Deliberately set one below each documented ceiling. The published limit is
# enforced per-second server-side with its own clock; running exactly at it
# means a burst that straddles a second boundary gets throttled, and NCBI
# answers a violation with a 429 that costs far more than the request saved.
NCBI_RATE_WITH_KEY    = 9.0
NCBI_RATE_WITHOUT_KEY = 3.0

import threading as _ncbi_thread   # this block sits above the main
import time as _ncbi_time          # threading/time imports below
_ncbi_rate_lock = _ncbi_thread.Lock()
_ncbi_last_call = [0.0]


def _ncbi_rate_limit() -> None:
    """Block until the next NCBI request is allowed. Thread-safe.

    Serialises only the SPACING decision, not the request: the lock is released
    before the caller performs its HTTP call, so N threads still overlap their
    network waits while their departures stay correctly spaced.
    """
    rate = (NCBI_RATE_WITH_KEY if (os.getenv("NCBI_API_KEY") or "").strip()
            else NCBI_RATE_WITHOUT_KEY)
    min_gap = 1.0 / rate
    with _ncbi_rate_lock:
        wait = _ncbi_last_call[0] + min_gap - _ncbi_time.perf_counter()
        if wait > 0:
            _ncbi_time.sleep(wait)
        _ncbi_last_call[0] = _ncbi_time.perf_counter()


def ncbi_get(url: str, **kwargs):
    """requests.get for NCBI endpoints, rate-limited. Use this, never
    requests.get directly, or the limiter can be bypassed silently."""
    _ncbi_rate_limit()
    return requests.get(url, **kwargs)


def _warn_if_no_ncbi_key() -> None:
    """One line at startup. An absent key is not an error — it is a 3x
    slowdown, and the only way to know is to be told."""
    if not (os.getenv("NCBI_API_KEY") or "").strip():
        print("  [ncbi] No NCBI_API_KEY set — limited to "
              f"{NCBI_RATE_WITHOUT_KEY:.0f} req/sec instead of "
              f"{NCBI_RATE_WITH_KEY:.0f}. Register a free key at "
              "https://www.ncbi.nlm.nih.gov/account/settings/ and add "
              "NCBI_API_KEY=... to .env")


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

# The labelled blocks PubMed's text renderer emits alongside the abstract.
# "Longest paragraph" is a proxy for "the abstract", and these are the things
# that can be longer than one:
#
#   * `Author information:` — one paragraph holding every affiliation.
#     PMID 39743567 (a consensus with ~30 institutional addresses) stored
#     6,304 characters of university departments in place of its 707-character
#     abstract, and that text reached synthesis as the paper's content and was
#     written into `abstract_cache`, which is what the citation-support check
#     reads.
#   * `Publisher:` — a foreign-language abstract. PMID 41337506's Portuguese
#     version is longer than its English one.
#
# 175 of 9,985 `abstract_cache` rows and 4 of 2,348 library rows were in one of
# those two states. Measured against efetch XML on 198 library PMIDs, 95 of
# them structured, the collapse loses NOTHING to a structured abstract —
# PubMed prints BACKGROUND/METHODS/RESULTS/CONCLUSIONS as one blank-line-free
# block — so this is the whole of the defect, and it is over-capture rather
# than the loss that was on record.
#
# ANCHORED at the start of the paragraph. A paper about authorship, or one
# whose abstract mentions an erratum, keeps its abstract.
_NON_ABSTRACT_BLOCK_RE = re.compile(
    r"^\s*(?:Author information|Publisher|Collaborators|Comment (?:in|on)|"
    r"Erratum (?:in|for)|Update (?:in|of)|Republished (?:in|from)|"
    r"Expression of [Cc]oncern (?:in|for)|Retraction (?:in|of)|"
    r"Conflict of interest statement|Grant support|Copyright|"
    r"DOI|PMID|PMCID)\s*:",
    re.IGNORECASE)


def _select_abstract_paragraph(paragraphs: list, min_chars: int = 200) -> str:
    """Pick the paper's abstract out of a PubMed text entry's paragraphs.

    The longest paragraph of at least `min_chars`, EXCLUDING the labelled
    blocks above. Shared by every site that parses `retmode=text`, because
    four sites each kept their own copy of this heuristic and they had already
    drifted — `_parse_efetch_batch` returned "" when no paragraph cleared the
    floor while `ingest_classics` fell back to the longest of any length.

    If every long paragraph is an excluded block, the longest of them is
    returned anyway. A record whose only abstract is publisher-supplied still
    has an abstract, and blanking the field would be a second data loss on top
    of the first — worse, an empty abstract silently skips that paper in
    `verify_citation_support`, so the guardrail would go quiet rather than
    complain.
    """
    paras = [p for p in (paragraphs or []) if p and len(p) >= min_chars]
    if not paras:
        return ""
    kept = [p for p in paras if not _NON_ABSTRACT_BLOCK_RE.match(p)]
    return max(kept or paras, key=len)


def _parse_efetch_batch(raw_text: str) -> dict:
    """Split an efetch batch text dump into {pmid: {title, abstract}} chunks.

    The format from efetch (rettype=abstract, retmode=text) groups one paper
    per "1. ", "2. ", ... entry. We split on those boundaries, locate the
    `PMID: NNNNNN` line, then extract title + abstract from the entry's
    paragraph structure (the second paragraph is the title; the abstract comes
    from `_select_abstract_paragraph`, which knows which long paragraphs are
    not abstracts).
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

        out[pmid] = {"title": title,
                     "abstract": _select_abstract_paragraph(paragraphs)}
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

# ── Streaming ─────────────────────────────────────────────
# Publish cadence for partial answers. The browser polls /status, and one job
# write per token would both hammer that endpoint and take the jobs lock a few
# thousand times per answer. Publish when EITHER threshold trips, whichever
# comes first — the delta count paces a fast stream, the interval guarantees
# the first words appear quickly even when the model is slow to start.
STREAM_PARTIAL_MIN_DELTAS   = 40     # ~40 text deltas
STREAM_PARTIAL_MIN_INTERVAL = 0.5    # ...or 500 ms


class StreamAborted(RuntimeError):
    """abort_cb() went true mid-stream.

    Subclasses RuntimeError and carries 'Cancelled' in its message so the
    existing `except RuntimeError: if "Cancelled" in str(e)` handlers keep
    working unchanged.
    """
    def __init__(self, message: str = "Cancelled by user"):
        super().__init__(message)


def _stream_once(client, *, on_partial=None, abort_cb=None, **kwargs):
    """One streamed attempt. Reached only via `_invoke_claude(stream=True)`.

    Returns the same final `Message` object `client.messages.create()` would
    have returned, so every downstream consumer (cost log, validators, cache,
    audit) is unchanged and always sees the COMPLETE text.

    `on_partial(text_so_far)` receives the accumulated RAW model text at the
    cadence above — never per token, and never anything a guardrail has
    touched. Guardrail output is appended by the caller after this function
    has returned, which is what keeps a half-written citation from ever
    reaching `validate_evidence_mapping` / `verify_citation_support`.

    `abort_cb()` is polled once per stream event; a true result raises
    StreamAborted, which closes the HTTP stream via the context manager.
    """
    chunks = []
    since_publish = 0
    with client.messages.stream(**kwargs) as stream:
        last_publish = _time.monotonic()
        for event in stream:
            if abort_cb is not None and abort_cb():
                raise StreamAborted()
            if getattr(event, "type", None) != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) != "text_delta":
                continue
            text = getattr(delta, "text", "") or ""
            if not text:
                continue
            chunks.append(text)
            since_publish += 1
            now = _time.monotonic()
            if on_partial is not None and (
                since_publish >= STREAM_PARTIAL_MIN_DELTAS
                or (now - last_publish) >= STREAM_PARTIAL_MIN_INTERVAL
            ):
                on_partial("".join(chunks))
                since_publish = 0
                last_publish  = now
        message = stream.get_final_message()

    # Flush the tail so the displayed partial matches what the model actually
    # said before the guardrails start running.
    if on_partial is not None and chunks and since_publish:
        on_partial("".join(chunks))
    return message


# Mid-stream transport failures, which the SDK does NOT map to
# APIConnectionError. Guarded because httpx is anthropic's dependency rather
# than ours declared directly; if it is ever absent the retry simply loses this
# clause instead of failing to import.
try:
    import httpx as _httpx
    _TRANSPORT_ERRORS = (_httpx.TransportError,)
except Exception:            # pragma: no cover — httpx ships with anthropic
    _TRANSPORT_ERRORS = ()


def _invoke_claude(client, *, function_name: str = "claude", stream: bool = False,
                   on_partial=None, abort_cb=None, **kwargs):
    """Wrap client.messages.create with retry-on-transient-error.

    Pass through kwargs identically to client.messages.create. On 529 / 503 /
    504 / 429 / connection error, sleep with exponential backoff + jitter and
    retry. Re-raises the original error after all attempts exhausted.

    THIS IS THE ONLY SEAM. Every Claude call in this module goes through this
    one function, streaming included, so a test that stubs `_invoke_claude`
    stubs the whole module offline. Do not call `client.messages.create` or
    `client.messages.stream` anywhere else — `tests/test_streaming.py`
    ::test_no_network_escapes_when_the_seam_is_stubbed pins that.

    `stream=True` switches to `client.messages.stream()`. It returns the same
    final Message object either way, so callers and everything downstream of
    them are identical between the two modes. See `_stream_once` for the
    partial-publishing contract.
    """
    last_exc = None
    for attempt in range(len(_RETRY_BACKOFF_SEC) + 1):
        try:
            if stream:
                return _stream_once(client, on_partial=on_partial,
                                    abort_cb=abort_cb, **kwargs)
            return client.messages.create(**kwargs)
        except StreamAborted:
            # A user cancellation is not a transient error.
            raise
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
        except _TRANSPORT_ERRORS as e:
            # A MID-STREAM transport failure. The SDK maps connection problems
            # to APIConnectionError only while it is making the REQUEST; once
            # the response is open and being iterated, a dropped connection
            # surfaces as the raw httpx exception and walks straight past the
            # clause above.
            #
            # This gap was invisible until the stitcher started streaming,
            # because streaming is what makes a call long enough to be
            # interrupted: the laser regeneration died on
            # `httpx.ReadError: [WinError 10054] An existing connection was
            # forcibly closed by the remote host` after paying for all four
            # modules. Every one of them had to be regenerated.
            #
            # A retry restarts the whole generation, which costs. Losing it
            # costs more. NOTE that on the paths with an `on_partial`, a retry
            # replays from the beginning, so a viewer can see the text get
            # shorter once — cosmetic, and only on a transport failure.
            last_exc = e
            reason = f"stream transport error ({type(e).__name__})"

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

    # Streaming is meaningless when two models run concurrently into one
    # callback — the partials would interleave into nonsense. The comparison
    # mode is a flag-gated debug harness, so it drops the streaming kwargs
    # rather than the caller having to know which mode it is in.
    for _k in ("stream", "on_partial"):
        create_kwargs.pop(_k, None)

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


# ── WHO SPENT THIS: product, test, or script ─────────────
# `cost_log.jsonl` currently holds $5.70 of imaginary spend — stubbed TTS from
# a test suite that used to write into the product's own record, and which
# `/admin/costs` still counts. Those rows are staying: an append-only audit log
# is not rewritten after the fact, and rewriting it is how you lose the ability
# to tell what the log said at the time. What was missing was the field that
# lets a reader FILTER instead.
#
# Resolved per write, not cached, and not passed in by the caller. Passing it
# in means every call site can forget it, and the call sites that would forget
# are exactly the ones inside a test. Detection asks what the process IS:
#
#   COST_LOG_SOURCE env var   — explicit override, for a script that knows
#                               better (a re-warm is arguably product spend).
#   pytest in sys.modules     — a test. This is the case that actually
#                               happened, and it must not depend on anyone
#                               remembering to set anything.
#   argv[0] under scripts/ or eval/ — a script or a measurement run.
#   otherwise                 — product.
#
# Rows written before this field existed have no `source` and READ as product,
# which is what they mostly were; the $5.70 of stubbed TTS is the documented
# exception (OVERNIGHT_REPORT_2.md §7).
COST_SOURCES = ("product", "test", "script")


def cost_log_source() -> str:
    """Which kind of process is spending this. See the note above."""
    env = (os.getenv("COST_LOG_SOURCE") or "").strip().lower()
    if env in COST_SOURCES:
        return env
    if "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST"):
        return "test"
    # Split into path COMPONENTS rather than substring-matching "/scripts/".
    # `python scripts/capture_attempt1.py` gives argv[0] = "scripts/..." with
    # no leading slash, so the substring test missed every script invoked the
    # ordinary way — and the suite could not catch it, because under pytest the
    # branch above returns first and the argv branch is never reached. Found by
    # reading the rows the first script run actually wrote: they said
    # `product`.
    entry = ((sys.argv[0] if sys.argv else "") or "").replace("\\", "/").lower()
    parts = [p for p in entry.split("/") if p]
    if parts and ("scripts" in parts[:-1] or "eval" in parts[:-1]
                  or parts[-1] == "run_eval.py"):
        return "script"
    return "product"


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
        "source":        cost_log_source(),
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

# ── TTS COST LOGGING (PRESENTATION_WORKLIST §4.5) ─────────
# OpenAI speech models are billed per CHARACTER of input, not per token, so
# they cannot reuse log_llm_call's usage object. Rates confirmed against the
# OpenAI pricing page (developers.openai.com/api/docs/pricing), USD per 1M
# characters of synthesised input.
TTS_PRICING = {
    "tts-1":    15.00,
    "tts-1-hd": 30.00,
}

# Whisper transcription, USD per minute of audio. Used by the narration
# verification path (§4.4), not by the production export pipeline.
TRANSCRIPTION_PRICING = {
    "whisper-1": 0.006,
}


def log_tts_call(function_name: str, model: str, characters: int,
                 mode: str = "export", request_id: str = None,
                 duration_seconds: float = None, voice: str = None) -> float:
    """Log a text-to-speech call to cost_log.jsonl and return its USD cost.

    Written into the same append-only log as log_llm_call so /admin/costs
    aggregates narration alongside Claude spend. `input_tokens`/`output_tokens`
    are recorded as 0 — the billable unit is `characters`, which is carried as
    an extra field the aggregator ignores.

    Unknown models are billed at the tts-1-hd rate: over-reporting cost is the
    safe direction for a spend log.
    """
    chars = max(0, int(characters or 0))
    rate  = TTS_PRICING.get(model, TTS_PRICING["tts-1-hd"])
    cost  = chars / 1_000_000.0 * rate

    record = {
        "ts":            datetime.now().isoformat(),
        "function":      function_name,
        "model":         model,
        "mode":          mode,
        "input_tokens":  0,
        "output_tokens": 0,
        "cost_usd":      round(cost, 6),
        "source":        cost_log_source(),
        "kind":          "tts",
        "characters":    chars,
        "rate_usd_per_1m_chars": rate,
    }
    if voice:
        record["voice"] = voice
    if duration_seconds is not None:
        record["duration_seconds"] = round(float(duration_seconds), 2)
        if duration_seconds > 0:
            record["cost_usd_per_minute"] = round(cost / (duration_seconds / 60.0), 6)
    if request_id:
        record["request_id"] = request_id

    try:
        with _COST_LOG_LOCK:
            with open(_COST_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
    except Exception as e:
        # Never let logging break a real export
        print(f"  [cost_log] TTS write failed: {e}")

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


# ── REVIEW-MODE CONVERSATION MEMORY ───────────────────────
# "What about in immature teeth?" is unanswerable on its own: the noun it
# modifies lives in the previous exchange. Four call sites need that noun — the
# clarify gate, the intent router, search-term generation and synthesis — so the
# thread is compacted ONCE, here, and the same block is prepended to each prompt.
#
# What travels is deliberately narrow: the previous QUESTION, its CLINICAL
# RECOMMENDATION only, and the PMIDs it cited. Carrying the full answer would
# cost several thousand tokens per exchange on four separate calls, and — the
# real reason — it would let a model answer the new question out of old prose
# instead of new retrieval. The label states that in the model's reading order:
# context informs the query, it never substitutes for evidence.
CONTEXT_BLOCK_LABEL = ("Prior exchange, for context; re-verify everything "
                       "against retrieved evidence.")

# Older exchanges drop. Three is the depth a clinician's follow-up chain
# actually reaches back to; past that the block costs more on every one of the
# four calls than the recall is worth.
MAX_CONTEXT_EXCHANGES = 3

# The recommendation is 2-4 sentences by construction (the synthesis prompt
# mandates it). This is the guard for a model that overruns, not the norm.
CONTEXT_RECOMMENDATION_CHARS = 700
CONTEXT_PMIDS_PER_EXCHANGE   = 8


def extract_clinical_recommendation(answer: str,
                                    max_chars: int = CONTEXT_RECOMMENDATION_CHARS) -> str:
    """Pull the CLINICAL RECOMMENDATION section out of a finished answer.

    Inline `[[PMID:N]]` markers are STRIPPED. The PMIDs travel separately as a
    plain list, because a marker sitting in prose the model is reading is an
    invitation to copy it into the next answer — where it would be a citation to
    a paper that this question's retrieval never produced, i.e. a fabrication as
    far as validate_evidence_mapping is concerned.
    """
    if not answer:
        return ""
    for title, body in _split_sections(answer):
        t = re.sub(r"^[*_\s#]+", "", (title or "").strip().lower())
        if not t.startswith("clinical recommendation"):
            continue
        text = _PMID_RE.sub("", body or "")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s*\n\s*", " ", text).strip()
        if len(text) > max_chars:
            cut = text[:max_chars]
            stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            text = (cut[:stop + 1] if stop > max_chars // 2 else cut).strip() + " […]"
        return text
    return ""


def build_context_block(exchanges: list,
                        max_exchanges: int = MAX_CONTEXT_EXCHANGES) -> str:
    """Compact the last `max_exchanges` exchanges into one prompt-ready block.

    `exchanges` is oldest-first; only the tail survives. Returns "" when there
    is nothing usable, and "" must mean "no context" everywhere downstream —
    the cache fingerprint, the UI's continues-from line and the prompts all key
    off emptiness rather than off a separate flag that could disagree with it.
    """
    usable = []
    for ex in (exchanges or []):
        q = (ex.get("question") or "").strip()
        if q:
            usable.append(ex)
    usable = usable[-max(1, int(max_exchanges)):] if usable else []
    if not usable:
        return ""

    lines = [CONTEXT_BLOCK_LABEL]
    for i, ex in enumerate(usable, 1):
        lines.append(f"{i}. Earlier question: {(ex.get('question') or '').strip()}")
        rec = (ex.get("recommendation") or "").strip()
        if rec:
            lines.append(f"   Its clinical recommendation was: {rec}")
        pmids = [str(p).strip() for p in (ex.get("pmids") or []) if str(p).strip()]
        if pmids:
            lines.append("   Papers it cited: "
                         + ", ".join("PMID " + p
                                     for p in pmids[:CONTEXT_PMIDS_PER_EXCHANGE]))
    return "\n".join(lines)


def case_prior_pmids(messages: list,
                     max_turns: int = MAX_CONTEXT_EXCHANGES) -> list:
    """Every PMID the earlier ASSISTANT turns of a case conversation cited.

    The case equivalent of `context_prior_pmids`, and it exists for the same
    reason (`case-v3` Item E): a follow-up rebuilt its evidence base from
    scratch, so the papers the clinician had just been reading about were
    re-found or not depending on how the combined query embedded. "Is there
    anything a dentist can do to prevent it?" is a different query from the
    original case, and the continuity between the two turns lived only in the
    prose.

    These SEED retrieval; they never bypass it. They are handed to
    `build_evidence_base_with_progress` as `prior_pmids`, which adds them as
    CANDIDATES after the routing gate has already decided — that ordering is
    the safety property, and it is asserted in
    `tests/test_review_context.py::TestSeedsDoNotDecideTheRoute`. Every gate
    then applies to them unchanged: the similarity floor recomputed against
    THIS turn's question, tier banding, and the retracted / withdrawn /
    superseded exclusions in `rag.search_by_pmids`.

    Newest turn first, de-duplicated, and only the assistant's turns — a PMID
    the CLINICIAN typed is not something this system retrieved.
    """
    out, seen = [], set()
    assistant = [m for m in (messages or [])
                 if (m or {}).get("role") == "assistant"]
    for m in reversed(assistant[-max(1, int(max_turns)):]):
        for p in _extract_cited_pmids(m.get("content") or ""):
            p = str(p).strip()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def context_prior_pmids(exchanges: list,
                        max_exchanges: int = MAX_CONTEXT_EXCHANGES) -> list:
    """Every PMID cited across the carried exchanges, newest exchange first,
    de-duplicated. These SEED retrieval; they never bypass it."""
    out, seen = [], set()
    tail = (exchanges or [])[-max(1, int(max_exchanges)):]
    for ex in reversed(tail):
        for p in (ex.get("pmids") or []):
            p = str(p).strip()
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _with_context(context_block: str, prompt: str, note: str = "") -> str:
    """Prepend the context block (and an optional per-call-site instruction) to
    a prompt. A blank block leaves the prompt byte-identical to the
    context-free one — that identity is what the offline tests assert."""
    block = (context_block or "").strip()
    if not block:
        return prompt
    head = block + (("\n" + note.strip()) if note and note.strip() else "")
    return f"{head}\n\n{prompt}"


# ── CLINICAL CLARIFYING QUESTIONS ─────────────────────────
# ── CASE DISCUSSION OPENING ──────────────────────────────
# The scaffold the UI shows before the clinician types. It is deliberately a
# single open invitation rather than a form: a case is a narrative, and asking
# for it field-by-field produces stilted fragments that retrieve badly. The
# parenthetical is a reminder of what usually matters, not a checklist to
# complete — a clinician who writes three sentences still gets an answer.
CASE_OPENING_SCAFFOLD = (
    "Describe the case in your own words — patient age and relevant medical "
    "history, the tooth and what you see clinically, imaging findings, symptoms "
    "and their history, and anything already tried."
)

# ── What KIND of case question is this? ──────────────────
#
# "What could the cause be?" and "what should I do?" are different questions
# and were being answered by the same pipeline. The measurement that made this
# an item rather than an opinion, from `case-v2` Item 1: on a 20-year-old with
# a necrotic, unrestored, caries-free tooth, the query generators put trauma in
# 8 runs of 8 and dens invaginatus in 2 — the palatogingival groove in none —
# so WHICH candidate causes got any literature at all was a coin flip. And the
# answer had nowhere to put a differential regardless, because the case prompt
# mandates Assessment / Recommendation / Evidence / Key Considerations and
# nothing else.
#
# FAIL OPEN TO TREATMENT, always. Treatment is the path that exists today and
# is measured; a router that fails to "diagnostic" would send a routine
# follow-up down a new, more expensive path on a Haiku hiccup. Every failure
# mode here — empty text, malformed JSON, an API error, an unrecognised label —
# resolves to "treatment", which is exactly the behaviour that shipped before
# this function existed.
CASE_INTENT_TREATMENT  = "treatment"
CASE_INTENT_DIAGNOSTIC = "diagnostic"

CASE_INTENT_PROMPT = """A clinician is discussing a case with an endodontic colleague. Classify what THIS turn is asking for.

CASE (first message):
\"\"\"{case}\"\"\"

THIS TURN:
\"\"\"{turn}\"\"\"

Return ONE word, nothing else:

diagnostic — the clinician is asking WHY, or WHAT this is: the cause, the
  aetiology, the diagnosis, the differential, what explains the finding, what
  else it could be, why it happened. Examples: "what could the cause be?",
  "why is this tooth necrotic with no caries?", "what's my differential?",
  "what am I missing?", "is this endodontic or periodontal in origin?"

treatment — the clinician is asking WHAT TO DO: management, technique,
  materials, prognosis, referral, sequencing, whether to treat or extract.
  Examples: "how should I manage this?", "MTA or Biodentine here?", "is this
  restorable?", "what's the prognosis if I treat it?"

If the turn asks for both, or you are not sure, answer treatment."""


def classify_case_intent(case_description: str, turn: str = "") -> str:
    """`diagnostic` or `treatment` for one case turn. Fails open to treatment.

    `turn` is the message being answered; on the first turn it is the case
    description itself, so the caller may pass either or both.
    """
    text = (turn or case_description or "").strip()
    if not text:
        return CASE_INTENT_TREATMENT
    try:
        client = anthropic.Anthropic(api_key=_get_api_key())
        resp = _invoke_claude(
            client, function_name="classify_case_intent",
            model      = MODELS["structured_fast"],
            max_tokens = 8,
            messages   = [{"role": "user", "content": CASE_INTENT_PROMPT.format(
                case=(case_description or text)[:4000], turn=text[:4000])}])
        log_llm_call("classify_case_intent", MODELS["structured_fast"],
                     resp.usage, mode="case")
        word = (resp.content[0].text or "").strip().lower()
        # `startswith`, not equality: a model that answers "diagnostic." or
        # "diagnostic - the clinician..." despite the instruction is still
        # telling you the answer, and treating that as a parse failure would
        # send a diagnostic turn down the treatment path for a full stop.
        if word.startswith(CASE_INTENT_DIAGNOSTIC):
            return CASE_INTENT_DIAGNOSTIC
        return CASE_INTENT_TREATMENT
    except Exception as e:
        print(f"  [case] intent classification failed, "
              f"defaulting to treatment: {e}")
        return CASE_INTENT_TREATMENT


# Facts that genuinely change the differential or the treatment plan. Anything
# outside this list is interesting but not worth a round trip: the clinician is
# chairside and every question costs them time.
_CASE_DECIDING_FACTS = """
FACTS THAT CHANGE THE DIFFERENTIAL (what is causing this):
- TRAUMA HISTORY — type of injury, how long ago, apex maturity at the time. A
  luxation the patient does not think of as an injury is the commonest cause of
  a necrotic virgin tooth.
- WHICH TOOTH, and its anatomy — a maxillary lateral incisor raises dens
  invaginatus and the palatogingival groove; a mandibular premolar raises dens
  evaginatus; a cracked molar is a different conversation from a cracked
  incisor.
- DEVELOPMENTAL ANOMALY on imaging or probing — invagination, evagination, a
  radicular or palatogingival groove, an isolated deep narrow pocket.
- CRACK OR INFRACTION — transillumination, a bite test, staining, an isolated
  probing defect.
- ORTHODONTIC HISTORY — force, duration, and whether this tooth was moved.
- DISCOLORATION and when it appeared — it dates the pulp death.
- SINUS TRACT, swelling or an isolated deep pocket — where the infection is
  draining tells you where it started.
- PULP STATUS / vitality testing — separates reversible pulpitis, irreversible
  pulpitis and necrosis.
- PERIAPICAL FINDINGS on imaging — presence, size and character of a lesion.

FACTS THAT CHANGE THE PLAN (what to do about it):
- RESTORABILITY — ferrule, remaining tooth structure, crown-root ratio.
- PRIOR ENDODONTIC TREATMENT and what specifically failed.
- MEDICAL RED FLAGS — bisphosphonates/antiresorptives, head-and-neck radiation,
  immunosuppression, uncontrolled diabetes, anticoagulation, endocarditis risk.
  **These are only worth asking about when this patient could plausibly have
  one and the answer would change what you advise.** Ask a 68-year-old facing
  an extraction about antiresorptives; do not run the list past a 20-year-old
  with a virgin tooth, where every item is a no and none of them would change
  anything.
- WHEN A RED FLAG IS ALREADY NAMED, its DETAIL is the missing fact, and it is
  usually the highest-value question in the case. "On alendronate" is not the
  answer — duration, route (oral or intravenous), and any drug holiday are what
  decide whether extraction carries a real MRONJ risk, and therefore whether
  the tooth is worth retaining. Treat a named red flag as an open question
  about its detail, not as a box already ticked.
"""


# The prompt itself, hoisted so tests can assert on what the model is
# actually told rather than on the function source — which includes a
# docstring describing the same rules, and so passed a mutation check
# that had deleted the rule from the prompt.
CASE_FOLLOWUP_PROMPT = """You are an experienced endodontist. A colleague has described a case:

\"\"\"{case_description}\"\"\"

STEP 1 — Read the description again and list, to yourself, every clinical fact
it already gives you. This matters: asking for something the colleague has
already told you reads as not having listened, and wastes their chairside time.

STEP 2 — Decide which of these decision-changing facts are genuinely MISSING:
{facts}

STEP 3 — Draft the questions for facts that are missing.

STEP 4 — THE RELEVANCE TEST. Take each drafted question one at a time and ask:

  Given THIS patient's age and THIS presentation, is there a plausible answer
  to this question that would change the differential or the plan?

Not "is the fact missing" — Step 2 already established that, and almost
everything is missing from a two-line description. The test is whether the
ANSWER could matter. If every plausible answer leads to the same differential
and the same plan, DROP the question. Do not keep it because it is on the list.

Worked example, because this is the failure this step exists to prevent:

  Case: "20-year-old, necrotic tooth, no restoration, no caries."
  Drafted: "Any history of bisphosphonates, radiation or immunosuppression?"
  Test:    at 20, with a virgin tooth, every one of those is almost certainly
           no, and a yes would not change the differential for why the pulp
           died or the decision to treat it.
  Verdict: DROP.

  Case: "68-year-old on alendronate for osteoporosis, extraction versus root
         canal on a lower molar with a large lesion."
  Drafted: "How long has she been on alendronate, and by what route?"
  Test:    this patient plausibly has the risk, and the answer moves the
           decision directly — it is the reason to retain the tooth rather
           than extract.
  Verdict: KEEP.

The topic is the same in both. Relevance is not a property of the topic; it is
a property of the topic AND this patient. Never drop a subject on principle,
and never ask about one on principle either.

Then weight what survives by what the colleague is ASKING. If they are asking
what is CAUSING this, the differential facts are what matter and a restorability
question can wait. If they are asking what to DO, the plan facts lead.
Fewer is always better.

How many to ask depends on how much the colleague already gave you:
- If the description already covers pulp/vitality status, periapical findings,
  restorability and relevant medical history: ask AT MOST ONE question, and
  only if that single fact would genuinely change what you advise. Otherwise
  return [] — a thorough description has earned an answer, not another round
  trip.
- If it covers some of those: at most two.
- If it is a bare sentence: at most three, aimed at the biggest gaps.

Return [] whenever the description is sufficient to give useful advice.

ONE EXCEPTION, and it is the case this whole step exists for. If the colleague
is asking what is CAUSING something — the cause, the aetiology, the diagnosis,
why this happened — and the description does not give you the trauma history
AND does not identify the tooth, then it is not sufficient, however short it
is. Ask at least one question. Returning none there is not restraint; it is
answering a diagnostic question while declining to obtain the two facts that
most narrow the differential.

Each question must be ONE line in this shape:
  <the question> — <why it matters, one clause>
For example:
  Is the tooth restorable with an adequate ferrule? — this decides retreatment
  versus extraction more than any other single factor.

Never ask about anything the description states or clearly implies.
Never ask more than one thing per question.

Return ONLY a JSON array of strings. No markdown, no explanation."""


def generate_case_followups(case_description: str) -> list:
    """Up to three follow-up questions about a case, or [] if none are needed.

    Deliberately NOT `generate_clarifying_questions`, which is shared with
    Review and asks 2-3 questions on principle. That behaviour is wrong here:
    it produced an interrogation that re-asked things the clinician had already
    written, which reads as not having been listened to.

    The three rules that make this different:
      1. Re-read the description first, and never ask for anything it states or
         clearly implies.
      2. Ask only about facts that change the differential or the plan.
      3. Say in one clause WHY each question matters, so the clinician can
         judge whether it is worth answering.

    Returns [] when the description already carries what is needed — a complete
    description SHOULD get straight to the answer.
    """
    client = anthropic.Anthropic(api_key=_get_api_key())
    try:
        resp = _invoke_claude(
            client, function_name="generate_case_followups",
            model=MODELS["structured_fast"],
            max_tokens=400,
            messages=[{"role": "user", "content":
                      CASE_FOLLOWUP_PROMPT.format(
                          case_description=case_description,
                          facts=_CASE_DECIDING_FACTS)}]
        )
        log_llm_call("generate_case_followups", MODELS["structured_fast"],
                     resp.usage, mode="case")
        raw = re.sub(r"```json|```", "", resp.content[0].text).strip()
        result = _parse_question_array(raw)
        if result is not None:
            return [q for q in result[:3]]
    except Exception as e:
        # Fail open: a clarify step that errors must not block the case answer.
        print(f"  [case] follow-up generation failed, proceeding: {e}")
    return []


def _parse_question_array(raw: str):
    """Parse a JSON array of question strings, tolerantly. None if unparseable.

    These questions contain em dashes, quoted clinical terms and apostrophes,
    and one run in ten came back with a `"` inside a string that the model did
    not escape — `Expecting ',' delimiter: line 2 column 57`. Strict
    `json.loads` returned nothing, the caller failed open, and the clinician
    got NO clarifying questions at all on a case that needed them. Silence from
    a parse error is indistinguishable from "the description was sufficient",
    which is this repo's bug class (d) — a check that fails open and shows
    nothing — arriving through a JSON delimiter.

    Same tolerance ladder the search-term parser earned in WORKLIST §1.1:
    strict parse, then the first bracketed array, then line extraction.
    """
    if not raw:
        return None
    for attempt in (raw, ):
        try:
            data = json.loads(attempt)
            if isinstance(data, list):
                return [str(q).strip() for q in data if str(q).strip()]
        except Exception:
            pass
    m = re.search(r"\[.*\]", raw, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return [str(q).strip() for q in data if str(q).strip()]
        except Exception:
            pass
    # Last resort: the model wrote a list of quoted strings that does not
    # parse. Recover each complete quoted item. Better a question with an
    # unescaped quote in it than no questions at all.
    items = re.findall(r'"((?:[^"\\]|\\.){20,600}?)"\s*(?:,|\])', raw, re.S)
    items = [i.strip() for i in items if i.strip()]
    if items:
        print(f"  [case] follow-up JSON was malformed; recovered "
              f"{len(items)} question(s) by extraction")
        return items
    return None


# A20 (revision), RB 2026-09-03. Curriculum MAY ask — but only to narrow a
# topic too broad to teach from, never to interrogate a specific one.
#
# Hoisted for the same reason as CASE_FOLLOWUP_PROMPT: a test that reads the
# function source passes over a docstring restating the rule and survives a
# mutant that deleted it from the prompt.
CURRICULUM_NARROWING_PROMPT = """A colleague has asked for a teaching curriculum on:

\"\"\"{topic}\"\"\"

Curo will build FOUR modules from this. Your only job is to decide whether the
topic is specific enough to build four modules from, or so broad that the four
would each have to pick a different subject.

BUILD IT — return [] — when the topic already names what is being taught: a
procedure, a material, a technique, a population, or a comparison.

  "apicoectomy of mandibular teeth"                    -> build
  "use of lasers in root canal disinfection"            -> build
  "MTA versus Biodentine for pulpotomy in mature teeth" -> build
  "anesthesia for endodontics"                          -> build

ASK — return one or two questions — only where a teacher would genuinely have
to choose before starting, and different choices would produce entirely
different curricula.

  "regenerative endodontics" -> immature apex or mature tooth? outcomes or technique?
  "trauma"                   -> which injury, and which dentition?
  "endodontics"              -> the whole specialty

The test is NOT "could this be more specific" — almost anything could, and
asking on that basis is the interrogation this gate exists to prevent. The test
is: WOULD FOUR MODULES BUILT FROM THIS BE ABOUT FOUR DIFFERENT THINGS?

If you ask, offer the actual choice rather than an open prompt: "Immature apex
or mature tooth?" — never "Can you be more specific?". At most two questions.

Return ONLY a JSON array of strings, empty if the topic is ready to build. No
markdown, no explanation."""


def generate_curriculum_narrowing(topic: str) -> list:
    """One or two narrowing questions for a topic too broad to teach from, or
    [] for a topic that is ready to build.

    Deliberately NOT `generate_clarifying_questions`, which asks 2-3 clinical
    questions on principle — the behaviour A20 removed from Literature. A
    curriculum is not a patient: the only thing worth asking before building
    one is which curriculum was meant.

    Fails OPEN, and open here means BUILD. A gate that errors must not leave
    the clinician staring at a question they cannot get past, and a slightly
    too-broad curriculum is a far better failure than a refused one.
    """
    client = anthropic.Anthropic(api_key=_get_api_key())
    try:
        resp = _invoke_claude(
            client, function_name="generate_curriculum_narrowing",
            model=MODELS["structured_fast"],
            max_tokens=300,
            messages=[{"role": "user", "content":
                      CURRICULUM_NARROWING_PROMPT.format(topic=topic)}]
        )
        log_llm_call("generate_curriculum_narrowing", MODELS["structured_fast"],
                     resp.usage, mode="learn")
        raw = re.sub(r"```json|```", "", resp.content[0].text).strip()
        result = _parse_question_array(raw)
        if result is not None:
            return result[:2]
    except Exception as e:
        print(f"  [learn] narrowing check failed, building anyway: {e}")
    return []


def generate_clarifying_questions(question: str, context_block: str = "") -> list:
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
            messages=[{"role": "user", "content": _with_context(context_block,
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

Return ONLY valid JSON — no markdown, no explanation.""",
                note="The clinician is continuing the thread above. Do NOT ask for "
                     "anything the earlier exchange already establishes; ask only "
                     "about what is genuinely new in this question.")}]
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

# ── AND-GROUP CAP ────────────────────────────────────────
# The prompt asks for 2-3 concept groups; the model sometimes emits 4 or more.
# Each extra AND is a hard conjunction, so a 4-group query demands that all four
# concepts co-occur in one record — pips-vs-ultrasonic emitted
# (laser) AND (irrigation) AND (ultrasonic) AND (healing) and retrieved 3 papers
# where sibling runs of the same question retrieved 29.
#
# When over-cap, keep the groups with the MOST OR-synonyms. Those are the
# broadest and, empirically, the ones carrying the question's core concepts; a
# narrow trailing qualifier like ("healing outcome*") is what should go.
MAX_AND_GROUPS = 3


def _split_and_groups(query: str) -> list:
    """Split a boolean query on top-level ' AND ' (depth 0 only).

    Naive string splitting would cut inside a parenthesised OR-list that itself
    contains AND, so this tracks depth and ignores anything inside quotes.
    """
    parts, buf, depth, in_q = [], [], 0, False
    i = 0
    while i < len(query):
        ch = query[i]
        if ch == '"':
            in_q = not in_q
        elif not in_q and ch == "(":
            depth += 1
        elif not in_q and ch == ")":
            depth -= 1
        elif (not in_q and depth == 0
              and query.startswith(" AND ", i)):
            parts.append("".join(buf).strip())
            buf = []
            i += 5
            continue
        buf.append(ch)
        i += 1
    if "".join(buf).strip():
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _or_breadth(group: str) -> int:
    """How many alternatives this concept group offers."""
    return group.upper().count(" OR ") + 1


BROADEN_THRESHOLD = 5   # below this many hits, retry once with one group dropped


def _broaden_query(term: str) -> str:
    """Drop the narrowest top-level AND-group. Returns "" if not broadenable.

    The design/domain filters appended by fetch_papers are themselves
    AND-groups, so only the leading TOPIC groups are eligible — broadening by
    removing the endodontics filter would return the whole of PubMed.
    """
    groups = _split_and_groups(term)
    if not groups:
        return ""
    # fetch_papers builds "(TOPIC) AND (design) AND domain NOT ...", so the
    # whole topic is ONE depth-0 group. Unwrap it and broaden inside; dropping
    # a depth-0 group would remove the design or domain filter and return most
    # of PubMed.
    head, rest = groups[0], groups[1:]
    inner = head[1:-1].strip() if head.startswith("(") and head.endswith(")") else head
    sub = _split_and_groups(inner)
    if len(sub) < 2:
        return ""
    narrowest = min(sub, key=_or_breadth)
    kept = " AND ".join(g for g in sub if g is not narrowest)
    return " AND ".join([f"({kept})"] + rest)


def cap_and_groups(query: str, max_groups: int = MAX_AND_GROUPS) -> tuple:
    """Return (query, dropped_groups). Keeps the broadest `max_groups`.

    Original order is preserved among the kept groups so the query still reads
    the way the model wrote it.
    """
    groups = _split_and_groups(query)
    if len(groups) <= max_groups:
        return query, []
    ranked = sorted(range(len(groups)), key=lambda i: -_or_breadth(groups[i]))
    keep = sorted(ranked[:max_groups])
    dropped = [groups[i] for i in ranked[max_groups:]]
    return " AND ".join(groups[i] for i in keep), dropped


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
        if not _looks_like_query(t) or t in seen:
            continue
        t, dropped = cap_and_groups(t)
        if dropped:
            print(f"  [search_terms] capped to {MAX_AND_GROUPS} AND-groups, "
                  f"dropped: {' | '.join(d[:60] for d in dropped)}")
        if t in seen:
            continue
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


def generate_multi_search_terms(question: str, primary_term: str,
                                context_block: str = "") -> list:
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
    base_prompt = _with_context(
        context_block, base_prompt,
        note="The question may be elliptical. Resolve it against the earlier "
             "exchange first; every query must carry the topic of the earlier "
             "question AND the new qualifier.")

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
        _log_term_degradation(
            "thin_term_set", question,
            f"{len(result)} term(s) after retry, minimum {MIN_SEARCH_TERMS}",
            " | ".join(result))
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

# A31 — observational and descriptive designs.
#
# The seven filters below this one are all publication types or MeSH terms for
# THERAPY and SYNTHESIS designs: trial, review, meta-analysis, cohort,
# case-control, case report. Nothing among them matches a cross-sectional,
# morphometric, imaging or diagnostic-accuracy study, so those papers were not
# down-ranked — they were unreachable. Measured on the apicoectomy module
# query: 46 of the 100 most relevant papers were reachable by NO tier at all,
# including the paper A23 calls the single most on-topic one for the question.
#
# Three candidate filters were measured before choosing (A31a):
#
#   A broad   (+ anatomy[sh], diagnostic imaging[sh], radiography[sh])
#             20 new papers, recovered 4 of 7 named, admitted noise like
#             "[Microinvasive endodontic access]" and a 1972 case note
#   B middle  13 new papers, recovered 5 of 7 named including Jeon 2021 and
#             the bone-window paper; every addition on topic       <- CHOSEN
#   C narrow  11 new papers, recovered 2 of 7 — misses Jeon, which is the
#             paper the whole item exists for
#
# B is not the most permissive; it is the one whose additions were all
# relevant. The 1991 bony-lid paper is recovered by none of them — it predates
# the MeSH terms that describe its design — a corpus-age limit rather than a
# filter choice, reported rather than tuned around.
LEVEL_OBS_TERMS = [
    "cross-sectional studies[mh]",
    "observational study[pt]",
    '"cone-beam computed tomography"[mh]',
    '"imaging, three-dimensional"[mh]',
    '"anatomy and histology"[sh]',
    '"sensitivity and specificity"[mh]',
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
    # Bench work: extracted teeth, dentine blocks, bovine models, agar
    # diffusion, capillary tubes. Endodontics is heavily bench-based, so
    # without this tier a large share of the library classified as
    # "prospective" and sat at Level II. An in vitro result is real
    # evidence about a mechanism and no evidence at all about what happens
    # in a patient, so it ranks below a human case series and above expert
    # opinion.
    "invitro":  15,
    # A7 — expert consensus synthesised by a specialty body. Above one
    # expert's opinion, below a bench result about a mechanism, and not a
    # study at all. Sits between invitro (15) and level5 (10) to match its
    # position in TIER_ORDER.
    "guideline": 12,
    "level5":   10,
    # A31 — descriptive and morphometric designs. Weakest rung: this tier
    # exists to make them REACHABLE, and A25 decides later whether an anatomy
    # question should rank them higher.
    "observational": 8,
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
# A31b — `observational` sits at the WEAKEST end on purpose. This item makes
# these designs REACHABLE; it does not claim they are strong. A25 decides later
# whether an anatomy question should rank them higher, and that is a separate
# change to a separate thing (A12: reachability now, ranking later, never in
# one commit). Nothing above it moves and nothing already retrieved is
# displaced.
TIER_ORDER = ["cochrane", "level1", "classic", "level2", "level3a", "level3",
              "level3b", "level4", "invitro", "guideline", "level5", "observational"]
TIER_LABEL = {
    "cochrane": "Cochrane Reviews",
    "level1":   "Level I — RCTs and Systematic Reviews",
    "level2":   "Level II — Prospective Studies",
    "level3a":  "Level IIIa — Retrospective Cohort",
    "level3b":  "Level IIIb — Case-Control",
    "level3":   "Level III — Retrospective / Case-Control (legacy)",
    "level4":   "Level IV — Case Series",
    "invitro":  "In Vitro / Ex Vivo — Bench Studies (not clinical evidence)",
    "guideline": "Specialty Guidelines & Position Statements (consensus, not a study)",
    "level5":   "Level V — Expert Opinion / Reviews",
    "observational": "Observational / Anatomical — Descriptive Studies "
                     "(not comparative evidence)",
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
    if not _looks_like_query(best):
        return ""
    best, dropped = cap_and_groups(best)
    if dropped:
        print(f"  [search_terms] capped to {MAX_AND_GROUPS} AND-groups, "
              f"dropped: {' | '.join(x[:60] for x in dropped)}")
    return best


def generate_search_terms(question, context_block: str = ""):
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
            "content": _with_context(context_block,
                f"""Convert this clinical endodontic question into a PubMed BOOLEAN query.
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

PubMed boolean query:""",
                note="The question may be elliptical (\"what about in immature teeth?\"). "
                     "Resolve it against the earlier exchange first, then write the query "
                     "for the RESOLVED question — it must carry the topic of the earlier "
                     "question AND the new qualifier.")
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
        # A13c. The fallback is the raw question, which has no AND-groups — so
        # A1's coverage condition abstains and the run takes the library route
        # without that check. Counted, not merely printed.
        _log_term_degradation("primary_fallback", question,
                              "no usable primary query after retry", question)
        search_string = question
    print(f"  Smart search terms: '{search_string}'")
    return search_string

# ── TERM-GENERATION DEGRADATION, COUNTED ──────────────────
#
# A13c. Both degradation paths below printed a WARNING to stdout and nothing
# else, so the only record of a degraded run was a console line nobody keeps.
# A1's abstention then makes a degraded primary term route to the LIBRARY —
# the less cautious of the two routes — which is a silent decision taken on a
# silent signal. Standing rule §1.5: a component that discards or downgrades
# must log and count what it did.
#
# A13a measured the rate before this existed, by recovering the generated topic
# from `pubmed_audit.jsonl` (the search term is stored verbatim on every live
# esearch):
#
#   1,790 distinct generated topics over 155 live runs
#     healthy (2-3 AND-groups)   1,605   89.7%
#     DEGRADED (<2 groups)         108    6.0%   <- 92 of them raw prose
#     over 3 groups (capped)        77    4.3%
#
#   PRIMARY terms specifically — the only one A1's condition reads:
#     0 of 149 runs.  Never, April to September.
#
# So the abstention path guards a state that has not occurred in production,
# and the 6% is entirely in the EXTRA terms, where the cost is retrieval
# breadth rather than routing. This counter exists so that stays true
# observably rather than by assumption.

_TERM_DEGRADE_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "term_degradation.jsonl")
_TERM_DEGRADE_LOCK = _cost_thread.Lock()
# Process-lifetime tallies, so a caller can assert on them without reading the
# file. `kind` is "primary_fallback" or "thin_term_set".
TERM_DEGRADE_COUNTS = {}


def _log_term_degradation(kind: str, question: str, detail: str,
                          produced: str = "") -> None:
    """Record one degraded generation. Never raises — this is telemetry."""
    try:
        with _TERM_DEGRADE_LOCK:
            TERM_DEGRADE_COUNTS[kind] = TERM_DEGRADE_COUNTS.get(kind, 0) + 1
            row = {"ts": datetime.now().isoformat(), "kind": kind,
                   "question": (question or "")[:300], "detail": detail,
                   "produced": (produced or "")[:400]}
            with open(_TERM_DEGRADE_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as ex:      # pragma: no cover — telemetry must not break a run
        print(f"  [search_terms] degradation log failed: {ex}")


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
                    "level4", "invitro", "level5"]


# ── IN VITRO / EX VIVO DETECTION ─────────────────────────
# Bench studies are indexed as ordinary journal articles and read as
# "prospective" to a design classifier, so they land at Level II. What
# separates them is not the design language but the SUBJECT: extracted teeth,
# dentine blocks, bovine incisors, agar plates. Precision matters far more than
# recall here — wrongly demoting a real clinical trial to a bench tier is a much
# worse error than leaving one bench paper at Level II — so a single weak hint
# is never enough.

# Unambiguous on their own: each names a preparation that cannot be a patient.
_INVITRO_STRONG_RE = re.compile(
    r"\b(?:"
    r"extracted\s+(?:human\s+|bovine\s+|permanent\s+|single-rooted\s+)*teeth"
    r"|extracted\s+(?:human\s+|bovine\s+)?(?:tooth|molars?|premolars?|incisors?)"
    r"|dentin(?:e)?\s+(?:blocks?|slices?|discs?|specimens?|cylinders?)"
    r"|bovine\s+(?:teeth|tooth|dentin(?:e)?|incisors?)"
    r"|(?:resin|acrylic)\s+blocks?"
    r"|agar\s+(?:diffusion|plates?)"
    r"|capillary\s+tubes?"
    r"|ex\s+vivo"
    r"|in\s+vitro"
    r")",
    re.IGNORECASE)

# Individually weak — "biofilm model" and "fracture resistance" turn up in
# clinical papers too — so two distinct ones are required, or one strong.
_INVITRO_WEAK_RE = re.compile(
    r"\b(?:"
    r"biofilm\s+model"
    r"|(?:mono|poly)microbial\s+biofilm"
    r"|enterococcus\s+faecalis"
    r"|simulated\s+(?:canals?|root\s+canals?)"
    r"|artificial\s+(?:canals?|teeth)"
    r"|scanning\s+electron\s+microscop"
    r"|micro-?ct|micro\s+computed\s+tomograph"
    r"|push-?out\s+bond\s+strength"
    r"|fracture\s+resistance"
    r"|colony[- ]forming\s+units?"
    r"|CFU"
    r"|specimens?\s+were\s+(?:randomly\s+)?(?:divided|assigned|allocated)"
    r")",
    re.IGNORECASE)

# Clinical language that overrides everything. A study following PATIENTS is not
# a bench study even when it also runs SEM on extracted samples — and clinical
# trials that collect extracted third molars genuinely exist.
_CLINICAL_OVERRIDE_RE = re.compile(
    r"\b(?:"
    r"patients?\s+(?:were|was)\s+(?:randomi|recruit|enroll|assign)"
    r"|were\s+(?:randomi[sz]ed|recruited|enrolled)"
    r"|informed\s+consent"
    r"|ethics\s+committee\s+approv"
    r"|institutional\s+review\s+board"
    r"|follow(?:ed)?[- ]up\s+(?:period\s+)?of\s+\d+\s*(?:month|year)"
    r"|clinical\s+trial\s+registr"
    r"|randomi[sz]ed\s+controlled\s+(?:clinical\s+)?trial"
    r")",
    re.IGNORECASE)

# Designs whose label already outranks any cue. A Cochrane review or an RCT is
# not reclassified on the strength of a phrase in its abstract, and a systematic
# review OF in vitro studies is a real category that stays where it is.
_INVITRO_PROTECTED_LEVELS = {"cochrane", "level1", "classic"}


def detect_in_vitro(title: str, abstract: str, level_key: str = "") -> tuple:
    """Return (is_in_vitro, reason). Deliberately conservative.

    Requires one strong cue or two distinct weak cues, is vetoed by clinical
    language, and never touches a protected design tier. The reason string is
    returned so a migration can print WHY each row moved and a human can audit
    the decision rather than trusting a boolean.
    """
    if level_key in _INVITRO_PROTECTED_LEVELS:
        return False, "protected tier"
    text = f"{title or ''}\n{abstract or ''}"
    if not text.strip():
        return False, "no text"
    if _CLINICAL_OVERRIDE_RE.search(text):
        return False, "clinical-language override"
    strong = {m.group(0).lower() for m in _INVITRO_STRONG_RE.finditer(text)}
    if strong:
        return True, f"strong: {sorted(strong)[0][:40]}"
    weak = {m.group(0).lower() for m in _INVITRO_WEAK_RE.finditer(text)}
    if len(weak) >= 2:
        return True, f"weak x{len(weak)}: {', '.join(sorted(weak)[:2])[:50]}"
    return False, f"insufficient ({len(weak)} weak cue)"


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
    auth = paper.get("authors", "") or "Unknown author"
    # Impact factor is NOT in this line (`trust-surface-v1` Q3, invariant 11).
    # It was, as `IF=12.0`, and that is how it reached the rendered reference
    # list: the number was in the model's context, the REFERENCES template
    # asked for "Journal (IF: X.X)", and the model dutifully wrote it. Curo's
    # stated method — and its pitch — is that journal identity carries no
    # weight; showing the number next to a score contradicts that on the one
    # surface a clinician reads it. Handing it to the model at all is the
    # mechanism, so the fix starts here rather than at the renderer.
    return (
        f"\nPMID: {paper['pmid']} | Authors: {auth} | Year: {paper.get('year')} | "
        f"Citations: {paper.get('citations', 0)} | {ss} | {fu} | "
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
    resp = ncbi_get(f"{NCBI_EUTILS_BASE}/efetch.fcgi", params=fetch_params, timeout=25)
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
        r    = ncbi_get(summary_url, params=summary_params, timeout=10)
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
        r         = ncbi_get(elink_url, params=elink_params, timeout=10)
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
(Journal impact factor is not used and is not shown. Journal identity carries no weight anywhere in this system — PRISMA and Cochrane both advise against screening by journal. Never write an impact factor into an answer.)"""
)


# ── A20 — Literature answers; it does not interview ───────
#
# Hoisted to module level for the same reason as CASE_FOLLOWUP_PROMPT: a test
# that asserts on the function source passes over a docstring restating the
# rule, and so survives a mutant that deleted the rule from the prompt itself.
# This is the text the model is actually shown.
#
# The other half of A20 is in `app.py`: the clarify gate no longer interrupts
# a review question before the answer. This half is the answer body.
_NO_QUESTIONS_RULE = """- NEVER end your response with a question. NEVER ask the clinician for more information.
- If the question is genuinely ambiguous, answer the most reasonable reading and say which reading you took, in ONE sentence beginning "Assumed:" - for example "Assumed: a mature permanent tooth with a necrotic pulp." An assumption declared is not a question asked; it tells the clinician what to correct if you read them wrong, without making them answer an interrogation first.
- If key clinical details are missing, state what information would change the recommendation - but do not pose questions."""


# ── The grounding rule ────────────────────────────────────
#
# Every synthesis prompt in this file mandates a [[PMID:N]] marker on every
# standalone clinical claim, and until now none of them said what to do when
# no retrieved paper supports one. `_build_corrective_message` pushed the same
# way ("Add markers from the evidence base, OR rephrase"). That is a prompt
# that asks for a marker on every claim and never gives permission to omit
# one, which is the remaining known mechanism for a decorative citation — and
# unlike the missing-abstracts bug fixed in `grounding-v1`, it applies on the
# LIVE path too, where abstracts were never missing.
#
# ONE constant spliced into all three prompts, not three copies: the rule is
# the same on every path and three copies drift. `verify_citation_support`
# asks exactly the question this rule tells the model to ask itself first, so
# the two must not be able to disagree about what a marker means.
#
# What it deliberately does NOT do: relax the marker mandate. An evidence-
# derived claim still needs a marker. The rule adds the third option the
# prompt was missing — say less, or say it unmarked — so the model is not
# forced to choose between an unmarked claim and a wrong citation.
_GROUNDING_RULE = """GROUNDING — WHAT A CITATION MARKER ASSERTS (read before attaching one):
A `[[PMID:N]]` marker is itself a factual claim ABOUT PAPER N: it asserts that this paper's own text, as supplied to you in the evidence block, states or directly implies the sentence the marker is attached to. It is not a topic label, not a nod to a related paper, and not a way to satisfy the attribution requirement.

Before you write a marker, locate the specific language in that paper's title or abstract that carries the claim — the sentence you could quote or paraphrase to a clinician who asked "where does it say that?". If you cannot find it, you have exactly three correct moves:
1. Cite a DIFFERENT paper in the evidence block that does state it.
2. WEAKEN the sentence to what the paper actually states — its population, its numbers, its wording — and cite it for that.
3. Write the sentence with NO marker as background, or drop it.

An unmarked sentence is a correct outcome when the evidence base does not support one. A marker on a paper that does not carry the claim is worse than no marker: it passes every check that only asks whether the PMID is real, it cannot be verified by the clinician who clicks it, and it is indistinguishable from a citation you did read. Never attach one to reach a citation density.

Specific traps, because these are the ones that actually occur:
- A MECHANISM or physics claim cited to an outcomes review that reports only results. If the abstract does not describe the mechanism, it does not support the mechanism.
- A NUMERIC parameter — a concentration, an energy, a time, a tip size — cited to a paper that does not report that number. Take the number from the paper that reports it, or state that the cited study did not report it.
- An ARGUMENT FROM SILENCE ("no included study reported X") presented as the paper's finding. A review that does not mention X has not stated anything about X.
- A claim GENERALISED past the paper's scope ("no difference for any modality" when the review pooled only one).

If the evidence base genuinely does not address something the answer needs, say so in the answer.

ANSWERING BEYOND THE EVIDENCE BASE — allowed, in one specific shape:
You MAY give general clinical knowledge the retrieved literature does not cover, when the clinician needs it to act. It must be SEPARATED, never woven into a paragraph beside cited prose, and it must be followed by a return to what this evidence base does support.

1. Put the whole out-of-domain passage in one continuous run and open it with a phrase that says so plainly — "From the wider literature (which this search did not return)", "standard practice, not from the retrieved evidence base". Never split it across a cited sentence.
2. Do NOT attach a `[[PMID:N]]` marker to any of it. It is unverified, and saying so is the point. A marker here is the worst available move: it launders unchecked advice into checked advice.
3. Name the guideline bodies you are leaning on (SDCEP, ESE, AAE, ACC/AHA, NICE, …) so the clinician can go to the document itself.
4. Then COME BACK. Immediately after the passage, state the decision the retrieved literature DOES support, with its marker — including when that is "the alternative treatment is a legitimate option here". This is required, not optional; an answer that ends outside its evidence base has left the clinician there.

The renderer lifts that run into a bordered "NOT FROM THE EVIDENCE BASE — UNVERIFIED" block, so write it as ordinary prose and let the structure do the labelling."""


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

# ── DOES THE RETRIEVED SET ADDRESS THE QUESTION? ──────────
#
# Addendum A1. The library-first gate asked four questions — enough hits, enough
# above the similarity floor, at least one high tier, not stale — and every one
# of them is a question about the CORPUS, not about the QUESTION. On "eliquis in
# patients who needs apicectomy" all four passed (200 hits, 14 above the floor
# against a minimum of 12, 11 high-tier, newest 2026) and live PubMed was never
# attempted. None of those 14 papers mentions anticoagulation anywhere.
#
# The gate was measuring similarity to the endodontic corpus. Every one of its
# conditions is satisfiable by the endodontic HALF of a two-part question, so a
# question with one foot outside the library scores as well covered.
#
# WHAT A CONCEPT IS. `generate_search_terms` emits a PubMed boolean whose
# top-level AND-groups are exactly the question's concepts:
#
#   (apicectomy OR apicoectomy OR "periapical surgery")     <- the procedure
#   AND (Eliquis OR apixaban OR anticoagulant*)             <- the drug
#   AND (patient* OR perioperative OR bleeding)             <- the setting
#
# Each AND-group is a hard requirement in the query the system would have sent
# to PubMed. So requiring that each one is REPRESENTED in the candidate set is
# not a new judgement about the question — it is the query's own structure,
# applied to what came back.
#
# Only the PRIMARY term is used. `generate_multi_search_terms` deliberately
# generates "different angles", and an angle is allowed to find nothing; the
# primary term is the one derived from the question itself.
#
# Generic groups are dropped. A group of nothing but endodontic vocabulary
# ("root canal" OR endodontic*) is satisfied by every paper in the library and
# tests nothing — it is the same tautology the old gate was built on.

# Vocabulary that every paper in an endodontic library carries, plus the
# connective words a query generator reaches for. A group made only of these
# cannot discriminate.
_COVERAGE_GENERIC = {
    "endodontic", "endodontics", "root canal", "root canals", "dental pulp",
    "pulp", "pulpal", "pulpitis", "periapical", "periradicular", "tooth",
    "teeth", "dental", "dentistry", "oral", "canal", "canals",
    "patient", "patients", "management", "manage", "treatment", "treatments",
    "therapy", "clinical", "outcome", "outcomes", "efficacy", "effectiveness",
    "safety", "success", "failure", "study", "studies", "trial", "trials",
    "adult", "adults", "human", "humans",
}

_TERM_SPLIT_AND = re.compile(r"\)\s+AND\s+\(")
_TERM_SPLIT_OR  = re.compile(r"\s+OR\s+", re.IGNORECASE)


def _clean_term(t: str) -> str:
    """One synonym, stripped of quotes, parens and PubMed field tags."""
    t = (t or "").strip()
    t = re.sub(r"\[[a-z]+\]\s*$", "", t, flags=re.IGNORECASE)   # [tiab], [mh]
    t = t.strip().strip("()").strip().strip('"').strip()
    return t.lower()


def parse_search_term_groups(term: str) -> list:
    """The top-level AND-groups of a generated PubMed boolean, as term lists."""
    if not term:
        return []
    s = term.strip()
    groups = []
    for chunk in _TERM_SPLIT_AND.split(s):
        terms = [_clean_term(x) for x in _TERM_SPLIT_OR.split(chunk)]
        terms = [t for t in terms if len(t) >= 3]
        if terms:
            groups.append(terms)
    return groups


def _group_is_generic(terms: list) -> bool:
    """True when every synonym in the group is corpus-wide vocabulary."""
    return all(t.rstrip("*").strip() in _COVERAGE_GENERIC for t in terms)


# A generated query has three AND-groups by spec. When generation fails,
# `generate_search_terms` falls back to the RAW QUESTION — "Single visit versus
# multiple visit endodontic treatment?" — which parses as one group holding one
# 60-character string that no title contains. Coverage then scores 0 and the
# condition routes every degraded run to live PubMed.
#
# Caught by `tests/test_end_to_end.py`, which drives the real path with a stubbed
# Claude and hit the fallback. It is the failure mode A1c exists to bound, and it
# would have been paid for in latency on every run whose term generation slipped.
#
# A fallback string is not a concept decomposition, so the condition abstains
# rather than failing: fewer than two AND-groups means there is nothing here the
# query itself treated as a separate requirement.
_COVERAGE_MIN_GROUPS = 2
# No paper's title or abstract contains a whole clause. A "synonym" this long is
# prose that leaked through the parser, not a term to match on.
_COVERAGE_MAX_TERM_WORDS = 6


def coverage_groups(primary_term: str) -> list:
    """The question's DISCRIMINATING concepts — its AND-groups, generics dropped.

    Returns [] when the query has no boolean structure to read, which makes the
    gate condition abstain instead of blocking.
    """
    parsed = parse_search_term_groups(primary_term)
    if len(parsed) < _COVERAGE_MIN_GROUPS:
        return []
    out = []
    for g in parsed:
        g = [t for t in g if len(t.split()) <= _COVERAGE_MAX_TERM_WORDS]
        if g and not _group_is_generic(g):
            out.append(g)
    return out


def _term_in_text(term: str, text: str) -> bool:
    """`apixaban` matches; `anticoagulant*` matches "anticoagulants"."""
    t = term.rstrip("*").strip()
    if len(t) < 3:
        return False
    return re.search(r"(?<![a-z])" + re.escape(t), text) is not None


def question_coverage(groups: list, candidates: list) -> list:
    """Per concept, how many candidate papers mention any of its synonyms.

    Reads title and abstract. A candidate with neither contributes nothing —
    which is the honest direction: an unread paper is not evidence that the
    concept is covered.
    """
    blobs = []
    for c in (candidates or []):
        blobs.append(((c.get("title") or "") + " " +
                      (c.get("abstract") or "")).lower())
    out = []
    for g in groups:
        n = sum(1 for b in blobs if any(_term_in_text(t, b) for t in g))
        out.append({"terms": g, "hits": n})
    return out


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


# cost_log.jsonl has had _COST_LOG_LOCK and evidence_mapping.jsonl _EVMAP_LOG_LOCK
# since they were written; this log had neither, which was invisible while every
# esearch came from one thread. The curriculum builder now retrieves four modules
# concurrently, so two threads can be inside the append at once — and a torn line
# in the proof-of-fetch log destroys exactly the record that proves a PMID came
# from NCBI rather than from a model.
_PUBMED_AUDIT_LOCK = _cost_thread.Lock()
# Module-level so `tests/conftest.py` can redirect it, the way it already
# redirects the cost and evidence-mapping logs. The path used to be built
# inside the writer, which made it the one audit log a test run could not
# be kept out of.
_PUBMED_AUDIT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pubmed_audit.jsonl")


def _pubmed_audit_log(label: str, level_key: str, search_term: str,
                       returned_pmids: list, http_status: int, ms: int) -> None:
    """Append-only proof-of-fetch log: every esearch call we make against NCBI
    is recorded with the exact search term, returned PMIDs, HTTP status, and
    latency. This is the audit trail showing PMIDs came from a live NCBI
    response — not synthesised. Stored in pubmed_audit.jsonl.

    Thread-safe: serialised on _PUBMED_AUDIT_LOCK.

    `pid` is the writer's process id, and it is the third file in this repo to
    need one. `run_eval._esearch_hits_since` measures a case's retrieval as a
    BYTE-OFFSET WINDOW into this file — and this file is one file shared by
    every process on the machine, so anything else fetching from PubMed while
    an eval is in flight lands inside that case's numerator. It happened
    through `evidence_mapping.jsonl` first: nine rows from a concurrent pytest
    run turned 16/119 into 16/146. This log has the same shape and had no
    guard.

    A TIMING heuristic was written for that incident and thrown away, and the
    reason generalises here: the contaminating burst was 1.3 s apart, which is
    also exactly what four curriculum modules finishing on a thread pool look
    like. Threads share a pid; separate processes do not. The pid is the only
    signal that separates the two cases, so it is the one recorded.
    """
    rec = {
        "ts":           datetime.now().isoformat(),
        "pid":          os.getpid(),
        "label":        label,
        "level_key":    level_key,
        "search_term":  search_term[:600],
        "n_returned":   len(returned_pmids),
        "pmid_sample":  returned_pmids[:10],
        "http_status":  http_status,
        "latency_ms":   ms,
    }
    try:
        line = json.dumps(rec) + "\n"
        with _PUBMED_AUDIT_LOCK:
            with open(_PUBMED_AUDIT_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception as e:
        print(f"    [pubmed_audit] write failed: {e}")


def fetch_papers(topic, filter_term, label, level_key, max_results=50, mode="review",
                 question=None):
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
        search_response = ncbi_get(search_url, params=search_params, timeout=20)
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

        # A3 auto-broaden. A tier that comes back nearly empty is usually
        # over-conjoined rather than genuinely unstudied: every AND is a hard
        # requirement that all concepts co-occur in one record. Drop the
        # NARROWEST group (fewest OR-synonyms) and try once more. One retry
        # only — a second would mostly return the domain filter's own results.
        if len(ids) < BROADEN_THRESHOLD:
            broadened = _broaden_query(search_term)
            if broadened:
                print(f"  ~~ {label}: {len(ids)} hits, broadening once")
                try:
                    bp = dict(search_params); bp["term"] = broadened
                    t1 = _time.perf_counter()
                    r2 = ncbi_get(search_url, params=bp, timeout=20)
                    ms2 = int((_time.perf_counter() - t1) * 1000)
                    if r2.status_code == 200:
                        raw2 = r2.json().get("esearchresult", {}).get("idlist") or []
                        ids2 = [pid for pid in raw2 if _PMID_FORMAT_RE.match(str(pid))]
                        _pubmed_audit_log(label + " [broadened]", level_key,
                                          broadened, ids2, r2.status_code, ms2)
                        if len(ids2) > len(ids):
                            print(f"  [NCBI_LIVE] {label} [broadened]: "
                                  f"{len(ids2)} PMIDs in {ms2}ms")
                            ids, search_term = ids2, broadened
                except Exception as _be:
                    print(f"  ~~ {label}: broaden failed, keeping original ({_be})")

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
        fetch_response = ncbi_get(fetch_url, params=fetch_params, timeout=20)
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
        # A30/rule 19. `ids` arrives in PubMed's own relevance order — esearch
        # is called with sort=relevance — and that order is the only relevance
        # signal the live path has, since these papers have no embedding
        # similarity yet. It used to be destroyed by the score sort below and
        # the cap then kept the top N by SCORE. Remembering the rank here is
        # what lets the cap decide membership by relevance and leave ranking
        # to the score, where invariant 1 puts it.
        for _pm_rank, pmid in enumerate(ids, 1):
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
                "pubmed_rank":     _pm_rank,
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
                # `topic` is the query this write-back came from, so a big
                # write-back can clear the answers cached on that topic.
                #
                # CAVEAT (WORKLIST 4.6): at this point `topic` is the generated
                # PubMed BOOLEAN string, not the clinician's question — the
                # question is not threaded past build_evidence_base(). Measured
                # against real cached questions, a boolean topic string scores
                # 0.42-0.45 cosine where the question itself scores 0.87-1.00,
                # The CLINICIAN'S question, not `topic`. topic is the
                # generated PubMed boolean string; measured against real
                # cached questions it scores 0.42-0.45, so a 0.85 invalidation
                # threshold could never be reached from it and the feature was
                # inert. Falls back to topic when a caller has no question to
                # give, which is no worse than before.
                learn_from_live_results(scored_papers, _per_pmid,
                                        query_text=question or topic)
            except Exception as _we:
                print(f"    [learn] write-back skipped: {_we}")

        return annotated_text, ids, scored_papers

    except Exception as e:
        print(f"  XX{label}: Could not fetch ({e})")
        # Record the failure in the audit log too. It is the proof-of-fetch
        # trail, and a fetch that never happened is exactly what it should be
        # able to prove. Without this, a network outage is indistinguishable
        # downstream from a query that legitimately matched nothing — during a
        # DNS drop the eval harness reported "1.0 hits/query, the laser
        # regression's real signature" for 62 calls that were never sent.
        # http_status 0 means "no HTTP response at all".
        try:
            _pubmed_audit_log(label, level_key, locals().get("search_term", ""),
                              [], 0, 0)
        except Exception:
            pass
        return "", [], []

# ── DYNAMIC QUALITY THRESHOLD ─────────────────────────────
# Live results above the quality floor are added to the local library, so the
# corpus tracks what clinicians actually ask about. Disable with
# LIBRARY_WRITE_BACK=false if the library must stay a curated, fixed set.
LIBRARY_WRITE_BACK = os.getenv("LIBRARY_WRITE_BACK", "true").lower() in ("1", "true", "yes")

_warn_if_no_ncbi_key()

QUALITY_FLOOR    = 50   # global ceiling on any per-tier floor (see below)

# Per-tier quality floors. Score is NOT comparable across tiers by
# construction: study design contributes 39% of it, so a Cochrane review starts
# from 100 and a case series from 20 before anything about the individual paper
# is weighed. A single flat cut therefore does not remove weak papers evenly —
# it removes whole tiers. Measured on the real library at the flat 50
# (scripts/measure_quality_floor.py):
#
#     tier      n    survived  share   p90    
#     level4    175  4          2%     43.7   even its best work was below the floor
#     invitro   155  1          1%     42.9   same
#     level5    153  3          2%     39.8   same
#     level3    320  94        29%     53.4   thinned to a third
#
# Only MIN_PAPERS_KEPT=3 was rescuing those tiers, so a "case series" block
# shown to a clinician held three papers picked by a rule that had already
# discarded the other 172 — not the best three of 175.
#
# Each floor is that tier's own 40th percentile, so a tier is judged against
# its own distribution. Every value is CAPPED at QUALITY_FLOOR by _tier_floor:
# this change may only ever loosen a tier, never tighten one, so no paper that
# reaches a clinician today can be removed by it.
# A31 — how deep each tier's esearch goes. Everything defaults to 50; the
# observational tier goes to 100 because it is drawing from a much larger and
# less sharply ranked pool. Measured on the apicoectomy anatomy module: the
# tier query matches 770 papers, and the ones the module actually needs sit at
# ranks 32, 57, 71 and 76 — Bi 2022 was the only one inside 50. This is a
# depth change, not a relevance change: esearch is still sorted by relevance
# and the tier's own cap still keeps only the most relevant 6-10 of them.
TIER_FETCH_DEPTH = {"observational": 100}

TIER_QUALITY_FLOORS = {
    # A7 — permissive on purpose. These rows score 30.9-90.0 on a scorer
    # built for therapy designs; the score is not what makes a specialty
    # guideline worth surfacing, and A12 forbids changing it here.
    "guideline": 27,
    # A31 — the same floor as level4 (case series), the weakest clinical tier
    # that already exists, rather than a number invented for this one.
    #
    # It cannot be level5's 38: the score is computed by a therapy-shaped
    # scorer that gives a descriptive study no credit for a comparison it never
    # made or a follow-up it never had. Measured on the apicoectomy anatomy
    # module, this tier's 50 papers score min 15.4, median 33.5, max 46.5 — a
    # floor of 38 admitted 16 and cut the paper the item exists for. The floor
    # is a junk filter here; the tier's cap is what does the choosing, and it
    # chooses by relevance.
    "observational": 27,
    "cochrane": 50, "level1": 50, "classic": 50, "level2": 50, "level3b": 50,
    "level3a": 45, "level3":  41,
    "level4":   27, "invitro": 31, "level5": 38,
}


def _tier_floor(tier_key: str) -> float:
    """This tier's quality floor, never above the global QUALITY_FLOOR."""
    return min(QUALITY_FLOOR, TIER_QUALITY_FLOORS.get(tier_key, QUALITY_FLOOR))
MIN_PAPERS_KEPT  = 3    # keep at least this many even if low-quality (avoid empty tier)
MAX_PAPERS_KEPT  = 25   # default hard cap so one tier can't drown out others

# Mode-specific per-tier paper caps.
#   review  — chairside literature review: bias toward Tiers I-III primary evidence
#   learn   — deep-learning lecture: over-index on Tier V reviews/editorials/guidelines
#             (they supply the narrative scaffolding a 20-min teaching module needs)
# A31c — `observational` carries its own quota in every mode. The quotas are
# per-tier and independent: `fetch_papers` runs once per tier with that tier's
# own cap, so a slot here can never be taken from level1 or anything above it.
# Learn gets the larger share because a curriculum's anatomy module is the
# thing this item exists to feed.
MODE_TIER_QUOTAS = {
    "review": {
        "cochrane": 10, "level1": 18, "level2": 14,
        "level3a": 10, "level3b": 6, "level3": 8,
        "level4": 4,   "level5": 4,
        "guideline": 4,
        "observational": 6,
    },
    "learn": {
        "cochrane": 8,  "level1": 10, "level2": 8,
        "level3a": 6,  "level3b": 4,  "level3": 6,
        "level4": 6,   "level5": 25,   # narrative-rich tier promoted
        "guideline": 6,
        "observational": 10,
    },
    # case discussion uses the same balance as review
    "case": {
        "cochrane": 10, "level1": 18, "level2": 14,
        "level3a": 10, "level3b": 6, "level3": 8,
        "level4": 4,   "level5": 4,
        "guideline": 4,
        "observational": 6,
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
      - retain every paper scoring >= this TIER's floor (see
        TIER_QUALITY_FLOORS; never above the global QUALITY_FLOOR)
      - if fewer than MIN_PAPERS_KEPT survive, top up with the next-best
      - never keep more than the per-tier cap for the active mode

    A30/rule 19. The FLOOR is a quality bar and stays a quality decision: a
    paper below it is not good enough for any question. The CAP is a
    membership decision among papers that have already cleared the bar, and it
    used to keep the top N by score — the live-path twin of the per-tier cap
    A5b found dropping the most on-point RCT in the library at rank 54 of 60.

    Membership is therefore decided in PubMed's relevance order (`pubmed_rank`,
    recorded in `fetch_papers` before the score sort), and the survivors are
    returned ordered by score, which is where invariant 1 puts ranking.
    """
    if not scored_papers:
        return scored_papers

    cap = _tier_cap(mode, tier_key) if tier_key else MAX_PAPERS_KEPT
    floor = _tier_floor(tier_key) if tier_key else QUALITY_FLOOR
    above = [p for p in scored_papers if p.get("score", 0) >= floor]

    def _by_relevance(papers):
        # A paper with no rank (older cached shapes, or a caller that built the
        # list itself) sorts last rather than first: absent evidence of
        # relevance is not evidence of relevance.
        return sorted(papers, key=lambda p: p.get("pubmed_rank") or 10 ** 6)

    def _cut(papers):
        if len(papers) <= cap:
            return sorted(papers, key=lambda p: p.get("score", 0), reverse=True)
        ranked  = _by_relevance(papers)
        kept    = ranked[:cap]
        dropped = ranked[cap:]
        # Standing rule 5.
        print(f"    [cap] {tier_key or 'tier'}: {len(papers)} above the quality "
              f"floor, keeping the {cap} most relevant; dropped {len(dropped)} "
              f"(best dropped PubMed rank {dropped[0].get('pubmed_rank')})")
        return sorted(kept, key=lambda p: p.get("score", 0), reverse=True)

    if len(above) >= MIN_PAPERS_KEPT:
        return _cut(above)

    # Sparse tier — top up to MIN_PAPERS_KEPT with the next most RELEVANT of
    # the papers below the floor. Topping up by score would fill a thin tier
    # with whatever happened to score well rather than with what was asked.
    short = [p for p in _by_relevance(scored_papers) if p not in above]
    topped = above + short[:max(0, MIN_PAPERS_KEPT - len(above))]
    return _cut(topped)


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
                                         mode=mode, question=topic)
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
        # A31 — last in the list and last in TIER_ORDER. Its own query,
        # its own quota, its own floor; it takes nothing from the tiers
        # above it.
        ("observational", LEVEL_OBS_TERMS, TIER_LABEL["observational"]),
    ]

    for level_key, terms, label in levels:
        text, ids, scored = fetch_papers(
            smart_topic, " OR ".join(terms), label, level_key, mode=mode,
            question=topic, max_results=TIER_FETCH_DEPTH.get(level_key, 50)
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
#
# THE FOUR ADDED IN `case-v3` are at the end, and each is a real sentence from
# the DE case conversation that the detector let through. The originals catch
# a claim by its NUMBERS — a percentage, an n, a p-value, a dose. A chairside
# protocol has a different shape: it is an instruction, and an instruction can
# be entirely uncited and entirely actionable without containing a statistic.
#
#   "Reduce occlusal contact on the tubercle — selective equilibration to
#    eliminate traumatic occlusal loading on the cusp."
#   "This is the single most impactful step."
#   "Calcium hydroxide or MTA liner placement after each reduction step is
#    advocated in the literature for deeper reductions."
#   "Screen the entire mouth for DE."
#
# Four instructions a clinician could act on this afternoon, no marker on any
# of them, and the third one appeals to a literature it does not cite. The
# measurement is in `eval/logs/case_uncited.json`: 6 claims of these shapes
# across the two turns, all missed.
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

    # ── added in `case-v3`, from the DE conversation ──
    # An interval written as a RANGE — "6-8 week intervals", "2-3 month
    # recall". This is the only one of the three shapes the item listed that
    # the original patterns actually miss, and the mutation run is what
    # established that: a mutant disabling the other two survived every test,
    # because "0.5 mm per visit" already matches `\d+ mm` and "every 6 months"
    # already matches `\d+ months` in the unit pattern above. A range escapes
    # because "6-8 week" is SINGULAR and that list holds only plurals.
    #
    # The two redundant alternatives were written, tested, found unkillable,
    # and deleted. A pattern no input needs is the regex equivalent of a test
    # that cannot fail.
    re.compile(r"\b\d+\s*[-–—]\s*\d+\s*(?:day|week|month|year)s?\s+"
               r"(?:intervals?|recall|review|apart)\b", re.IGNORECASE),

    # An appeal to the literature, with no citation. This is the sharpest of
    # the four: the sentence explicitly claims a body of evidence exists and
    # declines to name it.
    re.compile(r"\b(?:advocated|described|reported|documented|established|"
               r"recommended|supported|shown|demonstrated|validated)\s+in\s+the\s+"
               r"literature\b"
               r"|\bthe\s+literature\s+(?:advocates|supports|shows|describes|"
               r"recommends|reports)\b"
               r"|\b(?:studies|trials|reviews|authors)\s+(?:have\s+)?"
               r"(?:shown|demonstrated|reported|found|suggest(?:ed)?)\b",
               re.IGNORECASE),

    # An imperative clinical instruction. Anchored to the start of the unit so
    # it fires on a protocol STEP and not on the same verb used mid-sentence
    # ("...which would reduce the load..."). The optional list marker and bold
    # run are there because a protocol step is almost always written
    # "3. **Reduce ...**".
    re.compile(r"^\s*(?:[-*•]\s*|\d{1,2}[.)]\s*)?(?:\*\*)?\s*"
               r"(?:Reduce|Recontour|Equilibrate|Apply|Place|Seal|Bond|Monitor|"
               r"Refer|Screen|Perform|Prescribe|Adjust|Remove|Restore|Instruct|"
               r"Review|Repeat|Avoid|Splint|Extract|Obturate|Irrigate|Medicate)\b",
               re.IGNORECASE),

    # A superlative about clinical importance. "The single most impactful step"
    # ranks an intervention against every alternative, which is exactly the
    # kind of claim a paper either supports or does not.
    re.compile(r"\b(?:the\s+single\s+most\s+\w+|most\s+impactful|"
               r"is\s+critical\b|is\s+essential\b|is\s+mandatory\b|"
               r"key\s+determinant|dominant\s+(?:factor|determinant)|"
               r"the\s+deciding\s+factor)\b", re.IGNORECASE),
]

# An EXPLICIT admission that a claim is not from the evidence base. A claim
# carrying one of these is attributed — not to a paper, but to the clinician's
# own judgement, out loud, which is the honest ending for a step the retrieved
# literature does not cover.
#
# Without this the escape hatch is a trap: the prompt offers "label it", the
# model labels it, and `_detect_unattributed_claims` flags it anyway because
# there is no marker — so the honest move and the silent one fail identically
# and the model learns nothing from the retry. The label has to count.
_UNSOURCED_LABEL_RE = re.compile(
    r"not\s+from\s+the\s+(?:retrieved\s+)?evidence\s+base"
    r"|standard\s+practice[,;]?\s+not\s+(?:from|supported)"
    r"|no\s+paper\s+(?:in\s+)?(?:this|the)\s+evidence\s+base"
    r"|this\s+evidence\s+base\s+does\s+not\s+(?:address|contain|cover)"
    r"|which\s+this\s+search\s+did\s+not\s+return"
    r"|from\s+the\s+wider\s+literature"
    r"|convention(?:al)?\s+practice,\s+uncited"
    r"|not\s+(?:derived\s+)?from\s+the\s+(?:papers|literature)\s+(?:above|below|retrieved)",
    re.IGNORECASE)


# A named author with no marker anywhere in the same claim — "Sjogren et al.
# demonstrated that…" with nothing to click. `case-v3` Item B(c): this is a
# FORMAT violation, not a judgement call. The prompt says every inline
# reference must be wrapped as [[PMID:N]], and an author surname is an inline
# reference: it tells the clinician a specific paper exists and then gives
# them no way to reach it.
#
# The surname must be capitalised and followed by `et al` or `and <Surname>`,
# which is how the model actually writes them. A bare capitalised word is not
# enough — "Scenario A" and "Reduce occlusal" would both match.
_AUTHOR_MENTION_RE = re.compile(
    r"\b([A-Z][A-Za-zÀ-ÿ'’-]{2,})\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-zÀ-ÿ'’-]{2,}\b)"
)
# Phrases that look like an author mention and are not one.
_AUTHOR_MENTION_STOPWORDS = {
    "Cochrane", "PubMed", "Level", "Scenario", "Type", "Class", "Table",
    "Figure", "Module", "Step", "Grade", "Tooth", "Patient", "Evidence",
}

# ── What an inline citation marker looks like ─────────────
#
# `trust-surface-v1` Q4. This used to be `(\d+)`, and the whole marker layer
# inherited that assumption. It is wrong: hand-ingested authority documents —
# the ESE quality guidelines, the AAE position statements, NCBI Bookshelf
# chapters — carry synthetic identifiers (`ESE-QG-2023`, `AAE-PS-obturation`,
# `NBK430685`), and `build_evidence_base` puts them in the evidence base under
# exactly those keys. So the model correctly writes `[[PMID:ESE-QG-2023]]` and
# every consumer of this pattern was blind to it.
#
# Six consumers share this regex, and before this change exactly ONE of them
# knew about the other key shape — `validate_evidence_mapping` had a local
# `non_numeric` re-scan bolted on beside it. The other five did not, and the
# measured consequences on the apixaban fixture were:
#
#   * `_extract_claim_citation_pairs` never built a pair for the ESE claim, so
#     the banner read "9/9 CONSISTENT" over 10 cited claims. A denominator that
#     silently drops a citation is invariant 15's fail-open shape.
#   * `_detect_unattributed_claims` saw the ESE sentence as carrying no marker.
#   * the browser's own `[[PMID:(\d+)]]` replacer left `[[PMID:ESE-QG-2023]]`
#     RAW on the rendered page — invariant 3, the defect Q4 is named for.
#
# One pattern, both shapes, and the local patch deleted: a second scan that
# only one caller runs is how the shapes drifted apart in the first place.
_PMID_ID_PAT      = r"(?:\d+|[A-Za-z][A-Za-z0-9._-]{1,63})"
_PMID_RE          = re.compile(r"\[\[PMID:\s*(" + _PMID_ID_PAT + r")\s*\]\]")
# The bibliographic key shape used ONLY in the final numbered reference list
# (`[PMID: 12345678]`). Same two id shapes, single brackets.
_REF_PMID_RE      = re.compile(r"\[PMID:\s*(" + _PMID_ID_PAT + r")\s*\]")
_HEADING_RE       = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.MULTILINE)

# A period inside an abbreviation is not a sentence end. Each lookbehind is
# fixed-width on its own, which is what `re` requires; chaining them is how a
# variable-width guard is spelled without pulling in `regex`.
#
# Measured on the 77 stored answers: 10.7% of claim-citation pairs sat on a
# piece cut at one of these. "Er:YAG vs. SWEEPS" broke in two, and — far more
# often — "Dagher et al. 2019" put the author on one side of the cut and the
# citation on the other, leaving the PMID judged against a subjectless
# fragment.
_SENT_ABBREV_GUARD = (
    r"(?<!\bvs\.)(?<!\bcf\.)(?<!\bDr\.)(?<!\bSt\.)(?<!\bNo\.)(?<!\bFig\.)"
    r"(?<!\bet al\.)(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bapprox\.)"
    r"(?<!\bInc\.)(?<!\bLtd\.)(?<!\bJr\.)(?<!\bSr\.)(?<!\bResp\.)"
    r"(?<!\bmin\.)(?<!\bsec\.)(?<!\bmo\.)(?<!\bwk\.)(?<!\byr\.)"
)
_SENTENCE_SPLIT_RE = re.compile(
    _SENT_ABBREV_GUARD + r"(?<=[.!?])\s+(?=[A-Z\d])")

# The generator's REAL section markers are bold pseudo-headings, not ATX
# headings: `**Level II — Prospective Studies**` on a line of its own.
# `_HEADING_RE` does not match them, so `_split_sections` does not split there;
# `_SENTENCE_SPLIT_RE` does not either, because the line starts with `*` and
# not [A-Z\d]. Everything from the previous sentence through the heading and
# into the next paragraph therefore fused into ONE "sentence" carrying several
# claims and several PMIDs — 32% of all claim-citation pairs — and each PMID
# was judged against all of them.
#
# The measurement that matters, and it reverses an earlier "no effect" reading:
# merged pairs are flagged 37.6% of the time against 50.8% for clean ones
# (p=0.002). Merged pairs are flagged LESS. A long blob gives the judge more
# surface on which to find something the abstract does support, so a bad
# citation buried in a merge is less likely to be caught than the same citation
# on its own sentence. This defect SUPPRESSES the guardrail.
_PSEUDO_HEADING_RE = re.compile(
    r"^[ \t]*\*\*[^*\n]{2,120}\*\*[ \t]*:?[ \t]*$", re.MULTILINE)

# ── The three shapes a curriculum writes that prose splitting cannot see ──
#
# `_PSEUDO_HEADING_RE` above closed the case where the bold run IS the whole
# line. A Deep Learning module writes three more shapes that the sentence
# splitter also cannot break, for the same two reasons every time: the line
# does not end in `.!?`, and the next line starts with `*` or `|` rather than
# [A-Z\d]. Each one fuses a whole structure into ONE "claim" carrying every
# marker in it, and every marker is then judged against the whole blob.
#
# Measured, by hand, over all 37 Deep Learning citation flags
# (`eval/logs/dl_flag_verdicts.json`): 13 of the 37 — the largest single
# remaining cause in this metric — are this. The mechanism, from the
# worksheet:
#
#   1. DECISION TREE. `#### 4b. Decision Tree` emits
#        **IF** <condition>
#        **THEN** <action>
#        **BECAUSE** <evidence> [[PMID:a]] [[PMID:b]]
#      repeated. A seven-branch tree is one claim carrying seven papers'
#      markers, so a marker on the postoperative-pain branch is judged
#      against the radiographic-healing branch too (flag 12 in the worksheet).
#      A branch ends where the next `**IF**` begins — that is the unit,
#      condition through justification, because the BECAUSE is only a claim
#      in the presence of the THEN it justifies.
#
#   2. TABLE ROW. `#### Clinical Protocol Summary` and
#      `#### 4c. Materials & Instrumentation` are markdown pipe tables whose
#      rows each carry their own citation. The whole table was one claim.
#      A row is a claim; the separator row and a header row that cites
#      nothing are not.
#
#   3. INLINE BOLD LABEL. `**KTP laser (532 nm):** Ayhan et al. found ...` —
#      a bold label at the START of a line with its content following ON THE
#      SAME LINE. `_PSEUDO_HEADING_RE` requires the bold run to be the entire
#      line, so it does not match, and three sub-points fused (flags 17, 33,
#      34, 37). This is the pseudo-heading rule finishing its own job.
#
#   4. LIST ITEM. Found while measuring the first three, not from the
#      worksheet:
#        - **Heterogeneity of protocols**: ... [[PMID:36156804]]
#        - **Irrigant extrusion risk**: ... [[PMID:40287048]]
#      Four bullets, four different papers, ONE claim of 1,438 characters. The
#      existing code strips the bullet MARKER (`^\s*[-*•]\s+`) and then never
#      splits on it, so the marker's only effect was to hide the boundary it
#      marks. A list item is a claim; that is what a list is for.
#
# DIRECTION OF THE FIX, stated because the last change to this splitter
# reversed its expected direction: un-merging makes the checker STRICTER.
# Merged pairs were flagged at 37.6% against 50.8% for clean ones (p=0.002)
# — a long blob gives the judge more surface on which to find something the
# abstract does support, so a bad citation hides in a merge. Splitting cannot
# be a way of moving the flag rate down by giving the judge less to object to;
# it moves it down only by removing pairs that were never one claim.
_DTREE_OPEN_RE   = re.compile(r"^[ \t]*\*\*\s*IF\s*\*\*", re.IGNORECASE)
_TABLE_ROW_RE    = re.compile(r"^[ \t]*\|.*\|[ \t]*$")
_TABLE_SEP_RE    = re.compile(r"^[ \t]*\|[\s:|\-]+\|[ \t]*$")
_ATX_HEADING_RE  = re.compile(r"^[ \t]*#{1,6}[ \t]+\S")
# A bold label opening a line, with content after it on the same line. The
# negative lookahead keeps the decision-tree keywords out: they are handled by
# the branch rule above, which must not be cut into three by this one.
_INLINE_LABEL_RE = re.compile(
    r"^[ \t]*\*\*(?!\s*(?:IF|THEN|BECAUSE)\s*\*\*)[^*\n]{2,100}\*\*[ \t]*:?[ \t]*\S",
    re.IGNORECASE)
# `*` needs the trailing space to be a bullet: `**bold**` is not a list.
_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-•+]|\*(?!\*)|\d{1,2}[.)])[ \t]+\S")

# Shape names, used in the audit record and in the before/after reporting.
SHAPE_PROSE  = "prose"
SHAPE_DTREE  = "decision_tree"
SHAPE_TABLE  = "table_row"
SHAPE_LABEL  = "bold_label"
SHAPE_LIST   = "list_item"
CLAIM_SHAPES = (SHAPE_PROSE, SHAPE_DTREE, SHAPE_TABLE, SHAPE_LABEL, SHAPE_LIST)


def _flatten_table_row(line: str) -> str:
    """`| aPDT laser | Diode, 660 nm · 100 mW |` -> `aPDT laser — Diode, ...`.

    The pipes are layout. The judge is asked whether a paper supports a
    proposition, and `| a | b |` is not one — the cells joined by an em dash
    are, and the marker stays inside the cell it was written in.
    """
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    cells = [c for c in cells if c]
    return " — ".join(cells)


def _segment_body(body: str):
    """Yield (shape, text) for a section body, before sentence splitting.

    Line-driven rather than regex-split, because these three shapes are
    defined by what a LINE starts with and a split on any one of them loses
    the boundaries of the other two.
    """
    lines = (body or "").split("\n")
    prose, dtree = [], []
    prose_shape = [SHAPE_PROSE]   # list so the closures can rebind it

    def flush_prose():
        if prose:
            chunk = "\n".join(prose)
            shape = prose_shape[0]
            prose.clear()
            prose_shape[0] = SHAPE_PROSE
            if chunk.strip():
                return (shape, chunk)
        return None

    def flush_dtree():
        if dtree:
            chunk = "\n".join(dtree)
            dtree.clear()
            if chunk.strip():
                return (SHAPE_DTREE, chunk)
        return None

    for line in lines:
        opens_branch = bool(_DTREE_OPEN_RE.match(line))
        is_table     = bool(_TABLE_ROW_RE.match(line))
        is_heading   = bool(_ATX_HEADING_RE.match(line))
        is_item      = bool(_LIST_ITEM_RE.match(line))
        # A bullet whose text opens with a bold label is a list item first —
        # the bullet is the boundary, the label is decoration inside it.
        is_label     = bool(_INLINE_LABEL_RE.match(line)) and not is_item

        if dtree:
            # Inside a branch. It ends at the next **IF**, or at any structure
            # that cannot be part of it: a table, a heading, a bold pseudo-
            # heading on its own line. THEN/BECAUSE and their continuations
            # stay attached, which is the whole point of the branch unit.
            if opens_branch or is_table or is_heading or \
                    _PSEUDO_HEADING_RE.match(line):
                seg = flush_dtree()
                if seg:
                    yield seg
            else:
                dtree.append(line)
                continue

        if opens_branch:
            seg = flush_prose()
            if seg:
                yield seg
            dtree.append(line)
            continue

        if is_table:
            seg = flush_prose()
            if seg:
                yield seg
            if not _TABLE_SEP_RE.match(line):
                flat = _flatten_table_row(line)
                if flat:
                    yield (SHAPE_TABLE, flat)
            continue

        if is_item or is_label:
            # A list item or a bold label starts a new sub-point; whatever
            # came before it is finished. A continuation line matches neither
            # and so stays with the item it wraps from.
            seg = flush_prose()
            if seg:
                yield seg
            prose_shape[0] = SHAPE_LIST if is_item else SHAPE_LABEL

        prose.append(line)

    seg = flush_dtree()
    if seg:
        yield seg
    seg = flush_prose()
    if seg:
        yield seg


def _split_claim_units_tagged(body: str) -> list:
    """Split a section body into [(shape, claim_unit), ...].

    A bold pseudo-heading on its own line is a hard boundary — it is a
    heading, never part of a claim — and inside each prose block the sentence
    split respects abbreviations. Deliberately NOT folded into
    `_split_sections`: that would also change which sections
    `_is_exempt_section` skips and how `_detect_gap_sections` counts, and
    neither of those is the defect here. Widening `_HEADING_RE` would
    additionally make a `**Key Takeaways**` pseudo-heading EXEMPT and so
    reduce what the guardrail checks, which is the wrong direction for a
    safety gate.

    A decision-tree branch and a table row are returned WHOLE: they are
    already claim-sized, and running the sentence splitter over a branch would
    strand `**BECAUSE** ...` away from the `**THEN** ...` it justifies.
    """
    out = []
    for shape, chunk in _segment_body(body or ""):
        if shape in (SHAPE_DTREE, SHAPE_TABLE):
            out.append((shape, chunk))
            continue
        # A bold-label run is still prose inside; the label only says where it
        # STARTED, which is what the reporting needs in order to attribute a
        # flag to the shape that used to merge it.
        for block in _PSEUDO_HEADING_RE.split(chunk):
            cleaned = re.sub(r"^\s*[-*•]\s+", "", block, flags=re.MULTILINE)
            out.extend((shape, s) for s in _SENTENCE_SPLIT_RE.split(cleaned))
    return out


def _split_claim_units(body: str) -> list:
    """PROSE-ONLY claim units — what `_detect_unattributed_claims` still uses.

    Deliberately NOT `_split_claim_units_tagged` minus the shapes, and the
    difference is a scoping decision rather than an oversight.

    `_detect_unattributed_claims` feeds `validate_evidence_mapping`, which
    FAILS an answer and buys a full Opus regeneration. Under the shape-aware
    split, a materials-table row like `| Irrigant | 2.5% NaOCl · 60 sec |`
    stops being part of a blob that cites something and becomes a unit of its
    own with a numeric parameter and no marker — a new UNATTRIBUTED_CLAIMS
    finding, on rows that today are silently absorbed. That may well be right:
    an uncited numeric protocol row is exactly what invariant 6 exists for.
    But it changes the retry rate, and the retry rate is what the very next
    item in this batch measures. Two changes to the same number in one batch
    is the confound this item was split out to avoid.

    So: the CHECKER sees the real claim units (it only annotates), and the
    VALIDATOR keeps the unit it had (it can reject). Recorded in
    OVERNIGHT_REPORT_3.md as found-not-fixed with the measurement it needs.
    """
    out = []
    for block in _PSEUDO_HEADING_RE.split(body or ""):
        cleaned = re.sub(r"^\s*[-*•]\s+", "", block, flags=re.MULTILINE)
        out.extend(_SENTENCE_SPLIT_RE.split(cleaned))
    return out


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

    Quarantine blocks are removed first (`trust-surface-v1` Q2). The block
    header attributes everything inside it, unmissably and in the answer text
    itself, so flagging those sentences again would fail an answer for using
    the structure the prompt requires — the same trap `_UNSOURCED_LABEL_RE`
    exists to avoid, one level up.
    """
    answer = _strip_quarantine_blocks(answer)
    flagged = []
    for title, body in _split_sections(answer):
        if _is_exempt_section(title):
            continue
        # Strip markdown bullets/headings before splitting into sentences
        for sent in _split_claim_units(body):
            s = sent.strip()
            if len(s) < 20:
                continue
            # Skip sentences that already have a marker
            if _PMID_RE.search(s):
                continue
            # ...or that say out loud where they came from instead. A claim
            # labelled "standard practice, not from the retrieved evidence
            # base" is attributed to the clinician's own judgement, which is
            # the honest ending for a step the literature does not cover. The
            # prompt offers this move; flagging it anyway would make the
            # honest answer and the silent one fail identically.
            if _UNSOURCED_LABEL_RE.search(s):
                continue
            # Does this sentence look like a clinical claim?
            for pat in _CLAIM_PATTERNS:
                if pat.search(s):
                    flagged.append({"sentence": s[:240], "section": title})
                    break
    return flagged


def _detect_uncited_author_mentions(answer: str) -> list:
    """Named authors introduced with no `[[PMID:N]]` marker on the same claim.

    "Sjogren et al. demonstrated that pulp status at the time of treatment is
    the dominant determinant of outcome" tells the clinician a specific paper
    exists and gives them nothing to click. That is a FORMAT violation, not a
    judgement call: the prompt's own rule is that every inline reference is
    wrapped as `[[PMID:N]]`, and an author surname is an inline reference.

    Deliberately scoped to the CLAIM UNIT, not the sentence: a name in the
    same unit as a marker is attributed, even if the marker sits on the
    neighbouring clause. Being stricter than that would flag the normal and
    correct "Sjögren et al. found X [[PMID:N]]".

    Returns [{name, sentence, section}].
    """
    out = []
    for title, body in _split_sections(answer):
        if _is_exempt_section(title):
            continue
        for sent in _split_claim_units(body):
            s = sent.strip()
            if len(s) < 20 or _PMID_RE.search(s):
                continue
            for m in _AUTHOR_MENTION_RE.finditer(s):
                if m.group(1) in _AUTHOR_MENTION_STOPWORDS:
                    continue
                out.append({"name": m.group(0), "sentence": s[:240],
                            "section": title})
                break
    return out


# ── OUT-OF-DOMAIN CONTENT IS QUARANTINED, NOT MIXED IN ────
#
# `trust-surface-v1` Q2, implementing RB's decision of 2026-09-02: Curo MAY
# answer beyond its evidence base, but that content is visually and
# structurally separated, and the answer then returns to the decision Curo can
# support.
#
# The apixaban answer is what the decision was made against. Its second
# paragraph opens "From the wider literature (which this search did not return
# …)" and then delivers, in ordinary prose indistinguishable from the cited
# paragraphs around it, a complete DOAC management protocol: bleeding-risk
# classification, a haemostatic-measures list, a dosing interval, two patient
# thresholds, and a bridging instruction. Nothing in the rendering said which
# half of the answer the library stood behind.
#
# WHY THIS NORMALISES SERVER-SIDE rather than in the browser. Q2a requires the
# block to survive EVERY export path — PDF, clipboard, slides, speaker notes,
# narration. The one representation all of them already consume is the answer
# text, so the quarantine is written INTO it, in markdown that stays readable
# if a path never learns to upgrade it. The browser then styles the same block
# into a bordered container; it does not create it.
#
# HOW THE SPAN IS FOUND. The model already labels this content out loud —
# `_UNSOURCED_LABEL_RE` is the vocabulary the prompt offers and the escape
# hatch `_detect_unattributed_claims` honours. That label starts the run; the
# run extends forward over following claim units until one carries a citation
# or the paragraph ends. It stops at a citation because a cited claim is by
# definition back inside the evidence base — which is exactly the reframe Q2c
# requires, so the boundary and the reframe are the same event.
#
# The run is extended over ANY uncited unit, not only directive ones. In the
# fixture that is what pulls "Bridging with LMWH is not indicated" and "INR
# testing is not applicable" — two short sentences carrying no numbers and no
# label of their own — into the block with the paragraph they belong to.
# Leaving them outside would satisfy the letter of the item and none of it:
# they are the two most quotable directives in the answer.

_QUARANTINE_HEADER = "⚠ **NOT FROM THE EVIDENCE BASE — UNVERIFIED**"
_QUARANTINE_NOTE   = ("_General clinical knowledge. No paper in this library was "
                      "retrieved for it and nothing below was checked against an "
                      "abstract._")
_QUARANTINE_FOOTER = "**Consult directly:**"

# Recognises a block already in place, so the pass is idempotent and so a model
# that has learned to emit the structure itself is not double-wrapped.
_QUARANTINE_BLOCK_RE = re.compile(
    r"(?:^>[^\n]*\n?)*?^>[ \t]*"
    + re.escape(_QUARANTINE_HEADER)
    + r"[\s\S]*?^>[ \t]*"
    + re.escape(_QUARANTINE_FOOTER)
    + r"[^\n]*\n?",
    re.MULTILINE)

# Bodies whose guidance the answer is standing on. Named in the footer so the
# clinician is pointed at the actual document rather than told, vaguely, to
# look elsewhere. Order-preserving and de-duplicated at use.
_AUTHORITY_BODY_RE = re.compile(
    r"\b(?:SDCEP|ESE|AAE|ADA|BDA|BSH|BSHT|ACC/AHA|ACC|AHA|ISTH|NICE|SIGN|WHO"
    r"|FDA|EMA|EFP|AAOMR|AAOM|IADT|FDI|EAPD|AAPD|ASA|ESC|RCS|SDCEP)\b")

_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n")


def _quarantine_footer(text: str) -> str:
    """The footer line, naming the guideline bodies the span leans on."""
    seen, bodies = set(), []
    for m in _AUTHORITY_BODY_RE.finditer(text or ""):
        name = m.group(0)
        if name not in seen:
            seen.add(name)
            bodies.append(name)
    if bodies:
        return (f"> {_QUARANTINE_FOOTER} " + " · ".join(bodies[:6]) +
                " — Curo has not retrieved or checked these sources.")
    return (f"> {_QUARANTINE_FOOTER} the specialty guidelines for this "
            "question — Curo has not retrieved or checked them.")


def _quarantine_block(units: list) -> str:
    """One quarantined span, as the markdown every surface will carry."""
    text = " ".join(u.strip() for u in units if u.strip())
    lines = [f"> {_QUARANTINE_HEADER}", ">", f"> {_QUARANTINE_NOTE}", ">",
             "> " + text, ">", _quarantine_footer(text)]
    return "\n".join(lines)


def quarantine_unsourced_content(answer: str):
    """Lift labelled out-of-domain prose into its own delimited block.

    Returns `(answer, blocks)` where `blocks` is the list of quarantined
    texts, in document order. Idempotent: an answer already carrying blocks is
    returned unchanged.

    Q2b — "may never be interleaved with cited prose in the same paragraph" —
    is enforced by SPLITTING the paragraph: anything before the label and
    anything from the first cited unit onward stay as ordinary prose, and only
    the run between them is wrapped.
    """
    if not answer:
        return answer or "", []

    blocks = []
    out_sections = []
    for title, body in _split_sections(answer):
        rebuilt = []
        for para in _PARAGRAPH_SPLIT_RE.split(body or ""):
            stripped = para.strip()
            # A blockquote is ALREADY a delimited block, and the engine's own
            # blocks are blockquotes: the citation-support status block, the
            # flagged-claim list, the validation warning, and a quarantine
            # block itself. Quarantining inside one is never right, and it made
            # `finalise_answer_text` non-idempotent — the status block quotes
            # the flagged claims verbatim, those quotes carry the "from the
            # wider literature" vocabulary, and a second pass wrapped the
            # banner in the very block it was reporting on.
            #
            # Found by `test_re_rendering_is_idempotent`, which A16 needs
            # because the archive routes now re-render on every read.
            already_a_block = (stripped.startswith(">")
                               or bool(_QUARANTINE_BLOCK_RE.search(para)))
            if not stripped or already_a_block:
                rebuilt.append(para)
                continue
            units = _SENTENCE_SPLIT_RE.split(para)
            start = None
            for i, u in enumerate(units):
                if _ANY_CITATION_RE.search(u):
                    continue
                if _UNSOURCED_LABEL_RE.search(u):
                    start = i
                    break
            if start is None:
                rebuilt.append(para)
                continue
            end = start
            while end + 1 < len(units) and not _ANY_CITATION_RE.search(units[end + 1]):
                end += 1
            before = " ".join(u.strip() for u in units[:start] if u.strip())
            after  = " ".join(u.strip() for u in units[end + 1:] if u.strip())
            block  = _quarantine_block(units[start:end + 1])
            blocks.append(" ".join(u.strip() for u in units[start:end + 1] if u.strip()))
            piece = ([before] if before else []) + [block] + ([after] if after else [])
            rebuilt.append("\n\n".join(piece))
        new_body = "\n\n".join(p for p in rebuilt)
        out_sections.append((title, new_body))

    if not blocks:
        return answer, []

    # Reassemble with the heading markers the split consumed. `_split_sections`
    # reports the title text only, so the level is recovered from the original.
    levels = {m.group(2).strip(): m.group(1) for m in _HEADING_RE.finditer(answer)}
    parts = []
    for title, body in out_sections:
        if title == "(intro)":
            parts.append(body)
        else:
            parts.append(f"{levels.get(title, '##')} {title}\n\n{body}")
    return "\n\n".join(parts).strip(), blocks


# ── THE BIBLIOGRAPHY IS THE CITATION SET ──────────────────
#
# `trust-surface-v1` Q5. The apixaban Review answer listed 29 papers under
# "FULL BIBLIOGRAPHY" and cited 7 of them — including Sjögren 1990, which is
# the same uncited boilerplate seen in the anesthesia curriculum. That
# confirms the defect is STRUCTURAL rather than a truncation artifact, and
# that it affects Review as well as Deep Learning.
#
# The cause: the browser's bibliography was built from `job.papers`, which is
# `evidence["_summary"]["all_scored"]` — the RETRIEVAL CANDIDATE POOL. A
# bibliography is a list of what an answer drew on. A list of what a search
# returned is a different document, and presenting one as the other inflates
# the apparent evidence base by 4x and puts papers the answer never read under
# a heading that says it did.
#
# The deck path already had this right (`webdeck.plan.build_reference_slides`
# takes `cited_pmids`), which is why the defect was visible on one surface and
# not the other. This is that logic, lifted to where both can share it.
#
# The pool is NOT hidden — it is disclosed separately, under a heading that
# says what it is. Q5 allows that explicitly; what it forbids is calling it a
# bibliography.
def assemble_bibliography(answer: str, papers: list) -> dict:
    """Split a retrieval pool into what the answer cited and what it did not.

    Returns {"cited": [...], "uncited": [...], "cited_pmids": [...]} with the
    pool's own ordering preserved inside each list. `cited_pmids` includes
    every id the answer cites, in first-seen order, INCLUDING any the pool
    does not contain — a citation to a paper missing from the payload is a
    finding, not something to drop silently.
    """
    # IN-TEXT markers only. The final numbered REFERENCES list is deliberately
    # NOT a source here, even though it uses a PMID key of its own: that list
    # is supposed to BE the citation set, so treating it as an input would let
    # a padded reference list re-inflate the bibliography it is meant to
    # mirror — the same defect, one layer along. A mutation run found this:
    # dropping the in-text scan entirely changed nothing, because the
    # reference list alone reproduced all seven ids.
    cited_ids = list(dict.fromkeys(_extract_cited_pmids(answer)))
    cited_set = set(cited_ids)
    cited, uncited = [], []
    for paper in (papers or []):
        pid = str((paper or {}).get("pmid") or "").strip()
        (cited if pid and pid in cited_set else uncited).append(paper)
    return {"cited": cited, "uncited": uncited, "cited_pmids": cited_ids}


# Answers written before Q1 carry a citation-support block with only the FIRST
# number in it. `finalise_answer_text` runs on the cache-hit path, so those
# answers get their impact factors stripped and their out-of-domain content
# quarantined — and then render "CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT" as
# a clean tick over the five uncited directives the quarantine block was just
# built around.
#
# Found by asking the apixaban question through the restarted server: the block
# rendered, the count did not, and the banner was the pre-Q1 tick. That is the
# exact defect Q1 exists to fix, surviving on the one path that does not
# regenerate the answer.
_UNCITED_HALF_RE = re.compile(
    r"\d+\s+claims?\s+not\s+from\s+the\s+evidence\s+base", re.IGNORECASE)
_SUPPORT_BLOCK_RE = re.compile(
    r"^>\s*[\u2713\u26a0\u25cb][^\n]*\*\*Citation support:", re.MULTILINE)


def ensure_uncited_half(answer: str) -> str:
    """Add the banner's second number to an answer that predates it.

    A no-op when the answer already carries the count, when it has no
    citation-support block to attach to, or when there is nothing to report.
    """
    if not answer or _UNCITED_HALF_RE.search(answer):
        return answer or ""
    m = _SUPPORT_BLOCK_RE.search(answer)
    if not m:
        return answer
    found = _detect_uncited_directive_claims(answer)
    if not found:
        return answer
    support = {"flags": [], "checked": 0, "status": "silent",
               "uncited_directive": len(found), "uncited_directive_claims": found}
    # Reuse the one renderer, so a cached answer and a fresh one word the
    # second half identically.
    half = _append_support_warnings("", support)
    marker = "\n>\n> \u26a0"
    half = half[half.index(marker):] if marker in half else ""
    if not half:
        return answer
    end = answer.find("\n\n", m.end())
    end = len(answer) if end == -1 else end
    return answer[:end] + half + answer[end:]


# ── A QUESTION'S TITLE IS THE QUESTION, NOT THE TRANSCRIPT ──
#
# A15f.1. When the clinician answers the clarifying questions, `/ask` builds
#
#     f"{question}\n\nAdditional clinical context provided by the clinician:\n{context}"
#
# and everything downstream — the cache key, the learn-history record, the
# history sidebar — stores THAT as the question. So the report list reads
#
#   "vital pulp therapy in adults Additional clinical context provided by the
#    clinician: Q1: Are you asking about a specific patient case (e.g.,
#    traumatized tooth, carious exposure, asym…"
#
# The context belongs to the answer; it is not the title.
#
# `query_cache.question_text` is load-bearing — it is the semantic lookup key,
# so the stored string must keep the context or a follow-up would collide with
# its own parent. That is why this truncates at DISPLAY time for cache rows,
# while `save_learn_output` stores the clean question outright: fix it at the
# source where there is a free field, truncate where there is not.
_TITLE_CONTEXT_MARKER = "Additional clinical context provided by the clinician"


def display_title(question: str, limit: int = 160) -> str:
    """The clinician's own question, without the appended clarification block."""
    q = (question or "").strip()
    i = q.find(_TITLE_CONTEXT_MARKER)
    if i > 0:
        q = q[:i].rstrip(" \n:\u2014-")
    q = " ".join(q.split())
    return q if len(q) <= limit else q[:limit - 1].rstrip() + "\u2026"


def finalise_answer_text(answer: str):
    """Everything a finished answer goes through before anything renders it.

    ONE list, in one place. These normalisations have to happen on every path
    that produces an answer AND on the path that serves a cached one, and a
    convention spread over six call sites is how a surface gets missed — which
    is the shape of most of `trust-surface-v1`.

    Order matters: the impact factor is stripped first, so a reference line
    inside a quarantined span cannot carry one past the block boundary.

    Returns `(answer, quarantined_blocks)`.
    """
    answer = strip_impact_factor(answer)
    answer, blocks = quarantine_unsourced_content(answer)
    # Last, so it counts the quarantined content the step above just created.
    return ensure_uncited_half(answer), blocks


def _strip_quarantine_blocks(answer: str) -> str:
    """The answer with every quarantine block removed.

    `_detect_unattributed_claims` reads this rather than the raw answer: the
    block header attributes everything inside it, out loud and unmissably, so
    flagging those sentences again would punish the model for using the
    structure the prompt now requires. It is the same reasoning that makes
    `_UNSOURCED_LABEL_RE` an exemption there — the block is that label, in
    structural form.

    `_detect_uncited_directive_claims` deliberately does NOT strip them — the
    banner's second number is what quarantined content feeds (Q2b). It reads
    `_quarantine_content_only` instead, for the reason recorded there.
    """
    return _QUARANTINE_BLOCK_RE.sub("", answer or "")


def _quarantine_content_only(answer: str) -> str:
    """Quarantine blocks reduced to the prose inside them.

    FOUND BY MEASURING THE POST-FIX ANESTHESIA CURRICULUM (`dl-quality-v2` M2),
    and it is a defect Stage 1 introduced. `_detect_uncited_directive_claims`
    was reading the raw answer, so it counted the block's own FURNITURE — the
    header, the note, the "Consult directly:" footer — as uncited clinical
    claims:

        total flagged in the regenerated curriculum   24
        ...that were quarantine furniture             12   (50%)

    Curo wrote those lines to LABEL unverified content. Counting them as
    unverified content is circular, and it doubled the number on the one
    surface whose whole purpose is to be believed.

    It did not show up in Stage 1 because no stored answer had a block yet: 0
    of 197 flags across the 22 stored curricula are furniture. Every document
    generated from now on would have had it.

    Two things are fixed at once. The `>` prefixes go, and the block is
    surrounded by blank lines — so a claim unit can no longer fuse the footer
    onto the numbered step that follows it, which is what produced flags
    reading `...checked against an abstract._ > > 4. **Deliver primary...`.
    """
    def _bare(m):
        kept = []
        for line in m.group(0).splitlines():
            text = re.sub(r"^>[ \t]?", "", line).strip()
            if not text:
                continue
            if (text == _QUARANTINE_HEADER
                    or text.startswith(_QUARANTINE_FOOTER)
                    or text.startswith(_QUARANTINE_NOTE[:40])):
                continue
            kept.append(text)
        return "\n\n" + " ".join(kept) + "\n\n"

    return _QUARANTINE_BLOCK_RE.sub(_bare, answer or "")


def _check_quarantine_reframe(answer: str) -> list:
    """Q2c. A quarantined block must be followed by evidence Curo does hold.

    The point of answering beyond the evidence base is to hand the clinician
    back to a decision the library supports — in the fixture, that the Cochrane
    review found no clear superiority for surgical over non-surgical
    retreatment (RR 1.15, 0.97-1.35), which makes non-surgical retreatment a
    legitimate option for a patient at bleeding risk. That reframe is the most
    valuable sentence in the answer and it was there by accident.

    Scoped to the SECTION: a cited claim anywhere after the block in the same
    section satisfies it. Requiring the very next paragraph would fail answers
    that reframe two sentences later, which is a style, not a defect.
    """
    issues = []
    for title, body in _split_sections(answer or ""):
        for m in _QUARANTINE_BLOCK_RE.finditer(body or ""):
            if not _ANY_CITATION_RE.search(body[m.end():]):
                issues.append(
                    f"UNREFRAMED_QUARANTINE in \"{title}\": content labelled as "
                    "outside the evidence base is not followed by any cited "
                    "claim. State the decision the retrieved literature DOES "
                    "support, with its [[PMID:N]] marker, after the block."
                )
    return issues


# ── UNCITED CLINICAL DIRECTIVES ON THE RENDERED ANSWER ────
#
# `trust-surface-v1` Q1. The apixaban Review answer carried the banner
#
#     CHECKED AGAINST ABSTRACTS: 9/9 CONSISTENT
#
# over a paragraph of drug directives — ">=4 hours after the morning dose",
# "tranexamic acid 4.8% mouthwash", "CrCl <50 mL/min", "age >75", "omit the
# morning dose" — carrying no citation at all. Both halves of that are true and
# together they mislead: `verify_citation_support` examines CITED claims, so an
# uncited claim is not a claim it disagreed with, it is a claim it never saw.
# The banner then asserted verification over the whole answer.
#
# WHY THE EXISTING GATE DID NOT CATCH IT, measured on the fixture:
#
#   `_detect_unattributed_claims` flagged 3, and `_EVMAP_MAX_UNATTRIBUTED` is 3
#   — it hard-fails ABOVE the limit, so the answer passed by one claim. And two
#   of the directives were invisible to it in any case:
#
#     "Bridging with LMWH is not indicated for apixaban."   no claim pattern
#     "INR testing is not applicable."                      no claim pattern
#
#   Those patterns catch a claim by its NUMBERS. A drug directive can be
#   entirely uncited, entirely actionable, and contain no statistic at all —
#   the same shape `case-v3` found chairside, arriving this time as a
#   prescribing instruction.
#
# THIS IS A REPORTER, NOT A GATE. It never blocks or rewrites an answer; it
# produces the second number the banner is required to show beside the first.
# That is deliberate: Q2's decision is that Curo MAY answer beyond its evidence
# base, so the honest handling of a labelled directive is to count it out loud,
# not to refuse it.
#
# TWO DELIBERATE DIFFERENCES FROM `_detect_unattributed_claims`:
#
#  1. `_UNSOURCED_LABEL_RE` does NOT exempt a claim here. Over there the label
#     is an escape hatch and has to count, or the prompt offers "label it", the
#     model labels it, and the honest answer fails identically to the silent
#     one. Here the label is the exact thing being counted: "from the wider
#     literature" is a claim nothing checked, and saying so is the number's
#     whole purpose. The escape hatch still works — a labelled claim does not
#     fail the validator — it simply does not vanish from the banner.
#
#  2. It reads the RENDERED answer. `_ANY_CITATION_RE` accepts the engine's
#     `[[PMID:N]]` and both single-bracket forms the browser and the reference
#     list produce, so the count is identical whether it is computed on the
#     stored answer or on the text a clinician is looking at. `test_uncited_
#     directives.py` asserts that equivalence, because the whole point of Q1a
#     is that the number describes the page, not an intermediate.

# Any inline attribution, in the engine's marker form or in either rendered
# form. `[PMID 27759881]` (no colon) is what the browser copy path emits.
_ANY_CITATION_RE = re.compile(
    r"\[\[PMID:\s*" + _PMID_ID_PAT + r"\s*\]\]"
    r"|\[PMID:?\s*" + _PMID_ID_PAT + r"\s*\]",
    re.IGNORECASE)

# ── what makes a claim DIRECTIVE ──
#
# A disjunction of three shapes, and drug names are deliberately NOT one of
# them. "The retrieved endodontic evidence base does not directly address
# perioperative management of apixaban" names a drug and directs nobody to do
# anything; it is a statement about coverage. Counting it would inflate the
# number with the very sentences that are being honest about the gap. The drug
# vocabulary is still recorded on each finding, because it is what makes a
# directive consequential, but it cannot fire one on its own.

# (a) Deontic: the claim says what should, must, or must not happen.
_DIRECTIVE_DEONTIC_RE = re.compile(
    r"\b(?:should\s+(?:not\s+)?\w+"
    r"|must\s+(?:not\s+)?\w+"
    r"|is\s+(?:not\s+)?indicated\b|are\s+(?:not\s+)?indicated\b"
    r"|is\s+contraindicated\b|are\s+contraindicated\b"
    r"|is\s+(?:not\s+)?recommended\b|are\s+(?:not\s+)?recommended\b"
    r"|is\s+(?:not\s+)?(?:applicable|required|necessary|needed|warranted|advised)\b"
    r"|are\s+(?:not\s+)?(?:applicable|required|necessary|needed|warranted|advised)\b"
    r"|standard\s+practice\s+is\b|usual\s+practice\s+is\b"
    r"|consider\s+\w+ing\b"
    r"|proceed\s+with(?:out)?\b"
    r"|in\s+consultation\s+with\s+the\s+(?:prescribing|treating)\b)",
    re.IGNORECASE)

# (b) Imperative: the claim opens with an instruction verb.
_DIRECTIVE_IMPERATIVE_RE = re.compile(
    r"^\s*(?:Use|Give|Administer|Prescribe|Avoid|Omit|Stop|Continue|Withhold"
    r"|Delay|Schedule|Reduce|Increase|Apply|Place|Check|Monitor|Ensure|Refer"
    r"|Confirm|Repeat|Consider|Discontinue|Resume|Interrupt|Bridge|Screen"
    r"|Do\s+not|Never|Always)\b")

# (c) A clinical quantity a clinician could act on: a dose, a concentration, an
#     interval, a measurement, or a threshold. Thresholds matter as much as
#     doses here — "CrCl <50 mL/min" and "age >75" are the two that decide
#     which arm of the apixaban directive a patient falls into.
_CLINICAL_QUANTITY_RE = re.compile(
    r"\d{1,4}(?:[.,]\d+)?\s*(?:mg|mcg|µg|ug|mmol|mEq|units?|IU"
    r"|m[lL]|L\b|g\b|kg|mm|cm|µm|um|%"
    r"|hours?|hrs?|minutes?|mins?|seconds?|secs?|days?|weeks?|months?|years?)\b"
    r"|[<>≥≤]\s*\d"
    r"|\b\d{1,4}\s*(?:mL/min|mg/kg|mm\s*Hg|mmHg)\b",
    re.IGNORECASE)

# Recorded on a finding, never a trigger. Suffix families first (they
# generalise past any list), then the abbreviations and the agents this
# specialty actually writes down.
_DRUG_VOCAB_RE = re.compile(
    r"\b(?:[A-Za-z]{3,}(?:caine|cillin|azole|xaban|parin|olol|pril|mycin"
    r"|statin|dipine|sartan|prazole|floxacin|dronate|sone|solone|profen)"
    r"|LMWH|DOACs?|NOACs?|INR|NSAIDs?|CrCl|MRONJ"
    r"|warfarin|aspirin|heparin|clopidogrel|tranexamic|paracetamol"
    r"|acetaminophen|adrenaline|epinephrine|chlorhexidine|NaOCl|EDTA"
    r"|calcium\s+hydroxide|MTA|corticosteroid)\b",
    re.IGNORECASE)


# ── WHAT IS NOT A CLINICAL DIRECTIVE (A3b) ────────────────
#
# Hand-adjudicating 40 flagged claims (25 DL, 15 Review, seed 20260902) put the
# detector's precision at 62.5% TRUE / 30% NARRATIVE / 7.5% CITED ELSEWHERE —
# and the over-reach was not spread evenly:
#
#   deontic     n=13   TRUE  4   NARRATIVE  9   (69%)
#   quantity    n=21   TRUE 15   NARRATIVE  3   (14%)
#   imperative  n=6    TRUE  6   NARRATIVE  0   ( 0%)
#
# An imperative verb opening a sentence is always an instruction. The other two
# fire on sentences ABOUT the evidence rather than sentences instructing a
# clinician — two distinct shapes, both excluded below.
#
# This is accuracy, not leniency (standing rule §1.6). Nothing here lowers a
# bar: every one of the 25 TRUE claims in the sample still flags, and
# `tests/test_uncited_directives.py` pins that in both directions.

# (1) The modal governs an INTERPRETATION, not an action. "This should not be
#     interpreted as mandating a switch" tells the reader how to read a finding;
#     "Omit the morning dose" tells them what to do to a patient.
_EPISTEMIC_DIRECTIVE_RE = re.compile(
    r"\b(?:should|must|may|can)\s+(?:not\s+|therefore\s+|then\s+)*"
    r"(?:be\s+)?(?:interpret(?:ed)?|frame[d]?|read|understood|regarded|construed"
    r"|taken\s+as|treated\s+as|distinguish(?:ed)?|recogni[sz]e[d]?|appreciate[d]?"
    r"|note[d]?|remember(?:ed)?|be\s+aware)\b"
    r"|\b(?:is|are)\s+necessary\s+but\s+not\s+sufficient\b"
    r"|\bwhether\s+\w+(?:\s+\w+)?\s+is\s+indicated\b"
    r"|\b(?:RCTs?|trials?|studies|research|evidence)\b[^.]{0,60}?"
    r"\b(?:are|is)\s+(?:required|needed|warranted)\b",
    re.IGNORECASE)

# (2) The sentence DESCRIBES the evidence base rather than instructing. Its
#     numbers are study counts, follow-up windows and effect sizes — the
#     furniture of a literature summary, not parameters a clinician sets.
# NOTE the two phrases deliberately ABSENT: "evidence base" and "the
# literature". Those are the UNSOURCED-LABEL vocabulary — "not from the
# retrieved evidence base", "from the wider literature" — and Q1's whole design
# is that a labelled directive is still counted, because the label is the thing
# the banner is reporting. Including them here vetoed
#
#   "From the wider literature, not from the retrieved evidence base: the drug
#    should not be routinely interrupted."
#
# which is a drug directive with a label on it, and is exactly what this
# detector exists to find. Caught by `test_the_unsourced_label_does_not_exempt_
# a_claim_here`, which Q1 wrote for precisely this confusion.
_EVIDENCE_DESCRIPTION_RE = re.compile(
    r"\b(?:systematic\s+reviews?|meta-?analys[ie]s|RCTs?|randomi[sz]ed\s+trials?"
    r"|included\s+(?:studies|trials)|prospective\s+stud(?:y|ies)|cohort\s+stud"
    r"|evidence\s+gap|these\s+(?:studies|trials)"
    r"|represents?\s+Level\s+[IVX0-9]+\s+evidence|GRADE\s+(?:rating|certainty)"
    r"|both\s+sources|sources?\s+converge|remarkably\s+concordant)\b",
    re.IGNORECASE)


# (3) …but a sentence can be ABOUT the evidence and still instruct, and the
#     first cut of the veto above threw four real directives away:
#
#       "The evidence base does not specify a tolerance value … apply standard
#        clinical practice (±0.5 mm of the radiographic apex)."
#       "Delivery method was not specified in either study — use a side-vented
#        needle and deliver to working length −1 mm."
#
#     Both name the evidence gap and then tell the clinician exactly what to do.
#     Vetoing them is leniency, which standing rule §1.6 forbids. So the veto
#     only applies when the sentence carries NO clinical action at all.
#
#     Deliberately narrow: physical and prescribing verbs. "select", "treat" and
#     "consider" are excluded because they are as often epistemic as clinical
#     ("whether laser is indicated and which modality to select", "should be
#     treated as expert-level awareness").
_CLINICAL_ACTION_RE = re.compile(
    r"\b(?:use|using|apply|applies|applied|deposit|deliver|delivered|administer"
    r"|inject|insert|place|placed|remove|irrigate|activate|flush|schedule"
    r"|confirm|verify|check|repeat|omit|withhold|discontinue|avoid|prescribe"
    r"|give|given|set|seal|obturate|prepare|isolate|re-?administer|reinject"
    r"|reduce|increase|wait|allow)\b",
    re.IGNORECASE)


def _claim_is_directive(sentence: str) -> str:
    """Which directive shape fired, or "" — see the patterns above.

    An imperative opening the sentence is always an instruction. A deontic or a
    bare clinical quantity is an instruction unless the sentence is talking
    ABOUT the evidence and asks the clinician to do nothing.
    """
    s = sentence or ""
    if _DIRECTIVE_IMPERATIVE_RE.search(s):
        return "imperative"
    about_the_evidence = bool(_EPISTEMIC_DIRECTIVE_RE.search(s)
                              or _EVIDENCE_DESCRIPTION_RE.search(s))
    asks_for_an_action = bool(_CLINICAL_ACTION_RE.search(s))
    meta = about_the_evidence and not asks_for_an_action
    if _DIRECTIVE_DEONTIC_RE.search(s):
        return "" if meta else "deontic"
    if _CLINICAL_QUANTITY_RE.search(s):
        return "" if meta else "quantity"
    return ""


def _detect_uncited_directive_claims(answer: str) -> list:
    """Clinically directive claims in `answer` that carry no attribution.

    Returns [{sentence, section, shape, names_drug}] in document order. Uses
    the same section exemptions and the same claim-unit split as every other
    checker, so a "claim" means one thing across the whole file.
    """
    out = []
    # Quarantined CONTENT is counted (Q2b); the block's own furniture is not.
    # See `_quarantine_content_only` — half the flags on the first curriculum
    # generated after Stage 1 were the header and footer Curo writes to label
    # the block.
    for title, body in _split_sections(_quarantine_content_only(answer or "")):
        if _is_exempt_section(title):
            continue
        for sent in _split_claim_units(body):
            s = sent.strip()
            if len(s) < 20:
                continue
            if _ANY_CITATION_RE.search(s):
                continue
            shape = _claim_is_directive(s)
            if not shape:
                continue
            out.append({"sentence": s[:240], "section": title, "shape": shape,
                        "names_drug": bool(_DRUG_VOCAB_RE.search(s))})
    return out


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
    out = {"present": False, "has_citation": False, "names_tier": False,
           "text": "", "issues": []}
    for title, body in _split_sections(answer or ""):
        if not title.strip().lower().startswith("clinical recommendation"):
            continue
        out["present"] = True
        out["text"] = (body or "").strip()
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

    # Non-numeric markers ("[[PMID:AAE-PS-obturation]]") used to need a second
    # scan here, because `_PMID_RE` was numeric-only and this was the one
    # consumer that had been taught otherwise. `_PMID_RE` now matches both id
    # shapes, so `cited` above already contains them and the re-scan would only
    # be a second place for the two shapes to drift apart. They are still NOT
    # automatically fabrications — hand-ingested authority documents carry
    # synthetic identifiers — and the test is unchanged: is it in the evidence
    # base? (`trust-surface-v1` Q4.)

    unattributed = _detect_unattributed_claims(answer)
    gaps         = _detect_gap_sections(answer)
    # `case-v3` Item B(c). A named author with nothing to click is a format
    # violation on the same footing as a bare PMID: it asserts that a specific
    # paper says this, and hands the clinician no way to check.
    author_mentions = _detect_uncited_author_mentions(answer)

    # Total cite-required sections (everything non-exempt with body)
    total_cite_required = 0
    for title, body in _split_sections(answer):
        if _is_exempt_section(title) or title == "(intro)":
            continue
        if body and len(body) >= 80:
            total_cite_required += 1
    gap_ratio = (len(gaps) / total_cite_required) if total_cite_required else 0.0

    rec = _check_recommendation(answer)
    # `trust-surface-v1` Q2c. Answering beyond the evidence base is allowed;
    # leaving the clinician there is not. A quarantine block must be followed
    # by the decision the retrieved literature DOES support.
    reframe_issues = _check_quarantine_reframe(answer)

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
    elif author_mentions:
        # No tolerance count, unlike unattributed claims. An unattributed
        # claim can be a background sentence the pattern read too eagerly; a
        # named author is unambiguous — the model reached for a specific paper
        # and did not wrap it. One is enough.
        names = ", ".join(sorted({a["name"] for a in author_mentions})[:5])
        failure_reason = (f"UNCITED_AUTHOR_MENTION: {len(author_mentions)} "
                          f"named author(s) with no [[PMID:N]] marker ({names})")
    elif reframe_issues:
        # Last in the chain deliberately: it can only fire on an answer that
        # already carries a quarantine block, which means the model did the
        # honest thing and then stopped one sentence short.
        failure_reason = "; ".join(reframe_issues)

    # Score: fabrication is dominant penalty
    score = 100
    score -= 30 * len(fabricated)
    score -= 5  * max(0, len(unattributed) - 1)
    score -= 10 * len(gaps)
    score -= 10 * len(rec["issues"])
    score -= 10 * len(author_mentions)
    score -= 10 * len(reframe_issues)
    score = max(0, min(100, score))

    return {
        "passed":               failure_reason is None,
        "score":                score,
        "evidence_pmids":       evidence_pmids,
        "cited_pmids":          cited_set,
        "fabricated_pmids":     fabricated,
        "valid_pmids":          valid,
        "unattributed_claims":  unattributed,
        "author_mentions":      author_mentions,
        "gap_sections":         gaps,
        "total_cite_required":  total_cite_required,
        "recommendation":       rec,
        "quarantine_issues":    reframe_issues,
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
    # The recommendation, in enough detail to diagnose a retry after the fact.
    # Seven UNTRACEABLE_RECOMMENDATION failures were logged on 2026-09-01, each
    # costing a full Opus regeneration, and the log said only that the section
    # had no marker — not what the model actually wrote there, so answering
    # "was it a citation it could not ground, or a citation it forgot?"
    # required generating the failures again. The text is what makes the
    # question answerable from the log.
    rec = result.get("recommendation") or {}
    if rec:
        record["rec"] = {
            "present":      rec.get("present"),
            "has_citation": rec.get("has_citation"),
            "names_tier":   rec.get("names_tier"),
            # Truncated, because this log is append-only and read by hand. Two
            # to four sentences is the whole section by construction.
            "text":         (rec.get("text") or "")[:900],
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
        # ORDER IS LOAD-BEARING, and it is the product of two batches that
        # pull in opposite directions.
        #
        # `guardrails-v1` established that the marker option must NOT lead:
        # this message reaches the model AFTER it has been told its answer
        # failed, which is the moment a decorative citation is cheapest to
        # add and hardest to notice. `case-v3` Item D then established that
        # the message must offer the LABEL, because a retry given only
        # "rephrase or delete" turned 7 unattributed claims into 8 by
        # rewriting the same uncited protocol in different words.
        #
        # Item D added the label and, in doing so, moved MARK back to the
        # front. The full suite caught it: two `tests/test_grounding_rule.py`
        # assertions, written against a measurement, went red. Both are
        # satisfiable at once, and this is the order that does it. The two
        # moves that CANNOT produce a decorative citation come first; the
        # one that can comes last, carrying its condition.
        parts.append(
            f'\n2. **UNATTRIBUTED CLAIMS** — {len(ua)} sentence(s) make clinical/numeric claims with no '
            f'[[PMID:N]] marker. You have THREE moves. The first two cannot produce a decorative '
            f'citation, and one of them is usually the right ending for a chairside protocol step:\n'
            f'   (a) REPHRASE it so it no longer asserts an evidence-derived fact — drop the '
            f'percentage, the success rate, the comparative claim like \'superior to\' — or delete it.\n'
            f'   (b) LABEL it. If the step is genuinely standard practice and the clinician needs '
            f'it, keep it and say where it comes from: end the sentence \'— standard practice, not '
            f'from the retrieved evidence base\'. That counts as attribution and this warning will '
            f'clear. Use it for a real convention; do not use it to keep a number you invented.\n'
            f'   (c) Add a marker — ONLY where a paper in the evidence block actually states '
            f'that sentence. A marker asserts the cited paper says this, and adding one to clear '
            f'this warning is a worse answer than the unmarked sentence you started with.\n'
            f'   Do NOT simply rewrite the same uncited instructions in different words. That is '
            f'what happened on a previous retry of this kind — 7 unattributed claims became 8 — '
            f'and it costs a full regeneration to arrive nowhere. Examples:\n   - {sample}'
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

    if result.get("author_mentions"):
        am = result["author_mentions"]
        sample = "\n   - ".join(a["sentence"] for a in am[:4])
        parts.append(
            f"\n**NAMED AUTHORS WITH NO MARKER** — {len(am)} sentence(s) name "
            f"a specific author or study and carry no `[[PMID:N]]`. Naming an "
            f"author asserts that a particular paper says this, so it needs "
            f"the same marker any other claim about a paper needs. Either wrap "
            f"the paper you mean, or — if you cannot find it in the evidence "
            f"block — remove the name and state the point without attributing "
            f"it to anyone. Do NOT keep the name and attach the nearest PMID: "
            f"that clears this warning and misleads the reader, which is the "
            f"worse of the two failures. Examples:\n   - {sample}")

    if result.get("quarantine_issues"):
        parts.append(
            "\n**OUT-OF-DOMAIN CONTENT LEFT HANGING** — " +
            "; ".join(result["quarantine_issues"]) +
            " Answering beyond the retrieved literature is allowed and often "
            "right; leaving the clinician outside it is not. After the "
            "unverified block, return to what this evidence base DOES support "
            "and say what it means for the decision in front of them — even "
            "when that is \"the alternative treatment is a legitimate option\". "
            "One cited sentence is enough. Do not add a marker to the "
            "unverified content itself to satisfy this: it is unverified, and "
            "saying so is the point."
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
        "block. And do not MOVE a marker onto a claim its paper does not state: a citation that exists in the "
        "evidence block but does not support the sentence it is attached to clears this validator and fails "
        "the reader, which is the worse of the two failures. If the evidence base genuinely lacks coverage "
        "for a point, say so explicitly."
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
# None = NO CAP. Every cited claim in an answer is checked.
#
# This was 30, and it bound on three of four modules in both stored curricula:
# 117 of 130 claims checked on the anesthesia run, 120 of 133 on the laser run
# — 13 unchecked in each. The rendered block said so honestly ("4 further cited
# claim(s) were NOT checked"), which is invariant 15 working and is the only
# reason this was findable at all. But a guardrail that declines to look at 10%
# of a curriculum's claims is a guardrail with a hole in it, and the claims it
# skipped were the LAST ones in each module — the clinical-application
# protocols, which are the sentences most likely to be acted on.
#
# COST IS NOW LINEAR IN CLAIMS, deliberately and with no ceiling. Payload per
# request is still bounded by `_SUPPORT_BATCH_CHARS`, so removing the cap adds
# Haiku calls rather than growing any single one. A ceiling reintroduced "for
# safety" would be the same silent truncation this batch spent Item 1 removing:
# it would bind on exactly the answers that most need checking.
#
# Still settable to an int, because `scripts/measure_claim_units.py` holds it
# fixed to keep a before/after replay comparable. Production leaves it None.
_SUPPORT_MAX_PAIRS     = None

# The judge sees the WHOLE abstract. This used to be `abstract[:1200]`, a cap
# from when 57% of the library's abstracts were themselves cut at 1,000 or
# 1,200 characters at ingest — so it cost nothing, because there was nothing
# past it. `grounding-v1` healed those rows to a mean of 1,631 characters and
# left this cap in place, which turned it from a no-op into the last
# truncation in the pipeline. It sits on the guardrail.
#
# The measurement, from hand-judging all 37 Deep Learning flags: 36 of 37 cite
# a paper whose stored abstract exceeds 1,200 characters, and 17 of the 37 are
# claims whose supporting sentence is verbatim in the withheld tail. A
# structured abstract puts CONCLUSIONS last. The Cochrane review at PMID
# 27759881 is 6,724 characters and the judge was shown its search strategy.
#
# Payload is bounded by BATCHING, not by truncating: the pairs are split into
# Haiku calls of at most `_SUPPORT_BATCH_CHARS` of abstract text and the
# verdicts merged. More calls, same cost per character, and no claim is judged
# against an abstract the model was not allowed to finish reading.
#
# This makes the checker STRICTER, not looser — it can now see a contradiction
# in a conclusion it previously never reached — so it is not a way of moving
# the flag rate down.
_SUPPORT_BATCH_CHARS = 60000    # abstract characters per Haiku request


def _extract_claim_citation_pairs(answer: str, with_shape: bool = False) -> list:
    """Return [(claim_unit_without_markers, pmid), ...] in document order.

    A claim citing two papers yields two pairs (each pmid is checked against
    the claim independently). Exempt sections (References, Clinical
    Recommendation, ...) are skipped — same exemption set as the validator.

    `with_shape=True` returns 3-tuples `(claim, pmid, shape)` where shape is
    one of `prose` / `decision_tree` / `table_row`. The default arity is
    unchanged because `verify_citation_support` and four test files unpack
    2-tuples, and because a shape is reporting, not behaviour: nothing
    downstream judges a decision-tree branch differently from a sentence.
    """
    pairs = []
    for title, body in _split_sections(answer or ""):
        if _is_exempt_section(title):
            continue
        for shape, sent in _split_claim_units_tagged(body):
            s = sent.strip()
            if len(s) < 20:
                continue
            pmids = [m.group(1) for m in _PMID_RE.finditer(s)]
            if not pmids:
                continue
            claim = _PMID_RE.sub("", s).strip()
            if shape == SHAPE_DTREE:
                # A branch is three lines that mean three different things.
                # Collapsing them onto one line the way a prose sentence is
                # collapsed would hand the judge `IF ... THEN ... BECAUSE ...`
                # as a run-on. Normalise horizontal space only, and keep the
                # line breaks that carry the structure.
                claim = re.sub(r"[ \t]{2,}", " ", claim)
                claim = re.sub(r"\n{2,}", "\n", claim)
            else:
                claim = re.sub(r"\s{2,}", " ", claim)
            for pid in pmids:
                pairs.append((claim, pid, shape) if with_shape else (claim, pid))
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
        # Shapes come along for the ride so the audit record can say WHICH
        # claim shape each flag sat on — the question Item 3 has to answer
        # from the log rather than by hand-judging 37 flags again. Normalised
        # rather than assumed: a caller that replaces this extractor (the
        # before/after replay in `scripts/measure_claim_units.py` does) may
        # still hand back the 2-tuples this function has always taken.
        all_pairs = [(p[0], p[1], p[2] if len(p) > 2 else SHAPE_PROSE)
                     for p in _extract_claim_citation_pairs(answer,
                                                            with_shape=True)]
        pairs = (all_pairs if _SUPPORT_MAX_PAIRS is None
                 else all_pairs[:_SUPPORT_MAX_PAIRS])
        # How many pairs EXIST, not just how many were looked at. With the
        # cap gone these are normally equal, but NOT always: a pair whose
        # abstract is not in the cache is skipped below, and the reader still
        # has to be told. Invariant 15 requires the answer to state its
        # outcome, and "checked 28 of 31" is an outcome.
        out["total_pairs"] = len(all_pairs)
        if not pairs:
            out["detail"] = "no cited claims to check"
            return out

        from rag import get_cached_abstracts_bulk
        abstracts = get_cached_abstracts_bulk(sorted({p for _c, p, _s in pairs}))

        items = []
        for i, (claim, pmid, shape) in enumerate(pairs):
            ab = (abstracts.get(pmid) or {}).get("abstract") or ""
            if not ab.strip():
                continue   # nothing cached to judge against — cannot assess
            items.append({
                "i":        i,
                "pmid":     pmid,
                "shape":    shape,
                "claim":    claim[:400],
                # WHOLE abstract. See _SUPPORT_BATCH_CHARS above for why the
                # 1,200-character excerpt was the last truncation in the
                # pipeline and why the payload is bounded by batching instead.
                "abstract": ab,
            })
        if not items:
            out["detail"] = "source abstracts unavailable"
            print(f"  [citation_support] no abstracts available for {len(pairs)} "
                  f"claim-citation pairs — check skipped")
            return out

        # Split into requests small enough to send, on ITEM boundaries: an
        # item split across two calls would be judged on half an abstract,
        # which is the failure this change exists to remove. A single item
        # larger than the budget still goes in a call of its own rather than
        # being cut.
        batches, cur, cur_chars = [], [], 0
        for it in items:
            size = len(it["abstract"])
            if cur and cur_chars + size > _SUPPORT_BATCH_CHARS:
                batches.append(cur)
                cur, cur_chars = [], 0
            cur.append(it)
            cur_chars += size
        if cur:
            batches.append(cur)

        client = anthropic.Anthropic(api_key=_get_api_key())
        verdicts = {}
        for batch in batches:
            payload = json.dumps([{k: it[k] for k in ("i", "claim", "abstract")}
                                  for it in batch], ensure_ascii=False)
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
Read the WHOLE abstract before deciding: a structured abstract puts its RESULTS and CONCLUSIONS
last, so a claim about what a study found is usually supported at the END of the text, not the start.

ITEMS (JSON):
{payload}

Return ONLY a JSON array, no prose, no markdown fence:
[{{"i": 0, "verdict": "supports"}}, ...]"""
                }]
            )
            out["cost"] += log_llm_call("verify_citation_support",
                                        MODELS["structured_fast"],
                                        resp.usage, mode="guardrail")
            raw = re.sub(r"```json|```", "", resp.content[0].text).strip()
            verdicts.update({int(v["i"]): str(v.get("verdict", "")).strip().lower()
                             for v in json.loads(raw) if "i" in v})

        by_index = {it["i"]: it for it in items}
        out["checked"] = len(items)
        out["status"]  = "verified"
        for i, verdict in verdicts.items():
            if verdict == "not_supported" and i in by_index:
                out["flags"].append({
                    "pmid":    by_index[i]["pmid"],
                    "claim":   by_index[i]["claim"],
                    "shape":   by_index[i]["shape"],
                    "verdict": verdict,
                })
        # Denominator per shape, not just numerator: "3 decision-tree flags"
        # means nothing without how many decision-tree pairs there were.
        out["by_shape"] = {}
        for it in items:
            s = out["by_shape"].setdefault(it["shape"], {"checked": 0, "flagged": 0})
            s["checked"] += 1
        for f in out["flags"]:
            out["by_shape"].setdefault(f["shape"], {"checked": 0, "flagged": 0})
            out["by_shape"][f["shape"]]["flagged"] += 1

        # Audit trail — same JSONL stream as the fabrication validator. ONE
        # record per invocation regardless of how many requests it took, so a
        # batched check and an unbatched one aggregate identically.
        try:
            record = {
                "ts":        datetime.now().isoformat(),
                "function":  "verify_citation_support",
                # Whose check this was. `evidence_mapping.jsonl` is one file
                # shared by every process on this machine, and the eval reads
                # a byte-offset window of it to compute a case's flag rate —
                # so a pytest run, or the dev server answering a question,
                # lands in that case's numerator and denominator. It happened:
                # nine rows from a concurrent suite run turned 16/119 into
                # 16/146. The pid makes the window exact instead of hopeful.
                "pid":       os.getpid(),
                "checked":   out["checked"],
                "total_pairs": out["total_pairs"],
                "n_requests": len(batches),
                "n_flagged": len(out["flags"]),
                # Which claim SHAPE each flag sat on, with its denominator.
                # 13 of 37 Deep Learning flags were a merged decision tree or
                # table, and establishing that took a hand-judgement of every
                # flag. Recording it makes the next such question a query.
                "by_shape":  out["by_shape"],
                "flags":     [{"pmid": f["pmid"], "shape": f["shape"],
                               "claim": f["claim"][:160]} for f in out["flags"]],
            }
            with _EVMAP_LOG_LOCK:
                with open(_EVMAP_LOG_PATH, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record) + "\n")
        except Exception:
            pass

        capped = (f" ({out['total_pairs'] - out['checked']} more pair(s) not "
                  f"checked)" if out["total_pairs"] > out["checked"] else "")
        if out["flags"]:
            print(f"  [citation_support] {len(out['flags'])} of {out['checked']} "
                  f"claim-citation pairs flagged as not supported{capped}")
        else:
            print(f"  [citation_support] all {out['checked']} claim-citation "
                  f"pairs OK{capped}")
        return out

    except Exception as e:
        out["status"] = "not_run"
        out["detail"] = "check unavailable"
        print(f"  [citation_support] check skipped: {e}")
        return out


# A marker the truncation cut in half. The DOUBLE bracket is what makes this
# safe to run anywhere in the string: prose that mentions "a PMID" has no `[[`.
# The second pattern catches a cut that landed before the letters, leaving a
# bare `[[` or `[` at the end.
_PARTIAL_PMID_MARKER_RE = re.compile(r"\[\[\s*P?M?I?D?\s*:?\s*\d*\s*\]?")
_TRAILING_BRACKET_RE    = re.compile(r"\s*\[+\s*$")


def _quote_claim(claim: str, limit: int = 140) -> str:
    """A claim, cut to `limit`, with no half a citation marker left dangling.

    `_extract_claim_citation_pairs` strips the marker that ENDS a claim, but a
    merged claim — a decision tree, a bold pseudo-heading run — carries markers
    inside it, and cutting at a fixed character count lands inside one. A real
    curriculum did exactly that: the block rendered `... by day 14 [[PMID:` and
    the narration script then had a bare `[[PMID:` in it, which a raw-narration
    path would read aloud, and which is a raw marker on a rendered surface
    (invariant 3).
    """
    text = (claim or "")[:limit].rstrip()
    text = _PMID_RE.sub("", text)
    text = _PARTIAL_PMID_MARKER_RE.sub("", text)
    text = _TRAILING_BRACKET_RE.sub("", text)
    return re.sub(r"\s+([.,;:!?])", r"\1", text).rstrip()


# `trust-surface-v1` Q3 / invariant 11. Belt and braces: the prompt no longer
# asks for an impact factor and the model is no longer shown one, but every
# answer already in the query cache was written under the old template and
# carries "Cochrane Database Syst Rev (IF: 12.0)" in its reference list. A
# cached answer is a rendered surface. Matches the parenthesised form the
# template produced, and the bare "IF 4.5" the popover used.
# The parenthesised form also has to accept a NON-NUMERIC value. Found on the
# fourth demo question, live: the model no longer receives an impact factor,
# but the REFERENCES template used to ask for one, so it kept the slot and
# filled it in —
#
#     "J Clin Med (IF: n/a), 2025. Follow-up: >=6 mo. (Score: 79.4/100)"
#
# A digits-only pattern walked straight past that, and A16d's go/no-go caught
# it because it read the served answer rather than a regenerated one.
#
# The accepted non-numeric values are enumerated rather than wildcarded: a
# permissive `[^)]*` would eat a curriculum decision-tree row like
# "(IF the canal is calcified, THEN ...)", which is real content.
_IF_DISPLAY_RE = re.compile(
    r"\s*\((?:IF|impact\s+factor)[:=]?\s*"
    r"(?:[0-9]+(?:\.[0-9]+)?|n/?a|unknown|none|not\s+available|[-\u2013\u2014?])\)"
    r"|\s*\b(?:IF|impact\s+factor)\s*[:=]\s*[0-9]+(?:\.[0-9]+)?\b",
    re.IGNORECASE)


def strip_impact_factor(text: str) -> str:
    """Remove any rendered impact factor, leaving the reference readable."""
    if not text:
        return text or ""
    out = _IF_DISPLAY_RE.sub("", text)
    # "Int Endod J , 2023" — the space the removed parenthetical left behind.
    return re.sub(r"\s+([,.;:])", r"\1", out)


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

    # `trust-surface-v1` Q1b. The count of claims this check could not have
    # covered, because they carry no citation at all. It is computed HERE, from
    # the answer this block is about to be attached to, so that every surface
    # which renders the answer — browser, PDF, copy, deck, speaker notes —
    # carries the second number beside the first without any of them having to
    # know how to compute it.
    #
    # Written back into `support` rather than recomputed by each caller:
    # `_support_status_block` reproduces this exact string from the stored
    # result when the post-stitch guarantee restates a module's block, and a
    # recomputed count on an empty string would make the two disagree and the
    # restatement fire on every module.
    if "uncited_directive" not in support:
        found = _detect_uncited_directive_claims(answer)
        support["uncited_directive"] = len(found)
        support["uncited_directive_claims"] = found
    n_uncited = support.get("uncited_directive") or 0
    uncited   = support.get("uncited_directive_claims") or []

    def _uncited_block() -> str:
        """The second half of the banner, in the body text that feeds it.

        Never a tick and never merged into the sentence above it: the two
        numbers answer different questions, and a reader who sees them joined
        by "and" reads the second as a refinement of the first.
        """
        if not n_uncited:
            return ""
        noun  = "claim" if n_uncited == 1 else "claims"
        verb  = "carries" if n_uncited == 1 else "carry"
        lines = [
            f"\n>\n> ⚠ **{n_uncited} {noun} not from the evidence base.** "
            f"{ 'It' if n_uncited == 1 else 'They' } {verb} no citation, so no "
            "abstract was checked against "
            f"{ 'it' if n_uncited == 1 else 'them' } — not part of the count "
            "above:\n>",
        ]
        for c in uncited[:5]:
            lines.append(f"> - \"{_quote_claim(c['sentence'])}\"")
        if len(uncited) > 5:
            lines.append(f"> - …and {len(uncited) - 5} more.")
        return "\n".join(lines)

    # This tail is what made the 30-pair cap findable, and it stays now that
    # the cap is gone. `checked` can still fall short of `total_pairs` when a
    # cited paper's abstract is not in the cache — the pair is skipped rather
    # than judged against nothing. Saying "each of the 30 cited claims was
    # checked" while 15 were never looked at is the fail-open silence
    # invariant 15 exists to forbid: the sentence is true and the reader draws
    # the wrong conclusion from it.
    total    = support.get("total_pairs") or checked
    unchecked = max(0, total - checked)
    tail = (f" {unchecked} further cited claim(s) were NOT checked (the check "
            f"covers the first {checked})." if unchecked else "")

    if flags:
        lines = [
            "\n\n---\n",
            f"> ⚠ **Citation support: {len(flags)} of {checked} flagged.** An automated "
            "review of each cited abstract found these may not directly support the "
            f"claim they are attached to.{tail} Verify before relying on them:\n>",
        ]
        for f in flags[:5]:
            lines.append(f"> - [[PMID:{f['pmid']}]] cited for: "
                         f"\"{_quote_claim(f['claim'])}\"")
        return answer + "\n".join(lines) + _uncited_block()

    if status == "verified":
        return answer + (
            f"\n\n---\n\n> ✓ **Citation support: verified.** Each of the {checked} cited "
            f"claims was checked against its source abstract.{tail}"
        ) + _uncited_block()

    detail = support.get("detail") or "check unavailable"
    return answer + (
        f"\n\n---\n\n> ○ **Citation support: not available** ({detail}). Citations were "
        "confirmed to exist in the retrieved evidence, but whether each source supports "
        "its claim was not verified for this answer."
    ) + _uncited_block()


def _support_not_run(detail: str) -> dict:
    """A citation-support result for a path that never reached the checker.

    Same shape verify_citation_support returns, so _append_support_warnings
    renders it with the SAME vocabulary. A module that was never written still
    has to say so out loud — "no block" reads as "passed".
    """
    return {"flags": [], "checked": 0, "cost": 0.0,
            "status": "not_run", "detail": detail}


def _support_status_block(support: dict) -> str:
    """The shared renderer's status block on its own, with no answer attached.

    Rendering through _append_support_warnings (rather than re-writing the
    wording here) is the point: there is exactly ONE citation-support
    vocabulary in this codebase and this is how the curriculum path borrows it.
    """
    return _append_support_warnings("", support).strip()


def _ensure_curriculum_support_blocks(final: str, entries: list) -> str:
    """Guarantee every module's citation-support status survived the stitcher.

    Each module's block is appended to its script BEFORE stitching, and the
    stitcher is instructed to reproduce module bodies verbatim — but "the model
    was told to" is not a guarantee, and a status block that silently
    evaporates is the fail-open bug this whole check exists to avoid. So after
    stitching we count, deterministically, how many of each block actually
    made it through, and restate the missing ones in an appendix.
    """
    text = final or ""
    expected = {}          # block text -> [titles], in module order
    order    = []
    for i, e in enumerate(entries or []):
        support = (e or {}).get("citation_support")
        if not support:
            continue
        block = _support_status_block(support)
        title = (e or {}).get("title") or f"Module {i + 1}"
        if block not in expected:
            expected[block] = []
            order.append(block)
        expected[block].append(title)

    missing = []
    for block in order:
        titles  = expected[block]
        present = text.count(block)
        for title in titles[present:]:
            missing.append((title, block))

    if not missing:
        return text

    print(f"  [citation_support] {len(missing)} module status block(s) did not "
          f"survive stitching — restated in an appendix")
    out = [text.rstrip(),
           "\n\n---\n\n## Citation Support by Module\n\n",
           "The stitched curriculum did not carry every module's "
           "citation-support outcome through verbatim. Those outcomes are "
           "restated here so none of them is silently missing.\n"]
    for title, block in missing:
        out.append(f"\n**{title}**\n\n{block}\n")
    return "".join(out)


# ──────────────────────────────────────────────────────────
# INTENT ROUTER (Haiku)
# ──────────────────────────────────────────────────────────

_INTENT_KINDS     = {"simple", "standard", "complex"}
_INTENT_RETRIEVAL = {"local", "pubmed", "both"}


def classify_question_intent(question: str, context_block: str = "") -> dict:
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
            messages   = [{"role": "user", "content": _with_context(context_block,
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
{{"kind":"...","needs_clarify":false,"retrieval":"...","reason":"..."}}""",
                note="Judge the RESOLVED question — an elliptical follow-up inherits "
                     "its subject from the earlier exchange. \"needs_clarify\" is false "
                     "for context the earlier exchange already supplies.")
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
def ask_clinical_question(question, evidence, stream_cb=None, abort_cb=None,
                          phase_cb=None, context_block: str = ""):
    """Synthesise the answer, streaming it out as it is written.

    `stream_cb(partial_markdown)` — optional. Called at the cadence set by
    STREAM_PARTIAL_MIN_DELTAS / STREAM_PARTIAL_MIN_INTERVAL with the RAW model
    text written so far. It is the ONLY thing that ever sees partial text.

    `abort_cb()` — optional. Polled once per stream event; a true result raises
    StreamAborted so a cancelled job stops paying for tokens immediately.

    `phase_cb(label)` — optional. Fired once when the model stream closes and
    the guardrails start, so the UI can stop pretending text is still arriving
    without claiming the checks have finished either.

    THE GUARDRAIL INVARIANT: `validate_evidence_mapping` and
    `verify_citation_support` are called below on `answer`, which is read from
    the FINAL message after the stream has closed. Neither is reachable from
    inside `stream_cb`. A truncated citation ("[[PMID:312" mid-token) would
    read as a fabrication to the validator and produce a false warning about a
    perfectly good answer, so partial text must never reach them.
    """
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

__GROUNDING_RULE__

When referencing key papers in the evidence summary, use author surnames only — not PMIDs or scores.

Structure every answer exactly like this:

---

## CLINICAL RECOMMENDATION

2-4 concise, actionable sentences — the bottom line.

This section is what the clinician acts on, so it MUST be traceable:
- State the strength of evidence it rests on, using the literal tier name — e.g. "Based on Level I evidence," / "Cochrane-level evidence supports..." / "Only Level IV evidence addresses this, so treat as provisional:".
- Carry at least one `[[PMID:N]]` marker on the load-bearing clinical claim. Keep it to the one or two papers the recommendation actually rests on; the full argument belongs in the EVIDENCE SUMMARY below.
- THE GROUNDING RULE ABOVE APPLIES HERE IN FULL, WITH ONE DIFFERENCE: its third option — writing the sentence with no marker — is NOT available in this section. A recommendation the clinician cannot trace is not a shippable recommendation. Options 1 and 2 remain, and option 2 always terminates: NARROW the recommendation until it states something a paper in the evidence block does state, and cite that paper. A narrower recommendation you can ground beats a broader one you cannot, and both beat a marker you cannot support.
- IF THE EVIDENCE BASE DOES NOT ADDRESS THE QUESTION, that is a finding, and it is still traceable. Write it in three moves, in this order:
  (1) State the gap plainly and name what is missing. This needs no marker: it is a statement about the evidence base, not a claim about a paper.
  (2) Then state what this evidence base DOES establish that bears on the case — the general principle, the adjacent population, the procedural factor the retrieved papers do cover — and put your markers THERE. That is the load-bearing claim, it is groundable, and it is why this section stays traceable even when the direct evidence is absent. Each marker must sit on something ONE of the cited papers states by itself: do not compose a general principle out of several papers and then attach all their markers to it, because no one of them says the composite and every one of those markers is then unverifiable.
  (3) Any guidance you would give from outside the evidence base comes last and is explicitly labelled as such ("from the wider literature, which this search did not return"), carrying no marker.
  What this must never become: a recommendation full of survival percentages and success rates with no marker anywhere, on the reasoning that nothing here could be cited. If you cannot cite a number, do not give the number.

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
1. [PMID: 12345678] Author AB, Author CD et al. — Brief description. Journal, Year. Follow-up: X months. n=XX. (Score: XX/100)

---

Rules:
- Never fabricate PMIDs
- Flag conflicts between studies
- Note when follow-up is too short to draw conclusions
- Note when sample sizes are underpowered
- Note when evidence base is weak overall
- Keep recommendation concise
__NO_QUESTIONS_RULE__"""

    # Splice in the active scoring-weight description (impact factor on/off)
    # and the grounding rule, which is one constant shared with the curriculum
    # and case prompts so the three cannot drift on what a marker means.
    system_prompt = system_prompt.replace("__SCORE_WEIGHTS__", _SCORE_WEIGHTS_DESC)
    system_prompt = system_prompt.replace("__GROUNDING_RULE__", _GROUNDING_RULE)
    system_prompt = system_prompt.replace("__NO_QUESTIONS_RULE__", _NO_QUESTIONS_RULE)

    # Build context — feed papers in strict tier order (Cochrane → L5),
    # not cross-tier sorted by score
    context = _build_evidence_context(evidence)

    user_message = _with_context(context_block,
        f"""Peer-reviewed endodontic literature with evidence scores:

{context}

Clinical Question: {question}""",
        # The prior exchange's PMIDs are named in the block above. Some of them
        # will have survived this question's retrieval and appear in the
        # evidence; the rest did not, and citing one of those would be a
        # citation to a paper this answer was never given — indistinguishable
        # from a fabrication to validate_evidence_mapping, and unverifiable by
        # the clinician, since the bibliography would not contain it.
        note="Answer the NEW clinical question below on its own retrieved evidence. "
             "Cite ONLY PMIDs that appear in the evidence supplied for THIS question; "
             "a PMID named in the earlier exchange is citable only if it also appears "
             "below. Do not repeat the earlier answer — write a fresh one, and refer "
             "back only where the follow-up genuinely turns on it.")

    print(f"\nAsking Claude: '{question}'")
    print("=" * 60)

    # INTENTIONALLY OPUS (Tier 3) — Literature Review primary path. 7-tier evidence
    # synthesis with strict tier hierarchy, contradiction surfacing, PRISMA dedup,
    # inline [[PMID:N]] provenance. Quality regression here is most user-visible.
    # Revisit only after eval infrastructure exists.
    convo = [{"role": "user", "content": user_message}]

    def _publish_partial(partial_text: str):
        # A failure to show progress must never fail the answer.
        try:
            stream_cb(partial_text)
        except Exception as e:      # pragma: no cover — defensive
            print(f"  [stream] partial publish failed: {type(e).__name__}: {e}")

    message = _invoke_claude(client, function_name="ask_clinical_question",
        stream=True,
        on_partial=(_publish_partial if stream_cb is not None else None),
        abort_cb=abort_cb,
        model=MODELS["reasoning_heavy"],
        max_tokens=8000,
        system=system_prompt,
        messages=convo,
    )

    cost = log_llm_call("ask_clinical_question", MODELS["reasoning_heavy"],
                        message.usage, mode="review")
    print(f"  Cost: ${cost:.4f} ({message.usage.input_tokens} in / {message.usage.output_tokens} out)")

    # The COMPLETE text, read off the final message — not off the accumulated
    # stream chunks and not off anything stream_cb was handed. Everything past
    # this line (validators, support check, cache, audit, cost log) sees this
    # string and only this string.
    answer = message.content[0].text

    if abort_cb is not None and abort_cb():
        # Cancelled while the last tokens were in flight — don't spend two more
        # LLM calls validating an answer nobody will read.
        raise StreamAborted()

    if phase_cb is not None:
        try:
            phase_cb("checking")
        except Exception as e:      # pragma: no cover — defensive
            print(f"  [stream] phase publish failed: {type(e).__name__}: {e}")

    # `trust-surface-v1` Q2 — quarantine before anything reads the answer.
    # Every downstream consumer (validator, support check, cache, export,
    # narration) sees the normalised text, so the block cannot be a browser
    # decoration that a PDF or a slide quietly drops.
    answer, _quarantined = finalise_answer_text(answer)
    if _quarantined:
        print(f"  [quarantine] {len(_quarantined)} span(s) labelled outside "
              f"the evidence base, lifted into their own block")

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
        # DELIBERATELY NOT STREAMED. The retry rewrites the whole answer, so
        # streaming it would rewind text the clinician is already reading and
        # replace it line by line. The header chips still read "checking…"
        # throughout, so the pause here is honest rather than a false pass.
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
        retry_answer, _rq = finalise_answer_text(retry_answer)
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
1. [PMID: 12345678] Author AB et al. — Brief description. Journal, Year. n=XX. (Score: XX/100)

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

# 3200 -> 6000. MEASURED, not guessed: of 190 `write_curriculum_module` calls
# ever logged, 164 (86%) returned EXACTLY 3,200 output tokens. The median
# output length across the whole history of the feature was the cap itself,
# which is the signature of a value that was never large enough for the
# content the prompt asks for. Every module of the 2026-09-01 laser curriculum
# hit it, and both retries did too.
#
# The cap is NOT the only fix and must not be treated as one. A cap can always
# be reached, and until this batch nothing looked at `stop_reason` — so the
# durable guarantee is `detect_module_truncation` plus the regenerate-once
# gate, and this number only makes that gate fire rarely instead of always.
#
# SEPARATELY, AND NOT FIXED HERE: the modules were already running ~1,500
# words against a stated target of 650 (measured on the laser fixture: 1497 /
# 1489 / 1548 / 939, the last one being the truncated one). The 650-word
# target has been fiction for the life of the feature, and raising the cap
# does not make it true. Reported in OVERNIGHT_REPORT_7.md rather than
# silently corrected, because changing the target changes the curriculum's
# length contract and belongs in its own measured piece of work.
CURRICULUM_MODULE_MAX_TOKENS = 6000

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
            query, dropped = cap_and_groups(query)
            if dropped:
                print(f"  [curriculum] '{title[:30]}' capped to {MAX_AND_GROUPS} "
                      f"AND-groups, dropped: {' | '.join(x[:50] for x in dropped)}")
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

EACH MODULE'S QUERY MUST BE ABOUT THAT MODULE. The commonest failure is four
queries that are the TOPIC's terms with an aspect adjective bolted on. They
then return four copies of the same pile, and the anatomy module gets written
from evidence assembled for the topic as a whole.

  topic: "apicoectomy of mandibular teeth"

  BAD   module 1: (apicoectomy OR "apical resection" OR surgical endodontic*)
                  AND (mandibular OR molars OR premolars) AND (indication* OR anatom*)
        module 4: (apicoectomy OR "apical resection" OR surgical endodontic*)
                  AND (mandibular OR molars OR premolars) AND (prognos* OR outcome*)
        — the same two groups four times, differing only in an adjective.

  GOOD  module 1: ("cortical bone" OR "buccal bone thickness" OR "cortical plate"
                   OR "mandibular canal" OR "inferior alveolar nerve"
                   OR "mental foramen" OR "root apex position" OR "bone thickness")
                  AND (mandib* OR molar* OR premolar*)
        module 4: ("success rate*" OR survival OR healing OR "periapical repair"
                   OR recurrence OR "altered sensation" OR paresthesia OR complication*)
                  AND (apicoectomy OR "endodontic microsurgery" OR "apical surgery"
                       OR "root-end surgery")

Name the structures, measurements, materials, devices, landmarks and outcomes
the module actually teaches. A module about anatomy should be SEARCHING
anatomy, not searching the procedure and hoping anatomy comes back. At most one
concept group may be shared across modules; the rest must differ.

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


# ── TRUNCATION ────────────────────────────────────────────
#
# MEASURED BEFORE WRITING ANY OF THIS. Of 190 `write_curriculum_module` calls
# ever logged, **164 (86%) stopped at exactly `max_tokens`** — the median
# output length across the whole history of the feature IS the cap. On the
# laser curriculum of 2026-09-01 13:58 every one of the four modules and both
# retries returned exactly 3,200 output tokens, and two of them are visibly
# cut: Module 4 ends "…irrigant extrusion when tips are not", and Module 1's
# materials table ends mid-cell at "Wavelength 630".
#
# Nothing looked. `stop_reason` appeared once in this file, inside a comment.
# That is bug class (d) — a check that fails open and shows nothing — in the
# place it costs the most, because a curriculum is the output a clinician
# reads end to end.
#
# TWO SIGNALS, deliberately, because they are available in different places:
#
#   `stop_reason == "max_tokens"` is ground truth and is checked at the call
#   site, where a regeneration is possible.
#
#   `detect_module_truncation` reads the TEXT, and it is what guards the
#   stitcher — where the message object is long gone and, worse, where the
#   evidence says the damage gets cosmetically repaired. The stitcher is an
#   LLM pass instructed to reproduce module bodies verbatim; the truncated
#   table row reached the final document as `| **Laser — Diode (aPDT)** |
#   Wavelength 630 |`, with a closing pipe the module author never wrote. A
#   structural check that ran only after stitching would have called that row
#   well-formed.

# Function words that cannot end a finished clinical sentence. This list is
# the precision half of the mid-sentence rule: a paragraph ending "when tips
# are not" is unambiguously cut, while one ending "…reduces bacterial load"
# is not, and no amount of punctuation-counting separates those two.
_TRUNCATION_TAIL_WORDS = frozenset("""
a an the and or but nor for so yet of in on at to from by with without within
into onto upon over under between among across through during before after
above below near about against toward towards per via than then when while
where which who whom whose that this these those is are was were be been being
am has have had do does did can could may might must shall should will would
if unless until since because although though whereas however therefore thus
hence moreover furthermore additionally also both either neither each every
any some most more less least such as well not no nor only just even still
""".split())

_TABLE_ROW_LINE = re.compile(r"^\s*\|.*$")
_HRULE_RE       = re.compile(r"^[ 	]*(?:-{3,}|\*{3,}|_{3,})[ 	]*$")
_LIST_MARKER    = re.compile(r"^\s*(?:[-•+*]|\d{1,2}[.)])\s+")
# A finished line ends in terminal punctuation, a closing delimiter, or the
# end of a citation marker. `:` counts — a module legitimately ends a lead-in
# line with a colon before a list.
_FINISHED_TAIL  = re.compile(r"""[.!?:;"'\)\]»…]\s*$|\]\]\s*$|\*\*\s*$|\|\s*$""")


def _table_cell_count(line: str) -> int:
    """Cells in a markdown table row, ignoring the outer pipes."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return len(s.split("|"))


def detect_module_truncation(text: str) -> dict:
    """Was this module cut off mid-thought?

    Returns {"truncated": bool, "reason": str|None, "tail": str}.

    CONSERVATIVE BY CONSTRUCTION. A false positive here replaces a real module
    with a "module not generated" notice, which is a worse outcome than the
    truncation it is trying to prevent — so every rule below fires only on
    something a finished module cannot contain: an unclosed citation marker, a
    table row with fewer cells than its own header, or a paragraph whose last
    word is a conjunction or a preposition.
    """
    out = {"truncated": False, "reason": None, "tail": ""}
    if not (text or "").strip():
        return {"truncated": True, "reason": "empty module", "tail": ""}

    lines = [l for l in text.rstrip().split("\n")]
    # A trailing horizontal rule is a SEPARATOR, not content, and treating
    # it as the last line hides the very thing this function looks for: the
    # anesthesia curriculum's Module 4 ends '...19.35 mm from the' followed
    # by a blank line and `---`, and the first version of this scan called
    # it finished because `---` holds no words to inspect.
    non_empty = [l for l in lines
                 if l.strip() and not _HRULE_RE.match(l)]
    if not non_empty:
        return {"truncated": True, "reason": "no content", "tail": ""}
    last = non_empty[-1]
    out["tail"] = last.strip()[-80:]

    # 1. Mid-citation. A marker opened and never closed is the one shape the
    #    renderer cannot degrade gracefully: `[[PMID:412` is not a citation,
    #    it is three characters of a number the reader cannot look up.
    if text.count("[[") != text.count("]]"):
        out.update(truncated=True, reason="cut mid-citation (unclosed [[PMID marker)")
        return out

    # 2. Mid-table-row. Compared against the header of the row's OWN table,
    #    because a module may contain several tables with different widths.
    if _TABLE_ROW_LINE.match(last):
        header = None
        for l in reversed(lines[:lines.index(last)] if last in lines else []):
            if not _TABLE_ROW_LINE.match(l):
                break
            header = l
        if not last.strip().endswith("|"):
            out.update(truncated=True, reason="cut mid-table-row (no closing pipe)")
            return out
        if header is not None:
            want, got = _table_cell_count(header), _table_cell_count(last)
            if got < want:
                out.update(truncated=True,
                           reason=f"cut mid-table-row ({got} cells, header has {want})")
                return out

    # 3. Mid-sentence.
    #
    # There WAS an exemption here for headings and table rows, on the theory
    # that they finish without punctuation by design. It was deleted after
    # measurement: across 108 real module bodies it changed ZERO verdicts,
    # because a table row ends in a pipe and `_FINISHED_TAIL` already accepts
    # that, and no real heading ends on a conjunction or a preposition. A
    # mutation run is what surfaced it — the branch could be replaced with
    # `if False:` and every test still passed.
    #
    # Same precedent as the two interval patterns deleted in `case-v3` Item B:
    # a line no input needs is the code equivalent of a test that cannot fail,
    # and keeping it means keeping a rule nobody can check.
    if _FINISHED_TAIL.search(last):
        return out
    body = re.sub(r"[\*_`\[\]]+$", "", last.strip())
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", body)
    if words and words[-1].lower() in _TRUNCATION_TAIL_WORDS:
        out.update(truncated=True,
                   reason=f"cut mid-sentence (ends on \"{words[-1]}\")")
    return out


def _module_truncated_block(title: str, reason: str, query: str = "") -> str:
    """Rendered in place of a module the writer could not finish.

    Deliberately DIFFERENT wording from `_module_not_generated_block`. That one
    says the literature is thin, which is a fact about the world; this one says
    the generator failed, which is a fact about this system. Telling a reader
    the evidence was missing when the truth is that we ran out of tokens is a
    lie in the direction that happens to make us look better.
    """
    return (
        f"## Module \u2014 {title}\n\n"
        f"> **Module not generated \u2014 the text was cut off before it was "
        f"finished.**\n>\n"
        f"> The module was written and then found to be incomplete "
        f"({reason}). It was regenerated once and was still incomplete, so it "
        f"has been withheld rather than published with a severed sentence, "
        f"table or citation.\n>\n"
        f"> This is a GENERATION failure, not a gap in the literature \u2014 "
        f"the evidence for this module was retrieved successfully. No "
        f"protocol, parameters or decision rules are given here, because a "
        f"clinical instruction that stops mid-sentence is more dangerous than "
        f"an absent one.\n"
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

{_GROUNDING_RULE}

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
    # Routed to Sonnet — the per-module evidence context is small enough that
    # Opus's extra context window isn't needed. Validation+retry provides the
    # quality safety net. 5× cheaper than Opus with equivalent synthesis quality
    # at the density targets here (~650 words + evidence table).
    #
    # The bound this comment used to state ("< 25K tokens") no longer holds:
    # the library evidence block now carries titles and abstracts, so a 47-paper
    # module measured ~36K tokens at the worst case (2026-08-31). Sonnet's 200K
    # window is still far from the limit, so the ROUTING stands — but do not
    # quote 25K as a constraint when deciding anything else.
    convo = [{"role": "user", "content": user_message}]

    def _write(fn_name):
        r = _invoke_claude(client, function_name=fn_name,
            model=MODELS["reasoning_standard"],
            max_tokens=CURRICULUM_MODULE_MAX_TOKENS,
            system=system_prompt,
            messages=convo,
        )
        c = log_llm_call("write_curriculum_module", MODELS["reasoning_standard"],
                         r.usage, mode="learn")
        print(f"  Cost: ${c:.4f} ({r.usage.input_tokens} in / "
              f"{r.usage.output_tokens} out, stop={getattr(r, 'stop_reason', '?')})")
        return r, c

    resp, cost = _write(f"write_curriculum_module[{idx}/{total}]")
    answer = resp.content[0].text

    # ── REGENERATE ONCE ON A CUT MODULE ──
    # Two signals, because they are true in different ways. `stop_reason` is
    # ground truth from the API and needs no heuristic; the text detector
    # catches a module that stopped for another reason mid-thought, and is the
    # same function that guards the stitcher downstream. Either one is enough.
    #
    # This is a REGENERATION, not a continuation. Asking the model to carry on
    # from a severed sentence produces a module with two halves written under
    # different amounts of remaining budget, and the join is exactly where a
    # numeric protocol loses its citation.
    stop = getattr(resp, "stop_reason", None)
    cut  = detect_module_truncation(answer)
    if stop == "max_tokens" or cut["truncated"]:
        why = "stop_reason=max_tokens" if stop == "max_tokens" else cut["reason"]
        print(f"  [module {idx}] TRUNCATED ({why}) — regenerating once")
        print(f"      tail: ...{cut['tail']}")
        resp2, cost2 = _write(f"write_curriculum_module_untruncate[{idx}/{total}]")
        cost += cost2
        answer2 = resp2.content[0].text
        cut2 = detect_module_truncation(answer2)
        if getattr(resp2, "stop_reason", None) != "max_tokens" and not cut2["truncated"]:
            answer = answer2
            print(f"  [module {idx}] regeneration is complete — using it")
        elif len(answer2) > len(answer):
            # Still cut, but further in. The caller's gate decides what
            # happens next; handing it the longer of two cut modules is
            # strictly better than handing it the shorter one.
            answer = answer2
            print(f"  [module {idx}] regeneration STILL truncated, but longer — "
                  f"the assembly gate will decide")
        else:
            print(f"  [module {idx}] regeneration STILL truncated and no longer — "
                  f"keeping the first")

    # `trust-surface-v1` Q2 — quarantine before anything reads the answer.
    # Every downstream consumer (validator, support check, cache, export,
    # narration) sees the normalised text, so the block cannot be a browser
    # decoration that a PDF or a slide quietly drops.
    answer, _quarantined = finalise_answer_text(answer)
    if _quarantined:
        print(f"  [quarantine] {len(_quarantined)} span(s) labelled outside "
              f"the evidence base, lifted into their own block")

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
            max_tokens=CURRICULUM_MODULE_MAX_TOKENS,
            system=system_prompt,
            messages=convo,
        )
        retry_cost = log_llm_call("write_curriculum_module_retry", MODELS["reasoning_standard"],
                                  retry.usage, mode="learn")
        cost += retry_cost
        retry_answer = retry.content[0].text
        retry_answer, _rq = finalise_answer_text(retry_answer)
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

    # ── The v2 guardrail, now on the Deep Learning path too ──
    # validate_evidence_mapping above proves every cited PMID was actually
    # retrieved for this module. It does NOT ask whether the cited abstract
    # SUPPORTS the sentence it is attached to — that is the separate question
    # that catches a real-but-irrelevant citation. It ran on Review and on
    # Case, but not here, which left the longest and most citation-dense
    # document the product emits as the one output nothing checked.
    #
    # Per module, against that module's OWN evidence base: a module only ever
    # cites papers its own retrieval found, and one Haiku call per module is
    # noise next to the Sonnet call that wrote it. Fail-open and advisory,
    # exactly as at the other two call sites — the shared renderer appends the
    # outcome (including "not available") and nothing here can block or rewrite
    # the module.
    support = verify_citation_support(answer, evidence)
    cost   += support.get("cost", 0.0)
    answer  = _append_support_warnings(answer, support)
    # Hand the structured outcome back to the orchestrator without changing
    # this function's (script, cost) contract, which the parallel-module tests
    # stub against. `module` is the syllabus entry that _curriculum_module_body
    # spreads into the stitched entry, so the post-stitch guarantee
    # (_ensure_curriculum_support_blocks) can see what each module reported.
    try:
        module["citation_support"] = support
    except Exception:
        pass

    return answer, cost


# ── CROSS-MODULE CONSISTENCY (dl-quality-v1 Item 4) ───────
#
# Four module authors write independently from four different evidence bases,
# and nothing has ever compared their outputs to each other. Measured on the
# two stored curricula, that produces two kinds of defect a reader hits and
# the per-module guardrails cannot see, because each module is internally
# consistent and correctly cited:
#
#   NaOCl appears at 2%, 2.5%, 3% and 5.25% across modules 1 and 3 of the
#   laser curriculum. Every one of those is right for the study it came from.
#   Together, with nothing saying which is which, they are not a protocol.
#
#   220 IF/THEN/BECAUSE branches exist across the stored curricula and 4 of
#   them have a BECAUSE that contains no reason — two empty, one holding
#   nothing but `[[PMID:40818665]] [[PMID:41389357]]`. A citation is not a
#   justification; the branch tells the clinician to do something and then
#   cites two papers instead of saying why.
#
# THE DETECTORS ARE DETERMINISTIC AND THE MODEL IS NOT ASKED TO FIND ANYTHING.
# It is asked only to WRITE the reconciling sentence for a conflict already
# found, which is the half a regex cannot do. A model asked to find conflicts
# finds them whether or not they are there.

# Substances whose concentration is a clinical parameter. Deliberately a
# closed list: an open one turns every number in the document into a candidate.
_PARAM_AGENTS = (
    "NaOCl|sodium hypochlorite|EDTA|chlorhexidine|CHX|calcium hydroxide|"
    "MTA|Biodentine|epinephrine|adrenaline|lidocaine|lignocaine|articaine|"
    "mepivacaine|bupivacaine|prilocaine|citric acid|hydrogen peroxide|"
    "QMix|MTAD|saline|methylene blue|toluidine blue"
)
_PARAM_UNITS = r"%|mg/mL|mg"

# "5.25% NaOCl" — no filler word allowed between the value and the agent.
# Allowing even one admits "17% EDTA and NaOCl", which produced a phantom
# 17% NaOCl in the first version of this.
_PARAM_FWD = re.compile(
    r"(\d+(?:\.\d+)?)\s*(" + _PARAM_UNITS + r")\s+(" + _PARAM_AGENTS + r")\b", re.I)
# "NaOCl 5.25%" — one filler word allowed ("NaOCl at 5.25%").
_PARAM_BWD = re.compile(
    r"\b(" + _PARAM_AGENTS + r")\s+(?:\w+\s+){0,1}(\d+(?:\.\d+)?)\s*("
    + _PARAM_UNITS + r")", re.I)

# A percentage next to a drug name is usually a SUCCESS RATE, not a
# concentration, and the two are indistinguishable by shape. Two filters,
# both from the domain rather than from the text:
#   - no irrigant or anaesthetic in endodontic use is above 20% (EDTA at 17%
#     is the strongest of them);
#   - a rate word just before the number means it is a rate.
_PARAM_MAX_PCT   = 20.0
_PARAM_RATE_WORD = re.compile(
    r"\b(success|rate|efficac\w*|prevalence|incidence|reduction|CI|"
    r"P\s*[=<>]|versus|vs\.?|achiev\w*|compared)\b", re.I)

# Used to disown a value that belongs to the NEXT agent: in
# "2.5% NaOCl with 17% EDTA", the backward form matches "NaOCl with 17%"
# and would file EDTA's concentration under NaOCl.
#
# The word boundary is written as an explicit escape rather than a literal
# "\b" because this line reached the file through a shell heredoc once and
# arrived as a BACKSPACE character (0x08), which silently matches nothing.
# A regex that cannot match is a filter that never fires.
_PARAM_AGENT_HEAD = re.compile(chr(92) + "s*(?:" + _PARAM_AGENTS + ")", re.I)

_BECAUSE_RE = re.compile(
    r"\*\*BECAUSE\*\*(.*?)(?=\n\s*\n|\n\s*\*\*IF\*\*|\Z)", re.S | re.I)


def extract_numeric_parameters(text: str) -> list:
    """[{agent, value, unit, sentence}] for every clinical concentration.

    Concentrations only — not doses, not volumes, not success rates. See the
    two filters above for why that distinction has to be made by domain
    knowledge rather than by pattern.
    """
    out = []
    for sent in re.split(r"(?<=[.;])\s+", text or ""):
        for m in list(_PARAM_FWD.finditer(sent)) + list(_PARAM_BWD.finditer(sent)):
            g = m.groups()
            if g[0][0].isdigit():
                value, unit, agent = g[0], g[1], g[2]
            else:
                agent, value, unit = g[0], g[1], g[2]
            try:
                num = float(value)
            except ValueError:      # pragma: no cover — regex guarantees it
                continue
            if unit == "%" and num > _PARAM_MAX_PCT:
                continue
            # The window includes the MATCH ITSELF, not just the text before
            # it. For the backward form the rate word sits between the agent
            # and the number — "articaine success 12%" — so a window ending at
            # m.start() sees an empty string and the filter never fires. Found
            # by a mutation run: disabling this filter changed nothing,
            # because the only test exercising it was being caught by the
            # 20% ceiling instead.
            if _PARAM_RATE_WORD.search(sent[max(0, m.start() - 40):m.end()]):
                continue
            # "2.5% NaOCl with 17% EDTA" — the backward form matches
            # "NaOCl with 17%" and attributes EDTA's concentration to NaOCl.
            # When a value is immediately followed by an agent, it belongs to
            # THAT agent and the forward form has already recorded it.
            if not g[0][0].isdigit() and _PARAM_AGENT_HEAD.match(sent[m.end():]):
                continue
            out.append({"agent": agent.lower(), "value": num,
                        "unit": unit.lower(), "sentence": sent.strip()})
    return out


def detect_parameter_conflicts(modules: list) -> list:
    """Where two modules state different concentrations of the same agent.

    `modules` is [(title, text), ...]. A conflict needs BOTH more than one
    value AND more than one module: one module listing 2% and 5.25% NaOCl is
    usually a deliberate contrast within a single passage, and flagging it
    would annotate a document that is already clear.

    A conflict is NOT an error. Different trials use different concentrations
    and each module is citing its own correctly. What is missing is the one
    sentence saying which study used which, and that is what gets added.
    """
    by_key = {}
    for title, text in modules or []:
        for p in extract_numeric_parameters(text):
            key = (p["agent"], p["unit"])
            by_key.setdefault(key, {}).setdefault(p["value"], []).append(
                {"module": title, "sentence": p["sentence"]})
    out = []
    for (agent, unit), values in sorted(by_key.items()):
        mods = {o["module"] for occs in values.values() for o in occs}
        if len(values) < 2 or len(mods) < 2:
            continue
        out.append({
            "agent": agent,
            "unit":  unit,
            "values": [
                {"value": v,
                 "modules": sorted({o["module"] for o in values[v]}),
                 "example": values[v][0]["sentence"][:220]}
                for v in sorted(values)
            ],
        })
    return out


def detect_malformed_because(text: str) -> list:
    """IF/THEN/BECAUSE branches whose BECAUSE gives no reason.

    [{because, reason}] — `because` is the raw clause. A BECAUSE holding only
    `[[PMID:N]]` markers is the shape this exists for: the branch tells the
    clinician to do something and cites two papers instead of saying why.
    Measured across the stored curricula: 220 branches, 4 like this.
    """
    out = []
    for m in _BECAUSE_RE.finditer(text or ""):
        body = m.group(1)
        stripped = re.sub(r"\[\[PMID:[^\]]*\]\]", "", body)
        stripped = re.sub(r"[\s.;,:\-—()\[\]]+", "", stripped)
        if len(stripped) < 12:
            reason = ("empty" if not body.strip()
                      else "contains only citations, no reason")
            out.append({"because": body.strip()[:200], "reason": reason})
    return out


def _claim_lines(text: str) -> set:
    """Every line carrying a citation marker, normalised for whitespace.

    This is the unit the consistency guard protects: a line with a
    `[[PMID:N]]` on it is a line asserting something about the literature, and
    the annotation pass may not touch one.
    """
    return {" ".join(l.split()) for l in (text or "").split("\n")
            if "[[PMID:" in l and l.strip()}


def consistency_guard(before: str, after: str, repairable: list = None) -> tuple:
    """(ok, reason) — did the annotation pass stay inside its mandate?

    THE MANDATE IS NARROW ON PURPOSE. The pass annotates and repairs
    formatting; it must not rewrite evidence claims. So:

      - every `[[PMID:N]]` marker present before must still be present, with
        the same multiplicity. Dropping one deletes a citation; adding one
        attaches a paper to a sentence no module author chose it for.
      - every line carrying a marker must survive VERBATIM, except lines the
        detectors flagged as repairable (a malformed BECAUSE).

    It FAILS CLOSED. A guard that cannot verify the pass discards the pass and
    keeps the unannotated document, because an annotation is a convenience and
    a rewritten evidence claim is a defect.
    """
    before_marks = re.findall(r"\[\[PMID:\d+\]\]", before or "")
    after_marks  = re.findall(r"\[\[PMID:\d+\]\]", after or "")

    # NO MARKER MAY BE LOST. Dropping one deletes a citation from a claim that
    # had it, which is the failure this guard exists for.
    lost = [m for m in set(before_marks)
            if after_marks.count(m) < before_marks.count(m)]
    if lost:
        return False, f"citation markers lost: {sorted(set(lost))}"

    # A marker may be ADDED only if that paper is already cited somewhere in
    # the document.
    #
    # THIS RULE STARTED OUT AS "no marker may be added at all", and the first
    # real run rejected the whole pass for it — because the prompt invites the
    # model to cite in a reconciling sentence, and then the guard forbade
    # exactly what the prompt asked for. A sentence saying which study used
    # 2.5% NaOCl and which used 5.25% is USELESS without naming them, so the
    # prompt was right and the guard was wrong.
    #
    # What must still be impossible is a marker for a paper the curriculum
    # does not already cite — that would be a PMID from outside the evidence
    # the modules were written from, which is the fabrication case.
    already = set(before_marks)
    invented = sorted({m for m in after_marks if m not in already})
    if invented:
        return False, f"markers for papers the curriculum does not cite: {invented}"

    exempt = {" ".join(r.split()) for r in (repairable or [])}
    missing = []
    after_lines = _claim_lines(after)
    for line in _claim_lines(before):
        if line in after_lines:
            continue
        if any(e and e in line for e in exempt):
            continue
        missing.append(line[:120])
    if missing:
        return False, (f"{len(missing)} cited line(s) were rewritten, e.g. "
                       f"{missing[0]!r}")
    return True, ""


CONSISTENCY_PROMPT = """You are the consistency editor for a finished endodontic teaching curriculum on "__QUESTION__".

Four module authors wrote independently from four different evidence bases. Each module is internally consistent and correctly cited. Your job is the one thing none of them could do: reconcile what they say to EACH OTHER.

YOU MAY ONLY ADD SENTENCES AND REPAIR MALFORMED BRANCHES. You may not rewrite, reword, shorten, re-order or re-source any existing claim, and you may not move, add or delete a [[PMID:N]] marker. This is enforced mechanically — output that touches an existing cited sentence is discarded in full, and the curriculum ships unannotated.

__DETECTED__

YOUR TASKS

1. PARAMETER CONFLICTS. For each conflict listed above, write ONE sentence that says which value goes with which study or clinical situation. A conflict is NOT an error — different trials use different concentrations and each module cites its own correctly. What is missing is the sentence that lets a clinician tell them apart. Anchor it to the module that introduces the parameter first. If the sources listed do not let you say which is which, say exactly that instead of guessing: "The evidence base does not establish which concentration is preferred."

2. CROSS-MODULE RECOMMENDATION TENSIONS. If two modules recommend incompatible actions for the same clinical situation, add ONE sentence naming the tension. Reconcile it ONLY if the evidence quoted in those modules settles it — higher tier, larger n, more recent. If it does not, say the tension is unresolved and name what would settle it. Never resolve a tension by asserting something neither module cites. If you find no genuine tension, return no annotation for this task; a manufactured tension is worse than a missed one.

3. MALFORMED BRANCHES. Each BECAUSE listed above contains no reason — only citations, or nothing. Write the reason, drawn ONLY from what the branch's own THEN and the cited papers in that module already state. A BECAUSE justifies a clinical instruction; a list of PMIDs is not a justification. Keep every existing [[PMID:N]] marker in your replacement text.

OUTPUT — return ONLY this JSON object, no fence, no commentary:

{
  "annotations": [
    {"anchor": "<a line copied VERBATIM from the curriculum, after which your sentence is inserted>",
     "text": "<your one sentence, plain markdown, may carry [[PMID:N]] markers that already appear in that module>",
     "kind": "parameter" | "tension"}
  ],
  "repairs": [
    {"because": "<the malformed BECAUSE body, copied VERBATIM from the list above>",
     "text": "<the replacement body: the reason, followed by the same [[PMID:N]] markers>"}
  ]
}

THE ANCHOR MUST BE ONE COMPLETE LINE, copied from its first character to its last. Not a prefix, not a sentence taken out of the middle of a paragraph, not a shortened version — the WHOLE line. An anchor that is not a complete line of the curriculum is dropped and your sentence is lost, because inserting after a partial line would split a clinical claim in half. Return empty lists rather than inventing work."""


def _consistency_findings_block(conflicts: list, malformed: list) -> str:
    """The detected items, as the prompt sees them.

    The model is told WHAT was found and asked only to write the sentence. It
    is never asked to search for conflicts itself: a model asked to find
    conflicts finds them whether or not they are there, and this pass edits a
    document that has already passed every other guardrail.
    """
    parts = []
    if conflicts:
        parts.append("PARAMETER CONFLICTS DETECTED (deterministically, by "
                     "comparing modules — these are real):")
        for c in conflicts:
            parts.append(f"\n  {c['agent']} ({c['unit']}):")
            for v in c["values"]:
                mods = ", ".join(m.replace("## ", "") for m in v["modules"])
                parts.append(f"    - {v['value']}{c['unit']} in {mods}")
                parts.append(f"      e.g. \"{v['example']}\"")
    else:
        parts.append("PARAMETER CONFLICTS DETECTED: none.")

    if malformed:
        parts.append("\nMALFORMED BECAUSE CLAUSES DETECTED:")
        for m in malformed:
            parts.append(f"    - [{m['reason']}] {m['because'] or '(empty)'}")
    else:
        parts.append("\nMALFORMED BECAUSE CLAUSES DETECTED: none.")
    return "\n".join(parts)


def _apply_consistency_edits(text: str, payload: dict, malformed: list) -> tuple:
    """Apply the model's insertions and repairs PROGRAMMATICALLY.

    (new_text, applied_counts). The model never returns the document — it
    returns anchors and sentences, and this function does the editing. That
    makes "annotate only, never rewrite" a structural property rather than
    something a guard has to catch after the fact, and it keeps the model's
    output small enough that the pass cannot itself be truncated: returning a
    40,000-character document from a model with an output cap is how Item 1's
    defect got into the modules in the first place.
    """
    applied = {"annotations": 0, "repairs": 0, "dropped_anchor": 0,
               "dropped_because": 0}

    for rep in (payload.get("repairs") or []):
        body, new = rep.get("because") or "", rep.get("text") or ""
        if not body or not new:
            continue
        if body not in text:
            applied["dropped_because"] += 1
            continue
        text = text.replace(body, new, 1)
        applied["repairs"] += 1

    # THE ANCHOR MUST BE A COMPLETE LINE, and this is the second thing the
    # laser regeneration taught this function.
    #
    # The first version inserted after any substring match. The model returned
    # a ~110-character prefix of a 398-character cited line, the insertion
    # split that line in two, the original no longer existed verbatim, and
    # `consistency_guard` reported "2 cited line(s) were rewritten" and
    # discarded the whole pass. The model had not rewritten anything — the
    # APPLIER had, by inserting into the middle of a sentence, and the guard
    # was right to refuse it.
    #
    # Matching whole lines makes an insertion structurally incapable of
    # splitting a claim: either the anchor names a line and the sentence goes
    # after it, or nothing happens.
    lines = text.split(chr(10))
    norm = [" ".join(l.split()) for l in lines]
    for ann in (payload.get("annotations") or []):
        anchor, sentence = ann.get("anchor") or "", ann.get("text") or ""
        if not anchor or not sentence:
            continue
        key = " ".join(anchor.split())
        try:
            i = norm.index(key)
        except ValueError:
            applied["dropped_anchor"] += 1
            continue
        lines[i + 1:i + 1] = ["", sentence]
        norm[i + 1:i + 1] = ["", " ".join(sentence.split())]
        applied["annotations"] += 1
    text = chr(10).join(lines)

    return text, applied


def annotate_curriculum_consistency(final_md: str, modules: list,
                                    parent_question: str) -> tuple:
    """One pass over the ASSEMBLED curriculum. (text, cost, report).

    `modules` is [(title, text), ...] — the module bodies as written, which is
    what the parameter comparison needs; the BECAUSE scan runs on the assembled
    document, because that is where the branches live after stitching.

    FAILS CLOSED, in three separate places. If the detectors find nothing, no
    call is made. If the model's reply will not parse, the document is returned
    unchanged. If `consistency_guard` says an existing cited line moved, the
    whole pass is discarded — an annotation is a convenience and a rewritten
    evidence claim is a defect, so there is never a reason to keep a pass that
    might have done the second to buy the first.
    """
    conflicts = detect_parameter_conflicts(modules)
    malformed = detect_malformed_because(final_md)
    report = {"conflicts": len(conflicts), "malformed": len(malformed),
              "applied": False, "reason": "", "counts": {}}

    if not conflicts and not malformed:
        report["reason"] = "nothing detected"
        print("  [consistency] no parameter conflicts, no malformed branches")
        return final_md, 0.0, report

    print(f"  [consistency] {len(conflicts)} parameter conflict(s), "
          f"{len(malformed)} malformed BECAUSE clause(s)")

    client = anthropic.Anthropic(api_key=_get_api_key())
    system = (CONSISTENCY_PROMPT
              .replace("__QUESTION__", parent_question)
              .replace("__DETECTED__",
                       _consistency_findings_block(conflicts, malformed)))
    try:
        resp = _invoke_claude(
            client, function_name="curriculum_consistency",
            model=MODELS["reasoning_standard"],
            max_tokens=3000,
            system=system,
            messages=[{"role": "user",
                       "content": "The assembled curriculum:\n\n" + final_md}],
        )
        cost = log_llm_call("curriculum_consistency",
                            MODELS["reasoning_standard"], resp.usage,
                            mode="learn")
    except Exception as e:                        # pragma: no cover
        report["reason"] = f"call failed: {type(e).__name__}: {e}"
        print(f"  [consistency] {report['reason']} — leaving the curriculum alone")
        return final_md, 0.0, report

    raw = resp.content[0].text
    try:
        payload = json.loads(_strip_json_fence(raw))
    except Exception as e:
        report["reason"] = f"unparseable reply ({type(e).__name__})"
        print(f"  [consistency] {report['reason']} — leaving the curriculum alone")
        return final_md, cost, report

    annotated, counts = _apply_consistency_edits(final_md, payload, malformed)
    report["counts"] = counts

    ok, why = consistency_guard(final_md, annotated,
                                repairable=[m["because"] for m in malformed])
    if not ok:
        report["reason"] = f"guard rejected the pass: {why}"
        print(f"  [consistency] REJECTED — {why}")
        print("  [consistency] shipping the curriculum unannotated")
        return final_md, cost, report

    report["applied"] = True
    print(f"  [consistency] applied {counts['annotations']} annotation(s), "
          f"{counts['repairs']} repair(s); dropped "
          f"{counts['dropped_anchor']} bad anchor(s), "
          f"{counts['dropped_because']} bad because-match(es)")
    return annotated, cost, report


STITCH_BUDGET_CEILING = 32000


def stitch_token_budget(module_blocks: str) -> int:
    """Output tokens the stitcher needs to reproduce `module_blocks` and wrap
    them.

    A FUNCTION rather than an expression inline, so a test can call it with
    real inputs instead of eval-ing a source line — which is the same
    source-inspection mistake that let three mutants through earlier in this
    batch.

    characters / 3.5 -> tokens; x1.35 because the stitcher re-punctuates and
    inserts transitions as it copies; + 3500 for the overview, takeaways,
    final verdict and reference list it writes itself.
    """
    return min(int(int(len(module_blocks or "") / 3.5) * 1.35) + 3500,
               STITCH_BUDGET_CEILING)


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
    # THE STITCHER WAS TRUNCATING EVERY FOUR-MODULE CURRICULUM EVER BUILT.
    #
    # This was `min(int((n_modules * 1800 + 2500) * 1.2), 32000)` = 11,640 for
    # four modules. Measured across every `stitch_curriculum` call in
    # `cost_log.jsonl`: **23 of 26 returned EXACTLY 11,640 output tokens.**
    # The stitcher must reproduce every module body VERBATIM and then add an
    # overview, transitions, takeaways and a reference list — so 1,800 tokens
    # per module was never the right unit. Modules measure 3,700-4,500 tokens
    # each, and the budget was under half of what reproduction alone needs.
    #
    # This is the SAME defect as the module cap and it is the one that produced
    # the reported symptom. "Module 4 ends mid-sentence" is what a reader sees
    # when the stitcher runs out of output partway through the LAST module it
    # was reproducing — which also explains why every truncation found in the
    # stored curricula sits in Module 4 and never in modules 1-3.
    #
    # Budget from the ACTUAL text this call has to reproduce, not from a
    # per-module guess: characters / 3.5 gives tokens, x1.35 for the model's
    # own phrasing, plus a fixed allowance for the parts it writes itself.
    stitch_budget = stitch_token_budget(module_blocks)

    print(f"\n[curriculum] Step D — stitching {n_modules} modules (budget={stitch_budget} tokens)")
    # TIER 2 (flag-gated) — Sonnet candidate; reproduces module bodies verbatim
    # and only writes overview/transitions/takeaways/refs (light synthesis).
    # STREAMED, and not for progress — there is no `on_partial` here and
    # nothing displays the partials. The SDK REFUSES a non-streaming request
    # whose `max_tokens` could take it past ten minutes:
    #
    #   ValueError: Streaming is required for operations that may take longer
    #   than 10 minutes
    #
    # The old 11,640 budget sat under that threshold, which is part of why the
    # under-budgeting went unnoticed for 26 runs — the value that was too small
    # to finish the job was also small enough never to trip this. Capping the
    # budget back under the threshold would "fix" the crash by restoring the
    # truncation, so the call streams instead.
    resp, cost = tier2_invoke(
        "stitch_curriculum",
        mode="learn",
        max_tokens=stitch_budget,
        stream=True,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    print(f"  Cost: ${cost:.4f} ({resp.usage.input_tokens} in / "
          f"{resp.usage.output_tokens} out, "
          f"stop={getattr(resp, 'stop_reason', '?')})")
    final = resp.content[0].text

    # ── DID EVERY MODULE SURVIVE? ──
    # The gate `dl-quality-v1` Item 1 put on module text cannot see this: each
    # module was complete when it was handed over, and the loss happens here.
    # A curriculum silently missing its last module is a worse failure than a
    # truncated sentence, because nothing in the document says anything is
    # absent.
    missing = _modules_missing_from_stitch(final, modules_with_scripts)
    truncated = getattr(resp, "stop_reason", None) == "max_tokens"
    if missing or truncated:
        why = (f"stop_reason=max_tokens" if truncated else "") + \
              (f" missing: {missing}" if missing else "")
        print(f"  [stitch] INCOMPLETE ({why.strip()}) — retrying once at the "
              f"ceiling")
        resp2, cost2 = tier2_invoke(
            "stitch_curriculum_retry",
            mode="learn",
            max_tokens=32000,
            stream=True,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        cost += cost2
        final2 = resp2.content[0].text
        missing2 = _modules_missing_from_stitch(final2, modules_with_scripts)
        if not missing2 and getattr(resp2, "stop_reason", None) != "max_tokens":
            print("  [stitch] retry is complete — using it")
            return final2, cost
        # STILL incomplete. Assemble deterministically rather than ship a
        # document with a module missing. The LLM stitcher writes the prose
        # around the modules; the modules ARE the curriculum, and losing one to
        # buy a nicer transition paragraph is not a trade worth making.
        print(f"  [stitch] retry STILL incomplete (missing: {missing2}) — "
              f"assembling deterministically")
        return _assemble_curriculum_without_stitcher(
            parent_question, modules_with_scripts, refs_block), cost

    return final, cost


def _modules_missing_from_stitch(final: str, modules_with_scripts: list) -> list:
    """Which module titles do NOT appear in the stitched document.

    Matched on the TITLE rather than on the body, because the stitcher is
    allowed to insert transitions and is not allowed to drop a module. A title
    is compared loosely — whitespace-normalised, case-folded — since the
    stitcher renumbers and re-punctuates headings.
    """
    hay = " ".join((final or "").split()).lower()
    out = []
    for m in modules_with_scripts or []:
        title = " ".join((m.get("title") or "").split()).lower()
        if not title:
            continue
        if title in hay:
            continue
        # A partial match is enough: the stitcher rewrites "Module 4 —
        # Clinical Outcomes" into its own heading style. Require most of the
        # title's distinctive words to be present together.
        words = [w for w in re.findall(r"[a-z]{4,}", title)]
        if words and sum(1 for w in words if w in hay) >= max(2, len(words) - 1):
            continue
        out.append(m.get("title"))
    return out


def _assemble_curriculum_without_stitcher(parent_question: str,
                                          modules_with_scripts: list,
                                          refs_block: str) -> str:
    """The fallback. Every module, in order, with no LLM in the loop.

    Deliberately plain, and it SAYS it is plain. A reader who is told the
    connective prose is missing has a complete curriculum with a rough edge; a
    reader who is told nothing has an incomplete curriculum that looks whole.
    """
    parts = [
        f"# {parent_question}",
        "",
        "> **Note — assembled without the editorial pass.** Every module below "
        "is complete and carries its own citations, but the overview, "
        "inter-module transitions and closing synthesis could not be generated "
        "within the output budget. Nothing has been omitted from the modules "
        "themselves.",
        "",
    ]
    for m in modules_with_scripts or []:
        parts.append(f"## {m.get('title', 'Module')}")
        parts.append("")
        parts.append(m.get("script", ""))
        parts.append("")
        parts.append("---")
        parts.append("")
    if refs_block:
        parts.append("## REFERENCES")
        parts.append("")
        parts.append(refs_block)
    return "\n".join(parts)


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


# ═════════════════════════════════════════════════════════════════════════
# PARALLEL MODULE GENERATION (steps B + C)
#
# Modules are independent of each other until the stitcher: each retrieves its
# own evidence and writes its own script over that evidence alone. Serially the
# phase costs sum(module_time); in parallel it costs max(module_time). Measured
# on the laser curriculum (run 2026-08-30 10:45, reconstructed from
# pubmed_audit.jsonl + cost_log.jsonl):
#
#   module   retrieval   writing   total
#     1         44.7s     145.1s   189.8s
#     2        107.9s     138.6s   246.5s
#     3         70.7s     131.7s   202.4s
#     4         63.5s     137.4s   200.9s
#   serial sum  286.8s    552.7s   839.5s      critical path: 246.5s
#
# Measured again after the change, same question, 4 workers: modules 229.9 /
# 236.3 / 235.9 / 257.5 s, phase 257.5 s wall against a 959.6 s serial
# equivalent (3.73x), whole curriculum 1080.7s -> 508.6s (18.01 -> 8.48 min).
# Cost moved 1.3633 -> 1.4772, entirely on module input tokens (243.8K ->
# 282.7K): same call count, same models, same max_tokens, larger evidence
# contexts from the retrieval changes that landed alongside this one.
#
# Bounded at 4 workers. What actually bounds this is not CPU:
#   * NCBI — every eutils request goes through _ncbi_rate_limit(), a
#     process-wide spacing lock (3 req/s bare, 9 with a key). Extra threads
#     queue behind it rather than exceeding it, so this module deliberately
#     adds NO second rate limiter; measured demand is ~0.2 req/s, far under it.
#   * The psycopg2 ThreadedConnectionPool (DB_POOL_MAX, default 10), which
#     RAISES rather than blocks when exhausted. One module holds at most one
#     connection at a time, so 4 workers leaves 6 spare.
#   * Anthropic — four concurrent Sonnet calls is inside any tier's limit.
CURRICULUM_MAX_WORKERS = max(1, int(os.getenv("CURRICULUM_MAX_WORKERS", "4")))

# Progress band owned by the parallel module phase (step A ends at 8,
# the stitcher starts at 82).
_MODULE_PROGRESS_BASE = 15
_MODULE_PROGRESS_SPAN = 60

import threading as _curriculum_thread
from concurrent.futures import ThreadPoolExecutor as _CurriculumPool
from concurrent.futures import as_completed as _curriculum_as_completed


def _is_cancellation(exc: BaseException) -> bool:
    """Did the progress callback abort us, or did it merely fail?

    app.py's learn-mode callback raises RuntimeError("Cancelled by user") when
    is_aborted(job_id) goes true. That raise IS the abort signal — it is the only
    one build_deep_learning_module ever receives. Any other callback failure is a
    UI problem and must not take down a run that has already been paid for.
    """
    return isinstance(exc, RuntimeError) and "cancel" in str(exc).lower()


class _CurriculumProgress:
    """Thread-safe, monotonic progress reporting for the parallel module phase.

    Two things break when N modules report from N threads:

      1. The callback mutates `jobs[job_id]`. app.py's update_job holds
         jobs_lock, so the dict itself is safe — but nothing serialises the
         *decision* about what percentage to report, and modules finishing out
         of order make a per-module percentage jump backwards.
      2. A smooth ramp stops being meaningful anyway once four modules are all
         "in progress" at once. So the module phase reports completions —
         "N of M modules complete" — and the percentage is clamped
         non-decreasing.
    """

    def __init__(self, progress_cb):
        self._cb   = progress_cb
        self._lock = _curriculum_thread.Lock()
        self._pct  = 0
        self._msg  = ""
        self._done = 0

    def tick(self, pct: int, msg: str) -> None:
        with self._lock:
            self._pct = max(self._pct, int(pct))
            self._msg = msg
            self._emit()

    def module_complete(self, total: int) -> int:
        """One module finished, in whatever order. Returns the new done count."""
        with self._lock:
            self._done += 1
            done = self._done
            self._pct = max(self._pct, _MODULE_PROGRESS_BASE +
                            int(done / max(total, 1) * _MODULE_PROGRESS_SPAN))
            self._msg = f"{done} of {total} modules complete"
            self._emit()
            return done

    def probe(self) -> None:
        """Re-emit the current state without moving it.

        Worker threads call this at their stage boundaries for one reason: to
        give the callback a chance to raise the cancellation that signals an
        aborted job. It is the parallel equivalent of the serial builder's
        is_aborted() checkpoints.
        """
        with self._lock:
            self._emit()

    def _emit(self) -> None:
        if not self._cb:
            return
        try:
            self._cb(self._pct, self._msg)
        except BaseException as e:      # noqa: BLE001 — deliberate, see below
            # The old _tick swallowed *everything*, which quietly disabled abort
            # for the whole learn path: app.py raised "Cancelled by user" into a
            # bare `except Exception: pass` and the run carried on to completion.
            # Cancellation now propagates; genuine callback bugs still do not.
            if _is_cancellation(e):
                raise


def _run_curriculum_module(idx: int, mod: dict, question: str, total: int,
                           progress: "_CurriculumProgress", abort_evt) -> dict:
    """Thread entry point for one module. See _curriculum_module_body.

    The only thing this adds is raising the abort flag on the way out of a
    failure. It has to happen here, not in the orchestrator: with fewer workers
    than modules, the worker thread picks up the next module the instant this
    one's future settles — before the main thread has woken from as_completed —
    and a run that has already lost a module should not pay for four more.
    """
    try:
        return _curriculum_module_body(idx, mod, question, total,
                                       progress, abort_evt)
    except BaseException:
        abort_evt.set()
        raise


def _curriculum_module_body(idx: int, mod: dict, question: str, total: int,
                            progress: "_CurriculumProgress",
                            abort_evt) -> dict:
    """Steps B + C for ONE module: retrieval, evidence gate, writing, validation.

    Runs on a worker thread. Returns
        {"index", "evidence", "entry", "cost", "elapsed"}
    and mutates nothing shared — the caller reassembles by "index", so the order
    modules happen to finish in cannot reach the document. Raises only on
    cancellation.

    Every gate is the serial one, unchanged: module_has_usable_evidence /
    MIN_MODULE_PAPERS, the single broadening retry, the "Module not generated"
    block, and validate_module_output's numeric-parameter-without-citation
    rejection. A module that failed its gate before still fails it here.
    """
    started = _time.perf_counter()
    num     = idx + 1
    title   = mod.get("title", f"Module {num}")

    def _bail():
        return {"index": idx, "evidence": {}, "entry": None, "cost": 0.0,
                "elapsed": _time.perf_counter() - started, "aborted": True}

    if abort_evt.is_set():
        return _bail()
    progress.probe()          # abort checkpoint before we spend anything

    # ── Step B — retrieval for this module ──
    print(f"\n[curriculum] Step B.{num}/{total} — retrieving: '{title}'")
    ev = build_evidence_base(mod["search_query"], mode="learn")
    ok, n_papers = module_has_usable_evidence(ev)

    # Retrieval came back empty or near-empty. Broaden the query once before
    # giving up — a narrow or over-specified query is the usual cause.
    if not ok:
        print(f"  [module {num}] only {n_papers} paper(s) — broadening and retrying")
        try:
            broadened = generate_search_terms(
                f"{mod['title']} (broad concept search; use OR-groups of "
                f"synonyms, abbreviations and device names)"
            )
            ev_retry = build_evidence_base(broadened, mode="learn")
            ok_retry, n_retry = module_has_usable_evidence(ev_retry)
            if n_retry > n_papers:
                ev, ok, n_papers = ev_retry, ok_retry, n_retry
                print(f"  [module {num}] broadened search found {n_retry} paper(s)")
        except Exception as e:
            print(f"  [module {num}] broadened retry failed: {e}")

    if abort_evt.is_set():
        return _bail()
    progress.probe()          # abort checkpoint between retrieval and writing

    if not ok:
        # Still nothing. Emit an explicit gap rather than a module: a numeric
        # protocol written from no sources is the worst output this system can
        # produce, and a disclaimer does not redeem it.
        print(f"  [module {num}] SKIPPED — {n_papers} paper(s), below minimum "
              f"{MIN_MODULE_PAPERS}")
        support = _support_not_run("module not generated — no evidence retrieved")
        return {
            "index":   idx,
            "evidence": ev,
            "cost":    0.0,
            "elapsed": _time.perf_counter() - started,
            "entry": {
                **mod,
                "script": _append_support_warnings(
                    _module_not_generated_block(
                        title, n_papers, mod.get("search_query", "")),
                    support),
                "not_generated":    True,
                "citation_support": support,
            },
        }

    # ── Step C — writing for this module ──
    script, cost = write_curriculum_module(mod, ev, question, idx=num, total=total)

    # ── THE ASSEMBLY GATE — a cut module never reaches the stitcher ──
    # `write_curriculum_module` has already regenerated once. If the text is
    # still cut, it must not be stitched: the stitcher is an LLM pass told to
    # reproduce module bodies verbatim, and on the 2026-09-01 laser curriculum
    # it silently REPAIRED the damage into something that looks well-formed —
    # a table row cut mid-cell arrived in the final document as
    # `| **Laser — Diode (aPDT)** | Wavelength 630 |`, closing pipe and all.
    # A reader cannot tell that from a row whose author meant to write 630.
    #
    # So the notice is emitted instead, the same one an evidence-less module
    # gets, for the same reason: a half-written clinical protocol is worse
    # than a stated absence.
    cut = detect_module_truncation(script)
    if cut["truncated"]:
        print(f"  [module {num}] REJECTED — truncated: {cut['reason']}")
        print(f"      tail: ...{cut['tail']}")
        support = _support_not_run("module not generated — the text was "
                                   f"truncated ({cut['reason']})")
        return {
            "index":   idx,
            "evidence": ev,
            "cost":    cost,
            "elapsed": _time.perf_counter() - started,
            "entry": {
                **mod,
                "script": _append_support_warnings(
                    _module_truncated_block(
                        title, cut["reason"], mod.get("search_query", "")),
                    support),
                "not_generated":    True,
                "truncated":        True,
                "citation_support": support,
            },
        }

    # Even with evidence present, refuse a module that specifies clinical
    # parameters while citing nothing.
    verdict = validate_module_output(script, ev)
    if not verdict["ok"]:
        print(f"  [module {num}] REJECTED — {verdict['reason']}")
        support = _support_not_run("module not generated — failed the "
                                   "evidence-anchoring gate")
        return {
            "index":   idx,
            "evidence": ev,
            "cost":    cost,
            "elapsed": _time.perf_counter() - started,
            "entry": {
                **mod,
                "script": _append_support_warnings(
                    _module_not_generated_block(
                        title, n_papers, mod.get("search_query", "")),
                    support),
                "not_generated":    True,
                "citation_support": support,
            },
        }

    # write_curriculum_module ran the citation-support check and recorded the
    # outcome on `mod` (see the note at its call to verify_citation_support).
    # Spreading mod carries it into the entry, where the post-stitch guarantee
    # in build_deep_learning_module can find it.
    return {"index": idx, "evidence": ev, "cost": cost,
            "elapsed": _time.perf_counter() - started,
            "entry": {**mod, "script": script}}


def build_deep_learning_module(question: str, progress_cb=None) -> tuple:
    """
    Top-level orchestrator for the agentic curriculum builder.
    Returns: (final_markdown, total_cost, combined_evidence)

    `progress_cb(percent: int, message: str)` — optional, called between stages
    so the Flask job tracker can update the UI.

    Steps B (retrieval) and C (writing) run concurrently across modules on a
    pool of at most CURRICULUM_MAX_WORKERS threads. Step D (the stitcher) is
    strictly after every module has finished, and module order in the output is
    the syllabus order regardless of completion order.
    """
    progress   = _CurriculumProgress(progress_cb)
    total_cost = 0.0

    # ── Step A — Syllabus ──
    progress.tick(8, "Generating curriculum syllabus...")
    syllabus, c = generate_curriculum_syllabus(question)
    total_cost += c

    n       = len(syllabus)
    workers = max(1, min(CURRICULUM_MAX_WORKERS, n))
    progress.tick(_MODULE_PROGRESS_BASE, f"0 of {n} modules complete")
    print(f"\n[curriculum] Steps B+C — {n} module(s) across {workers} worker(s)")

    # ── Steps B + C — retrieval and writing, one task per module ──
    abort_evt = _curriculum_thread.Event()
    results   = {}
    cancelled = None
    phase_t0  = _time.perf_counter()

    with _CurriculumPool(max_workers=workers,
                         thread_name_prefix="curriculum") as pool:
        futures = {
            pool.submit(_run_curriculum_module, i, mod, question, n,
                        progress, abort_evt): i
            for i, mod in enumerate(syllabus)
        }
        for fut in _curriculum_as_completed(futures):
            i = futures[fut]
            try:
                res = fut.result()
            except BaseException as e:
                if _is_cancellation(e):
                    # Tell every other worker to stop at its next checkpoint.
                    # We do NOT kill running threads: a half-torn Anthropic call
                    # is worse than waiting out the one in flight.
                    abort_evt.set()
                    cancelled = cancelled or e
                    continue
                abort_evt.set()
                raise
            if res.get("aborted"):
                continue
            results[i] = res
            try:
                progress.module_complete(n)
            except BaseException as e:
                if _is_cancellation(e):
                    abort_evt.set()
                    cancelled = cancelled or e
                else:
                    raise

    if cancelled is not None:
        # Same exception type and message the serial builder used to raise, so
        # app.py's `except RuntimeError` → status="aborted" is unchanged.
        raise cancelled

    phase_s  = _time.perf_counter() - phase_t0
    serial_s = sum(r.get("elapsed", 0.0) for r in results.values())
    for i in sorted(results):
        print(f"  [module {i+1}] wall {results[i].get('elapsed', 0.0):.1f}s  "
              f"${results[i].get('cost', 0.0):.4f}")
    print(f"[curriculum] module phase: {phase_s:.1f}s wall on {workers} worker(s); "
          f"serial equivalent {serial_s:.1f}s"
          + (f" ({serial_s / phase_s:.2f}x)" if phase_s > 0 else ""))

    # Reassemble in SYLLABUS order. Completion order must never reach the
    # document — a curriculum whose modules shuffle run to run is not the same
    # teaching artefact, and the stitcher writes transitions between whatever
    # order it is handed.
    per_module_evidence  = []
    modules_with_scripts = []
    for i in range(n):
        res = results.get(i)
        if res is None:
            # A worker that neither produced an entry nor cancelled the run.
            # Shrinking the curriculum silently is the wrong failure: render the
            # same explicit gap block the evidence floor renders.
            mod = syllabus[i]
            support = _support_not_run("module not generated — the module "
                                       "worker produced no output")
            modules_with_scripts.append({
                **mod,
                "script": _append_support_warnings(
                    _module_not_generated_block(
                        mod.get("title", f"Module {i+1}"), 0,
                        mod.get("search_query", "")),
                    support),
                "not_generated":    True,
                "citation_support": support,
            })
            continue
        per_module_evidence.append(res["evidence"])
        modules_with_scripts.append(res["entry"])
        total_cost += res["cost"]        # summed in index order → deterministic

    # ── Step D — Stitch (strictly after every module has completed) ──
    progress.tick(82, "Stitching curriculum...")
    combined = merge_evidence_bases(per_module_evidence)
    final, c = stitch_curriculum(question, modules_with_scripts, combined)
    total_cost += c

    # The stitcher is an LLM told to reproduce module bodies verbatim. If it
    # drops a citation-support block anyway, the reader sees a module with no
    # status — indistinguishable from a module that passed. Restate whatever
    # did not survive, deterministically.
    final = _ensure_curriculum_support_blocks(final, modules_with_scripts)

    # ── CROSS-MODULE CONSISTENCY (dl-quality-v1 Item 4) ──
    # AFTER assembly and after the support blocks are restored, because it
    # annotates the document a reader actually receives. It runs last for a
    # second reason: every other guardrail has already passed by this point,
    # so anything this pass changes is a change to output that was otherwise
    # ready to ship — which is why it may only insert, and why it discards
    # itself entirely rather than risk touching a cited sentence.
    progress.tick(93, "Checking cross-module consistency...")
    final, c, _consistency = annotate_curriculum_consistency(
        final, [(m["title"], m["script"]) for m in modules_with_scripts],
        question)
    total_cost += c

    progress.tick(95, "Finalising...")
    return final, total_cost, combined


# ── DIFFERENTIAL GENERATION (diagnostic case turns) ──────
#
# Clinical-reasoning scaffolding, NOT final content. Nothing this returns
# reaches the clinician: it becomes retrieval topics, and the synthesis prompt
# then ranks the candidates against the evidence that came back. A candidate
# with no literature behind it is a candidate the answer must say it cannot
# support, which is the whole point of generating them explicitly.
#
# WHY IT EXISTS. Measured in `case-v2` Item 1 on the reported case — a
# 20-year-old with a necrotic, unrestored, caries-free tooth — sampling the
# search-term generators 8 times:
#
#   trauma / luxation / fracture   8/8
#   crack / infraction             4/8
#   "developmental anomaly"        4/8
#   dens invaginatus               2/8
#   dens evaginatus                1/8
#   palatogingival groove          0/8
#
# The brief's hypothesis was that the query contained no candidate etiology.
# It contained one — always trauma — and the rest were a coin flip. That is
# worse than it sounds: a differential the retrieval reaches only 25% of the
# time is a differential the answer can cite only 25% of the time, and the
# grounding rule then correctly stops the model asserting the other 75%
# without a paper. Enumerating candidates first turns a coin flip into a list.
DIFFERENTIAL_MIN = 3
DIFFERENTIAL_MAX = 6

DIFFERENTIAL_PROMPT = """You are an endodontist reasoning about what is CAUSING a clinical finding — not yet about what to do.

CASE:
\"\"\"{case}\"\"\"

THIS TURN ASKS:
\"\"\"{turn}\"\"\"

List the {lo}-{hi} candidate CAUSES worth considering, most likely first. Reason from the specific features of THIS case — the patient's age, the state of the tooth, what is present and what is conspicuously absent.

Rules:
- A candidate is an AETIOLOGY or a DIAGNOSIS, never a treatment. "Dens invaginatus" is a candidate; "root canal treatment" is not.
- Name what in THIS case supports it, and what would argue against it. Use the case's own words where you can.
- Include candidates the case's ABSENCES point to. A necrotic tooth with no caries and no restoration is a different differential from a necrotic tooth with a deep filling, and the absence is the informative part.
- WHICH TOOTH IT IS, and who the patient is, are strong priors — use them explicitly. A tooth number or name tells you which developmental anomalies are even possible: dens invaginatus concentrates in maxillary lateral incisors, dens evaginatus in mandibular premolars, the palatogingival groove in maxillary laterals, and a mandibular premolar in a patient of East or Southeast Asian ancestry is the classic dens evaginatus presentation. Where the case gives you a tooth or a demographic, say in `supports` what it makes MORE likely, and do not let a candidate that is common overall crowd out one that is common in THIS tooth.
- Do not omit an uncommon cause that fits the presentation well. A differential that lists only the common things is not a differential.
- Name the single examination, test or image that would most cheaply confirm or exclude each candidate.

Return ONLY a JSON array, no prose and no markdown fence:
[
  {{"candidate": "short name of the cause",
    "supports": "the case features that fit it",
    "against": "the case features that do not, or 'nothing in this case argues against it'",
    "discriminator": "the single test, sign or image that settles it",
    "search_topic": "a literature search topic for this candidate in this presentation"}}
]"""


def _parse_candidate_array(raw: str):
    """Parse the differential's JSON array, tolerantly. None if nothing parses.

    Three rungs, and the third is the one that matters:

      1. the whole reply as JSON;
      2. the first bracketed array in it, for a prose wrapper;
      3. OBJECT BY OBJECT, for a reply the model did not finish.

    Rung 3 exists because a truncated list is not an empty list. When the
    reply stops at `max_tokens` mid-string, the first four or five candidate
    objects are complete and perfectly usable — and the alternative, returning
    nothing, drops a diagnostic turn onto the treatment path where it produces
    the very answer this feature was built to replace. Losing the last
    candidate is a smaller error than losing the differential.
    """
    if not raw:
        return None
    for attempt in (raw, ):
        try:
            data = json.loads(attempt)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    m = re.search(r"\[.*\]", raw, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    decoder = json.JSONDecoder()
    out, i = [], 0
    while True:
        i = raw.find("{", i)
        if i < 0:
            break
        try:
            obj, end = decoder.raw_decode(raw, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
        i = end
    if out:
        print(f"  [case] differential JSON was incomplete; recovered "
              f"{len(out)} candidate(s) object by object")
        return out
    return None


def generate_case_differential(case_description: str, turn: str = "") -> tuple:
    """Return (candidates, cost) for a diagnostic case turn.

    `candidates` is a list of dicts with keys candidate / supports / against /
    discriminator / search_topic, capped at DIFFERENTIAL_MAX.

    Fails to an EMPTY list, never to an invented one. An empty differential
    sends the caller back to the ordinary case path — the same answer it would
    have produced before this function existed — whereas a fabricated
    differential would drive retrieval with topics no clinician proposed.
    """
    text = (turn or case_description or "").strip()
    if not text:
        return [], 0.0
    cost = 0.0
    try:
        client = anthropic.Anthropic(api_key=_get_api_key())
        resp = _invoke_claude(
            client, function_name="generate_case_differential",
            # Sonnet, not Haiku: this is the clinical-reasoning step, and the
            # thing it has to get right is remembering the uncommon cause that
            # fits. Tier 2 is where that lives.
            model      = MODELS["reasoning_standard"],
            # 1500 -> 3000. Six candidates x five prose fields does not fit in
            # 1500 output tokens: the reply stopped at `max_tokens` mid-string,
            # `json.loads` raised "Unterminated string", this function returned
            # [], and the caller fell back to the ordinary case path — so a
            # DIAGNOSTIC turn was answered with a treatment-shaped answer that
            # opened "Proceed with non-surgical root canal treatment". That is
            # the exact failure `case-v2.1` exists to fix, reintroduced by a
            # token cap. Measured: 1,500 output tokens, stop_reason max_tokens.
            max_tokens = 3000,
            messages   = [{"role": "user", "content": DIFFERENTIAL_PROMPT.format(
                case=(case_description or text)[:6000], turn=text[:6000],
                lo=DIFFERENTIAL_MIN, hi=DIFFERENTIAL_MAX)}])
        cost = log_llm_call("generate_case_differential",
                            MODELS["reasoning_standard"], resp.usage,
                            mode="case")
        raw = re.sub(r"```json|```", "", resp.content[0].text or "").strip()
        data = _parse_candidate_array(raw)
        if data is None:
            raise ValueError("no candidate object could be parsed")
        out = []
        for item in (data if isinstance(data, list) else []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("candidate") or "").strip()
            if not name:
                continue
            out.append({
                "candidate":     name[:120],
                "supports":      str(item.get("supports") or "").strip()[:400],
                "against":       str(item.get("against") or "").strip()[:400],
                "discriminator": str(item.get("discriminator") or "").strip()[:240],
                "search_topic":  (str(item.get("search_topic") or "").strip()
                                  or name)[:240],
            })
        return out[:DIFFERENTIAL_MAX], cost
    except Exception as e:
        print(f"  [case] differential generation failed, falling back to the "
              f"ordinary case path: {e}")
        return [], cost


# The shape a TREATMENT turn answers in. Unchanged from before `case-v2`:
# treatment is the measured path and this batch does not touch it.
_CASE_FORMAT_TREATMENT = """Format every response exactly like this:

**Assessment:** 1-2 sentences on your clinical interpretation.

**Recommendation:** Clear, actionable recommendation with rationale.

**Evidence:** the studies that actually bear on THIS case, cited as Author et al. (Year) [[PMID:XXXXXXXX]]. Draw across the tiers you were given — a systematic review for the general question, a cohort or case series for the specific presentation — rather than stopping at the first one or two. You are typically given 40-150 papers; citing two of them wastes evidence the clinician is relying on you to have read. Cite as many as genuinely support the advice and no more: breadth that is real, never padding.

**Key Considerations:** Any caveats, red flags, alternative approaches, or follow-up plan."""

_MARKERS_TREATMENT = ("- Do NOT add markers to the **Assessment** sentence "
                      "(which is your interpretation, not an evidence-derived "
                      "claim) or to general transitions. Markers belong on "
                      "**Recommendation**, **Evidence**, and any **Key "
                      "Considerations** that cite literature.")

# The shape a DIAGNOSTIC turn answers in. The clinician asked what is CAUSING
# this; an answer that opens with management has answered a question they did
# not ask, and `case-v2` Item 1 found the old prompt had nowhere else to put
# the reasoning — Assessment was one sentence and Recommendation was a plan.
_CASE_FORMAT_DIAGNOSTIC = """The clinician is asking what is CAUSING this, not what to do about it. Answer the question they asked, in this order and no other:

**Differential — most likely first**

One block per candidate cause, in descending order of likelihood FOR THIS PATIENT. For each:

**1. <Candidate cause>**
- *Fits because:* the features of THIS case that support it — the age, the tooth, what is present, and what is conspicuously absent.
- *Argues against:* the features that do not fit, or "nothing in this case argues against it".
- *Evidence:* what the literature says about this cause in this presentation, with markers. If the evidence base contains nothing on this candidate, say exactly that — "no paper in this evidence base addresses X in this presentation" — and keep the candidate in the list. A cause worth considering does not stop being worth considering because nobody has published on it, and an unmarked candidate the clinician can see is worth more than a candidate you dropped.

**What would discriminate**

The examinations, tests or images that would separate these candidates, each named against the candidate it settles — a transillumination test for a crack, CBCT for an invagination or a radicular groove, a trauma history for a prior luxation. Order them by how much they narrow the differential per unit of chair time.

**Then, briefly: management**

Two to four sentences, no more, and only after the differential. What to do first, and what the plan would become under each of the top candidates. Do not turn this into the answer — if the management section is longer than the differential, you have written the wrong answer.

Do not open with management, a treatment plan, or a guideline. The first thing on the page is the differential."""

_MARKERS_DIAGNOSTIC = (
    "- Markers belong on the *Evidence:* line of each candidate. Do NOT mark "
    "the *Fits because:* and *Argues against:* lines — those are your reading "
    "of THIS case, not claims about a paper, and a marker on them asserts "
    "something no paper says.\n"
    "- In the discriminator section, a marker goes on a test ONLY where the "
    "cited paper itself evaluated that test. A line that merely says which "
    "candidate a test settles — \"also evaluates canal obliteration for "
    "candidate 5\", \"confirms this candidate\" — is your clinical reasoning "
    "and takes NO marker. It is not a proposition a paper can support, and a "
    "marker there is a citation the clinician cannot check.\n"
    "- A statement about what the evidence base does NOT contain — \"no "
    "literature here evaluates this sign in isolation\" — is a true and useful "
    "thing to write and takes NO marker, because no abstract can state what it "
    "omits. Write it as its own sentence. If you then want to say something "
    "positive that a paper does support, that is a SECOND sentence, and the "
    "marker goes there.")


# ── CASE DISCUSSION ───────────────────────────────────────
def ask_case_question(messages: list, evidence: dict,
                      differential: list = None, stream_cb=None,
                      abort_cb=None, phase_cb=None) -> tuple:
    """
    Clinical case discussion / chat mode.
    messages: conversation history [{"role": "user"|"assistant", "content": str}]
    `differential` — when non-empty, this is a DIAGNOSTIC turn: the answer is
    formatted as a ranked differential and the candidates are supplied to the
    model as reasoning scaffolding. Omitted or empty means the treatment path,
    byte-identical to what shipped before `case-v2`.

    `stream_cb(partial_markdown)` / `abort_cb()` / `phase_cb(label)` are the
    same three the Review path takes, and they mean the same things here
    (`case-v3` Item E). A case turn's wall time is dominated by synthesis and
    the post-checks, not retrieval, so the clinician was watching a spinner for
    the whole of both. With `stream_cb` the differential or the assessment is
    readable while the rest is still being written, and `phase_cb` fires when
    the model stops so the header chips can say "checking…" for exactly the
    window in which that is true.

    THE GUARDRAIL INVARIANT, unchanged and load-bearing:
    `validate_evidence_mapping` and `verify_citation_support` run on `answer`,
    read from the FINAL message after the stream closes. Neither is reachable
    from inside `stream_cb`. A half-written "[[PMID:312" would read as a
    fabrication and produce a false warning about a good answer, so partial
    text must never reach them.

    Returns (answer, cost).
    """
    client = anthropic.Anthropic(api_key=_get_api_key())
    diagnostic = bool(differential)

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

__CASE_FORMAT__

INLINE PROVENANCE (REQUIRED for clinician verifiability):
Every standalone clinical claim — a recommendation, statistic, treatment success rate, comparative finding, or factual statement supported by literature — MUST be followed immediately by `[[PMID:nnnnnnn]]` markers, one per supporting paper. Use the EXACT format `[[PMID:12345678]]` (double brackets, no space after the colon). Place markers at the END of the sentence the claim appears in.
- Example: "MTA outperforms calcium hydroxide in vital pulp therapy [[PMID:31543236]] [[PMID:34234567]]."
- Multiple supporting papers can be cited (space-separated markers).
- If a claim summarises a systematic review's pooled estimate, cite the SR's PMID, not the underlying primary trials.
__MARKER_PLACEMENT__
- The double-bracket format `[[PMID:N]]` is what powers the click-through source-abstract side panel in the UI. Do NOT use the single-bracket form `[PMID: N]` anywhere in your response — the UI will not recognise it as a verifiability marker.
- NEVER name an author without a marker. "Sjögren et al. demonstrated…" tells the clinician a specific paper exists and gives them nothing to click, which is the same failure as a bare PMID. Either wrap the paper — "Sjögren et al. demonstrated X [[PMID:N]]" — or drop the name and state the point without attributing it to anyone.

A NUMERIC CLINICAL DIRECTIVE HAS EXACTLY THREE HONEST ENDINGS.
A step a clinician can act on — a depth, an interval, a number of visits, a material, a recall period — is a claim. When the evidence block does not support one, you have three moves and no fourth:
1. CITE it, if a paper in the block states it.
2. CUT it, if it is not needed to answer the question.
3. LABEL it, if it is genuinely standard practice and the clinician needs it: write it and mark it plainly — "standard practice, not from the retrieved evidence base" — carrying NO marker.
What you must never do is state it with the same confidence as a cited step and no marker. "Reduce in 0.5 mm increments at 6–8 week intervals" reads exactly like the cited sentence above it, and the clinician has no way to tell them apart. Silent confidence is the failure; a labelled convention is not.

__GROUNDING_RULE__

Keep responses concise and focused. Build naturally on prior messages in the conversation.
Never fabricate PMIDs or invent studies.
NEVER end your response with a question to the clinician. NEVER ask for more information. If missing details would change your recommendation, list what those details are — but do not pose questions.

UNIVERSAL NUMBERING SYSTEM — always use the correct tooth name when a number is mentioned:
Upper (R→L): 1=Mx R 3rd molar, 2=Mx R 2nd molar, 3=Mx R 1st molar, 4=Mx R 2nd premolar, 5=Mx R 1st premolar, 6=Mx R canine, 7=Mx R lateral incisor, 8=Mx R central incisor, 9=Mx L central incisor, 10=Mx L lateral incisor, 11=Mx L canine, 12=Mx L 1st premolar, 13=Mx L 2nd premolar, 14=Mx L 1st molar, 15=Mx L 2nd molar, 16=Mx L 3rd molar
Lower (L→R): 17=Mn L 3rd molar, 18=Mn L 2nd molar, 19=Mn L 1st molar, 20=Mn L 2nd premolar, 21=Mn L 1st premolar, 22=Mn L canine, 23=Mn L lateral incisor, 24=Mn L central incisor, 25=Mn R central incisor, 26=Mn R lateral incisor, 27=Mn R canine, 28=Mn R 1st premolar, 29=Mn R 2nd premolar, 30=Mn R 1st molar, 31=Mn R 2nd molar, 32=Mn R 3rd molar
(Mx=Maxillary, Mn=Mandibular)"""

    # Same shared rule as the Review and curriculum prompts. NOT measured this
    # batch: neither eval subset contains a case, so the change here rests on
    # the Review and Deep Learning before/after numbers and on the fact that
    # the defect it addresses is identical in all three prompts. Leaving one
    # synthesis path with a known mechanism for a decorative citation, to keep
    # a measurement tidy, is the worse trade.
    system_prompt = system_prompt.replace("__GROUNDING_RULE__", _GROUNDING_RULE)
    system_prompt = system_prompt.replace(
        "__CASE_FORMAT__",
        _CASE_FORMAT_DIAGNOSTIC if diagnostic else _CASE_FORMAT_TREATMENT)
    system_prompt = system_prompt.replace(
        "__MARKER_PLACEMENT__",
        _MARKERS_DIAGNOSTIC if diagnostic else _MARKERS_TREATMENT)

    # Build evidence context — strict tier order (Cochrane → L5),
    # same builder as review/learn modes
    context = _build_evidence_context(evidence)

    # The candidates reach the model as SCAFFOLDING, explicitly labelled as a
    # working list rather than a conclusion. It is a starting point it is told
    # to revise: a differential the model cannot argue with is a differential
    # the retrieval step has quietly made final, and the retrieval step never
    # read the papers.
    scaffold = ""
    if diagnostic:
        lines = ["\n\n---\n\nWORKING DIFFERENTIAL (a first pass, generated "
                 "BEFORE the literature below was read — revise it against "
                 "the evidence, reorder it, drop a candidate the papers rule "
                 "out, and add one they suggest):\n"]
        for i, c in enumerate(differential, 1):
            lines.append(
                f"{i}. {c.get('candidate', '')}\n"
                f"   fits because: {c.get('supports', '')}\n"
                f"   argues against: {c.get('against', '')}\n"
                f"   discriminator: {c.get('discriminator', '')}")
        diff_meta = (evidence.get("_differential") or {})
        # WHICH CANDIDATE EACH PAPER CAME FROM. Without this the evidence block
        # is one undifferentiated pool and every PMID in it looks equally
        # available to every candidate — which is how a paper titled "clinical
        # outcomes of vital intact teeth close to large cystic lesions" came to
        # carry three claims about dens invaginatus prevalence, complete with
        # counts ("93/170", "134/136") that appear nowhere in it. Three real
        # flags in one answer, all the same mechanism: a real PMID from the
        # block attached to a fact the model knew from somewhere else.
        with_papers = [(n, v) for n, v in diff_meta.items() if v.get("pmids")]
        if with_papers:
            lines.append(
                "\nWHICH PAPERS WERE RETRIEVED FOR WHICH CANDIDATE. A paper "
                "retrieved for one candidate is not evidence for another just "
                "because it is in the block below — check that the paper's own "
                "subject is the candidate you are citing it for:")
            for name, v in with_papers:
                lines.append(f"  - {name}: "
                             + ", ".join(str(p) for p in v["pmids"][:25]))
        empties = [n for n, v in diff_meta.items() if not v.get("n_papers")]
        if empties:
            lines.append(
                "\nThe evidence base below contains NO papers retrieved for: "
                + "; ".join(empties)
                + ". Keep these candidates in the differential and say plainly "
                  "that the evidence base does not address them — do not drop "
                  "them, and do not attach a marker to them.")
        scaffold = "\n".join(lines)

    # Inject evidence only into the first user message
    api_messages = []
    for i, msg in enumerate(messages):
        if i == 0 and msg["role"] == "user":
            api_messages.append({
                "role": "user",
                "content": (
                    f"Evidence base for this consultation:\n{context}\n\n"
                    f"---\n\nCase: {msg['content']}{scaffold}"
                )
            })
        else:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

    print(f"\nCase consultation -- asking Claude...")
    print("=" * 60)

    def _publish_partial(partial_text: str):
        # A failure to show progress must never fail the answer.
        try:
            stream_cb(partial_text)
        except Exception as e:      # pragma: no cover — defensive
            print(f"  [stream] partial publish failed: {type(e).__name__}: {e}")

    # TIER 2 (flag-gated) — Sonnet candidate; 2K tok chat-friendly responses
    # with conversation memory, no fresh evidence synthesis required.
    stream_kwargs = {}
    if stream_cb is not None or abort_cb is not None:
        stream_kwargs = {
            "stream":     stream_cb is not None,
            "on_partial": _publish_partial if stream_cb is not None else None,
            "abort_cb":   abort_cb,
        }
    resp, cost = tier2_invoke(
        "ask_case_question",
        mode       = "case",
        # 2000 -> 6000. Measured: case answers cited a median of 2 papers from
        # a median-100 evidence base. A conversational answer that must also
        # carry citations cannot spend what it has not got; ask_clinical_question
        # runs at 8000. Kept below Review's because a chairside reply should
        # still read as a conversation, not a literature review.
        max_tokens = 6000,
        system     = system_prompt,
        messages   = api_messages,
        **stream_kwargs,
    )
    print(f"  Cost: ${cost:.4f} ({resp.usage.input_tokens} in / {resp.usage.output_tokens} out)")

    # THE COMPLETE text, read off the final message — never off the accumulated
    # stream chunks and never off anything `stream_cb` was handed. Everything
    # past this line sees this string and only this string.
    answer = resp.content[0].text

    if abort_cb is not None and abort_cb():
        # Cancelled while the last tokens were in flight — do not spend two
        # more LLM calls validating an answer nobody will read.
        raise StreamAborted()

    if phase_cb is not None:
        # The model has stopped writing and the guardrails have NOT finished.
        # The chips say "checking…" for exactly this window.
        try:
            phase_cb("checking")
        except Exception as e:      # pragma: no cover — defensive
            print(f"  [stream] phase publish failed: {type(e).__name__}: {e}")

    # `trust-surface-v1` Q2 — quarantine before anything reads the answer.
    # Every downstream consumer (validator, support check, cache, export,
    # narration) sees the normalised text, so the block cannot be a browser
    # decoration that a PDF or a slide quietly drops.
    answer, _quarantined = finalise_answer_text(answer)
    if _quarantined:
        print(f"  [quarantine] {len(_quarantined)} span(s) labelled outside "
              f"the evidence base, lifted into their own block")

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
            max_tokens = 6000,
            system     = system_prompt,
            messages   = retry_messages,
        )
        cost += retry_cost
        retry_answer = retry_resp.content[0].text
        retry_answer, _rq = finalise_answer_text(retry_answer)
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

    # The v2 guardrail, now on the case path too. validate_evidence_mapping
    # above proves every cited PMID is REAL; this asks the separate question of
    # whether the cited abstract actually SUPPORTS the claim, which is what
    # catches a real-but-irrelevant citation. It ran only inside
    # ask_clinical_question, so chairside advice — the output most likely to be
    # acted on immediately — was the one place it was missing. Fail-open and
    # advisory, exactly as on the Review path.
    support = verify_citation_support(answer, evidence)
    cost += support.get("cost", 0.0)
    answer = _append_support_warnings(answer, support)

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

8. stat_panel  (ONE quantity measured across TWO OR MORE arms — a like-for-like comparison)
   {"pattern":"stat_panel","eyebrow":"MODULE X · OUTCOMES","title":"Short title","primary_stat":"86.9%","primary_label":"Laser-activated irrigation","secondary_stat":"74.5%","secondary_label":"Conventional irrigation","callout":"Insight sentence about the comparison.","citation":"Author et al., Journal Year [[PMID:N]]","speaker_notes":"..."}
   primary_stat and secondary_stat MUST be the SAME quantity in the SAME unit, copied
   digit-for-digit from the evidence report (86.9%, not "approximately 87%").
   primary_label and secondary_label name the two ARMS being compared, 2-5 words each —
   the title and callout say what is being measured, the labels say who is being measured.
   Put every supporting [[PMID:N]] in "citation".
   Omit secondary_stat/secondary_label only when the slide is a single headline number
   with no counterpart in the source — see the comparison rules below.

   THREE OR MORE ARMS — use "arms" INSTEAD OF primary/secondary, never both:
   {"pattern":"stat_panel","eyebrow":"MODULE X · OUTCOMES","title":"Short title","arms":[{"label":"1% NaOCl","stat":"78.4%"},{"label":"2.5% NaOCl","stat":"88.1%"},{"label":"5.25% NaOCl","stat":"96.2%"}],"callout":"Insight sentence.","citation":"Author et al., Journal Year [[PMID:N]]","speaker_notes":"..."}
   Use "arms" for a dose-response ladder, three or more wavelengths, or any
   comparison the source measured across more than two groups — those were
   previously impossible to state and had to be flattened to a pair or written
   as prose. 2-8 arms. Every rule above still applies to EVERY arm: one
   quantity, one unit, each value digit-for-digit from the evidence report. If
   any single arm's number is not in the source, or one arm carries a different
   unit or a range, the whole comparison is refused — so do not pad a ladder
   with an arm you are unsure of.

9. evidence_summary  (evidence hierarchy + insight callout)
   {"pattern":"evidence_summary","eyebrow":"MODULE X · EVIDENCE","title":"Short title","hierarchy_rows":[{"tier_label":"PRIMARY","description":"What studies","stat":"96.1%","color":"accent_teal"}],"trap_callout":{"heading":"THE TRAP","body":"Why headline figure misleads.","stat":"61%","stat_label":"What the real number is","color":"accent_coral"},"speaker_notes":"..."}
   color options: accent_teal, accent_gold, accent_coral, ink_secondary, ink_muted
   "stat" is OPTIONAL per row. Include it only when that row carries a real number in the
   SAME unit as every other row's stat. A verdict word ("Unproven", "Limited", "Superior",
   "p < 0.05") is not a stat — omit the key on that row and put the word in "description".
   Mixing a number and a word across rows makes the whole set unusable.

10. takeaways_slide  (final summary, always last or second-to-last)
    {"pattern":"takeaways_slide","eyebrow":"MODULE X · KEY TAKEAWAYS","title":"Short serif italic title","items":[{"number":"01","header":"Bold takeaway","body":"Supporting sentence."}],"does_not_apply":"The single clearest situation in which this recommendation does NOT hold, taken verbatim from the source text. Omit the key entirely if the source states no such limit — never invent one.","speaker_notes":"..."}
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
- Two arms measured on the SAME outcome (success rate, reduction %, healing %) → stat_panel
- THREE OR MORE arms on the same outcome (a concentration ladder, several wavelengths,
  three materials) → stat_panel with "arms". Do not flatten it to the best two.
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

COMPARISON RULES (these decide whether a slide's numbers can be plotted — read them before writing any stat):
- When presenting a comparison, give two or more values of the SAME quantity in the SAME unit
  across arms or groups — success rate % for single-visit vs multiple-visit, lesion volume
  reduction % for laser vs control, bacterial reduction % per wavelength — with the [[PMID:N]]
  for that comparison in the slide's "citation" field. Two arms go in
  primary_stat/secondary_stat; three or more go in "arms" (pattern 8). The
  number of arms is whatever the source measured — do not drop one to fit a pair.
- A single value pairs with nothing. NEVER pair different quantities: an effect size beside a
  heterogeneity statistic (SMD −0.551 vs I² 23.89%), a duration beside a count (24–48 h vs 0
  adverse events), an outcome beside a device setting (86.9% vs 2940 nm · 75–100 mJ). Those are
  two facts, not a comparison — put each in prose on a content_slide or cascade_slide instead.
- Ranges are text, not comparison values: "24–48 h", "2–3 mL", "0.005%–0.1%" may never be used
  as primary_stat, secondary_stat or a hierarchy "stat".
- Words are not stats: "Superior", "Limited", "Unproven", "Significant", "p < 0.05", "Day 7".
- Every comparison value must carry its unit (%, mm, months, mJ, n=). A bare unitless number
  is never a comparison value: standardised mean differences, P-scores, odds ratios, I²,
  p-values and confidence limits belong in the callout or speaker_notes as prose, never in
  primary_stat, secondary_stat or a hierarchy "stat". Two unitless numbers look comparable
  and usually are not (a P-score of 0.993 and an SMD of −0.58 measure nothing in common).
- Copy each value digit-for-digit from the evidence report — same digits, same decimal places.
  A rounded or re-derived number is treated as fabricated.
- If the evidence report contains no same-quantity comparison for a topic, emit no stat_panel
  and no hierarchy stats for it. A comparison is optional; a false comparison is forbidden.

CONTENT RULES:
- speaker_notes per slide: ~{words_per_slide} words, natural spoken English, no markdown, no headers. This is the narration track the clinician will hear.
- Card body / table cell / step body: terse, max 20 words each
- All statistics must come from the evidence report below — do not fabricate numbers
- Use [[PMID:N]] citations within speaker_notes and in the "citation"/"footer_caption" fields; never in card body text, labels or headers
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
    print("  ENDO AI -- Evidence-Based Dental Educator")
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