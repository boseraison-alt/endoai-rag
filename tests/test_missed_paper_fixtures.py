"""Regression fixtures built from real misses.

Every competitor comparison that surfaces a paper Curo missed contributes its
PMID here. Over a year this accumulates a suite built from actual failures
rather than invented ones, and it is the only mechanism in the project that
gets stronger each time it catches us out.

WHAT THESE ASSERT, AND WHY IT IS RETRIEVAL AND NOT CITATION
-----------------------------------------------------------
Each test asserts that the paper REACHES THE POOL. None asserts that the
answer cites it. Whether synthesis cites a paper it can see is a judgement
call and will differ run to run; whether retrieval can see it at all is a
guarantee, and it is the guarantee that was broken. A test that asserted
citation would be red for reasons that are nobody's defect and would be
switched off within a week.

ALL THREE FAIL TODAY, for three DIFFERENT reasons, and the fix differs with
the reason. They are `xfail(strict=True)`, never `skip`: a skip records
nothing and a red suite is a landmine, while a strict xfail states the defect,
keeps the suite green, and fails loudly the moment someone fixes the
underlying bug without noticing that they did.

    42388091  Sulaiman 2026    live path    no lane admits a bare Journal Article
    39117767  Komora 2024      library path cosine 0.5807 against a 0.60 floor
    42018467  EFCD-ESE-ORCA    live path    guideline pubtypes have no lane

HOANG 2026 IS DELIBERATELY EXCLUDED
-----------------------------------
The fourth paper from the same comparison — Hoang et al. 2026, a claimed SR/MA
of 23 RCTs on mature posterior irreversible pulpitis — is NOT a fixture here.
It could not be found on PubMed by author, topic or publication type. It
reached us relayed, unverified, from a competitor's reference list, and it has
no PMID and no DOI.

That is not a conclusion that it does not exist. It is a refusal to build on
an unverified record, and the reason is specific: the A2 guideline audit found
six hardcoded records naming documents that do not exist, and inventing a
fixture out of a competitor's citation would be the identical error committed
in the opposite direction. A fixture asserting that retrieval must surface a
paper nobody can produce would be permanently, unfalsifiably red.

If the PMID or DOI is supplied, add it here. Until then it stays out, and
`test_hoang_is_not_a_fixture` pins the exclusion so that a future session has
to read this paragraph before quietly promoting it.
"""

import json
from pathlib import Path

import pytest

import endo_ai as E

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "missed_papers"

SULAIMAN = "42388091"
KOMORA = "39117767"
EFCD = "42018467"

VPT_QUESTION = "vital pulp therapy in adult teeth"


def load(pmid: str) -> dict:
    path = FIXTURE_DIR / f"{pmid}.json"
    assert path.exists(), (
        f"missing fixture {path}. Regenerate with "
        f"`python scripts/fetch_missed_paper_fixtures.py`."
    )
    return json.loads(path.read_text(encoding="utf-8"))


def admitting_lanes(pmid: str) -> list:
    """Which of the filters production ACTUALLY issues admit this paper.

    The lane list comes from `endo_ai.live_path_filters()` — production's own,
    not a copy — so adding a lane changes what this reads. Whether a given
    lane admits the paper is read from the fixture's measured admission map,
    because PubMed is the only authority on that: `review[pt]` explodes down
    the publication-type tree and admits `Practice Guideline`, so an offline
    matcher over the paper's own publication types gets EFCD wrong. The map
    was measured against PubMed by `scripts/fetch_missed_paper_fixtures.py`.

    A lane with no measured entry is a hard error. It must not default to
    "admits" (which would silently turn these xfails green on a lane nobody
    checked) and it must not default to "does not admit" (which would let a
    real fix go unnoticed). Re-run the script instead.
    """
    rec = load(pmid)
    amap = rec.get("admission_map", {})
    out = []
    for lane, filt in sorted(E.live_path_filters().items()):
        entry = amap.get(lane)
        assert entry is not None, (
            f"lane {lane!r} has no measured admission entry for PMID {pmid}. "
            f"A lane was added or renamed since the fixture was captured; "
            f"re-run `python scripts/fetch_missed_paper_fixtures.py` rather "
            f"than guessing whether PubMed admits it."
        )
        assert entry["filter"] == filt, (
            f"lane {lane!r} filter string changed since the fixture was "
            f"captured.\n  measured: {entry['filter']}\n  current:  {filt}\n"
            f"Re-run `python scripts/fetch_missed_paper_fixtures.py`."
        )
        if entry["admits"]:
            out.append(lane)
    return out


def untyped_lane_reaches(pmid: str) -> bool:
    """Does the untyped-recent lane (item 4) reach this paper?

    Returns False while the lane does not exist. The lane ANDs no publication
    type at all, so a paper is reachable through it purely on being recent and
    carrying nothing but `Journal Article`; there is no filter string to look
    up in the admission map.
    """
    fn = getattr(E, "untyped_recent_admits", None)
    if fn is None:
        return False
    return bool(fn(load(pmid)))


# ── the fixtures themselves ──────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="Sulaiman 42388091 is unreachable by the live path: its only PubMed "
           "publication type is `Journal Article`, and no tier lane admits a "
           "bare Journal Article. Published 2026-07-02, MEDLINE has not yet "
           "assigned it a study-design type. Every generated query ANDs a tier "
           "filter, so the paper is structurally invisible however good the "
           "topic terms are — and its title carries five of the topic's own "
           "terms. This is not a VPT defect; it is a rolling blind spot over "
           "the newest literature on every topic.",
)
def test_sulaiman_reachable_by_live_path():
    """A 2026 partial-pulpotomy trial must reach the pool for a VPT question."""
    rec = load(SULAIMAN)
    assert rec["publication_types"] == ["Journal Article"], (
        "fixture drift: this test exists because the paper is UNTYPED. If "
        "MEDLINE has since typed it, the paper is no longer the example and "
        "the fixture must be replaced with another untyped one, not deleted."
    )
    lanes = admitting_lanes(SULAIMAN)
    assert lanes or untyped_lane_reaches(SULAIMAN), (
        f"PMID {SULAIMAN} is admitted by no lane the live path issues "
        f"({sorted(E.live_path_filters())}) and no untyped-recent lane exists. "
        f"Its publication types are {rec['publication_types']}."
    )


@pytest.mark.xfail(
    strict=True,
    reason="Komora 39117767 is IN the library at level1/74.8 and the library "
           "path still does not deliver it for this question: its cosine to "
           "'vital pulp therapy in adult teeth' is 0.5807 against an "
           "evidence_floor of 0.60 — cut by 0.0193. It sits at rank ~325 of "
           "3,162, far below min_evidence_papers=40, so the thin-pool rescue "
           "cannot reach it either. This xfail is a deliberate RECORD, not a "
           "task: the floor is on the do-not-change list and one paper is not "
           "a basis for moving it. What it records is that A42 measured the "
           "floor as free on CITATION COUNTS, which is a different question "
           "from whether a specific on-point paper was lost.",
)
def test_komora_reaches_pool_from_library_path():
    """A network meta-analysis of 21 RCTs on capping materials, on a
    materials question, must survive the evidence floor."""
    import app as A

    pool = [
        {"pmid": KOMORA, "similarity": 0.5807, "title": "Komora 2024"},
    ] + [
        # The 324 library rows measured as more similar than Komora for this
        # question. Their exact identity does not matter to the floor; their
        # count and their being above it does, because that is what decides
        # whether the min_evidence_papers rescue can reach down this far.
        {"pmid": f"filler{i}", "similarity": 0.62 + (i % 50) / 1000.0}
        for i in range(324)
    ]
    kept = A.apply_evidence_floor(pool)
    assert any(str(p["pmid"]) == KOMORA for p in kept), (
        f"PMID {KOMORA} at cosine 0.5807 was dropped by evidence_floor "
        f"{A.RELEVANCE_GATE['evidence_floor']}; {len(kept)} papers kept."
    )


@pytest.mark.xfail(
    strict=True,
    reason="EFCD-ESE-ORCA S3 42018467 — the current European guideline on the "
           "exact question — is reachable only by accident. Its publication "
           "types are `Journal Article` and `Practice Guideline`; "
           "`practice guideline[pt]`, `guideline[pt]` and `consensus "
           "development conference[pt]` appear in no lane. It is admitted "
           "ONLY by level5, because `review[pt]` explodes down the "
           "publication-type tree — and there it ranked 521 of 608 reviews, "
           "nowhere near the top 50 production takes. level_key='guideline' "
           "already exists as a tier; what is missing is a query filter that "
           "can reach one.",
)
def test_efcd_guideline_reachable_by_a_guideline_lane():
    """A current S3-level clinical practice guideline must be reachable by a
    lane that selects for guidelines, not by accident through the review
    bucket at rank 521."""
    rec = load(EFCD)
    assert "Practice Guideline" in rec["publication_types"]
    lanes = admitting_lanes(EFCD)
    guideline_lanes = [l for l in lanes if l not in
                       ("level5", "cochrane", "level1", "level2", "level3a",
                        "level3b", "level4", "observational")]
    assert guideline_lanes, (
        f"PMID {EFCD} is admitted only by {lanes}. Reaching a clinical "
        f"practice guideline through the review/editorial/comment/letter "
        f"bucket is an accident of PubMed's publication-type tree, not a "
        f"retrieval path: it ranked 521 of 608 there."
    )


# ── guards on the fixtures themselves ────────────────────

def test_hoang_is_not_a_fixture():
    """Hoang 2026 stays out until a PMID or DOI is supplied.

    Pinned rather than left implicit because the pressure to add it is real —
    it is the paper the competitor comparison leaned on hardest. See this
    module's docstring for why an unverified record must not become a fixture.
    """
    present = sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
    assert present == sorted([SULAIMAN, KOMORA, EFCD]), (
        f"unexpected fixture set {present}. If a paper was added, confirm it "
        f"was verified on PubMed first — Hoang 2026 was relayed unverified "
        f"from a competitor's reference list and has no PMID or DOI."
    )
    for pmid in present:
        rec = load(pmid)
        assert rec["pmid"] == pmid
        assert rec["title"], f"{pmid} fixture has no title"
        assert rec["publication_types"], f"{pmid} fixture has no publication types"


def test_admission_map_covers_every_live_lane():
    """The map must answer for every lane production issues.

    This is the guard that stops the three xfails above from turning green for
    the wrong reason. If a lane is added and the fixture is not refreshed,
    `admitting_lanes` raises — and this test says so in one place with the
    remedy, rather than three confusing xpasses.
    """
    lanes = set(E.live_path_filters())
    for pmid in (SULAIMAN, KOMORA, EFCD):
        measured = set(load(pmid).get("admission_map", {}))
        missing = lanes - measured
        assert not missing, (
            f"PMID {pmid} has no measured admission entry for {sorted(missing)}. "
            f"Re-run `python scripts/fetch_missed_paper_fixtures.py`."
        )
