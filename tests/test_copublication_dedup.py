"""Item E (2026-09-06) — one document, three PMIDs, one row.

The EFCD-ESE-ORCA S3 deep-caries guideline is co-published in three journals
and carries three PubMed accessions:

    42018467   Caries Res              <- the manifest primary
    42017497   Int Endod J
    42014635   Clin Oral Investig

Verified against PubMed on 2026-09-06: identical titles, all three typed
`Practice Guideline`. Two of them reached the SAME retrieval pool on
2026-09-06 and were presented to the model as two independent guidelines
saying the same thing — unanimity manufactured by counting one document twice.

Every dedup path in `endo_ai` works on PMIDs and therefore cannot see this.
The identity that survives co-publication is the MANIFEST ID.

The three accessions here are real and are the fixture, per the batch's
standing rule that fixtures come from real rows.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E

GID = "EFCD-ESE-ORCA-DEEPCARIES-2026"
PRIMARY = "42018467"
COPIES = ["42017497", "42014635"]


def _pool():
    """One guideline tier holding all three accessions, plus an unrelated row.

    The unrelated row is not decoration: a collapse that empties the tier, or
    that drops rows carrying no guideline_id, would pass a test containing only
    the three copies.
    """
    return {
        "guideline": {
            "ids": [PRIMARY] + COPIES + ["37772327"],
            "scored": [
                {"pmid": COPIES[0], "guideline_id": GID, "score": None,
                 "title": "Deep Caries Management: EFCD-ESE-ORCA S3-Level "
                          "Clinical Practice Guideline",
                 "journal": "Int Endod J"},
                {"pmid": PRIMARY, "guideline_id": GID, "score": None,
                 "title": "Deep Caries Management: EFCD-ESE-ORCA S3-Level "
                          "Clinical Practice Guideline",
                 "journal": "Caries Res"},
                {"pmid": COPIES[1], "guideline_id": GID, "score": None,
                 "title": "Deep caries management: EFCD-ESE-ORCA S3-level "
                          "clinical practice guideline",
                 "journal": "Clin Oral Investig"},
                {"pmid": "37772327", "guideline_id": "ESE-S3-2023",
                 "score": None, "title": "ESE S3 guideline",
                 "journal": "Int Endod J"},
            ],
        }
    }


class TestThreeAccessionsCollapseToOne:

    def test_only_one_copy_survives(self):
        ev = E.collapse_guideline_copies(_pool())
        pmids = [p["pmid"] for p in ev["guideline"]["scored"]]
        efcd = [p for p in pmids if p in [PRIMARY] + COPIES]
        assert len(efcd) == 1, (
            "expected one EFCD row, got %s — the pool still double-counts "
            "one document" % efcd)

    def test_the_survivor_is_the_manifest_primary(self):
        """WHICH copy survives is not arbitrary: it decides the journal and
        the DOI a clinician is sent to. The manifest primary wins even though
        it is not first in the pool — it is deliberately second in `_pool()`."""
        ev = E.collapse_guideline_copies(_pool())
        pmids = [p["pmid"] for p in ev["guideline"]["scored"]]
        assert PRIMARY in pmids, (
            "the manifest primary %s did not survive; kept %s"
            % (PRIMARY, [p for p in pmids if p in [PRIMARY] + COPIES]))

    def test_unrelated_rows_are_untouched(self):
        ev = E.collapse_guideline_copies(_pool())
        pmids = [p["pmid"] for p in ev["guideline"]["scored"]]
        assert "37772327" in pmids, "collapsed an unrelated guideline"

    def test_the_ids_list_is_collapsed_too(self):
        """`ids` and `scored` are read by different callers. Collapsing one
        and not the other leaves the double-count visible on whichever surface
        reads `ids`."""
        ev = E.collapse_guideline_copies(_pool())
        ids = [str(i) for i in ev["guideline"]["ids"]]
        efcd = [i for i in ids if i in [PRIMARY] + COPIES]
        assert len(efcd) == 1, "ids still carries %s" % efcd

    def test_rows_without_a_guideline_id_are_never_collapsed(self):
        """Papers carry no guideline_id. If a missing id were treated as a
        shared one, an entire tier would collapse to a single paper."""
        ev = {"level1": {"ids": ["1", "2", "3"],
                         "scored": [{"pmid": "1", "score": 80.0},
                                    {"pmid": "2", "score": 79.0},
                                    {"pmid": "3", "guideline_id": "",
                                     "score": 78.0}]}}
        out = E.collapse_guideline_copies(ev)
        assert len(out["level1"]["scored"]) == 3

    def test_a_single_copy_is_left_alone(self):
        ev = {"guideline": {"ids": [PRIMARY],
                            "scored": [{"pmid": PRIMARY, "guideline_id": GID,
                                        "score": None}]}}
        out = E.collapse_guideline_copies(ev)
        assert len(out["guideline"]["scored"]) == 1

    def test_copies_split_across_tiers_still_collapse(self):
        """Before tonight's ingest these rows sat at level1/level2, not at
        `guideline`. A collapse that only looked inside one tier would have
        missed exactly the case that motivated the item."""
        ev = {
            "level1": {"ids": [COPIES[0]],
                       "scored": [{"pmid": COPIES[0], "guideline_id": GID,
                                   "score": 54.8}]},
            "guideline": {"ids": [PRIMARY],
                          "scored": [{"pmid": PRIMARY, "guideline_id": GID,
                                      "score": None}]},
        }
        out = E.collapse_guideline_copies(ev)
        total = sum(len(b["scored"]) for b in out.values())
        assert total == 1, "copies in different tiers were not collapsed"


class TestTheManifestCarriesTheAlternates:

    def test_the_efcd_record_lists_both_co_publications(self):
        import json
        man = json.load(open("data/guidelines_seed.json", encoding="utf-8"))
        rec = next(g for g in man["guidelines"] if g["id"] == GID)
        alts = [str(a) for a in (rec.get("alt_pmid") or [])]
        for c in COPIES:
            assert c in alts, (
                "%s is not listed as an alt_pmid on %s, so nothing downstream "
                "can know it is the same document" % (c, GID))

    def test_the_primary_is_not_also_an_alternate(self):
        import json
        man = json.load(open("data/guidelines_seed.json", encoding="utf-8"))
        for g in man["guidelines"]:
            alts = [str(a) for a in (g.get("alt_pmid") or [])]
            assert str(g.get("pmid") or "") not in alts, (
                "%s lists its own primary accession as an alternate" % g["id"])
