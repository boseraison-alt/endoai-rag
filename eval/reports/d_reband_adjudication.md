# Item D (2026-09-08) — pubtype vs abstract, adjudicated by hand

**No database write.** This item decides whether either derivation writer is
reliable enough to drive a reband. The answer is no, but not symmetrically, and
the asymmetry points at a single fixable mapping.

## The population, and a number I could not reproduce

| | rows |
|---|---|
| stage-1 candidates | 446 |
| both writers can decide (row has an abstract-derived design) | 272 |
| **the two writers disagree** | **180** |
| of those disagreements, off-ladder | 159 |

The batch says "208 of 272 disagreements" and "off-ladder 185". I get **180**
and **159** against the same `e_reband_stage1.json`, comparing the pubtype
writer's `derived` against `extract_stated_design(abstract, title)["rung"]` —
the tier key, not the prose label. Comparing the prose label instead inflates
the count to 272, because `level1` and `"randomised controlled trial"` are the
same verdict written two ways; that is the likeliest origin of a higher figure,
but I cannot reconstruct 208 exactly and am not going to present a number I
cannot derive. The adjudication below is drawn from the 180 I can.

## "Off-ladder 185" explained

Prediction 10 was: *these are rows whose derived tier is a key outside the study
ladder — moves that leave the ladder entirely.* **Confirmed.** 159 of the 180
disagreements involve a key that is not one of `cochrane … level5`, and they are
dominated by two buckets:

| disagreement | n | what it means |
|---|---|---|
| `level3a` vs `invitro` | **116** | pubtype puts bench work on the human clinical ladder |
| `level3a` vs `animal` | 14 | pubtype puts animal work on the human clinical ladder |
| everything else | 29 | |

So "off-ladder" is not a scattering of odd cases. It is one mapping, firing 116
times.

## The 30 adjudicated

Stratified proportionally across the 22 disagreement buckets, ascending PMID
within each — deterministic, so the sample cannot be reshuffled until it says
something convenient. Quotes are from the stored abstract.

### Where the pubtype writer is wrong — 19 of 30

The cause is almost always the same: **NLM's `Comparative Study` is a modifier,
not a design.** It is attached to in vitro bench work, animal experiments and
prospective clinical studies alike, and mapping it to `level3a` asserts a human
clinical comparison that was never performed.

| PMID | pubtype said | truth | the sentence that decides it |
|---|---|---|---|
| 1940735 | level3a | invitro | "solvent effects … on **bovine pulp tissue**" |
| 2015993 | level3a | invitro | bench comparison of finishing discs (title) |
| 7561651 | level3a | invitro | SEM evaluation of root-end preparations (title) |
| 7642327 | level3a | invitro | "The aim of this **in vitro study** was to assess the sealability…" |
| 7673842 | level3a | invitro | "In this **in vitro investigation**, radiovisiography was compared…" |
| 7751067 | level3a | invitro | apical seal of root-end fillings, extracted roots |
| 8665319 | level3a | animal | "seven **beagle dogs** … After 6 months the dogs were killed." |
| 8670024 | level3a | animal | "the young **rat** molar" |
| 16499632 | level3a | level2 | "A **prospective study** of 140 intruded permanent teeth" |
| 20813556 | level3a | level2 | "this **prospective clinical study**" |
| 21915706 | level2 | level3a | "this multicenter **retrospective** study" (`multicenter study` is also a modifier) |
| 22322495 | level3b | invitro | "To evaluate, **in vitro**, the antimicrobial activity…" |
| 25963721 | level4 | invitro | "This **ex vivo** study evaluated…" — and `case reports` is plainly wrong |
| 28068207 | level1 | invitro | planktonic *E. faecalis* in root canals; specimen randomisation is not an RCT |
| 29336883 | level4 | level3a | "In this **retrospective study**, we investigated long-term follow-up…" |
| 29984369 | guideline | level1 | "The primary objective of this **systematic review** was to compare…" |
| 36862198 | level1 | invitro | fatigue testing of molars; randomised **specimens**, no human subjects |
| 38481211 | level1 | level3a | "This **retrospective cohort** study included eighteen adult patients" |
| 40755177 | level3a | level5 | "A **narrative review**" |

Two of these are worse than a rung error. `28068207` and `36862198` were tagged
**randomized controlled trial** for studies with no human subjects at all —
specimens were randomised, and the pubtype writer read that as a clinical trial.
That is a lab study entering the library at the top of the human evidence
ladder.

### Where the abstract writer is wrong — 9 of 30

A different failure, and a consistent one: **it matches a design word in a
sentence that is about something else.** Five of the nine are exactly this.

| PMID | abstract said | truth | what it actually matched |
|---|---|---|---|
| 2098464 | invitro | level3a | "A **previous in vitro study** has shown…" — someone else's study |
| 9198442 | observational | invitro | "**Cross-sectional** cuts were made at the 2-mm … levels" — a physical section |
| 34275184 | protocol | level1 | "The review **protocol** was registered in PROSPERO" — the meta-analysis has results |
| 38591808 | protocol | level3a | "The study **protocol** was approved by the Ethics Committee" |
| 18215667 | unclear | level3a | "requires validation from **randomized** controlled trials" — future work |
| 8530996 | level2 | level1 | "A prospective, **randomized** study compared bleeding complications" — it *is* randomised |
| 42175523 | level1 | level3a | meta-research **about** systematic reviews, not a systematic review |
| 39487671 | level5 | guideline | an IADT consensus; "scoping review" describes its method, not its status |
| 28650788 | invitro | undecided | label asserted with **no supporting sentence** in the abstract |

### Genuinely definitional — 2 of 30

- **30135248** — animal regeneration work *and* "enroll 40 patients … in a
  randomized, controlled trial" in one paper. Both writers are reading a real
  part of it.
- **41637255** — a diagnostic-accuracy comparison; `level3a` and
  "cross-sectional" are two defensible names for the same thing.

## Per-writer error rates

| writer | wrong | rate |
|---|---|---|
| **pubtype** | 19/30 | **63%** |
| **abstract extraction** | 9/30 | **30%** |
| definitional (neither wrong) | 2/30 | 7% |

**Prediction 9 was wrong in both halves.** I predicted that abstract extraction
would be wrong more often than pubtype, and that "definitional" would be the
largest bucket. Pubtype is wrong **twice as often**, and definitional is the
**smallest** bucket at 7%.

## Recommendation

**Do not run an automated reband from either writer.** A 63% error rate on the
disagreements is not a banding signal, and a 30% error rate is not a referee.

But the errors are not evenly spread, and one change would resolve most of them:

1. **Stop deriving `level3a` from `Comparative Study` alone.** It accounts for
   116 of the 180 disagreements on its own, and in every one of the 7 sampled
   from that bucket the pubtype writer was wrong. `Comparative Study` says two
   things were compared, not that humans were treated.
2. **Never derive `level1` from `Randomized Controlled Trial` when the abstract
   has no human subjects.** Two of 30 sampled rows are lab studies sitting at
   the top of the clinical ladder today.
3. **Teach the abstract writer sentence scope.** Five of its nine errors are
   design words in sentences about prior work, registrations, ethics approval or
   recommended future studies. A cue in a sentence whose subject is not this
   study should not count.

Each of those is a separate, measurable change with its own dry run. None is
made here.

## Manifest text proposed for the two consensus documents

Both are consensus statements currently sitting **on the study ladder**, which
is the category error A49 exists to fix. Proposed, not written.

### `39743567`

> Expert consensus on apical microsurgery. *International Journal of Oral
> Science* 2025. Pubtypes: `Journal Article`, `Consensus Statement`, `Review`.
> **Currently in the library at `level5`.**

```json
{ "id": "IJOS-APICAL-MICROSURGERY-2025", "org": "IJOS", "year": 2025,
  "title": "Expert consensus on apical microsurgery",
  "journal": "International Journal of Oral Science", "pmid": "39743567",
  "doi": "", "confidence": "confirmed", "status": "current",
  "jurisdiction": "CN", "flagship": false,
  "scope": ["apical surgery", "apicoectomy", "endodontic microsurgery",
            "root-end filling", "apical microsurgery"],
  "question": "How should apical microsurgery be performed and when is it indicated?",
  "url": "https://pubmed.ncbi.nlm.nih.gov/39743567/",
  "note": "Expert consensus convened by Chinese specialty societies. Sat at level5 until 2026-09-08; a consensus statement is not expert opinion on the study ladder." }
```

### `39487671`

> Appropriate Terminology for the Time Elapsed From Avulsion of a Permanent
> Tooth to Replantation: A Scoping Review and Consensus. *Dental Traumatology*
> 2025. Pubtypes: `Journal Article`, `Scoping Review`, `Consensus Statement`.
> **Currently in the library at `level2`** — a clinical-trial rung, for a
> terminology consensus.

```json
{ "id": "IADT-AVULSION-TERMINOLOGY-2025", "org": "IADT", "year": 2025,
  "title": "Appropriate terminology for the time elapsed from avulsion of a permanent tooth to replantation",
  "journal": "Dental Traumatology", "pmid": "39487671", "doi": "",
  "confidence": "confirmed", "status": "current", "jurisdiction": "INT",
  "flagship": false,
  "scope": ["dental trauma", "avulsion", "replantation", "extra-oral time",
            "dry time"],
  "question": "What terminology should be used for the time between avulsion and replantation?",
  "url": "https://pubmed.ncbi.nlm.nih.gov/39487671/",
  "note": "IADT consensus on terminology; 'scoping review' is its METHOD, not its status. Sat at level2 until 2026-09-08. Related to the IADT trauma guideline lineage." }
```

Both `scope[]` lists are drawn from the documents' own titles and abstracts, not
inferred. Neither is marked `flagship`: neither is a whole-specialty position
for its jurisdiction, and the flagship test pins at most one per jurisdiction.
