# Curo vs OpenEvidence — comparison set

Twelve questions chosen to test specific hypotheses, plus one Curo-only case.
Not a random sample: each one is here because we predict a particular outcome, and
a wrong prediction is more useful than a right one.

**How to run it.** Ask both tools the same question, verbatim, same day. Save both
answers into `eval/fixtures/compare/<slug>_curo.md` and `<slug>_oe.md`. Record
Curo's cost, time, and paper count from its own header. Do not clean up either
answer — the formatting is part of what is being compared.

**Two rules that keep this honest.** Check numbers against the *cited abstract*,
not against your memory of the field. And where a tool declares an evidence gap,
verify the gap is real before scoring it as honesty — a retrieval hole announced as
a literature hole is the worse failure, and Curo has already done it once.

---

## A · Bread and butter — baseline quality

**A1.** What sodium hypochlorite concentration and contact time should be used for
irrigation in a necrotic molar?

*Watch for:* whether each concentration is attributed to the study that used it, or
whether a single number is presented as settled. Curo's consistency annotations
should attribute 2 / 2.5 / 3 / 5.25% rather than picking one.

**A2.** Is a cuspal-coverage restoration necessary after root canal treatment of a
mandibular molar?

*Watch for:* this sits in prosthodontics, not endodontics. Prediction: Curo's domain
filter thins the evidence and OpenEvidence answers more fully. If Curo does well
here, the filter is less restrictive than we think.

---

## B · Where the literature genuinely conflicts

**B1.** Is articaine better than lidocaine for inferior alveolar nerve block in
irreversible pulpitis?

*Watch for:* at least three meta-analyses disagree here. Does each tool surface the
disagreement and adjudicate it, or does it pick the answer it found first? Curo's
tier logic should rule; OpenEvidence tends to present a clean consensus.

**B2.** Is single-cone obturation with a bioceramic sealer equivalent to warm
vertical compaction?

*Watch for:* the in vitro trap. Most of this literature is bench work. An answer that
gives operating recommendations from in vitro data without saying so has failed,
whichever tool produces it.

---

## C · Where high-level evidence does not exist

**C1.** How long should a tooth with a separated instrument in the apical third be
monitored before intervening?

*Watch for:* whether either tool says plainly that this is consensus rather than
trial evidence, or whether it manufactures a confident interval.

**C2.** What is the evidence for the efficacy of intrapulpal anesthesia in
irreversible pulpitis?

*Watch for:* we know the ground truth here — no SR/MA or RCT isolates it. This is the
cleanest gap-honesty test in the set. Curo should declare the gap; check that its
declaration is scoped to what it searched, not to the literature as a whole.

---

## D · Out of domain — the crossover cases

**D1.** A patient on denosumab needs either extraction or endodontic retreatment of a
tooth with a large periapical lesion. How does MRONJ risk affect the decision?

*Watch for:* prediction — OpenEvidence answers the drug question better; Curo should
quarantine any drug guidance it cannot cite and then reframe to the endodontic
decision (retaining the tooth avoids the extraction risk entirely). That reframe is
the thing OpenEvidence structurally cannot do.

**D2.** Is antibiotic prophylaxis indicated before apical surgery in a patient with a
prosthetic hip replacement?

*Watch for:* pure guideline territory (AAOS / ADA). Neither tool should be inventing
this. Does Curo name the guideline body rather than answering from general knowledge?

---

## E · Retrieval traps

**E1.** What is the success rate of inferior alveolar nerve block in teeth with
symptomatic irreversible pulpitis?

*Watch for:* the Ohio State corpus — Reader, Nusstein, Drum, Fowler. This is the
direct test of the classics work. Note whether the cited papers are recent reviews
only, or the primary trials underneath them.

**E2.** Does laser-activated or multisonic irrigation improve clinical outcomes
compared with conventional needle irrigation?

*Watch for:* whether each tool distinguishes bench outcomes from clinical ones. Curo's
laser corpus is almost entirely in vitro and it should say so; the honest answer is
that no comparative in vivo RCT exists.

---

## F · Does the number trace back?

**F1.** What is the reported success rate of endodontic microsurgery at five years or
more?

**F2.** How much does CBCT change the detection rate of periapical lesions compared
with periapical radiography?

*Watch for:* pick two numbers from each answer and open the cited abstract. Does the
figure appear verbatim, same quantity, same unit? Is it the paper's finding, or its
method or background? That last distinction is the one nothing else checks.

---

## Curo only — no OpenEvidence equivalent

**G1.** 45-year-old, tooth 46, root canal treatment eight years ago. Now tender to
percussion, isolated 6 mm probing defect distobuccal, J-shaped radiolucency.

*Watch for:* does it lead with a differential (vertical root fracture vs failed
endodontics vs primary periodontal) rather than a treatment plan, and does it ask
only questions that would change the answer? OpenEvidence has no case mode, so this
is a capability difference, not a comparison.

---

## Scoring — six marks per answer, one line each

1. **Answered the question asked**, or an adjacent easier one?
2. **Numbers traceable** — two checked per answer, verbatim in the cited abstract?
3. **Citations resolvable** — could you find the paper from what is shown?
4. **Conflict surfaced** or smoothed into false consensus?
5. **Gaps declared honestly**, and is the declared gap real?
6. **Would you act on it chairside** without checking the sources first?

Also record for Curo: cost, elapsed time, paper count, and whether the banner
reported any claims outside the evidence base.

---

## What to do with the results

These twelve become eval cases. Where Curo loses, the pair is a fixture with a known
correct answer; where it wins, the pair is demo material. Either way the comparison
is worth more stored than remembered — file both answers before forming an opinion,
because the impression a well-formatted answer leaves is not the same as what
survives checking.
