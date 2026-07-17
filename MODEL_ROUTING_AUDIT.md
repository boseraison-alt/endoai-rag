# Model Routing Audit

**Date:** 2026-04-27
**Status:** PROPOSAL — no code changes made yet. Awaiting approval.

## Methodology

Searched the codebase for every `client.messages.create(...)` invocation. All 13 Claude calls live in `endo_ai.py`; `app.py` contains zero direct Anthropic calls (it imports the helpers).

Vision calls (Gemini / OpenAI for radiograph analysis) live at `endo_ai._analyze_with_gemini` (line 2158) and `endo_ai._analyze_with_openai` (line 2192). These are **out of scope** for this audit — they target a different provider — but flagged here for completeness.

## Current state — every Claude call

| # | Function | File:Line | Current model | max_tokens | Typical input | Task type | Used by mode |
|---|---|---|---|---|---|---|---|
| 1 | `generate_clarifying_questions` | endo_ai.py:181 | `claude-opus-4-5` | 300 | ~200 tok | classification + JSON gen | Review, Case Discussion (clarify gate) |
| 2 | `generate_multi_search_terms` | endo_ai.py:220 | `claude-opus-4-5` | 200 | ~150 tok | structured (JSON list) | Review (RAG fallback path) |
| 3 | `generate_search_terms` | endo_ai.py:507 | `claude-opus-4-5` | 200 | ~100 tok | structured (single string) | Review, Learn, Case Discussion (every retrieval) |
| 4 | `ask_clinical_question` | endo_ai.py:1216 | `claude-opus-4-5` | 8000 | 5–25 K tok | **complex multi-tier evidence synthesis** | Literature Review (primary) |
| 5 | `ask_learn_question` (legacy) | endo_ai.py:1341 | `claude-opus-4-5` | 8000 | 5–25 K tok | **complex multi-tier evidence synthesis** | Deep Learning (legacy single-shot fallback only — primary path uses 5+6+7+9 below) |
| 6 | `generate_curriculum_syllabus` | endo_ai.py:1382 | `claude-opus-4-5` | 600 | ~150 tok | structured (JSON of 4 modules) | Deep Learning (Step A) |
| 7 | `write_curriculum_module` | endo_ai.py:1476 | `claude-opus-4-5` | 2500 | 5–15 K tok | **complex clinical synthesis per module** (×4 per request) | Deep Learning (Step C) |
| 8 | `stitch_curriculum` | endo_ai.py:1551 | `claude-opus-4-5` | 8000 | 8–20 K tok | text stitching + ref dedup + transitions | Deep Learning (Step D) |
| 9 | `ask_case_question` | endo_ai.py:1704 | `claude-opus-4-5` | 2000 | 5–20 K tok | conversational synthesis with memory | Case Discussion (every turn) |
| 10 | `generate_slides_content` | endo_ai.py:1784 | `claude-opus-4-5` | 12000 | 6 K tok | structural reformat (answer → JSON slide deck) | Export (any mode) |
| 11 | `generate_podcast_script` | endo_ai.py:1849 | `claude-opus-4-5` | 8000 | 7 K tok | reformat (answer → dialogue script) | Export (any mode) |
| 12 | `generate_audio_script` | endo_ai.py:1902 | `claude-opus-4-5` | 8000 | 7 K tok | reformat (answer → TTS-friendly narration) | Export (any mode) |
| 13 | `generate_referral_letter` | endo_ai.py:2641 | `claude-opus-4-5` | 700 | ~500 tok | formatted clinical letter | Case Assessment (referral button) |

**Note on current model:** every call uses `claude-opus-4-5`. The user-supplied target identifiers are `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` — so even calls that "stay on Opus" will move from `4-5` to `4-7`.

## Proposed routing

### Tier 1 — Haiku (`claude-haiku-4-5-20251001`)
Pure structured/classification tasks. Output is a short JSON object or a single search string. No clinical synthesis happens here.

| # | Function | Why Haiku |
|---|---|---|
| 1 | `generate_clarifying_questions` | Returns a JSON array of 2–3 strings. Classification + structured output. |
| 2 | `generate_multi_search_terms` | Returns a JSON list of 2 PubMed strings. Pure structural. |
| 3 | `generate_search_terms` | Returns a single 10-word PubMed query string. |
| 6 | `generate_curriculum_syllabus` | Returns a JSON list of 4 `{title, search_query}` objects. |
| — | *intent router (not yet built — Task 3 from prior roadmap)* | 4-way classification when implemented. |

### Tier 2 — Sonnet (`claude-sonnet-4-6`) — flag-gated with parallel comparison logging

Real reasoning but light synthesis. Will run BOTH Opus and Sonnet in parallel when `LOG_TIER2_COMPARISON=True` so you can review side-by-side outputs before flipping `USE_TIER2_SONNET=True` for production.

| # | Function | Why Sonnet |
|---|---|---|
| 8 | `stitch_curriculum` | Reproduces module bodies verbatim; Claude only writes overview/transitions/takeaways/refs. Light synthesis. |
| 9 | `ask_case_question` | 2 K tok chat-friendly responses with conversation memory. Sonnet should handle this well — but per-turn quality matters, so flag-gate it. |
| 13 | `generate_referral_letter` | Formatted clinical letter from a structured input (case + reasons). Pattern-following, light reasoning. |
| 10 | **`generate_slides_content`** *(not in your original spec — proposing Tier 2)* | Reformats already-synthesized answer into a JSON slide deck. Structural transformation. |
| 11 | **`generate_podcast_script`** *(not in your original spec — proposing Tier 2)* | Reformats answer into dialogue script. Structural transformation. |
| 12 | **`generate_audio_script`** *(not in your original spec — proposing Tier 2)* | Reformats answer into TTS-friendly narration. Structural transformation. |

The three "export" functions (10/11/12) all take an already-synthesized clinical answer and restructure it for a different output medium. They're not doing fresh medical reasoning — they're transforming format. Sonnet is appropriate, possibly even Haiku, but I'm proposing Sonnet to keep the "no quality regression" bar high since exports are user-facing artifacts. **Want me to demote them to Haiku instead?**

### Tier 3 — Opus (`claude-opus-4-7`) — KEEP

Complex multi-tier evidence synthesis with strict tier hierarchy, contradiction surfacing, procedural specificity, and inline `[[PMID:N]]` provenance. The output has to be defensible chairside; quality regression here would be costly.

| # | Function | Why stay on Opus |
|---|---|---|
| 4 | `ask_clinical_question` | Literature Review primary path — 7-tier evidence synthesis, contradiction surfacing, tier-hierarchy enforcement. |
| 5 | `ask_learn_question` (legacy) | Single-shot fallback for Learn mode if curriculum builder fails. Same synthesis complexity as #4. |
| 7 | `write_curriculum_module` | 4 calls per request, each a dense ~650-word clinical synthesis with procedural specificity, consensus checking, contradiction surfacing. |

## Summary of changes

| Change | Count |
|---|---|
| Total Claude calls in codebase | 13 |
| Will move to Haiku | 4 (+ 1 future intent router) |
| Will move to Sonnet (flag-gated, comparison logging) | 6 (proposed — 3 new beyond your original spec) |
| Will stay on Opus (model bumped 4-5 → 4-7) | 3 |

## Cost expectations (rough, per-request)

Approximate Anthropic pricing (per 1M tokens):
- Opus: $15 in / $75 out
- Sonnet: $3 in / $15 out
- Haiku: $1 in / $5 out

For a typical Deep Learning request (current: 6 Opus calls):
- syllabus: 150 in / 600 out → $0.047
- 4× module write: ~10K in / 2.5K out each → $0.90 total
- stitch: ~15K in / 8K out → $0.83
- **Current total per Learn request: ~$1.78**
- **After routing: syllabus → Haiku ($0.003), modules stay Opus ($0.90), stitch → Sonnet ($0.165) = $1.07**
- Savings per Learn request: ~40%

For a typical Case Discussion turn (current: 1 Opus call + maybe 1 Opus clarify):
- ask_case_question: 8K in / 1.5K out → $0.23
- (clarify if first turn): 200 in / 300 out → $0.026
- **Current per turn: ~$0.23**
- **After routing: ask_case_question → Sonnet ($0.046), clarify → Haiku ($0.0017) = $0.048**
- Savings per Case turn: ~80%

Real numbers will only be measurable once the cost log is shipped (Step 5 in your plan).

## Open questions before I proceed

1. **Three additional functions** (10/11/12 — slides/podcast/audio export) — confirm Tier 2 (Sonnet, flag-gated) is what you want, or demote to Haiku, or leave on Opus.
2. **`ask_learn_question` (#5)** — legacy fallback. Currently never called by the primary path (curriculum builder replaced it). Should I keep it on Opus for safety, demote, or actually delete it as dead code?
3. The **intent router** (Task 3 from prior roadmap) is not yet built. When I implement it, it'll automatically use `MODELS["structured_fast"]` per your spec. Confirm this is fine.

Reply with answers to the open questions and your approval to proceed, and I'll move to Step 1 (centralizing the model config).
