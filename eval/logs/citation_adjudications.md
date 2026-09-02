# Citation adjudications

Claims flagged or challenged by hand, resolved against the source abstract
itself rather than against a memory of it. One entry per claim. A claim that
survives an adjudication is as much a result as one that does not.

---

## 1. PMID 27759881 — "no healing advantage for CBCT over radiography"

`dl-quality-v1` Item 2. Raised because the paper is *described elsewhere as
the LLLT post-surgical Cochrane*, which would make the CBCT citation a
misattribution.

**VERDICT: correctly attributed. The claim stands unchanged.**

PMID 27759881 is Del Fabbro M, Corbella S, Sequeira-Byron P, Tsesis I, Rosen E,
Lolato A, Taschieri S. *Endodontic procedures for retreatment of periapical
lesions.* Cochrane Database Syst Rev. 2016 Oct 19;10(10):CD005511.

Its abstract says, verbatim:

> There was no evidence that using CBCT rather than radiography for
> preoperative evaluation was advantageous for healing (RR 1.02, 95% CI 0.70
> to 1.47; one RCT, 39 participants; very low quality evidence)

That is the cited claim, in the source's own words, with an effect size and a
quality grading the curriculum could quote and did not.

**Why the challenge arose, which is the useful part.** This is a
twenty-RCT Cochrane review covering many comparisons at once, and the same
abstract also covers

> low energy level laser therapy versus placebo (irradiation without laser
> activation) versus control (no use of the laser device) (one study at high
> risk)

So "the LLLT post-surgical Cochrane" and "the CBCT-vs-radiography Cochrane"
are the same paper, read through two of its sub-analyses. Nothing is
misattributed; a multi-comparison review is simply hard to refer to by a
single description, and a reader who knows it by one of its arms will read a
citation to another arm as an error.

**Follow-through:** the claim should carry the effect size and the quality
grading, not just the direction. "No evidence of advantage (RR 1.02, 95% CI
0.70–1.47; one RCT, 39 participants; very low quality)" is a materially
different statement to a clinician than "no advantage", and the paper supplies
it.

*(Unrelated coincidence, noted so nobody chases it: 27759881 is also the PMID
truncated to `[[PMID:27759` in `answers/answer_20260829_174551.txt`. Different
defect, same number.)*

---

## 2. PMID 40818665 — the Sabeti claim

`dl-quality-v1` Item 3. Flagged by `verify_citation_support`. The claim, from
the laser curriculum's Module 4, under a heading **Adverse Effects**:

> Sabeti et al. confirmed that the overall adverse event profile of LAI met
> noninferiority criteria versus UAI [[PMID:40818665]].

**VERDICT: the flag is correct. The claim invents both its outcome and its
statistical framework, and must be CUT rather than re-sourced.**

PMID 40818665 is Sabeti M, Harouni A, Gabbay J. *Comparing Ultrasonically
Activated Irrigation and Laser-Activated Irrigation for Postoperative Pain
Reduction in Endodontics: A Systematic Review and Meta-Analysis of Randomized
Controlled Trials.* J Endod. 2026 Jan;52(1):37-46.

Three things were checked separately, because they fail separately:

| | |
|---|---|
| **Author attribution** | **CORRECT.** Sabeti M is the first author. |
| **"noninferiority criteria"** | **ABSENT, and not fairly implied.** The phrase appears nowhere. The design is a random-effects superiority meta-analysis reported as a standardised mean difference. There is no noninferiority margin, no noninferiority hypothesis, and no equivalence testing. |
| **"overall adverse event profile"** | **ABSENT.** The outcome is postoperative pain on a visual analogue scale. Adverse events are not an outcome of this review at all. |

The direction is also wrong in an interesting way: the paper does not report
that LAI merely fails to be worse, it reports that LAI is **better** —
SMD −0.58; 95% CI −0.94 to −0.22; P = .0016.

**Restated at source strength** (the `case-v2.1` dens evaginatus precedent —
say what the paper says, keep the topic, drop the reach):

> In a meta-analysis of seven RCTs (n = 490 teeth, 30 comparisons),
> laser-activated irrigation reduced postoperative pain compared with
> ultrasonic activation (SMD −0.58; 95% CI −0.94 to −0.22; P = .0016), with
> the largest effect at 24–48 hours. Pulsed Er:YAG modalities were strongest
> (PIPS SMD −1.10, SWEEPS SMD −1.57); diode lasers showed no significant
> effect (SMD 0.03) [[PMID:40818665]].

**And the adverse-event sentence has no source and must be cut.** This is the
load-bearing half. The module needed an adverse-events statement for a section
it had already titled "Adverse Effects", had no paper reporting adverse
events, and manufactured one out of a pain meta-analysis by reframing a
superiority result as a safety result. Re-pointing the marker at a different
paper would clear the checker and keep the invention; the honest endings are
the three the prompt already offers — cite it, cut it, or label it.

**The guardrail worked.** `verify_citation_support` flagged this claim on the
run that produced it. What failed was that a flagged claim still shipped inside
the curriculum with the flag rendered as an advisory footnote.
