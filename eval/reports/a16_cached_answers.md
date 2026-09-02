> **A cache is a time capsule of old behaviour. Any change to a rendered
> surface must say what happens to what is already stored.**
>
> — the class, for `HANDOVER.md`

# A16 — fixed surfaces did not reach cached answers

## A16a — what is stored, and on which path

The premise needed correcting before anything could be measured. There are
**three** stored-answer surfaces, not one, and they are different sizes from
what the item assumed:

```
  query_cache            10 rows    served by /history/<cache_id>   (History sidebar)
  learn_history/*.json   22 files   served by /learn_history/<file> (DL report list)
  answers/*.txt         141 files   an archive; never served
```

The ~113 figure is the `answers/` archive, which no route reads. The surfaces
that matter are the 10 cache rows and the 22 curricula.

**Only one of the three read paths normalised anything.**

| route | `finalise_answer_text` | `cited_pmids` |
|---|---|---|
| `/status/<job_id>` (live + cache) | yes | yes |
| `/history/<cache_id>` | **no** | **no** |
| `/learn_history/<filename>` | **no** | **no** |

Both archive routes handed the stored text straight to the browser. Both are
demo surfaces.

### What the current renderer would change, on the real rows

`query_cache`, 10 rows:

```
  strip an impact factor                      6
  add the banner's second number              7
  create a quarantine block                   1
  shrink the bibliography to the cited set   10      pools 17-100 vs cited 2-39
  change the answer text at all               8
```

`learn_history`, 22 files:

```
  add the banner's second number             13
  shrink the bibliography to the cited set   18
  change the answer text at all              17
```

**Every single cache row rendered the whole retrieval pool as its
bibliography.** That is Q5, unfixed, on the surface the demo opens.

### Which fixes reached cache, before this item

| fix | mechanism | reached a cached answer? |
|---|---|---|
| Q1 banner second half | server | only via `/status` |
| Q2 quarantine | server | only via `/status` |
| Q3 impact factor | server | only via `/status` |
| Q5 bibliography | server (`cited_pmids`) | only via `/status` |
| A3c claim marking | server text + browser | only via `/status` |
| Q4 marker rendering | browser | **yes** — every path |
| Q6 tier ordering | browser | **yes** |
| Q8 empty caveat | browser | **yes** |

The browser-side fixes reach everything because they transform whatever text
arrives. The server-side ones stopped at the one route that had been wired.

## A16b — re-render at read time

Both archive routes now call `finalise_answer_text` and return `cited_pmids`,
which is the option A16b prefers: every one of these fixes is presentational,
so nothing about the stored answer is wrong — only how it was being shown.
**The stored row is never mutated**, so the change is reversible and no history
is lost.

Both browser history loaders also render the answer themselves rather than
going through `showResult`, so they missed the A3c marking pass — the same
shape as the export-source bug already recorded in that function. Both now mark,
and the Deep Learning loader carries `cited_pmids` into the evidence-shape card.

## A16c — the general test, and a bug it found

`tests/test_cached_answers_render_current.py` builds a stored answer in the
shape the archives actually hold — pre-Stage-1, with an impact factor, a
pseudo-id marker, an out-of-domain paragraph, a support block carrying only the
first number, and a pool larger than its citation set — and asserts it renders
as the current renderer would.

It immediately found that **`finalise_answer_text` was not idempotent.** The
status block quotes the flagged claims verbatim; those quotes carry the "from
the wider literature" vocabulary; so a second pass quarantined the banner
inside the very block it was reporting on. The archive routes re-render on
every read, so this mattered.

Fixed by a general rule: **a blockquote is already a delimited block, so never
quarantine inside one.** That also protects the flagged-claim list and the
validation warning.

**8/8 mutants killed**, including one per reverted renderer fix, which is what
A16c asks for:

```
  M1  /history stops re-rendering                    KILLED
  M2  /learn_history stops re-rendering              KILLED
  M3  /history stops sending the cited set           KILLED
  M4  Q3's strip reverted                            KILLED by the cache test
  M5  Q2's quarantine reverted                       KILLED by the cache test
  M6  Q1's second half reverted                      KILLED by the cache test
  M7  the browser loaders stop marking               KILLED
  M8  quarantining inside blockquotes restored       KILLED
```

M3 survived its first run: the test grepped the route body for `cited_pmids`,
and the line that *computes* the value contains that string. It now exercises
both routes through the Flask test client and asserts on the JSON they return
(standing rule 14).

## A16d — go/no-go for the demo script

Run against the running server, so this is what the demo will show.

```
  #   cached  2nd half       quar   IF text   IF wire   pool/cited   raw marker
  1   yes     1 (want 1)     0      clean     clean     43/10        none
  2   yes     1 (want 1)     0      clean     clean     33/13        none
  3   yes     0 (want 0)     0      clean     clean     31/12        none
  4   yes     0 (want 0)     0      clean     clean     38/13        none
```

**GO.** All four are cached (1.0 s each after the first) and render every Stage
1 fix.

### The defect this found, which only a live check could

The first run was a **NO-GO** on question 4: an impact factor still rendered.
The model writes

```
J Clin Med (IF: n/a), 2025. Follow-up: >=6 mo. (Score: 79.4/100)
```

`(IF: n/a)` — a **non-numeric** value. The model no longer receives an impact
factor, but the REFERENCES template used to ask for one, so it kept the slot
and filled it in. Every Q3 test passed because every one of them used a numeric
value. The strip now accepts an enumerated set of non-numeric values
(`n/a`, `unknown`, `none`, `not available`, a dash, `?`) — enumerated rather
than wildcarded, because a permissive `[^)]*` would swallow a curriculum
decision-tree row like `(IF the canal is calcified, THEN refer)`.

Two other NO-GO lines in that first run were **my checker's own false alarms**,
corrected rather than accommodated:

* a `[[PMID:XXX]]` marker in the answer TEXT is expected — Q4's fix is at the
  render layer, so the test is whether the shipped renderer turns it into a
  pill. It now runs `renderAnswer` over the served text.
* "no second half" is correct when the answer has no uncited directives. The
  expected count is now computed from the detector rather than assumed non-zero
  — which is why questions 3 and 4 read `0 (want 0)` rather than failing.

## Tests

15 new (`tests/test_cached_answers_render_current.py`), plus 5 for the
non-numeric impact factor. Suite 1,887 → **1,908**.

## Open for RB

**The demo is GO, but question 1 took 9.2 s on the first ask** and 1.0 s
thereafter — that is embedding-model load on a cold process, not retrieval. If
the demo machine is restarted immediately before presenting, ask question 1
once to warm it.
