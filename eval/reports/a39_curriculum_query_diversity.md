# A39 — the curriculum's one query, measured. The fix is not diversity.

A39 proposed that the curriculum path is thin because it generates one query per
module where Literature generates seven, and that query diversity is the fix.
Measured on the apicoectomy module against A23's five named papers:

**Diversity does recover the papers — and it does it by accident, at seven times
the cost. One term of art in the single query does the same job for nothing.**

---

## 1. Correction to A39's own premise, before the result

A39 says the single module query reaches "4 of 5". It does not. That number came
from my A33i probe, which used a **hand-written** apicoectomy query. The query the
generator actually writes for the module is narrower:

```
(apicoectomy OR "apical resection" OR "surgical endodontics" OR apicectomy)
  AND (mandibular OR "lower jaw" OR mandible)
```

It reaches **1 of 5**. Measuring a hand-written stand-in for the thing production
does is the same error as A33d's original mis-attribution, and it made the gap
look four times smaller than it is.

## 2. Single query against the seven-angle union

| | targets | union pool | esearch calls | seconds |
|---|---|---|---|---|
| single query, what the curriculum does today | **1 / 5** | 136 | 8 | 10 |
| 7-angle union, what Literature does | **4 / 5** | 435 | 56 | 63 |

Per module the union costs 48 extra esearch calls and 53 s — and that is
esearch **only**. The production path also efetches and fetches metadata per
(tier, term), so the real wall-clock cost is higher than this, not equal to it.
Four modules: ~192 extra calls and at least 3.5 extra minutes on a curriculum
that already takes 5–6.

## 3. Where the recall actually comes from — and it is not diversity

| term | pool | targets found |
|---|---|---|
| 1 (the module query) | 138 | 1 — Mainkar 2020 |
| 2 | 123 | 0 |
| 3 | 20 | 0 |
| 4 | 0 | 0 |
| 5 | 169 | 0 |
| 6 | 24 | 0 |
| **7** | **47** | **3 — Jeon 2021, Bi 2022, Lee 2020** |

```
term 1 is the only source of: Mainkar 2020
term 7 is the only source of: Jeon 2021, Bi 2022, Lee 2020
terms 2-6 added 297 papers to the pool and ZERO targets
```

Term 7 is:

```
("endodontic microsurgery" OR "periradicular microsurgery" OR "apical microsurgery")
  AND (mandib* tooth OR mandib* region OR "lower jaw tooth")
```

**The gain is not seven angles. It is one vocabulary — the field's modern name
for the procedure.** A clinician says apicoectomy; the literature indexes
*endodontic microsurgery*.

## 4. The cheap fix does the same job

Adding the term-of-art vocabulary to the **single** query:

| | targets | pool | esearch calls | seconds |
|---|---|---|---|---|
| the generated module query | 1 / 5 | 137 | 8 | 6 |
| + microsurgery / bony-lid vocabulary | **4 / 5** | 162 | **8** | 9 |
| (7-angle union, for comparison) | 4 / 5 | 435 | 56 | 63 |

**Same recall. One seventh of the retrieval. A pool a third the size.**

## 5. So A39's premise is not supported, and A41 is the answer

Three reasons the fan-out is the wrong instrument here:

1. **It works by luck.** The generator produced the microsurgery angle on 1 of 7
   this run. A14 says term generation varies run to run — next time it might not,
   and the curriculum would silently go back to 1 of 5.
2. **It is 7× the retrieval cost** for a gain attributable to one angle.
3. **It triples the pool** (136 → 435) with papers that contain none of the
   targets, which A42 has just finished measuring as pure cost.

The lexicon (A41) makes the same recovery deterministic and free. This is
independent evidence for A41 from a second fixture — the first was the GIC
question and "orifice barrier"; this is the apicoectomy module and "endodontic
microsurgery".

**`endodontic microsurgery` added to `eval/endodontic_lexicon.json`, marked
`generator_ever_wrote_it: true`, and that distinction is deliberate.** It is not
a term the generator *cannot* produce — it produced it. It is one it does not
produce *reliably*, and the curriculum path generates exactly one query, so it
gets the vocabulary only by luck. A blind spot and an unreliable reach need the
same fix; conflating them would have hidden this case.

## 6. What is NOT recovered, and why

`20951283` — Setzer 2010 part 1 — is reached by nothing, in any condition. It is
correctly typed Meta-Analysis and passes the domain filter; what excludes it is
the `mandibular` qualifier, because the paper is about traditional versus
microsurgery **in general** and never claims a jaw. No vocabulary fixes that, and
relaxation that drops `mandibular` takes the pool 2,170 → 7,562 and pushes Jeon
and Mainkar out of the top 200 (A33h-i). It is a genuine limit of a query that
carries a site restriction the paper does not.

## 7. Recommendation

**Do not build the fan-out.** Ship A41b instead — offer the lexicon to the term
generator as available vocabulary — and measure recovery on this module as one of
its fixtures. If A41b does not deliver, the fan-out is still available, and it
will then be justified by a measurement rather than by an analogy to the
Literature path.
