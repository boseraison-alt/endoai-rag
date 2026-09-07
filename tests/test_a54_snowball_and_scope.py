"""A54 — snowballing from the nominated review, and scope synonyms.

THE MISS. On "MTA versus bioceramic as retrograde filling after apicoectomy"
the pool held 66 papers, none of the head-to-head trials, and 55% of it was
off topic — MTA in apexification, pulpotomy, revascularisation, obturation.
Only one of three applicable guidelines appeared.

WHAT THE DIAGNOSIS ESTABLISHED, and it is not what the item assumed:

  * the question routed to the LIBRARY, so no lane query ran at all
  * none of the eight fixtures is in the library
  * the MATERIAL group matches every missed fixture; the SURGERY group is the
    sole point of failure, so expanding material nomenclature would have
    recovered nothing

Fixtures are real accessions, verified by title search before being pinned.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E

Q_SURGERY = "MTA versus bioceramic as retrograde filling after apicoectomy"
Q_SURGERY_UK = "outcome of apicectomy with a retrograde seal"
Q_PULPOTOMY = "MTA versus Biodentine for pulpotomy in mature permanent teeth"

# Verified 2026-09-07 by title search: journal, year and first author all match.
F1 = "31078325"   # Safi C, J Endod 2019
F2 = "27986096"   # Zhou W, J Endod 2017
COCHRANE_RETROFILL = "34647617"   # Materials for retrograde filling


class TestScopeSynonyms:

    def test_the_three_apical_surgery_guidelines_are_all_admitted(self):
        """Three jurisdictions cover this subject and only ESE-S3-2023
        appeared: ESE-S3-2023 (EU), AAE-TREATMENTSTANDARDS-2018 (US) and
        FDSRCS-PERIRADICULAR-2020 (UK). The UK one is not its jurisdiction's
        flagship, so the flagship rule alone could never reach it."""
        got = set(E.scope_matched_guidelines_for(Q_SURGERY))
        for gid in ("ESE-S3-2023", "AAE-TREATMENTSTANDARDS-2018",
                    "FDSRCS-PERIRADICULAR-2020"):
            assert gid in got, "%s not admitted for %r (got %s)" % (
                gid, Q_SURGERY, sorted(got))

    def test_a_british_spelling_hits_an_american_scope(self):
        """The whole point of the synonym map. `apicectomy` and `apicoectomy`
        are one subject; a word-bounded literal match cannot know that."""
        got = set(E.scope_matched_guidelines_for(Q_SURGERY_UK))
        assert "FDSRCS-PERIRADICULAR-2020" in got, sorted(got)
        assert "ESE-S3-2023" in got, sorted(got)

    def test_a_pulpotomy_question_does_not_admit_the_surgery_guideline(self):
        """THE NEGATIVE PIN. Synonyms widen spelling, never subject. If
        FDSRCS — a guideline about periradicular SURGERY — is admitted to a
        pulpotomy question, the map has become a way of admitting everything.
        """
        got = set(E.scope_matched_guidelines_for(Q_PULPOTOMY))
        assert "FDSRCS-PERIRADICULAR-2020" not in got, sorted(got)

    def test_the_uk_guideline_is_actually_ADMITTED_not_merely_matched(self):
        """BEHAVIOURAL. The test above checks the matcher; this drives
        `admit_scoped_guidelines`, which is what production calls. A mutation
        reverting admission to flagships only passed every matcher test —
        FDSRCS is not its jurisdiction's flagship, so only the admission path
        can prove it arrives."""
        ev = {"guideline": {"ids": [], "scored": [], "text": "",
                            "source": "rag"}}
        out = E.admit_scoped_guidelines(ev, Q_SURGERY)
        gids = [p.get("guideline_id") for p in out["guideline"]["scored"]]
        assert "FDSRCS-PERIRADICULAR-2020" in gids, gids
        assert "ESE-S3-2023" in gids, gids

    def test_the_synonym_groups_are_disjoint(self):
        """A term in two groups would silently join two subjects into one."""
        seen = {}
        for i, group in enumerate(E.SCOPE_SYNONYMS):
            for t in group:
                assert t not in seen, (
                    "%r is in synonym group %d and %d" % (t, seen[t], i))
                seen[t] = i

    def test_synonyms_expand_a_scope_and_never_shrink_it(self):
        scope = ["apicoectomy"]
        out = E._scope_terms_with_synonyms(scope)
        assert "apicoectomy" in out
        assert "apicectomy" in out and "root-end filling" in out
        assert E._scope_terms_with_synonyms([]) == set()

    def test_an_unknown_scope_term_survives_untouched(self):
        out = E._scope_terms_with_synonyms(["mronj"])
        assert out == {"mronj"}


class TestSnowballing:

    def test_it_reads_the_review_prisma_nominated_and_no_other(self):
        """MEASURED AND REJECTED FIRST: reading the top N reviews by score
        recovered no fixture reliably (which reviews land in the pool varies
        run to run) and pushed the off-topic share from 55% to 67% — a review
        about apexification pulls in apexification trials. Reusing the
        relevance nomination adds no new judgement and does not degrade
        precision."""
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "endo_ai.py"), encoding="utf-8").read()
        i = src.index("def snowball_from_reviews(")
        j = src.index("\ndef ", i + 10)
        body = src[i:j]
        assert '_prisma' in body and 'sr_pmid' in body, (
            "snowballing no longer reuses the PRISMA relevance nomination")

    def test_no_prisma_nomination_means_no_snowball(self):
        ev = {"level1": {"scored": [{"pmid": "1", "score": 80.0}],
                         "ids": ["1"], "text": ""}}
        before = len(ev["level1"]["scored"])
        out = E.snowball_from_reviews(dict(ev), "a question")
        assert len(out["level1"]["scored"]) == before

    def test_an_empty_evidence_base_is_returned_unchanged(self):
        assert E.snowball_from_reviews({}, "q") == {}
        assert E.snowball_from_reviews(None, "q") is None

    def test_the_cochrane_review_really_does_carry_the_fixtures(self):
        """Rule 34 — the mechanism's INPUT, checked. If this reference list
        were empty the snowball tests above would pass over nothing and prove
        nothing about recovery.

        This is also the measured LIMIT of the mechanism: the second review in
        this question's pool, 40637350, publishes no reference list at all, so
        snowballing can never reach anything through it."""
        refs = E.pubmed_reference_pmids(COCHRANE_RETROFILL)
        if not refs:
            pytest.skip("PubMed reference linkage unavailable")
        assert F1 in refs, "%s is not in %s's reference list" % (
            F1, COCHRANE_RETROFILL)
        assert F2 in refs

    def _stub(self, monkeypatch, pubtypes, ref="222"):
        class _R:
            status_code = 200

            def json(self):
                return {"esearchresult": {"idlist": [ref], "count": "1"}}

        monkeypatch.setattr(E, "pubmed_reference_pmids",
                            lambda *a, **k: frozenset({ref}))
        monkeypatch.setattr(E, "ncbi_get", lambda *a, **k: _R())
        monkeypatch.setattr(E, "_fetch_pubtypes_and_abstracts",
                            lambda ids, **k: {ref: {
                                "title": "A root-end filling study",
                                "abstract": "A real abstract, long enough to "
                                            "clear the content check applied "
                                            "before anything is admitted.",
                                "journal": "J Endod", "year": "2019",
                                "authors": "Safi C",
                                "publication_types": list(pubtypes)}})
        return {"level1": {"scored": [{"pmid": "111", "score": 80.0}],
                           "ids": ["111"], "text": ""},
                "_prisma": {"sr_pmid": "111"}}

    def test_a_reference_with_no_derivable_design_is_not_admitted(
            self, monkeypatch):
        """BEHAVIOURAL, and the source-shape version of this test did NOT
        catch its own mutation: defaulting an underivable reference onto
        `level5` left the asserted string in place and passed.

        Being cited by a review is a fact about the REVIEW, not about the
        paper's design. A reference whose publication types derive nothing is
        admitted at NO tier rather than defaulted onto one — the same rule the
        write-back guard follows."""
        ev = self._stub(monkeypatch, ["Journal Article"])
        out = E.snowball_from_reviews(ev, "q")
        everywhere = [str(p.get("pmid")) for _t, b in out.items()
                      if isinstance(b, dict)
                      for p in (b.get("scored") or [])]
        assert "222" not in everywhere, (
            "an untyped reference was admitted; its rung would be an "
            "assertion nobody made")

    def test_a_typed_reference_IS_admitted_at_its_own_rung(self, monkeypatch):
        """The control: the mechanism must actually work, or 'not admitted'
        above proves nothing (rule 4)."""
        ev = self._stub(monkeypatch,
                        ["Journal Article", "Randomized Controlled Trial"],
                        ref="333")
        out = E.snowball_from_reviews(ev, "q")
        rows = [p for p in (out.get("level1") or {}).get("scored") or []
                if str(p.get("pmid")) == "333"]
        assert rows, "a properly typed reference was not admitted"
        assert rows[0]["level_key"] == "level1"
        assert rows[0]["admitted_as"] == "snowball"
        assert rows[0]["score"] > 0, "admitted at score 0 it would sort last"
        assert "333" in (out["level1"].get("text") or ""), (
            "the row never reached the text the model reads")


class TestTheFixturesAreRealAndVerified:

    def test_the_pinned_accessions_resolve_to_the_named_papers(self):
        """The Hoang 2026 rule, pinned. These two are the trials inside the
        Cochrane pooled estimate the answer itself cited."""
        recs = E._fetch_pubtypes_and_abstracts([F1, F2])
        if not recs:
            pytest.skip("PubMed unavailable")
        assert "Safi" in recs[F1]["authors"] or "Safi" in recs[F1]["title"], \
            recs[F1]["authors"]
        assert recs[F1]["year"] == "2019"
        assert "Zhou" in recs[F2]["authors"], recs[F2]["authors"]
        assert recs[F2]["year"] == "2017"
