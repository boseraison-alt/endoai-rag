# Six-system benchmark — pre-registered protocol

Registered 2026-09-07 by the advisory session, before any answer was
collected. Nothing in this file changes after the first answer is captured;
corrections go in a dated addendum at the bottom.

## Systems

| # | system | how it is run |
|---|---|---|
| 1 | Curo | Literature mode on the running server, on the commit tagged `night-20260909-end` or later, after the v8 baseline. Commit hash recorded. |
| 2 | ChatGPT | chatgpt.com, RB's account, default model as offered, no manual toggles; model name recorded as displayed. |
| 3 | Gemini | gemini.google.com, default model; recorded. |
| 4 | OpenEvidence | openevidence.com, RB's clinician account. |
| 5 | Claude | claude.ai, a fresh chat, default model, no files or tools toggled; recorded. |
| 6 | DentalSource | dentalsource, RB's account. |

Rules of collection: the prompt text below is pasted verbatim, one
submission per question per system, no follow-ups, no regeneration, no
"try again". The full response is captured as rendered — text and
citations — with a timestamp and a screenshot, into
`eval/benchmark_2026-09/raw/<system>/Q<n>.md` and `.png`. Collected
through RB's own Chrome session by the advisory session. If a system
refuses or errors, that is recorded and scored as delivered.

## The five prompts — verbatim

**Q1 — vital pulp therapy.** *A 34-year-old has a mature mandibular first
molar with symptomatic irreversible pulpitis and a deep carious lesion. The
pulp is exposed during caries removal and haemostasis is achieved in about
8 minutes. Is full pulpotomy with a calcium silicate cement an acceptable
alternative to root canal treatment, and what do the current evidence and
guidance say about haemostasis time as a decision criterion?*

**Q2 — root-end filling.** *For root-end filling after apicoectomy
(endodontic microsurgery), is a premixed bioceramic root repair material
equivalent to MTA in clinical outcome? Cite the key trials and reviews.*

**Q3 — CBCT.** *What are the current indications for CBCT in endodontics,
and which guideline should I follow? Include the year of the guideline you
rely on.*

**Q4 — avulsion.** *A 19-year-old's avulsed maxillary central incisor
(closed apex) is replanted after 60 minutes of dry storage. What is the
recommended management, including when to start root canal treatment, and
which guideline are you following?*

**Q5 — antibiotics.** *A healthy adult presents with symptomatic
irreversible pulpitis, no swelling and no systemic signs; definitive
treatment can be provided today. Should systemic antibiotics be prescribed?
Cite the guidance.*

## Answer keys — fixed now

Key papers are PubMed-verified PMIDs already pinned in the repo's fixture
files. "Trap" = a superseded document that a stale answer cites as current.

**Q1.** Key papers: Sulaiman 2026 haemostasis-time trial (42388091);
Komora 2024 network meta-analysis of bioactive materials (39117767);
EFCD-ESE-ORCA deep-caries S3 guideline 2026 (42018467); ESE S3 2023
(37772327). Current guidance: ESE-S3-2023 (EU), AAE VPT position statement
2021 (US), EFCD-ESE-ORCA 2026 (EU). Facts: (a) full pulpotomy with a
calcium silicate cement is an accepted alternative to root canal treatment
in mature teeth with symptomatic irreversible pulpitis under current
guidance; (b) the traditional haemostasis criterion (about 5–10 minutes
with sodium hypochlorite) is stated as guidance, not as a hard abort rule,
and the answer acknowledges that recent evidence questions a fixed cutoff;
(c) calcium silicate materials, not calcium hydroxide, are the materials of
choice; (d) an immediate definitive coronal restoration is part of the
protocol. An answer that gives a fixed minute threshold as an absolute
stop rule with no caveat fails (b).

**Q2.** Key papers: Cochrane 2021 retrograde filling materials (34647617);
Safi 2019 RCT MTA vs RRM (31078325); Zhou 2017 RCT MTA vs iRoot BP Plus
(27986096); Ibáñez-Aravena 2025 SR/MA (40637350); Bliggenstorfer 2021
424-molar cohort (34499889). Current guidance: ESE-S3-2023 (EU); AAE
Treatment Standards 2018 (US); FDSRCS periradicular surgery guidelines 2020
(UK). Facts: (a) equivalence in clinical outcome; (b) the Cochrane 2021
review *does* contain a direct MTA-vs-root-repair-material comparison (two
trials, 278 teeth, RR 1.00) — stating that it does not is a pre-declared
error; (c) at least one of the head-to-head RCTs is named; (d) the contrary
retrospective signal (Bliggenstorfer, bioceramic ahead in molars) is
mentioned — bonus, not required.

**Q3.** Key documents: AAE/AAOMR joint position statement **2025 update**
(41412684) — current; AAE/AAOMR **2015** (26320105) — trap; ESE CBCT
position statement 2019 (31301231); ADA/AAOMR patient-selection
recommendations 2026 (41500761). Facts: (a) CBCT is not routine — limited
field of view, justified case by case; (b) the current joint statement is
the 2025 update; an answer relying on the 2015 statement as current fails
currency; (c) indications include non-resolving periapical pathosis after
treatment, complex or unidentified anatomy, suspected resorption or vertical
root fracture, dental trauma, and surgical planning; (d) jurisdiction is
stated (US joint statement vs ESE for Europe).

**Q4.** Key documents: IADT 2020 avulsion guideline (32460393) — current;
IADT 2012 avulsion (22409417) — trap; AAE trauma guidelines 2026
(41941956); ESE trauma position statement 2021 (33934366); Cochrane
CD006542 (30720860). Facts: (a) with more than 60 minutes of dry storage the
periodontal ligament is expected to be non-viable and the prognosis poor,
but replantation is still recommended with the patient counselled about
ankylosis-related resorption; (b) for a closed apex, root canal treatment is
initiated within about two weeks of replantation; (c) a flexible splint for
about two weeks (longer for delayed replantation is acceptable if stated as
per guideline); (d) systemic antibiotics and tetanus status are addressed;
(e) the guideline named is IADT 2020 (or AAE 2026 / ESE 2021) — citing the
2012 version as current fails currency.

**Q5.** Key documents: ADA 2019 antibiotic guideline for pulpal and
periapical conditions (31668170); ESE antibiotics position statement 2018
(28436043); Cochrane CD004969 2019 (31145805); ADA antibiotic stewardship
statement 2026 (42569978); AAE 2017 guidance (under review — an answer may
cite it but should not present it as the sole current authority). Facts:
(a) no systemic antibiotics — definitive treatment alone; (b) antibiotics
are reserved for systemic involvement or spreading infection, and the
answer says so; (c) pain is managed with NSAIDs with or without
paracetamol/acetaminophen; (d) at least one of the three key documents is
cited.

## Objective rubric — 60 points, scored by the advisory session and Curo's own checkers

| dim | points | rule |
|---|---|---|
| D1 citation integrity | 15 | Every citation is resolved (exists; title, journal, year as stated) and its abstract supports the sentence it is attached to, using the same citation-support checker Curo applies to itself. Score = fraction verified × 15. **Any fabricated citation → 0 for the dimension.** Uncited answers score 0. |
| D2 key-paper recall | 10 | Fraction of the question's key papers present, by PMID or unambiguous title. |
| D3 currency | 10 | 10 if no superseded document is cited as current; 7 if cited with its supersession stated; 0 if a trap document is presented as current. |
| D4 guideline coverage and jurisdiction | 10 | 5 for naming a current applicable guideline; 5 for stating jurisdiction where guidance is jurisdiction-specific (Q2, Q3, Q4) or naming both a US and a European document (Q1, Q5). |
| D5 factual anchors | 10 | Fraction of the question's pre-declared facts stated correctly × 10; each pre-declared error −5, floor 0. |
| D6 transparency | 5 | 5 if each source carries an evidence level or design; 3 if partial; 0 if none. |

## Blind clinical rubric — 40 points, scored by RB

Answers are anonymised per question (A–F, shuffled independently for each
question), branding and layout stripped to plain text, citations kept.
The mapping is written to `eval/benchmark_2026-09/blind_key.json` and not
opened by anyone until RB's sheet is complete and committed.

| dim | points | question RB answers |
|---|---|---|
| C1 correctness | 15 | Is the recommendation what a well-read endodontist would give today? |
| C2 calibration | 10 | Does it state uncertainty and conflicts honestly, without overclaiming? |
| C3 actionability | 10 | Could a colleague act on this tomorrow without looking anything up? |
| C4 safety | 5 | Nothing here would harm a patient if followed. |

## Reporting

One table: system × question, objective / clinical / total; totals per
system; rank. The write-up states, in this order: n = 5 questions, one run
each, collected on the dates recorded; model versions as displayed;
OpenEvidence and DentalSource are clinical-evidence products and the other
three are general assistants; the objective half was scored by the advisory
session (Claude) with the rubric above fixed before collection, and the
clinical half by RB blind — the conflict of interest is disclosed, not
resolved. Curo's answers are the last collected and come from the
post-v8 server.

## What this is not

Not a publication-grade benchmark. Five questions and one run per system
tell you where Curo stands this week on the things it claims to do well —
currency, supersession, verifiable citations, guideline jurisdiction — and
where it is beaten. That is what it is for.
