# Curo — Presentation & Narration Upgrade (complete instruction set)

Drop this file in the repo root as `PRESENTATION_WORKLIST.md` and hand it to the agent verbatim. It is self-contained: the full approved design spec is embedded below — do not ask the user for design decisions; they are all made.

---

## 0. Operating rules

Fully autonomous. Do not ask questions; do not pause; take conservative decisions and log them in the final report. Rules carried over from WORKLIST.md: measure before changing; mutation-check every new test; fixtures from real data; `git add -A && git commit -m "wip: <item>"` before any destructive git command; never `git reset --hard`; commit and push (or re-bundle) after every item; parallel agents on independent files, never two agents in one file. Work on `main`; tag `presentation-v1` at the end.

File ownership for parallel agents:
- Agent A: `presentations/` (pptx templates + chart rendering) — Phase 1
- Agent B: new web-deck module + one hook in `app.py` — Phase 2
- Agent C: TTS/narration in `endo_ai.py` media functions — Phase 3
Phases 1–3 are independent; run them concurrently. Phase 4 runs after all three land.

**The prime rule for everything below: rendering only, never authoring.** Every word on every slide and in every narration comes verbatim from the validated answer/curriculum text. No template may add, rewrite, or summarize clinical content. Both exports (pptx and web deck) must consume one canonical text object and assert its content hash matches between builds.

---

## 1. THE APPROVED DESIGN SPEC (encode exactly — user-approved on the design canvas)

### 1.1 Identity
- Fonts: **Instrument Serif** (display: slide titles, section numbers, takeaway numerals; regular + italic for the "Curo" wordmark) and **Inter** (everything else; weights 400/500/600/700). Web deck: load both from Google Fonts. PPTX fallback mapping: Instrument Serif → Georgia; Inter → Calibri/"Segoe UI". Document the mapping in the template code.
- Headings are **sentence case** (matches the app's typography change).
- Theme is **DARK** throughout (user-approved):

| Token | Hex | Use |
|---|---|---|
| bg | `#131b2c` | every slide background |
| surface | `#1c2740` | table header rows, notice boxes, canal-diagram fills |
| surface-alt | `#17213a` | table zebra rows |
| card | `#1a2440` | decision-tree cards |
| border | `#2c3a58` | all hairlines, table borders, footer rule |
| leader | `#33425f` | chart leader/grid lines |
| text-title | `#ffffff` | slide titles (Main/Divider) |
| text-body | `#eef2fa` | titles + primary body on content slides |
| text-secondary | `#c6d0e2` | BECAUSE text, table body alt |
| text-lead | `#aebad0` | lead paragraphs, labels |
| text-eyebrow | `#93a3bd` | eyebrow rows (11px, 600, letter-spacing 0.1em, UPPERCASE) |
| text-footer | `#8296b3` | citation footers (12px) |
| text-muted | `#7d8fae` | page numbers, chart axis numbers |
| accent-cyan | `#8bd7e8` | title-slide eyebrow, divider tick marks |
| divider-bg | `#1e40af` | section-divider background (flat, no gradient); numeral in `#3556c4` |

### 1.2 Tier color ladder (semantic — a hue always means the same tier, everywhere)
Chart fills on dark, in fixed ladder order (validated for color-blind readers on the light card; the dark set below is the brightened equivalent for marks on `#131b2c`):

| Tier | Chart fill (dark) | Chip bg / chip text (dark) |
|---|---|---|
| Cochrane | `#4ec78f` | `#12301f` / `#5ad196` |
| Level I | `#22c0dd` | `#0e2b33` / `#5fd4e8` |
| Level II | `#60a5fa` | `#1e2f55` / `#93b4f5` |
| Level III | `#c4b5fd` | `#241d47` / `#c4b5fd` — **must always carry its text label** |
| Level IV | `#f27596` | `#331420` / `#f27596` |
| In vitro | `#fbbf24` | `#33270f` / `#f5b84d` |
| Level V | `#e18aef` | `#2e1633` / `#e18aef` |

The evidence-shape bar (see 1.4 Title) sits on a LIGHT card (`#fcfcfd`) and uses the light-surface ladder there: `#0f7a4d, #0891b2, #2563eb, #a78bfa, #9f1239, #d97706, #86198f` (this exact set passed the CVD validator; keep the light card). Badge colors: COI/alert red family reserved — never used as a tier. PMID pills: bg `#1e2f55`, text `#93b4f5`. IF chip: `#1c2740`/`#aebad0` · THEN chip: `#1e2f55`/`#93b4f5` · BECAUSE chip: `#12301f`/`#5ad196` (11px, 700, letter-spacing 0.08em, radius 5px).

### 1.3 Slide furniture (identical on every content-class slide)
- Frame: 16:9 (1280×720 reference), padding `56px 64px 0`.
- Header row: fixed height 26px; left eyebrow (module · slide role), right: tier chip for the slide's evidence (pill, radius 999, with 8px colored dot) or "CURO" label on takeaways/references.
- Title: Instrument Serif 44px, line-height 1.1, `#eef2fa`, margin-top 22px.
- Optional lead: Inter 18px/1.5 `#aebad0`, margin-top 14px, max-width 860px.
- Footer: 1px top border `#2c3a58`, padding 14px 0 18px; left = short citations ("Schulte-Lünzum et al. 2017 · Photomedicine and Laser Surgery · n = 100 · PMID 28294701"), right = page number `#7d8fae`. Raw `[[PMID:N]]` markers must NEVER appear on a slide — test for this.
- Body budget: max 5 bullets OR one table OR one figure per slide, ~25 words of bullet text; overflow auto-splits to a continuation slide (implement + test the split).

### 1.4 The eight layouts (anatomy as approved)
1. **Title** — dark navy; wordmark row ("Curo" serif italic 24px white · 1px divider · cyan eyebrow); serif title 68px white; subtitle 18px `#aebad0`; then a LIGHT card (`#fcfcfd`, radius 12) holding the **evidence-shape bar**: label row, 26px stacked bar of tier segments (2px gaps, flex-grow = paper count), legend row of swatch+name+count per tier. Footer disclaimer 12px `#7487a3`. The evidence-shape card is MANDATORY on every deck (product signature).
2. **Section divider** — flat `#1e40af`; giant serif module number top-right in `#3556c4` (keep text column ≥450px clear of it); eyebrow "MODULE N OF M"; serif white 56px title; 3 tick-mark topic lines (18×2px cyan dash + `#dbe6fd` text); bottom: module evidence chip + one-line caveat.
3. **Content** — furniture + bullets (8px round `#60a5fa` markers, 17px/1.55 text) and optional right-side figure (stroke-based SVG diagrams, 2px strokes: approved example = two root-canal outlines comparing radial-firing vs bare-end fiber emission, green "Full-wall coverage" vs rose "Forward cone only" caption chips).
4. **Table** — bordered rounded container; 12-col grid rows; header row `#1c2740` with 11px/700 uppercase labels; zebra `#17213a`; parameter col 600-weight; source col right-aligned PMID pills. Long tables split with header repeated.
5. **Decision tree** — 2-col grid of cards (`#1a2440`, 1px `#2c3a58`, radius 10, padding 26/28); each card = IF/THEN/BECAUSE rows (chip + 16px/1.5 text). Never render as bullets.
6. **Chart** — see 1.5.
7. **Key takeaways** — 2×2 grid; serif 54px colored numerals (`#60a5fa`, `#4ec78f`, `#fbbf24`, `#e18aef`) + 18px/1.55 text with bold key phrases; below: "DOES NOT APPLY WHEN" notice box (`#1c2740`, radius 10) with the contraindication line.
8. **References** — numbered rows (15px title+journal+year, tier chip, PMID pill, right-aligned evidence score 13px/600), 1px separators; footer notes scores are Curo evidence scores.
Plus the existing **"Module not generated — insufficient evidence"** notice slide, restyled to the dark theme (notice box, not an error).

### 1.5 Charts (HARD RULES)
- Every plotted value must appear verbatim in the cited text; each chart carries its PMIDs in the footer; no chartable data → no chart. Never invent or interpolate. Tests: uncited numbers produce no chart; a cited comparison produces one; mutation-check both.
- Approved chart grammar: **dot plot** for near-equal comparisons (truncated axis allowed ONLY with an explicit axis note like "axis starts at 98"); **bar** for magnitude comparisons from zero; **evidence-shape stacked bar** (tier colors, 2px gaps, direct labels) for the paper-count breakdown. Single-series marks use `#60a5fa` only; multi-tier fills use the ladder. Value labels in text tokens (never the series color), direct labels over legends, leader lines `#33425f`, axis text `#7d8fae`.
- PPTX: render charts to PNG via matplotlib using these exact hexes on `#131b2c`. Web deck: inline SVG, same geometry.

---

## 2. PHASE 1 — PPTX templates (Agent A, `presentations/`)

2.1 Encode the spec into the design tokens file + the ten layout builders; delete/replace styles that conflict. Fallback fonts per 1.1.
2.2 Implement the body-budget auto-split and the no-raw-markers rule in the builder.
2.3 Implement chart rendering per 1.5 with the chartable-data detector (success percentages across arms, sample sizes, follow-up periods, per-tier counts).
2.4 Verification: regenerate the laser-curriculum deck; render every slide to PNG (libreoffice headless) and VIEW them — check overflow, clipping, contrast (body ≥4.5:1 on `#131b2c`), raw markers, table splits. Fix until clean; save before/after PNGs of 4 representative slides and list paths in the report.
2.5 Tests: split rule, no-raw-markers, footer presence, chip color = token value, chart hard rules. Mutation-check each.

## 3. PHASE 2 — Web deck export (Agent B, new files + export hook)

3.1 New export style "Web deck": ONE self-contained HTML file per answer/curriculum using reveal.js (pin the version; load from cdnjs; all CSS/JS inline; Google Fonts for the two faces). Slides mirror the layouts in §1 exactly.
3.2 Clickable citations: author-style pills exactly as in the app; click opens an in-deck abstract overlay served from `/api/abstract/<pmid>` when the server is reachable, falling back to abstracts embedded at build time so the file works standalone. Test standalone with the server stopped.
3.3 Narration sync: when an audio export exists for the same answer, embed it with a per-slide timestamp map (emit the map at TTS time from the module text boundaries) so the deck can autoplay slide-advance. Graceful without audio.
3.4 PDF: `?print-pdf` must produce one clean page per slide (dark backgrounds printed); fix print CSS until true.
3.5 Wire into the export bar as "Web deck", store in the Media tab, and support history-loaded answers by REUSING the displayed-answer mechanism from the audio-export fix (do not reimplement). Cap the client-supplied text size; same admin/session gating as other export routes.
3.6 Playwright: open the laser web deck, assert slide count, click a citation pill → non-empty abstract overlay, `?print-pdf` page count, partial deck renders standalone. Screenshot 3 slides; list paths.

## 4. PHASE 3 — Narration upgrade (Agent C)

4.1 Make **OpenAI TTS the primary voice** (key already in `.env`); gTTS remains fallback only. Pick one professional voice; expose `TTS_VOICE` in `.env`.
4.2 Pronunciation dictionary: a substitution map applied to the narration script only (never the displayed text): "Er,Cr:YSGG" → "erbium chromium Y-S-G-G", "Er:YAG" → "erbium YAG", "Nd:YAG" → "neodymium YAG", "NaOCl" → "sodium hypochlorite", "EDTA" → "E-D-T-A", "PIPS" → "pips", "µm" → "microns", "apexification", "MTA" → "M-T-A". Store as data, easy to extend; test the map.
4.3 Emit the per-slide timestamp map (for 3.3) as a sidecar JSON at TTS time.
4.4 Verify: regenerate the laser lecture audio; ffprobe-check; LISTEN to 60 seconds spanning at least three dictionary terms; report subjective quality in one line.
4.5 Cost: log per-minute TTS cost to the cost log like other model calls.

## 5. PHASE 4 — Wrap (after 1–3)

5.1 Regenerate the laser curriculum end-to-end: pptx + web deck + narrated audio with sync map. Assert both decks' source-text hash matches the canonical text object.
5.2 Full suite; the e2e test gains one deck assertion (slide count > 0, no raw markers).
5.3 Final report (WORKLIST §8 format): per item status/before-after/test/commit; PNG + screenshot paths; export timings (pptx, web deck, audio) for the laser curriculum; found-not-fixed; decisions taken. Fresh bundle; tag `presentation-v1`; push.

## 6. Explicitly OUT of scope (do not do)

- HeyGen/avatar video — a later manual prototype, not pipeline work.
- Any external slide-generation API (Gamma, SlideSpeak, etc.) — layout stays in-house under the validation gates.
- Light theme variant — later; dark is the approved default.
- Re-scoring, retrieval, or eval changes — separate worklist.
