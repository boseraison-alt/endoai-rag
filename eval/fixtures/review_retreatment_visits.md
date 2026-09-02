# Curo — Review answer: retreatment in one visit versus two visits

Captured from `answers/answer_20260902_105256.txt`, which is the file the app
itself writes on completion. Nothing below is edited.

**PROVENANCE (AGENT_QUEUE A4).** This answer was produced at 2026-09-02
10:52:56 by the server process pid 7488, started 08:21:07, whose `/health`
reports `git_revision: 082d67c` — four commits BEFORE `trust-surface-v1` began.
It runs `debug=False`, so Flask's reloader is off and the process still holds
the `endo_ai.py` and `templates/index.html` it imported at 08:21. Every Stage 1
fix (Q3 impact factor, Q4 synthetic citation keys, Q5 bibliography, Q6 tier
ordering) landed between 09:34 and 10:27 and is absent from this build.

So the impact factors, the raw `[PMID: AAE-PS-retreatment]`, the 33-paper
bibliography and the cross-tier score table in this document are **pre-fix
output**, not evidence that those items are incomplete.

**WHAT THIS FILE DOES AND DOES NOT CONTAIN.** It is the answer TEXT as saved by
the server: recommendation, evidence summary, references, and the citation
support block. The full bibliography panel and the "top papers" table are
rendered client-side from the job payload and are not part of the saved file;
the counts for those are quoted from the reader's own observation in the
addendum (33 papers listed, ~12 cited).

**WHY IT IS STILL A VALID FIXTURE (A5).** A5's defect is a RETRIEVAL failure —
two on-point 2022 RCTs not returned — and Stage 1 changed nothing in retrieval.
The retrieved set, the search terms and the gate behaviour recorded for this run
are unaffected by the build question above.

---

ENDO AI — Clinical Answer
============================================================
Date:             2026-09-02 10:52:56
Question:         retreatment in one visit versus two visits in endodontics

Additional clinical context provided by the clinician:
Q1: Are you asking about the general evidence and considerations, or do you have a specific retreatment case in mind?
Answer: general
Papers Retrieved: 33
Avg Score:        76.7/100
============================================================

## CLINICAL RECOMMENDATION

Based on Cochrane-level evidence, single-visit and multiple-visit protocols yield equivalent long-term outcomes for endodontic treatment, with no difference in radiological failure, tooth extraction, swelling, flare-up, or sinus tract healing; the only consistent trade-off is a modestly higher incidence of pain within the first week after single-visit treatment [[PMID:36512807]]. This evidence base pools primary treatment and retreatment together and does not isolate a retreatment-specific answer — a gap the clinician should note. For retreatment specifically, contemporary evidence shows favourable pooled healing rates (~78% strict / 87% loose criteria) with prognosis driven far more by preoperative lesion size, PAI score, and coronal restoration quality than by visit number [[PMID:38280514]] [[PMID:38145805]]; a pragmatic default is therefore to complete retreatment in a single visit when the canal can be dried and adequately disinfected, and to add an interappointment calcium hydroxide dressing when persistent exudate, a sinus tract, or a large lesion (>5–10 mm) is present.

---

## EVIDENCE SUMMARY

**Cochrane Reviews**

The 2022 Cochrane review by Mergoni et al. (47 RCTs, 5693 teeth) remains the highest-tier synthesis and directly addresses single- vs multiple-visit root canal treatment [[PMID:36512807]]. It found no difference between regimens in radiological failure at ≥1 year (RR 0.93, 95% CI 0.81–1.07; moderate-certainty), tooth extraction, swelling/flare-up, analgesic use, or sinus tract resolution. Moderate-certainty evidence showed a higher proportion of participants reporting pain within one week after single-visit treatment (RR 1.55, 95% CI 1.14–2.09), an effect that was strongest in vital teeth and with mechanical instrumentation. Importantly, the review does not stratify primary treatment from retreatment, so its conclusions must be extrapolated to the retreatment scenario rather than read as retreatment-specific.

**Level I — RCTs and Systematic Reviews**

The AAE position statement on retreatment recognises that retreatment success (~50–70% at 4 years) is inherently lower than primary treatment and emphasises adequate disinfection and immediate coronal seal rather than mandating a specific visit count. Sabeti et al.'s systematic review of contemporary non-surgical retreatment (29 studies) reported pooled periapical healing of 78.8% (strict) and 87.5% (loose), with meta-regression identifying preoperative periapical status, lesion size, apical filling extent, and follow-up duration — not visit number — as the significant prognostic factors [[PMID:38280514]]. Olivieri et al.'s meta-analysis of gutta-percha retreatment (11 studies) similarly found 71% strict / 87% loose success at 1–3 years, and importantly reported that **multiple-visit retreatments had a lower success rate under strict criteria** — the opposite direction to what many clinicians assume, though this likely reflects case-selection bias (harder cases receive interappointment medication) rather than a true detrimental effect of the two-visit protocol [[PMID:38145805]]. Gupta et al.'s 2026 umbrella review of 12 systematic reviews concluded that higher-confidence reviews show no consistent or clinically important pain difference between protocols [[PMID:41856391]], and Kumar et al. reached the same equivocal conclusion [[PMID:39780175]]. A CBCT-based systematic review by Brochado Martins et al. identified number of visits as one of several outcome predictors on meta-regression but did not report the direction of effect strongly enough to override the Cochrane finding [[PMID:40122230]]. Sabeti et al.'s separate meta-analysis on single-cone/bioceramic obturation found no difference in failure between the newer materials/technique and traditional approaches for either primary treatment or retreatment [[PMID:38548045]].

**Level II — Prospective Studies**

No prospective study in this evidence base directly compares single- vs two-visit retreatment protocols with adequate power.

**Level IIIa — Retrospective Cohort**

Jurič et al.'s large private-practice cohort (1259 teeth, 91% recall) is the most methodologically robust cohort here and identified single-visit treatment as an independent predictor of reduced success (OR 0.40, 95% CI 0.21–0.75) alongside ten other pre-, intra- and post-operative factors [[PMID:38243912]]. This finding conflicts with the Cochrane pooled estimate and should be interpreted cautiously: the cohort mixed primary and retreatment cases, single-visit selection was operator-driven (not randomised), and the strict PAI ≤2 endpoint favours regimens that allow longer disinfection. Artaza et al. (199 teeth with large lesions, mostly single-visit with NaOCl) achieved 89% loose / 67% rigid success for treatment and 79% / 47% for retreatment, showing that single-visit protocols can perform well even in adverse anatomy when disinfection is optimised [[PMID:39151889]]. Vieira et al. (304 teeth) reported that a higher number of treatment visits without intracanal medication negatively affected outcome — reinforcing that if a second visit is used, calcium hydroxide should be placed [[PMID:38214429]]. Olivieri et al.'s longitudinal retreatment study (129 teeth, 80.6% strict success at 2–3 years) did not identify visit number as a significant prognostic variable, with lesion size >5 mm being the dominant predictor [[PMID:37315780]]. Restrepo-Restrepo et al. similarly identified coronal restoration quality, obturation density, and lesion size — not visit number — as the robust predictors over 1–12 years [[PMID:31211862]].

**Synthesis of the disagreement**

The Cochrane review and most systematic reviews conclude equivalence between one- and two-visit protocols for the outcomes that matter to patients (healing, tooth survival, flare-up), with a small pain penalty for single-visit within the first week. One retrospective cohort [[PMID:38243912]] and Olivieri et al.'s meta-analysis under strict criteria [[PMID:38145805]] suggest single-visit may be inferior, but both are confounded by case selection. The higher-tier evidence (Cochrane, systematic reviews) should take precedence: **for retreatment, visit number is not a primary driver of outcome; disinfection quality, coronal seal, and lesion size are.**

---

## REFERENCES

1. [PMID: 36512807] Mergoni G, Ganim M, Lodi G et al. — Cochrane review of single vs multiple visit RoCT; 47 RCTs, 5693 teeth; no difference in radiological failure, more early pain with single-visit. Cochrane Database Syst Rev (IF: 12.0), 2022. n=5693. (Score: 73.7/100)
2. [PMID: AAE-PS-retreatment] American Association of Endodontists — Position statement on endodontic retreatment; 50–70% healed at 4 years; emphasises coronal seal. (IF: 8.0), 2016. (Score: 90.0/100)
3. [PMID: 38280514] Sabeti M, Chung YJ, Aghamohammadi N et al. — SR of contemporary NS retreatment; pooled healing 78.8% (strict) / 87.5% (loose); prognostic factors identified. J Endod (IF: 3.5), 2024. (Score: 74.8/100)
4. [PMID: 38145805] Olivieri JG, Encinas M, Nathani T et al. — SR/MA of retreatment obturated with gutta-percha; 71–87% success; multi-visit associated with lower strict success. Int Endod J (IF: 4.0), 2024. Follow-up: 12+ months. (Score: 81.7/100)
5. [PMID: 41856391] Gupta R, Abraham D, Ahmad L et al. — Umbrella review of 12 SRs on single- vs multi-visit RoCT and post-op pain; no consistent difference. (IF: 4.0), 2026. (Score: 74.8/100)
6. [PMID: 39780175] Kumar G, Jena S, Manila N et al. — SR on postoperative pain incidence, single vs multiple visits; inconsistent findings. (IF: 2.5), 2025. (Score: 74.8/100)
7. [PMID: 40122230] Brochado Martins JF, Georgiou AC, Nunes PD et al. — CBCT-assessed SR/MA of primary treatment and retreatment; visits identified as an outcome predictor on meta-regression. J Endod (IF: 3.5), 2025. (Score: 74.8/100)
8. [PMID: 38548045] Sabeti MA, Karimpourtalebi N, Shahravan A et al. — SR/MA on single-cone/bioceramic sealer failure in treatment and retreatment; no significant difference vs conventional. J Endod (IF: 3.5), 2024. (Score: 74.8/100)
9. [PMID: 38243912] Jurič R, Vidmar G, Blagus R et al. — Private-practice cohort, 1259 teeth, 91% recall; single-visit associated with reduced success (OR 0.40). Int Endod J (IF: 4.5), 2024. Follow-up: up to 156 months. n=1259. (Score: 73.9/100)
10. [PMID: 39151889] Artaza L, Campello AF, Soimu G et al. — Retrospective study of 199 teeth with large AP lesions, mostly single-visit NaOCl; 89% loose / 67% rigid success for treatment. J Endod (IF: 3.5), 2024. Follow-up: 32 mo. n=199. (Score: 68.3/100)
11. [PMID: 38214429] Vieira AR, Pacheco-Yanes J, Gazzaneo ID et al. — Retrospective study of 304 teeth; higher visit count without intracanal medication reduced success. 2024. n=304. (Score: 66.5/100)
12. [PMID: 37315780] Olivieri JG, Feijoo Pato N, Labraca P et al. — Longitudinal retreatment cohort, 129 teeth; 80.6% strict / 93% loose success at 2–3 years; visit number not a significant predictor. J Endod (IF: 3.5), 2023. Follow-up: 36 mo. n=129. (Score: 63.9/100)
13. [PMID: 31211862] Restrepo-Restrepo FA, Cañas-Jiménez SJ, Romero-Albarracín RD et al. — CBCT/DPR cohort of 125 teeth with pre-op AP; coronal restoration, obturation density, lesion size were dominant predictors. Int Endod J (IF: 4.5), 2019. Follow-up: up to 144 mo. n=125. (Score: 66.1/100)

---

> ⚠ **Citation support: 1 of 17 flagged.** An automated review of each cited abstract found these may not directly support the claim they are attached to. Verify before relying on them:
>
> - [[PMID:31211862]] cited for: "Restrepo-Restrepo et al. similarly identified coronal restoration quality, obturation density, and lesion size — not visit number — as the r"

============================================================
