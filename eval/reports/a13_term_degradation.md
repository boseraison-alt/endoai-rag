# A13 — term-generation degradation rate

## A13a — the measurement, before any fix

The degradation warnings are stdout only, so there was no log to count. But
`pubmed_audit.jsonl` stores the **full built search term** of every live
esearch, and `fetch_papers` composes it as

```
({topic}) AND ({tier_filter}) AND {ENDO_DOMAIN_FILTER} NOT ... NOT ...
```

so the generated topic is recoverable by peeling the two known filters back
off. That gives **1,790 distinct generated topics across 155 real live runs**,
April to September — the largest honest sample available, and it is the live
path, the one A1's routing decision governs.

A topic is **degraded** when it parses to fewer than two AND-groups, i.e. it is
not a boolean query.

```
  healthy (2-3 AND-groups)          1,605   89.7%
  DEGRADED (<2 AND-groups)            108    6.0%
  over 3 groups (capped upstream)      77    4.3%
```

Of the 108 degraded, **92 are raw prose with no boolean operator at all**:

```
  vital pulp therapy MTA mineral trioxide
  laser disinfection biofilm endodontic therapy
  pulp vitality tests caries exposure diagnosis adults
  root canal perforation diagnosis detection clinical presentation
  regenerative endodontics
```

By month:

```
  2026-04     69 topics,  18 degraded = 26.1%
  2026-05      4 topics,   1 degraded = 25.0%
  2026-07     16 topics,   4 degraded = 25.0%
  2026-08  1,316 topics,  59 degraded =  4.5%
  2026-09    385 topics,  26 degraded =  6.8%
```

Per run: **53 of 155 runs (34.2%) contained at least one degraded topic.**

### The number that actually decides A13b

A1's coverage condition reads **only the primary term** —
`generate_search_terms`'s output, which `fetch_papers` uses for the Cochrane
tier, so it is recoverable per run:

```
  runs with a recoverable primary term          149
  of those, DEGRADED (<2 AND-groups)              0   =  0.0%

  2026-04   6 runs,  0 degraded    2026-08   99 runs,  0 degraded
  2026-05   1 run,   0 degraded    2026-09   38 runs,  0 degraded
  2026-07   5 runs,  0 degraded
```

**Zero, in every month, across 149 runs.**

## A13b — what that means

The 6% is **entirely in the extra terms** from `generate_multi_search_terms` —
the "different angles". Those affect retrieval **breadth**, not routing: a
degraded extra term contributes fewer KNN hits and nothing else. The primary
term, the one that decides whether A1's condition can read the question at all,
has never degraded in production.

So, against A13b's own test — "if the rate is non-trivial, degradation is
itself the defect":

* **For the primary term the rate is 0.** A1's abstention path is a guard on a
  state that has not occurred, not a policy papering over a generator defect.
  It is still correct to have: `tests/test_end_to_end.py` reaches it with a
  stubbed Claude, so the code path is real, and without abstention that stub
  routed ten tests to live PubMed.
* **For the extra terms the rate is 6%**, and the trend is already downward —
  26% in April/May/July, 4.5–6.8% since August. It costs breadth, not
  correctness, and it is not what A13 was raised about.

**Recommendation: no generator change.** The measurement does not support one,
and standing rule §1.1 says not to fix a hypothesis. If the extra-term rate
matters on its own, that is a retrieval-breadth item and should be raised as
one, with hits-per-query as its metric.

**One caveat, stated plainly.** This measures live runs only — a library-routed
run leaves no audit row. Term generation happens *before* the routing decision
and is identical on both paths, so the sample is unbiased with respect to
route, but it is a sample of live runs and I cannot observe the other half
directly. The counter added below closes that gap going forward.

## A13c — degradation is now counted

Both paths wrote a WARNING to stdout and nothing else, so the only record of a
degraded run was a console line nobody keeps — and A1's abstention then takes
the **less cautious** route on that silent signal. Standing rule §1.5.

`_log_term_degradation` appends to `term_degradation.jsonl` and increments
`TERM_DEGRADE_COUNTS`, with the two kinds counted separately because they mean
different things:

| kind | fired by | consequence |
|---|---|---|
| `primary_fallback` | the primary query could not be parsed after a retry | **routing** — A1 abstains, library route taken unchecked |
| `thin_term_set` | fewer than `MIN_SEARCH_TERMS` terms after the retry | **breadth** — fewer KNN queries |

Each row carries the question, the reason, and the **produced output** — because
a count alone cannot answer A13a's "what does it look like", and it was
answering that which showed the 6% to be prose.

`tests/conftest.py` redirects the new log on the day it was written. The other
four audit logs in that fixture were each redirected only *after* a test run had
polluted the production record.

## Tests

7 new (`tests/test_term_degradation.py`). Suite 1,852 → **1,859**.
**6/6 mutants killed**, including both "only print again" restorations, the
collapse of the two kinds into one counter, and the removal of the conftest
redirect.

Standing rule 14 is honoured by `TestBothDegradationPathsAreWired`, which reads
the production functions and asserts the log call sits *before* the fallback is
taken — not a restatement of that ordering in the test.
