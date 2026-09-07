"""Item C change 4 (2026-09-08) — scope-based guideline admission.

THE MEASUREMENT THIS PINS, and it shipped NOTHING. The batch pre-declared the
bar: 3/3 on both probes, median block <= 8, max <= 25, no superseded / withdrawn
/ draft admitted; ship the first of (a) similarity-above-floor, (b) scope match
with >= 2 shared DOMAIN_NOUNS terms, (c) the union, that meets it. None did, so
nothing was shipped and the table was reported.

WHAT THE TABLE SAYS, now that terms are deterministic and the rules could be
scored honestly for the first time:

  (a) cannot pass because the documents never reach the pool. For probe 2,
      IADT-FRACTURES-LUXATIONS-2020 sits at similarity 0.526 against a 0.55
      floor and the other two watched documents are not in the top 100 at all.
      For probe 3, none of the three is in the top 100.
  (b) cannot pass because in EACH probe one watched document shares NO domain
      noun with the question. AAE-TRAUMA-2026's manifest scope is
      [dental trauma, avulsion, luxation, root fracture] and probe 2 asks about
      a CROWN fracture — its own declared scope says it is not about this.
      ACP-ASYMPTOMATIC-EXTRACTION-2016 says "failing endodontic treatment"
      where probe 3 says "failed root canal retreatment" — a vocabulary gap.

THAT OVERTURNS A PREMISE OF MY OWN. The 2026-09-07 report concluded "no
admission rule can meet it — the documents do not reliably reach the candidate
set, because `generate_search_terms` is non-deterministic". Terms are now
deterministic (0/10 -> 10/10 reproducible) and the bar is still not met, so
non-determinism was not the reason, or not the only one.

These tests therefore pin the BEHAVIOUR of the scope machinery that exists —
which is real and shipped — rather than a rule that was not adopted.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import endo_ai as E  # noqa: E402

import measure_guideline_admission_rules as M  # noqa: E402

PROBE2 = ("Complicated crown fracture with pulp exposure in a mature premolar, "
          "6 hours old. What is the management?")
PROBE3 = ("Mature molar with a failed root canal retreatment. The patient asks "
          "for extraction and an implant. How should this be decided?")


class TestTheQuestionsDomainNouns:

    def test_a_trauma_question_names_its_subject(self):
        hits = M.domain_nouns_in(PROBE2)
        assert "crown fracture" in hits
        assert "pulp" in hits

    def test_a_retreatment_question_names_its_subject(self):
        hits = M.domain_nouns_in(PROBE3)
        assert "retreatment" in hits
        assert "root canal" in hits

    def test_matching_is_word_bounded(self):
        """`\\btreatment\\b` must not fire inside "retreatment" — the bug this
        repo already fixed once in `scope_matched_guidelines_for`."""
        hits = M.domain_nouns_in("Discuss retreatment outcomes")
        assert "retreatment" in hits
        assert "treatment" not in hits


class TestTheThresholdIsWhatItClaims:

    def test_two_shared_terms_admits(self):
        """IADT-FRACTURES-LUXATIONS-2020 declares both `crown fracture` and
        `pulp capping`, so probe 2 shares two terms with it."""
        assert "IADT-FRACTURES-LUXATIONS-2020" in M.rule_b(PROBE2, need=2)

    def test_one_shared_term_does_not(self):
        """ESE-TRAUMA-2021 shares only `pulp`. Under the batch's >= 2 rule it
        is not admitted — which is why the probe cannot reach 3/3."""
        assert "ESE-TRAUMA-2021" not in M.rule_b(PROBE2, need=2)
        assert "ESE-TRAUMA-2021" in M.rule_b(PROBE2, need=1)

    def test_the_threshold_is_actually_consulted(self):
        """MUTATION CHECK, by running the rule at both thresholds rather than
        reading it. If `need` were ignored these two sets would be equal."""
        assert M.rule_b(PROBE3, need=1) != M.rule_b(PROBE3, need=2), (
            "the shared-term threshold changes nothing — it is not being "
            "applied")

    def test_zero_shared_terms_is_never_admitted_at_any_threshold(self):
        """AAE-TRAUMA-2026 declares avulsion, luxation and root fracture — not
        crown fracture. No scope rule can admit it for probe 2, and this is
        why the done-when as written is unreachable: the WATCH list asks for a
        document whose own manifest says it is not about this question."""
        for need in (1, 2, 3):
            assert "AAE-TRAUMA-2026" not in M.rule_b(PROBE2, need=need)


class TestNothingRetiredIsEverAdmitted:
    """The one property that must hold whatever rule is eventually shipped."""

    def test_no_superseded_withdrawn_or_draft_survives(self):
        for q in (PROBE2, PROBE3):
            for need in (1, 2):
                admitted = M.citeable(M.rule_b(q, need=need))
                bad = M.bad_status(admitted)
                assert not bad, (
                    "a non-current guideline was admitted for %r: %s"
                    % (q[:40], sorted(bad)))

    def test_the_status_detector_can_fire(self):
        """Otherwise the assertion above is a claim about today's manifest.
        Feed it a set that DOES contain a superseded record."""
        man = M.manifest()
        superseded = [g for g, r in man.items()
                      if (r.get("status") or "").lower() in M.NOT_CURRENT]
        assert superseded, "the manifest has no non-current record to test with"
        assert M.bad_status(set(superseded[:1])), (
            "bad_status did not flag a known non-current record")

    def test_only_current_records_are_considered(self):
        """`rule_b` filters on status before matching, so a superseded record
        whose scope matches perfectly is still not admitted."""
        man = M.manifest()
        for q in (PROBE2, PROBE3):
            for gid in M.rule_b(q, need=1):
                assert (man.get(gid, {}).get("status") or "").lower() == "current"


class TestTheAdmittedSetIsCiteable:

    def test_every_admitted_id_resolves_to_a_live_row(self):
        """An admitted manifest id with no citeable row is a citation the
        finaliser will drop — the block would name a document the answer
        cannot then cite.

        Measured before being asserted: across the whole 31-question set the
        rule made 118 proposals and every one was citeable. The first version
        of this test was written as `assert citeable(p) == p or True`, which
        cannot fail; it is asserted properly here because the measurement says
        it holds.
        """
        for q in (PROBE2, PROBE3):
            proposed = M.rule_b(q, need=1)
            assert proposed, "no proposals — the test proves nothing (rule 34)"
            assert M.citeable(proposed) == proposed, (
                "admitted ids with no citeable row: %s"
                % sorted(proposed - M.citeable(proposed)))

    def test_citeable_drops_a_row_that_does_not_exist(self):
        assert M.citeable({"NO-SUCH-GUIDELINE-9999"}) == set()
