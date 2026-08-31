"""The deck's stylesheet and runtime, kept out of builder.py for readability.

Everything here is inlined into the single output file (§3.1). The only
external requests the deck makes are the two pinned reveal.js assets on cdnjs
and Google Fonts; the cdnjs ones carry subresource-integrity hashes, and the
deck still renders — as a stacked, scrollable document — when neither loads.
"""
from __future__ import annotations

from . import tokens as T

# Pinned. cdnjs SRI values verified against the served bytes on 2026-08-30.
REVEAL_VERSION = "5.1.0"
REVEAL_BASE = f"https://cdnjs.cloudflare.com/ajax/libs/reveal.js/{REVEAL_VERSION}"
REVEAL_JS_SRI = ("sha512-sMRSj1Ns64C2OE6VNS7WrV63OHW7dLAvi96CXRoy9AEe/"
                 "tKF+868fhUJpc5ZKS166lwhe2ArCYjFitLJUY+VWA==")
REVEAL_CSS_SRI = ("sha512-0AUO8B5ll9y1ERV/55xq3HeccBGnvAJQsVGitNac/"
                  "iQCLyDTGLUBMPqlupIWp/rJg0hV3WWHusXchEIdqFAv1Q==")

SLIDE_W, SLIDE_H = 1280, 720


def stylesheet() -> str:
    return T.css_variables() + f"""
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: var(--bg); }}
body {{ font-family: var(--font-body); color: var(--text-body); }}

/* reveal.js paints its own background and type; the deck owns both. */
.reveal, .reveal .slides {{ background: var(--bg); }}
.reveal .slides section {{
  padding: 0; height: {SLIDE_H}px; width: {SLIDE_W}px;
  background: var(--bg); text-align: left; font-size: 16px;
}}
.deck-slide {{ position: relative; overflow: hidden; }}

/* ── §1.3 frame ── */
.frame {{
  position: absolute; inset: 0; padding: 56px 64px 0;
  display: flex; flex-direction: column;
}}
.furniture-head {{
  height: 26px; flex: 0 0 26px;
  display: flex; align-items: center; justify-content: space-between;
}}
.eyebrow {{
  font-size: 11px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--text-eyebrow);
}}
.tier-chip {{
  display: inline-flex; align-items: center; gap: 7px;
  border-radius: 999px; padding: 4px 12px 4px 10px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; white-space: nowrap;
}}
.curo-chip {{ background: var(--surface); color: var(--text-lead); }}
.chip-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}

.slide-title {{
  font-family: var(--font-display); font-weight: 400;
  font-size: 44px; line-height: 1.1; color: var(--text-body);
  margin: 22px 0 0; letter-spacing: 0.005em;
}}
.slide-lead {{
  font-size: 18px; line-height: 1.5; color: var(--text-lead);
  margin: 14px 0 0; max-width: 860px;
}}
.slide-body {{ flex: 1 1 auto; min-height: 0; margin-top: 22px; overflow: hidden; }}
.slide-body.with-figure {{ display: grid; grid-template-columns: 1fr 300px; gap: 34px; }}

.furniture-foot {{
  flex: 0 0 auto; border-top: 1px solid var(--border);
  padding: 14px 0 18px; margin-top: auto;
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
}}
.foot-cites {{ display: flex; gap: 8px; flex-wrap: wrap; min-width: 0; }}
.foot-page {{ font-size: 12px; color: var(--text-muted); flex: 0 0 auto; }}

/* ── §3.2 citation pills (the app's shape, §1.2's dark colours) ── */
.cite-pill {{
  display: inline-block; background: {T.PMID_PILL[0]}; color: {T.PMID_PILL[1]};
  border: 1px solid rgba(147,180,245,0.35); border-radius: 4px;
  padding: 2px 7px; font-size: 11px; font-weight: 700;
  font-family: ui-monospace, "Cascadia Mono", "JetBrains Mono", monospace;
  cursor: pointer; margin: 0 2px; line-height: 1.4; transition: all .12s;
}}
.cite-pill:hover, .cite-pill:focus-visible {{
  background: #2a4179; color: #dbe6fd; border-color: rgba(147,180,245,0.7);
  outline: none;
}}
.foot-pill {{ font-size: 12px; font-family: var(--font-body); font-weight: 500;
  color: var(--text-footer); background: transparent;
  border-color: var(--border); }}
.foot-pill:hover {{ color: {T.PMID_PILL[1]}; background: {T.PMID_PILL[0]}; }}
.pill-row {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }}

/* ── §1.4 #1 title ── */
.frame-title {{ justify-content: flex-start; padding-top: 62px; }}
.wordmark-row {{ display: flex; align-items: center; gap: 16px; }}
.wordmark {{ font-family: var(--font-display); font-style: italic;
  font-size: 24px; color: #fff; }}
.wordmark-rule {{ width: 1px; height: 20px; background: var(--border); }}
.wordmark-eyebrow {{
  font-size: 11px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--accent-cyan);
}}
.title-main {{
  font-family: var(--font-display); font-weight: 400; font-size: 68px;
  line-height: 1.05; color: var(--text-title); margin: 26px 0 0; max-width: 950px;
}}
.title-sub {{ font-size: 18px; color: var(--text-lead); margin: 16px 0 0; max-width: 800px; }}
.title-tagline {{ font-size: 16px; font-style: italic; color: var(--text-secondary);
  margin: 8px 0 0; }}
.title-disclaimer {{ font-size: 12px; color: #7487a3; margin: 14px 0 24px;
  padding-top: 14px; }}
.title-meta {{ font-size: 12px; color: var(--text-footer); margin: 10px 0 0; }}
.frame-title .evidence-card {{ margin-top: auto; }}

.evidence-card {{
  background: var(--evidence-card); border-radius: 12px;
  padding: 18px 22px 16px; margin-top: 24px; color: #1e2840;
}}
.ev-label-row {{ display: flex; justify-content: space-between; align-items: baseline; }}
.ev-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.1em; color: #47536b; }}
.ev-total {{ font-size: 12px; color: #6b7789; }}
.ev-bar {{ display: flex; gap: 2px; height: 26px; margin-top: 10px; }}
.ev-seg {{ border-radius: 2px; min-width: 4px; position: relative;
  display: flex; align-items: center; justify-content: center; }}
.ev-seg-empty {{ background: repeating-linear-gradient(45deg,#e3e7ee 0 6px,#eef1f6 6px 12px); }}
.ev-seg-label {{ font-size: 10px; font-weight: 700; color: #fff;
  letter-spacing: 0.04em; white-space: nowrap; }}
.ev-legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 12px; }}
.ev-legend-item {{ font-size: 11.5px; color: #47536b; display: inline-flex;
  align-items: center; gap: 6px; }}
.ev-legend-item b {{ color: #1e2840; }}
.ev-swatch {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}

/* ── §1.4 #2 section divider ── */
.deck-slide.layout-divider, .layout-divider .frame {{ background: var(--divider-bg); }}
.frame-divider {{ justify-content: center; padding: 56px 64px; }}
.divider-num {{
  position: absolute; top: 24px; right: 56px;
  font-family: var(--font-display); font-size: 250px; line-height: 1;
  color: var(--divider-num); user-select: none;
}}
.divider-col {{ max-width: 700px; position: relative; z-index: 1; }}
.divider-eyebrow {{ font-size: 11px; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--accent-cyan); }}
.divider-title {{ font-family: var(--font-display); font-weight: 400;
  font-size: 56px; line-height: 1.1; color: #fff; margin: 16px 0 0; }}
.divider-ticks {{ list-style: none; margin: 26px 0 0; padding: 0; }}
.divider-ticks li {{ display: flex; align-items: baseline; gap: 14px;
  margin-bottom: 12px; font-size: 18px; color: #dbe6fd; }}
.tick {{ width: 18px; height: 2px; background: var(--accent-cyan);
  flex: 0 0 18px; transform: translateY(-5px); }}
.divider-foot {{ position: absolute; left: 64px; right: 64px; bottom: 46px;
  display: flex; align-items: center; gap: 16px; }}
.divider-caveat {{ font-size: 13px; color: #c3d4fb; }}

/* ── §1.4 #3 content ── */
.bullets {{ list-style: none; margin: 0; padding: 0; }}
.bullet {{ position: relative; padding-left: 24px; margin-bottom: 16px;
  font-size: 17px; line-height: 1.55; color: var(--text-body); max-width: 980px; }}
.bullet::before {{ content: ""; position: absolute; left: 0; top: 9px;
  width: 8px; height: 8px; border-radius: 50%; background: {T.CHART_SERIES}; }}
.bullet.has-parts {{ display: block; }}
.b-num {{ font-family: var(--font-display); font-size: 20px;
  color: {T.CHART_SERIES}; margin-right: 10px; }}
.b-head {{ font-weight: 700; color: var(--text-body); }}
.b-body {{ display: block; color: var(--text-secondary); font-size: 16px;
  margin-top: 3px; }}

.slide-figure {{ margin: 0; display: flex; flex-direction: column; gap: 12px; }}
.slide-figure svg {{ width: 100%; height: auto; }}
.slide-figure .canal {{ fill: none; stroke: var(--text-lead); stroke-width: 2; }}
.slide-figure .ray {{ stroke: var(--accent-cyan); stroke-width: 2; fill: none; }}
.cap-chip {{ display: inline-block; font-size: 11px; font-weight: 700;
  letter-spacing: 0.06em; border-radius: 5px; padding: 4px 9px; margin-right: 6px; }}
.cap-ok {{ background: {T.CHIP_BECAUSE[0]}; color: {T.CHIP_BECAUSE[1]}; }}
.cap-warn {{ background: {T.TIER_CHIP_DARK["level4"][0]};
  color: {T.TIER_CHIP_DARK["level4"][1]}; }}

/* ── §1.4 #4 table ── */
.grid-table {{ border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }}
.tr {{ display: grid; grid-template-columns: repeat(12, 1fr);
  border-bottom: 1px solid var(--border); }}
.tr:last-child {{ border-bottom: none; }}
.th-row {{ background: var(--surface); }}
.tr.zebra {{ background: var(--surface-alt); }}
.th {{ padding: 11px 16px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-eyebrow); }}
.td {{ padding: 13px 16px; font-size: 15px; line-height: 1.45;
  color: var(--text-secondary); }}
.td-key {{ font-weight: 600; color: var(--text-body); }}
.td-src {{ text-align: right; }}

.notice-box {{ background: var(--surface); border-radius: 10px;
  padding: 16px 20px; margin-top: 18px; }}
.notice-big {{ padding: 26px 30px; }}
.notice-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
  color: {T.TIER_CHIP_DARK["level4"][1]}; margin-bottom: 8px; }}
.notice-text {{ font-size: 15px; line-height: 1.55; color: var(--text-secondary); }}

/* ── §1.4 #5 decision tree ── */
.dt-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
.dt-card {{ background: var(--card); border: 1px solid var(--border);
  border-radius: 10px; padding: 26px 28px; }}
.dt-card-label {{ font-size: 11px; font-weight: 700; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--accent-cyan); margin-bottom: 12px; }}
.itb-row {{ display: flex; gap: 12px; align-items: baseline; margin-bottom: 11px; }}
.itb-row:last-child {{ margin-bottom: 0; }}
.itb-chip {{ flex: 0 0 auto; font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; border-radius: 5px; padding: 3px 8px; }}
.itb-text {{ font-size: 16px; line-height: 1.5; color: var(--text-body); }}
.dt-caption {{ font-size: 13px; color: var(--text-lead); margin: 16px 0 0; }}

/* ── §1.4 #6 chart ── */
.chart-body {{ display: flex; flex-direction: column; gap: 10px; }}
.chart {{ width: 100%; max-height: 300px; }}
.chart .grid {{ stroke: var(--leader); stroke-width: 1; }}
.chart .axis {{ stroke: var(--border); stroke-width: 1.5; }}
.chart .v-label {{ fill: var(--text-body); font-size: 17px; font-weight: 700;
  font-family: var(--font-body); }}
.chart .x-label {{ fill: var(--text-muted); font-size: 13px;
  font-family: var(--font-body); }}
.chart .axis-note {{ fill: var(--text-muted); font-size: 12px; font-style: italic;
  font-family: var(--font-body); }}
.chart-keys {{ display: flex; flex-wrap: wrap; gap: 6px 22px; }}
.chart-key {{ font-size: 12.5px; color: var(--text-lead);
  display: inline-flex; align-items: baseline; gap: 7px; max-width: 560px; }}
.chart-key i {{ width: 9px; height: 9px; border-radius: 2px; flex: 0 0 9px; }}
.chart-callout {{ font-size: 15px; line-height: 1.5; color: var(--text-secondary);
  margin: 0; }}

/* ── §1.4 #7 takeaways ── */
.tk-grid {{ display: grid; grid-template-columns: 1fr 1fr;
  gap: 20px 44px; }}
.tk-cell {{ display: flex; gap: 16px; align-items: baseline; }}
.tk-num {{ font-family: var(--font-display); font-size: 54px; line-height: 0.9;
  flex: 0 0 auto; }}
.tk-text {{ font-size: 18px; line-height: 1.55; color: var(--text-body); }}
.tk-text strong {{ color: #fff; }}

/* ── §1.4 #8 references ── */
.ref-list {{ display: flex; flex-direction: column; }}
.ref-row {{ display: flex; align-items: center; gap: 14px;
  padding: 10px 0; border-bottom: 1px solid var(--border); }}
.ref-row:last-child {{ border-bottom: none; }}
.ref-n {{ flex: 0 0 26px; font-size: 13px; color: var(--text-muted); }}
.ref-main {{ flex: 1 1 auto; min-width: 0; }}
.ref-title {{ display: block; font-size: 15px; line-height: 1.35;
  color: var(--text-body); }}
.ref-pill {{ flex: 0 0 auto; }}
.ref-meta {{ display: block; font-size: 12px; color: var(--text-footer); }}
.ref-chip {{ flex: 0 0 auto; }}
.ref-score {{ flex: 0 0 46px; text-align: right; font-size: 13px;
  font-weight: 600; color: var(--text-secondary); }}
.ref-note {{ font-size: 12px; color: var(--text-muted); margin: 14px 0 0; }}

/* ── §3.2 abstract overlay ── */
#abs-overlay {{
  display: none; position: fixed; inset: 0; z-index: 60;
  background: rgba(8,12,22,0.72); backdrop-filter: blur(3px);
  align-items: center; justify-content: center; padding: 40px;
}}
#abs-overlay.open {{ display: flex; }}
#abs-panel {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; max-width: 780px; width: 100%; max-height: 80vh;
  overflow: auto; padding: 30px 34px; font-family: var(--font-body);
}}
#abs-title {{ font-family: var(--font-display); font-size: 27px; line-height: 1.2;
  color: var(--text-title); margin: 0 0 10px; }}
#abs-meta {{ font-size: 13px; color: var(--text-lead); margin-bottom: 6px; }}
#abs-source {{ font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-muted); margin-bottom: 16px; }}
#abs-body {{ font-size: 15px; line-height: 1.62; color: var(--text-secondary);
  white-space: pre-wrap; }}
#abs-foot {{ margin-top: 20px; display: flex; gap: 14px; align-items: center; }}
#abs-foot a {{ color: {T.PMID_PILL[1]}; font-size: 13px; text-decoration: none; }}
#abs-close {{ margin-left: auto; background: var(--card); color: var(--text-body);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 15px;
  font-size: 13px; cursor: pointer; }}

/* ── §3.3 narration bar ── */
#narration {{
  display: none; position: fixed; left: 50%; bottom: 16px; z-index: 50;
  transform: translateX(-50%); align-items: center; gap: 12px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 999px; padding: 7px 8px 7px 16px;
}}
#narration.on {{ display: flex; }}
#narration audio {{ height: 32px; }}
#narration .n-label {{ font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--text-eyebrow); }}
#n-sync {{ background: var(--card); color: var(--text-body);
  border: 1px solid var(--border); border-radius: 999px; padding: 5px 13px;
  font-size: 11px; cursor: pointer; }}
#n-sync[aria-pressed="true"] {{ background: {T.PMID_PILL[0]};
  color: {T.PMID_PILL[1]}; border-color: {T.PMID_PILL[1]}; }}

/* ── fallback: reveal.js unavailable, or ?print-pdf ── */
html.no-reveal body, html.print-pdf body {{ background: var(--bg); }}
html.no-reveal .reveal .slides, html.print-pdf .reveal .slides {{
  display: block; position: static; transform: none !important;
  width: auto; height: auto; left: auto; top: auto; zoom: 1;
}}
html.no-reveal .reveal, html.print-pdf .reveal {{
  position: static; width: auto; height: auto; overflow: visible;
}}
html.no-reveal .reveal .slides > section,
html.print-pdf .reveal .slides > section {{
  display: block !important; position: relative !important;
  visibility: visible !important; opacity: 1 !important;
  width: {SLIDE_W}px; height: {SLIDE_H}px; margin: 0 auto 18px;
  transform: none !important; top: auto !important; left: auto !important;
}}

/* ── §3.4 print: one page per slide, dark backgrounds actually printed ── */
@page {{ size: {SLIDE_W}px {SLIDE_H}px; margin: 0; }}
@media print {{
  html, body {{
    background: var(--bg) !important;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
    width: {SLIDE_W}px; height: auto; margin: 0; padding: 0;
  }}
  * {{ -webkit-print-color-adjust: exact !important;
       print-color-adjust: exact !important; }}
  #narration, #abs-overlay, .reveal .controls, .reveal .progress,
  .reveal .backgrounds, .reveal .slide-number, .deck-hint {{ display: none !important; }}
  .reveal, .reveal .slides {{
    position: static !important; width: auto !important; height: auto !important;
    transform: none !important; overflow: visible !important; zoom: 1 !important;
    left: auto !important; top: auto !important; display: block !important;
  }}
  .reveal .slides > section {{
    display: block !important; position: relative !important;
    visibility: visible !important; opacity: 1 !important;
    width: {SLIDE_W}px !important; height: {SLIDE_H}px !important;
    margin: 0 !important; padding: 0 !important;
    transform: none !important; top: auto !important; left: auto !important;
    page-break-after: always; break-after: page;
    page-break-inside: avoid; break-inside: avoid;
    overflow: hidden !important;
  }}
  .reveal .slides > section:last-child {{
    page-break-after: auto; break-after: auto;
  }}
  .deck-slide, .frame {{ background: var(--bg) !important; }}
  .layout-divider .frame, .deck-slide.layout-divider {{
    background: var(--divider-bg) !important; }}
  .evidence-card {{ background: var(--evidence-card) !important; color: #1e2840 !important; }}
}}

/* Sits bottom-LEFT: reveal.js parks its arrow controls bottom-right. */
.deck-hint {{ position: fixed; left: 14px; bottom: 10px; z-index: 40;
  font-size: 10.5px; color: var(--text-muted); font-family: var(--font-body);
  opacity: 0.65; pointer-events: none; }}
"""


def runtime_js(config_json: str) -> str:
    return """
(function () {
  var CFG = __CONFIG__;
  var qs = window.location.search || "";
  var PRINT = /print-pdf/i.test(qs);
  var root = document.documentElement;
  if (PRINT) root.classList.add("print-pdf");

  // ── §3.2 abstracts ─────────────────────────────────────
  // Server first, embedded fallback. The embedded copy is what makes the file
  // work as a file:// document with the app stopped; the server call exists so
  // a deck opened from the app shows whatever the abstract cache has learned
  // since the deck was built.
  var EMBEDDED = CFG.abstracts || {};
  var FETCH_TIMEOUT_MS = 2500;

  function fromServer(pmid) {
    if (!window.fetch || location.protocol === "file:") return Promise.resolve(null);
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, FETCH_TIMEOUT_MS);
    return fetch("/api/abstract/" + encodeURIComponent(pmid),
                 ctrl ? {signal: ctrl.signal} : {})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        return (d && d.abstract && String(d.abstract).length > 20) ? d : null;
      })
      .catch(function () { return null; })
      .then(function (d) { clearTimeout(timer); return d; });
  }

  function loadAbstract(pmid) {
    return fromServer(pmid).then(function (d) {
      if (d) { d.source = "server"; return d; }
      var e = EMBEDDED[String(pmid)];
      if (e && e.abstract) {
        return {pmid: pmid, title: e.title, abstract: e.abstract,
                journal: e.journal, year: e.year, authors: e.authors,
                source: "embedded"};
      }
      return {pmid: pmid, title: "", abstract: "", source: "none"};
    });
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function openAbstract(pmid) {
    var ov = document.getElementById("abs-overlay");
    document.getElementById("abs-title").textContent = "PMID " + pmid;
    document.getElementById("abs-meta").textContent = "";
    document.getElementById("abs-source").textContent = "Loading…";
    document.getElementById("abs-body").textContent = "";
    document.getElementById("abs-link").href =
      "https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/";
    ov.classList.add("open");
    return loadAbstract(pmid).then(function (d) {
      document.getElementById("abs-title").textContent =
        d.title || ("PMID " + pmid);
      document.getElementById("abs-meta").textContent =
        [d.authors, d.journal, d.year].filter(Boolean).join(" · ");
      // An unavailable abstract says so. A blank panel and a working one must
      // never look the same.
      document.getElementById("abs-source").textContent =
        d.source === "server"   ? "Abstract · live from the evidence base" :
        d.source === "embedded" ? "Abstract · embedded in this deck" :
                                  "Abstract not available offline";
      document.getElementById("abs-body").textContent =
        d.abstract || "No abstract was embedded for this PMID and the server "
                    + "could not be reached. Open the PubMed record below.";
      return d;
    });
  }

  function closeAbstract() {
    document.getElementById("abs-overlay").classList.remove("open");
  }

  document.addEventListener("click", function (e) {
    var pill = e.target.closest && e.target.closest(".cite-pill");
    if (pill) {
      e.preventDefault(); e.stopPropagation();
      openAbstract(pill.getAttribute("data-pmid"));
      return;
    }
    if (e.target.id === "abs-close" || e.target.id === "abs-overlay") closeAbstract();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeAbstract();
  });

  // ── §3.3 narration sync ────────────────────────────────
  function setupNarration(deck) {
    var n = CFG.narration;
    if (!n || !n.cues || !n.cues.length || !n.audio_src) return;
    var bar = document.getElementById("narration");
    var audio = document.getElementById("n-audio");
    var btn = document.getElementById("n-sync");
    audio.src = n.audio_src;
    bar.classList.add("on");

    var synced = true;
    btn.setAttribute("aria-pressed", "true");
    btn.addEventListener("click", function () {
      synced = !synced;
      btn.setAttribute("aria-pressed", synced ? "true" : "false");
    });

    var last = -1;
    audio.addEventListener("timeupdate", function () {
      if (!synced) return;
      var t = audio.currentTime, target = null;
      for (var i = 0; i < n.cues.length; i++) {
        var c = n.cues[i];
        if (t >= c.start && (c.end == null || t < c.end)) { target = c.slide; break; }
      }
      if (target != null && target !== last) {
        last = target;
        if (deck && deck.slide) deck.slide(target - 1);
      }
    });
  }

  // ── boot ───────────────────────────────────────────────
  // ?print-pdf never initialises Reveal: the stacked layout is already exactly
  // one 1280×720 block per slide, so the printed page count equals the slide
  // count without fighting a transform.
  function bootFallback() {
    root.classList.add("no-reveal");
    setupNarration(null);
  }

  window.CuroDeck = {
    slideCount: CFG.slide_count,
    loadAbstract: loadAbstract,
    openAbstract: openAbstract,
    closeAbstract: closeAbstract,
    embeddedPmids: Object.keys(EMBEDDED),
    printMode: PRINT
  };

  if (PRINT) { setupNarration(null); return; }
  if (typeof Reveal === "undefined") { bootFallback(); return; }
  Reveal.initialize({
    width: CFG.width, height: CFG.height, margin: 0,
    minScale: 0.2, maxScale: 1.6,
    hash: true, controls: true, progress: true, slideNumber: false,
    transition: "fade", transitionSpeed: "fast",
    // The pills are buttons; reveal must not swallow the click.
    keyboardCondition: null
  }).then(function () {
    window.CuroDeck.reveal = Reveal;
    setupNarration(Reveal);
  }).catch(bootFallback);
})();
""".replace("__CONFIG__", config_json)
