"""The citation-support check on the Deep Learning (curriculum) path.

`verify_citation_support` asks, for each (claim sentence, cited PMID) pair,
whether that paper's abstract actually SUPPORTS the claim. It is a different
question from `validate_evidence_mapping`, which only proves the PMID was
retrieved: a paper can be real, retrieved, correctly formatted — and still say
nothing about the sentence it is attached to.

It had exactly two call sites, `ask_clinical_question` (Review) and
`ask_case_question` (Case). The curriculum builder had none, which left the
longest and most citation-dense document the product emits as the one output
nothing checked. These tests pin the fix:

  1. PER MODULE      — every generated module carries a status, produced by the
                       SHARED renderer (`_append_support_warnings`), so there is
                       one citation-support vocabulary and not two.
  2. FLAGGING WORKS  — a real-but-irrelevant citation is flagged, and the
                       flagged claim reaches the stitched document.
  3. NEVER SILENT    — "the check could not run" is stated out loud. HANDOVER's
                       bug class (d) is "a check that fails open and shows
                       nothing"; a status block that is simply absent reads as
                       a pass.
  4. NEVER BLOCKING  — a verifier that raises must not cost the clinician the
                       curriculum they paid for.
  5. SURVIVES STITCH — the stitcher is an LLM told to reproduce module bodies
                       verbatim. If it drops a block anyway, the block is
                       restated deterministically.

All fixture data is REAL. The module prose is sentences lifted verbatim from
the archived "Use of lasers in root canal disinfection" curriculum in
learn_history/; the paper metadata is that run's own scored papers; the
abstracts are the real abstracts from the `abstract_cache` table, read once
when this file was written and frozen in below. The test itself is fully
offline: it stubs `endo_ai._invoke_claude` (the single Claude seam, pinned by
tests/test_streaming.py), stubs the abstract lookup, and redirects both JSONL
logs into tmp_path.

The seeded fixture is the bug in its natural shape: a REAL PMID from the
module's OWN evidence base, attached to a real clinical sentence it has nothing
to do with. It sails through validate_evidence_mapping — that is the point.

Run:  pytest tests/test_curriculum_support.py -v
"""

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

import endo_ai
import rag


# ══════════════════════════════════════════════════════════════════════════
# REAL DATA — see the module docstring for provenance. Do not hand-edit the
# abstracts; they are verbatim rows from abstract_cache.
# ══════════════════════════════════════════════════════════════════════════

_REAL_DATA_JSON = """
{
 "question": "Use of lasers in root canal disinfection",
 "abstracts": {
  "34293029": {
   "title": "Fungal species in endodontic infections: A systematic review and meta-analysis.",
   "abstract": "Fungal infections are common on oral mucosae, but their role in other oral sites is ill defined. Over the last few decades, numerous studies have reported the presence of fungi, particularly Candida species in endodontic infections, albeit in relatively small numbers in comparison to its predominant anaerobic bacteriome. Here, we review the fungal biome of primary and secondary endodontic infections, with particular reference to the prevalence and behavior of Candida species. Meta-analysis of the available data from a total of 39 studies fitting the inclusion criteria, indicate the overall weighted mean prevalence (WMP) of fungal species in endodontic infections to be 9.11% (from a cumulative total of 2003 samples), with 9.0% in primary (n = 1341), and 9.3% in secondary infections (n = 662). Nevertheless, WMP for fungi in primary and secondary infections which were 6.3% and 7.5% for culture-based studies, increased to 12.5% and 16.0% in molecular studies, respectively. The most prevalent fungal species was Candida spp. The high heterogeneity in the reported fungal prevalence suggests the need for standardized sampling, and speciation methods. The advent of the new molecular biologi"
  },
  "38340037": {
   "title": "Principle and antimicrobial efficacy of laser-activated irrigation: A narrative review.",
   "abstract": "In the last two decades, the activation of root canal irrigants with pulsed lasers as an adjunct in root canal treatment has become increasingly popular. This narrative review explains the physical basics and the working mechanism of laser-activated irrigation (LAI), explores the parameters influencing LAI efficacy, considers historical evolutions in the field and summarizes laboratory and clinical evidence with emphasis on the antimicrobial action of LAI. Cavitation is the driving force behind LAI, with growing and imploding vapour bubbles around the laser tip causing various secondary phenomena in the irrigant, leading to intense liquid dynamics throughout the underlying root canal. High-speed imaging research has shown that laser wavelength, pulse energy, pulse length and fibre tip geometry are parameters that influence this cavitation process. Nevertheless, this has not resulted in standardized settings for LAI. Consequently, there is significant variability in studies assessing LAI efficacy, complicating the synthesis of results. Laboratory studies in extracted teeth suggest that, with regard to canal disinfection, LAI is superior to conventional irrigation and there is a tren"
  },
  "38382735": {
   "title": "Comparative Analysis of Irrigation Techniques for Cleaning Efficiency in Isthmus Structures.",
   "abstract": "INTRODUCTION: This study aimed to evaluate the removal of a biofilm-mimicking hydrogel from isthmus structures in a simulated complex root canal system consisting of 2 curved root canals by Laser-activated irrigation (LAI, AdvErl Evo, Morita) and mechanical activation techniques. METHODS: A 3D-printed root canal model with 2 parallel root canals (60°-curvature, radius 5 mm, dimension 25/.06) with a total length of 20 mm connected via isthmuses (2.5 × 0.4 × 0.2 mm) at 5 mm and 8 mm from the apical endpoint and with lateral canals (diameter 0.2 mm) in all directions at 2, 5, and 8 mm from the apex was filled with a colored biofilm-mimicking hydrogel. Irrigation protocols under continuous irrigation with distilled water (3 × 20s per root canal; 3 ml/20s; n = 20) included conventional needle irrigation (=NI); manual agitation (=MA, gutta-percha point 25/.06); EndoActivator (=SAI-EA, 25/.04); EDDY (=SAI-E, 25/.04); ultrasonically-activated irrigation (=UAI) and LAI (Er:YAG-laser; P400FL tip at canal entrance; 25pps, 50 mJ, 300μs). Removal of the hydrogel was determined as a percentage via standardized photos through a microscope. Statistical analysis was performed using Kruskal-Wallis a"
  },
  "36156804": {
   "title": "Effectiveness of adjunct therapy for the treatment of apical periodontitis: A systematic review and meta-analysis.",
   "abstract": "BACKGROUND: Adjunct therapy refers to any intracanal procedure going beyond chemomechanical preparation with instruments and traditionally delivered irrigants (excluding interim dressings). It is not clear whether and which of these adjunct therapies have a significant impact on the outcome of root canal treatment [healing of apical periodontitis (AP) and other patient-related outcomes]. OBJECTIVES: This systematic review aimed to analyse available evidence on the effectiveness of adjunct therapy for the treatment of AP in permanent teeth, according to a population, intervention, comparison, outcome, time and study design framework formulated a priori by the European Society of Endodontology. METHODS: Five electronic databases (PubMed, Embase, Scopus, Cochrane and Web of Science) were searched up to October 2021 to identify clinical studies comparing adjunct therapy to no adjunct therapy in adult patients with AP. Animal studies, reviews, studies with less than 10 patients per arm and studies with a follow-up time of less than 1 year, or less than 7 days for postoperative pain, were excluded. The quality of the included studies was appraised by the appropriate tools [Risk of Bias 2"
  }
 },
 "papers": {
  "36156804": {
   "pmid": "36156804",
   "level_key": "level1",
   "is_reference_text": false,
   "year": "2023",
   "citations": 15,
   "authors": "Meire MA, Bronzato JD, Bomfim RA et al.",
   "sample_size": null,
   "followup_months": 12,
   "journal": "International endodontic journal",
   "journal_abbrev": "Int Endod J",
   "volume": "56 Suppl 3",
   "issue": "",
   "pages": "455-474",
   "impact_factor": 4.5,
   "score": 80.5,
   "has_coi": false,
   "coi_funder": "",
   "coi_status": "no_statement",
   "is_registered": true,
   "registry": "PROSPERO",
   "has_erratum": false,
   "has_retraction": false,
   "superseded_by": "",
   "medline_indexed": true
  },
  "34293029": {
   "pmid": "34293029",
   "level_key": "level1",
   "is_reference_text": false,
   "year": "2021",
   "citations": 16,
   "authors": "Alberti A, Corbella S, Taschieri S et al.",
   "sample_size": null,
   "followup_months": null,
   "journal": "PloS one",
   "journal_abbrev": "PLoS One",
   "volume": "16",
   "issue": "7",
   "pages": "e0255003",
   "impact_factor": 3.7,
   "score": 70.4,
   "has_coi": false,
   "coi_funder": "",
   "coi_status": "declared_none",
   "is_registered": false,
   "registry": "",
   "has_erratum": false,
   "has_retraction": false,
   "superseded_by": "",
   "medline_indexed": true
  },
  "38382735": {
   "pmid": "38382735",
   "level_key": "level2",
   "is_reference_text": false,
   "year": "2024",
   "citations": 5,
   "authors": "Donnermeyer D, Dust PC, Schäfer E et al.",
   "sample_size": 20,
   "followup_months": null,
   "journal": "Journal of endodontics",
   "journal_abbrev": "J Endod",
   "volume": "50",
   "issue": "5",
   "pages": "644-650.e1",
   "impact_factor": 3.5,
   "score": 60.4,
   "has_coi": false,
   "coi_funder": "",
   "coi_status": "no_statement",
   "is_registered": false,
   "registry": "",
   "has_erratum": false,
   "has_retraction": false,
   "superseded_by": "",
   "medline_indexed": true
  },
  "38340037": {
   "pmid": "38340037",
   "level_key": "level5",
   "is_reference_text": false,
   "year": "2024",
   "citations": 22,
   "authors": "Meire M, De Moor RJG",
   "sample_size": null,
   "followup_months": null,
   "journal": "International endodontic journal",
   "journal_abbrev": "Int Endod J",
   "volume": "57",
   "issue": "7",
   "pages": "841-860",
   "impact_factor": 4.5,
   "score": 39.8,
   "has_coi": false,
   "coi_funder": "",
   "coi_status": "no_statement",
   "is_registered": false,
   "registry": "",
   "has_erratum": false,
   "has_retraction": false,
   "superseded_by": "",
   "medline_indexed": true
  }
 },
 "sentences": {
  "36156804": [
   "This curriculum teaches you to select the right laser system for the right case, execute a reproducible operative protocol with specific parameters, and critically appraise an evidence base that is advancing rapidly but has not yet crossed the threshold of certainty required to change standard of care [[PMID:36156804]].",
   "The current standard of care — as reflected by the ESE position — remains conventional chemomechanical preparation with NaOCl and EDTA; laser adjuncts are optional enhancements, not replacements [[PMID:36156804]].",
   "The ESE review found low GRADE certainty; meta-analysis showed no significant difference in postoperative pain at 7 days compared with control [[PMID:36156804]]."
  ],
  "38340037": [
   "Energy transfer to intracanal irrigant creates rapid vapour-bubble formation, collapse, and photoacoustic streaming — the cavitation cascade that drives irrigant into lateral canals, isthmuses, and dentinal tubules [[PMID:38340037]].",
   "**Final NaOCl flush before laser activation.** Ensure intracanal irrigant volume is replenished immediately before LAI to provide sufficient fluid for cavitation bubble formation; the cited studies do not specify a standardised flush volume for this step — this step reflects mechanistic rationale described by Meire and De Moor [[PMID:38340037]] rather than a protocol-level numeric from a clinical trial. 6.",
   "Meire & De Moor (2024) detail how wavelength, pulse energy, pulse duration, and fibre-tip geometry all modulate cavitation intensity, but note that no standardised parameter set has yet emerged from the literature — a critical limitation for protocol reproducibility [[PMID:38340037]]."
  ],
  "38382735": [
   "In vitro, LAI with an Er:YAG tip (P400FL; 25 pps, 50 mJ, 300 µs pulse, 3 × 20 s per canal, 3 mL/20 s) achieved the greatest hydrogel removal from isthmus structures compared with all mechanical activation techniques tested [[PMID:38382735]].",
   "**Position laser tip.** For PIPS/SWEEPS: Donnermeyer et al. placed the P400FL tip at the canal entrance (not advanced to working length) and applied 25 pps, 50 mJ, 300 µs pulse duration [[PMID:38382735]].",
   "**Activate Er:YAG (PIPS).** Apply 25 pps, 50 mJ, 300 µs pulse duration × 3 cycles of 20 s per canal with 3 mL/20 s fresh irrigant replenishment between each cycle [[PMID:38382735]].",
   "**Irrigant activation efficacy.** In a 3D-printed complex model with 60°-curved canals connected by 2.5 × 0.4 mm isthmuses, Donnermeyer et al. (2024) demonstrated that Er:YAG LAI (P400FL flat tip, canal entrance position, 25 pps, 50 mJ, 300 µs, 3 × 20 s per canal at 3 ml/20 s) achieved the greatest hydrogel removal across the entire root canal system compared with sonic, ultrasonic, manual agitation, and conventional needle irrigation (p < 0.05) [[PMID:38382735]]."
  ],
  "34293029": [
   "Fungi complicate the picture: a meta-analysis of 2,003 samples (Alberti et al., 2021) found a weighted mean fungal prevalence of 9.11% across primary and secondary infections, rising to 16.0% in secondary infections when molecular detection methods are used, with *Candida* spp. identified as co-pathogens in approximately one in ten patients [[PMID:34293029]]."
  ]
 }
}
"""

REAL      = json.loads(_REAL_DATA_JSON)
QUESTION  = REAL["question"]
ABSTRACTS = REAL["abstracts"]          # pmid -> {title, abstract}
PAPERS    = REAL["papers"]             # pmid -> scored-paper row from that run
SENTS     = REAL["sentences"]          # pmid -> real sentences citing only it

LAI_MECHANISM = "38340037"   # Meire & De Moor — LAI principle / cavitation
ERYAG_PARAMS  = "38382735"   # Donnermeyer — Er:YAG P400FL 25 pps / 50 mJ / 300 µs
ESE_REVIEW    = "36156804"   # ESE adjunct-therapy systematic review
FUNGAL_PREV   = "34293029"   # fungal prevalence meta-analysis — the mis-citation

# The seeded unsupported claim: a REAL procedural sentence from the curriculum,
# re-pointed at a REAL paper in the same evidence base whose abstract is a
# meta-analysis of Candida prevalence and says nothing about Er:YAG pulse
# parameters. Real PMID, retrieved PMID, correct marker syntax — and wrong.
SEEDED_CLAIM_SOURCE = next(s for s in SENTS[ERYAG_PARAMS] if "25 pps" in s)
SEEDED_CLAIM = SEEDED_CLAIM_SOURCE.replace(f"[[PMID:{ERYAG_PARAMS}]]",
                                           f"[[PMID:{FUNGAL_PREV}]]")

TIERS = ("cochrane", "level1", "level2", "level3a", "level3b", "level4", "level5")

SYLLABUS = [
    {"title": "Laser physics and the cavitation mechanism",
     "search_query": "laser activated irrigation cavitation root canal"},
    {"title": "Er:YAG operative parameters and tip placement",
     "search_query": "Er:YAG PIPS SWEEPS pulse energy root canal irrigation"},
    {"title": "Clinical outcomes and the ESE position",
     "search_query": "laser adjunct apical periodontitis outcome systematic review"},
]

# Which paper each module's real prose is built from.
MODULE_SOURCE = [LAI_MECHANISM, ERYAG_PARAMS, ESE_REVIEW]


def module_body(idx: int, seeded: bool = False) -> str:
    """A module written from real curriculum sentences about this module's topic.

    `seeded` prepends the mis-cited sentence. Everything else is verbatim.

    The seeded module therefore carries the SAME sentence twice — once behind
    the fungal-prevalence PMID and once behind the paper that actually reports
    it. That is deliberate: it makes the check's job discriminating the
    citation, not the prose. Run live once against Haiku (2026-08-31), the real
    judge flagged the fungal copy and passed the correct one, at $0.0024 for
    the module's four pairs.
    """
    pmid  = MODULE_SOURCE[idx]
    lines = [s for s in SENTS[pmid] if len(s) > 100][:3]
    if seeded:
        lines = [SEEDED_CLAIM] + lines[:2]
    body = "\n\n".join(lines)
    return (f"## Module {idx + 1} — {SYLLABUS[idx]['title']}\n\n{body}\n\n"
            f"### Clinical Protocol Summary\n\n"
            f"| Step | Parameter | Evidence-Based Value |\n"
            f"| --- | --- | --- |\n"
            f"| Activation | Protocol | As cited above [[PMID:{pmid}]] |\n")


def evidence_base() -> dict:
    """A tier-organised evidence dict holding the four REAL scored papers.

    Shape matches build_evidence_base()'s return, which is what
    module_has_usable_evidence counts and _extract_evidence_pmids reads.
    """
    chosen = [PAPERS[p] for p in (LAI_MECHANISM, ERYAG_PARAMS, ESE_REVIEW,
                                  FUNGAL_PREV)]
    ev = {}
    for tier in TIERS:
        picked = [p for p in chosen if p.get("level_key") == tier]
        ev[tier] = {"text": "\n".join(f"PMID {p['pmid']} | {p.get('authors','')}"
                                      for p in picked),
                    "ids": [p["pmid"] for p in picked],
                    "scored": picked}
    ev["_summary"] = {
        "total_scored": len(chosen),
        "avg_score": round(sum(float(p.get("score", 0)) for p in chosen) / len(chosen), 1),
        "all_scored": sorted(chosen, key=lambda x: -float(x.get("score", 0))),
        "synthesis_order": [],
    }
    return ev


def thin_evidence_base() -> dict:
    """One paper — below MIN_MODULE_PAPERS, so the module is not generated."""
    ev = {t: {"text": "", "ids": [], "scored": []} for t in TIERS}
    p  = PAPERS[ESE_REVIEW]
    ev[p["level_key"]] = {"text": "", "ids": [p["pmid"]], "scored": [p]}
    ev["_summary"] = {"total_scored": 1, "avg_score": 0,
                      "all_scored": [p], "synthesis_order": []}
    return ev


# ══════════════════════════════════════════════════════════════════════════
# Offline harness
# ══════════════════════════════════════════════════════════════════════════

_STITCH_BODIES_RE = re.compile(
    r"MODULE BODIES \(reproduce verbatim with your wrapper text added\):\s*\n"
    r"═+\n(.*?)\n═+\n\s*REFERENCE METADATA", re.S)

# The exact shape _append_support_warnings emits, matched as a whole block so a
# stub stitcher can drop it the way a careless real one would.
_SUPPORT_BLOCK_RE = re.compile(
    r"\n*-{3,}[ \t]*\n+>[ \t]*[⚠✓○][^\n]*\*\*Citation support:[^\n]*(?:\n>[^\n]*)*")


class Harness:
    """Stubs every paid stage of the curriculum builder.

    `judge_verdicts(items)` decides what the citation-support model returns for
    the payload it is actually handed — the items are recorded, so a test can
    assert WHICH (claim, abstract) pairs were sent, not merely that a call
    happened.
    """

    def __init__(self):
        self.seeded_module   = None    # 0-based index to seed, or None
        self.abstracts       = dict(ABSTRACTS)
        self.stitcher_drops  = False   # simulate a stitcher that eats the blocks
        self.verify_raises   = False
        self.support_payloads = []     # one per verify_citation_support call
        self.module_texts    = {}
        self.calls           = []

    # -- the judge --------------------------------------------------------
    def judge(self, items):
        """Verdicts keyed by what the item actually CONTAINS, not by index.

        The abstract that never supports anything in this fixture is the fungal
        prevalence meta-analysis: whatever laser claim it is paired with, it is
        not evidence for it. Deciding from the item's own content is what makes
        the seeded-fixture test about the payload rather than about the stub's
        bookkeeping.
        """
        verdicts = []
        fungal_head = ABSTRACTS[FUNGAL_PREV]["abstract"][:60]
        for it in items:
            unrelated = (it["abstract"].startswith(fungal_head)
                         and "fung" not in it["claim"].lower()
                         and "candida" not in it["claim"].lower())
            verdicts.append({"i": it["i"],
                             "verdict": "not_supported" if unrelated else "supports"})
        return verdicts

    # -- the single Claude seam -------------------------------------------
    def invoke(self, client, *, function_name="claude", stream=False,
               on_partial=None, abort_cb=None, **kwargs):
        self.calls.append(function_name)

        if function_name == "verify_citation_support":
            if self.verify_raises:
                raise RuntimeError("Haiku unavailable")
            payload = json.loads(
                re.search(r"ITEMS \(JSON\):\n(\[.*?\])\n\nReturn ONLY",
                          kwargs["messages"][0]["content"], re.S).group(1))
            self.support_payloads.append(payload)
            return self._resp(json.dumps(self.judge(payload)))

        m = re.match(r"write_curriculum_module(?:_retry)?\[(\d+)/(\d+)\]", function_name)
        if m:
            idx  = int(m.group(1)) - 1
            text = module_body(idx, seeded=(idx == self.seeded_module))
            self.module_texts[idx] = text
            return self._resp(text)

        if function_name.startswith("stitch_curriculum"):
            bodies = _STITCH_BODIES_RE.search(kwargs["messages"][0]["content"])
            body   = bodies.group(1) if bodies else ""
            if self.stitcher_drops:
                body = _SUPPORT_BLOCK_RE.sub("", body)
            return self._resp(f"# {QUESTION}\n\n## OVERVIEW\n\nStub overview.\n\n"
                              f"{body}\n\n## KEY TAKEAWAYS\n\nStub takeaways.\n")

        return self._resp("{}")

    @staticmethod
    def _resp(text):
        return SimpleNamespace(
            content=[SimpleNamespace(text=text)],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=800))


@pytest.fixture
def harness(tmp_path, monkeypatch):
    h = Harness()

    # Never write to the live logs.
    monkeypatch.setattr(endo_ai, "_COST_LOG_PATH", str(tmp_path / "cost_log.jsonl"))
    monkeypatch.setattr(endo_ai, "_EVMAP_LOG_PATH",
                        str(tmp_path / "evidence_mapping.jsonl"))
    # A client object is constructed before the seam; give it a key to hold.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(endo_ai, "CITATION_SUPPORT_CHECK", True)

    monkeypatch.setattr(endo_ai, "_invoke_claude", h.invoke)
    monkeypatch.setattr(endo_ai, "generate_curriculum_syllabus",
                        lambda q, n_modules=4: ([dict(m) for m in SYLLABUS], 0.002))
    monkeypatch.setattr(endo_ai, "build_evidence_base",
                        lambda topic, mode="review": evidence_base())
    monkeypatch.setattr(endo_ai, "generate_search_terms",
                        lambda t, *a, **k: "broadened " + str(t)[:40])
    # verify_citation_support imports this from rag at call time — patch it
    # there so no test can reach the database.
    monkeypatch.setattr(rag, "get_cached_abstracts_bulk",
                        lambda pmids: {p: {"pmid": p, **h.abstracts[p]}
                                       for p in pmids if p in h.abstracts})
    h.tmp_path = tmp_path
    return h


def support_blocks(text):
    """Every citation-support status block in a document, in order."""
    return re.findall(r"\*\*Citation support:[^\n]*", text or "")


def cost_rows(tmp_path, function_name):
    path = tmp_path / "cost_log.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l)["function"] == function_name]


# ══════════════════════════════════════════════════════════════════════════
# 1. Every module carries a status
# ══════════════════════════════════════════════════════════════════════════

class TestEveryModuleCarriesAStatus:

    def test_each_generated_module_has_its_own_status_block(self, harness):
        answer, cost, _ = endo_ai.build_deep_learning_module(QUESTION)

        blocks = support_blocks(answer)
        assert len(blocks) == len(SYLLABUS), (
            f"{len(blocks)} status block(s) for {len(SYLLABUS)} modules — a "
            f"module with no block is indistinguishable from one that passed:\n"
            + "\n".join(blocks))
        assert all("Citation support: verified" in b for b in blocks), blocks

    def test_the_status_sits_inside_the_module_it_describes(self, harness):
        """Not one summary at the bottom — each module's own outcome, in place."""
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)
        for i, mod in enumerate(SYLLABUS):
            start = answer.index(f"## Module {i + 1} — {mod['title']}")
            nxt   = (answer.index(f"## Module {i + 2} — ")
                     if i + 1 < len(SYLLABUS) else len(answer))
            assert support_blocks(answer[start:nxt]), (
                f"module {i + 1} ('{mod['title']}') carries no citation-support status")

    def test_the_wording_comes_from_the_shared_renderer(self, harness):
        """One vocabulary, not two. The block must be byte-identical to what
        _append_support_warnings produces for the same result dict."""
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)
        n_pairs = len(harness.support_payloads[0])
        expected = endo_ai._append_support_warnings(
            "", {"flags": [], "checked": n_pairs, "status": "verified"}).strip()
        assert expected in answer, (
            "the curriculum path is not rendering through _append_support_warnings")

    def test_one_haiku_call_per_module_is_logged_through_log_llm_call(self, harness):
        answer, cost, _ = endo_ai.build_deep_learning_module(QUESTION)

        rows = cost_rows(harness.tmp_path, "verify_citation_support")
        assert len(rows) == len(SYLLABUS), (
            f"{len(rows)} citation-support call(s) logged for {len(SYLLABUS)} modules")
        assert all(r["model"] == endo_ai.MODELS["structured_fast"] for r in rows)
        assert all(r["mode"] == "guardrail" for r in rows)

        # …and the money reaches the curriculum's total. Every stage logs
        # through log_llm_call, so the returned cost must be the whole log plus
        # the stubbed syllabus fee — dropping the support cost on the floor
        # would leave the clinician's bill understated.
        every_row = [json.loads(l) for l
                     in (harness.tmp_path / "cost_log.jsonl")
                     .read_text(encoding="utf-8").splitlines() if l.strip()]
        assert cost == pytest.approx(0.002 + sum(r["cost_usd"] for r in every_row),
                                     abs=1e-6)


# ══════════════════════════════════════════════════════════════════════════
# 2. The seeded unsupported claim is flagged
# ══════════════════════════════════════════════════════════════════════════

class TestSeededUnsupportedClaimIsFlagged:

    def test_the_mis_cited_pair_is_actually_sent_to_the_judge(self, harness):
        """The claim and the abstract have to MEET. If the pair never reaches
        the model, a passing flag test would be proving nothing."""
        harness.seeded_module = 1
        endo_ai.build_deep_learning_module(QUESTION)

        # The payload the model sees carries only (i, claim, abstract) — the
        # PMID is deliberately withheld from the judge, so the pair is
        # identified here the same way: by its content.
        pairs  = [it for payload in harness.support_payloads for it in payload]
        fungal = ABSTRACTS[FUNGAL_PREV]["abstract"][:60]
        seeded = [it for it in pairs
                  if it["abstract"].startswith(fungal) and "25 pps" in it["claim"]]
        assert seeded, (
            "the seeded claim was never paired with the fungal-prevalence "
            f"abstract; pairs seen: "
            f"{[(p['claim'][:40], p['abstract'][:40]) for p in pairs]}")

    def test_it_is_flagged_in_the_stitched_curriculum(self, harness):
        harness.seeded_module = 1
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)

        flagged = [b for b in support_blocks(answer) if "flagged" in b]
        assert len(flagged) == 1, (
            f"expected exactly the seeded module to be flagged, got: "
            f"{support_blocks(answer)}")
        assert re.search(r"Citation support: 1 of \d+ flagged", flagged[0])
        assert f"[[PMID:{FUNGAL_PREV}]] cited for:" in answer
        assert "25 pps" in answer

    def test_the_honest_modules_are_not_flagged(self, harness):
        """A flag on every module would be a broken check, not a strict one."""
        harness.seeded_module = 1
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)
        assert sum("Citation support: verified" in b
                   for b in support_blocks(answer)) == 2

    def test_validate_evidence_mapping_does_not_catch_it(self, harness):
        """Why this check has to exist: the seeded PMID is REAL and RETRIEVED,
        so the mapping validator is happy with it."""
        ev  = evidence_base()
        res = endo_ai.validate_evidence_mapping(module_body(1, seeded=True), ev)
        assert res["fabricated_pmids"] == []
        assert FUNGAL_PREV in res["cited_pmids"]


# ══════════════════════════════════════════════════════════════════════════
# 3. "Not available" is stated out loud
# ══════════════════════════════════════════════════════════════════════════

class TestNotAvailableIsExplicit:

    def test_no_abstracts_means_an_explicit_not_available_per_module(self, harness):
        harness.abstracts = {}
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)

        blocks = support_blocks(answer)
        assert len(blocks) == len(SYLLABUS)
        assert all("Citation support: not available" in b for b in blocks), blocks
        assert "source abstracts unavailable" in answer
        assert not harness.support_payloads, "no judge call should have been made"
        assert not cost_rows(harness.tmp_path, "verify_citation_support")

    def test_the_check_being_disabled_is_stated_too(self, harness, monkeypatch):
        monkeypatch.setattr(endo_ai, "CITATION_SUPPORT_CHECK", False)
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)

        blocks = support_blocks(answer)
        assert len(blocks) == len(SYLLABUS)
        assert all("Citation support: not available" in b for b in blocks), blocks
        assert "disabled by configuration" in answer

    def test_a_module_that_was_never_generated_says_so(self, harness, monkeypatch):
        """Below MIN_MODULE_PAPERS: no module, and therefore no citations to
        check. That is still an outcome, and it is still stated."""
        monkeypatch.setattr(endo_ai, "build_evidence_base",
                            lambda topic, mode="review": thin_evidence_base())
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)

        assert "Module not generated" in answer
        blocks = support_blocks(answer)
        assert len(blocks) == len(SYLLABUS)
        assert all("Citation support: not available" in b for b in blocks), blocks
        assert "module not generated" in answer
        # The status travels WITH the gap block, so the post-stitch guarantee
        # has nothing to restore. If the gap path stopped emitting a status of
        # its own, the guarantee would paper over it with an appendix instead.
        assert "## Citation Support by Module" not in answer
        for mod in SYLLABUS:
            start = answer.index(f"## Module — {mod['title']}")
            assert support_blocks(answer[start:start + 1400]), (
                f"the gap block for '{mod['title']}' carries no status of its own")


# ══════════════════════════════════════════════════════════════════════════
# 4. Advisory, never blocking
# ══════════════════════════════════════════════════════════════════════════

class TestAdvisoryNeverBlocking:

    def test_a_verifier_that_raises_does_not_lose_the_curriculum(self, harness):
        harness.verify_raises = True
        answer, cost, _ = endo_ai.build_deep_learning_module(QUESTION)

        for i, mod in enumerate(SYLLABUS):
            assert f"## Module {i + 1} — {mod['title']}" in answer
        assert "25 pps" in answer          # module content survived intact
        blocks = support_blocks(answer)
        assert len(blocks) == len(SYLLABUS)
        assert all("Citation support: not available" in b for b in blocks), blocks
        assert "check unavailable" in answer

    def test_a_flagged_module_is_still_published(self, harness):
        """Flagging annotates; it must never suppress or rewrite the module."""
        harness.seeded_module = 1
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)
        assert f"## Module 2 — {SYLLABUS[1]['title']}" in answer
        assert "Module not generated" not in answer
        assert SEEDED_CLAIM.split("[[PMID:")[0][:60].strip() in answer


# ══════════════════════════════════════════════════════════════════════════
# 5. The status survives the stitcher
# ══════════════════════════════════════════════════════════════════════════

class TestStatusSurvivesTheStitcher:

    def test_blocks_dropped_by_the_stitcher_are_restated(self, harness):
        """The stitcher is an LLM told to reproduce module bodies verbatim.
        "Told to" is not a guarantee, and a status block that quietly
        evaporates is exactly the fail-open shape this check exists to end."""
        harness.stitcher_drops = True
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)

        assert "## Citation Support by Module" in answer
        blocks = support_blocks(answer)
        assert len(blocks) == len(SYLLABUS), blocks
        for mod in SYLLABUS:
            assert f"**{mod['title']}**" in answer

    def test_no_appendix_when_the_stitcher_behaved(self, harness):
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)
        assert "## Citation Support by Module" not in answer

    def test_identical_blocks_are_counted_not_matched(self, harness):
        """Three modules whose blocks are textually identical. A substring test
        would find the one surviving copy and call all three present."""
        harness.stitcher_drops = True
        modules = [{**m, "citation_support": {"flags": [], "checked": 4,
                                              "status": "verified"}}
                   for m in SYLLABUS]
        one = endo_ai._support_status_block(modules[0]["citation_support"])
        restored = endo_ai._ensure_curriculum_support_blocks(
            f"# doc\n\n{one}\n", modules)
        assert len(support_blocks(restored)) == 3


# ══════════════════════════════════════════════════════════════════════════
# 6. The Deep Learning VIEW shows it
# ══════════════════════════════════════════════════════════════════════════

TEMPLATE = (Path(__file__).parent.parent / "templates" / "index.html")


class TestTheDeepLearningViewShowsIt:

    def test_the_view_keeps_per_module_blocks_in_the_body(self):
        """Review moves its single block into the header chip. A curriculum
        cannot: one chip cannot say WHICH module was checked, so learn mode
        keeps every block where the reader can see which module it belongs to."""
        html = TEMPLATE.read_text(encoding="utf-8")
        assert "_stripSupportBlockquote(answerText, mode === 'learn')" in html

    def test_the_strip_pattern_cannot_swallow_the_document(self):
        """The old pattern ended in `[\\s\\S]*$`, anchored to the FIRST match.
        Harmless with one block at the bottom of a Review answer; with one
        block per module it would delete the whole curriculum from module 1
        onwards."""
        html = TEMPLATE.read_text(encoding="utf-8")
        assert "Citation support:\\s*(?:verified|not available)[\\s\\S]*$" not in html

    def test_the_chip_aggregates_every_block_not_just_the_first(self):
        """With N modules, matching only the first block would report module
        1's result as if it were the whole curriculum's."""
        html = TEMPLATE.read_text(encoding="utf-8")
        assert "while ((mm = flaggedRe.exec(answerText)) !== null)" in html
        assert "while ((mm = verifiedRe.exec(answerText)) !== null)" in html
        assert "while ((mm = naRe.exec(answerText)) !== null)" in html

    def test_the_chip_regexes_match_what_the_engine_emits(self, harness):
        """The view greps the answer text. Pin the two ends together: the
        strings the template looks for must be the strings the renderer writes."""
        harness.seeded_module = 1
        answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)

        # ports of the three template regexes
        flagged  = re.findall(r"Citation support:\s*(\d+)\s+of\s+(\d+)\s+flagged", answer)
        verified = re.findall(
            r"Citation support:\s*verified\.\*\*\s*Each of the (\d+) cited", answer)
        assert len(flagged) == 1 and len(verified) == 2, (flagged, verified)

        harness.abstracts = {}
        na_answer, _, _ = endo_ai.build_deep_learning_module(QUESTION)
        assert len(re.findall(r"Citation support:\s*not available", na_answer)) == 3
