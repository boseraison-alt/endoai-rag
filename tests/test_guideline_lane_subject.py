"""Item B (2026-09-06) — the guideline lane must query the SUBJECT.

THE REGRESSION THIS PINS. `guideline_topic` picked the AND-group with the
highest share of `_COVERAGE_GENERIC`, tie-broken by group length, and called
the winner "the subject". `_COVERAGE_GENERIC` encodes "vocabulary with no
discriminating power" — it was built for the coverage gate — and it holds
`outcome`, `efficacy`, `success`, `treatment`, `management`, `tooth` and
`dental` next to the real domain vocabulary. Selecting FOR it selected the
OUTCOME group on about a fifth of the questions, and the length tiebreak
selected a tooth identifier on another.

With the topic that broad, `ENDO_DOMAIN_FILTER` was the only discriminator
left, and it is a floor: one matching term admits a document. Measured over 32
questions on 2026-09-06, the lane admitted a feline veterinary dental guideline
into 13 pools and a paediatric brain-tumour radiotherapy guideline into 11.

EVERY FIXTURE HERE IS A REAL GENERATED TERM STRING, captured from
`eval/logs/night8_terms.json` — the actual output of `generate_search_terms`
on the eval questions, not a hand-written query. Invented fixtures would have
let the original bug pass: the failure depended on the generator's real habit
of writing an outcome group last and longest.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import endo_ai as E


def _terms(topic):
    return [t.strip() for t in re.split(r"\s+OR\s+|\)\s+AND\s+\(", topic)
            if t.strip()]


# ── REAL GENERATED QUERIES, captured 2026-09-06 ──────────────────────────
# (id, generated query, the concept the subject group must name)
REAL = [
    ("probe-avulsion-40min",
     "(avuls* OR \"tooth avulsion\" OR replant* OR \"tooth replantation\" OR "
     "reimplant*) AND (\"closed apex\" OR \"mature tooth\" OR \"complete root "
     "formation\") AND (prognosis OR outcome* OR healing OR \"root resorption\" "
     "OR survival OR success*)",
     "avuls"),
    ("regenerative-immature",
     "(\"regenerative endodontic*\" OR revitali* OR \"vital pulp therap*\" OR "
     "\"pulp regeneration\" OR REP OR RET) AND (\"immature tooth\" OR "
     "\"immature teeth\" OR \"open apex\" OR \"blunderbuss apex\" OR "
     "apexogenesis OR apexification) AND (success OR survival OR outcome* OR "
     "efficacy OR healing OR \"treatment outcome\")",
     "immature"),
    ("retreatment-vs-microsurgery",
     "(\"nonsurgical retreatment\" OR \"conventional retreatment\" OR "
     "\"orthograde retreatment\") AND (\"apical microsurgery\" OR "
     "\"endodontic surgery\" OR \"periapical surgery\" OR \"surgical "
     "retreatment\") AND (\"persistent apical periodontitis\" OR \"refractory "
     "apical periodontitis\" OR \"symptomatic apical periodontitis\" OR "
     "\"treatment outcome\" OR \"success rate\" OR prognosis)",
     "retreatment"),
    ("dens-invaginatus",
     "(\"dens invaginatus\" OR \"dens in dente\" OR \"invaginated "
     "odontodystrophy\" OR \"gestant odontodystrophy\") AND (\"type III\" OR "
     "\"class III\" OR \"Oehlers III\") AND (manag* OR treat* OR therap* OR "
     "surgical OR orthodontic* OR restor*)",
     "dens invaginatus"),
    ("mta-vs-biodentine-pulpotomy",
     "(MTA OR \"mineral trioxide aggregate\" OR Biodentine OR \"calcium "
     "silicate\") AND (pulpotomy OR \"pulp amputation\") AND (\"mature "
     "permanent teeth\" OR \"permanent teeth\" OR \"adult teeth\")",
     "pulpotomy"),
]


class TestTheSubjectGroupIsChosen:

    @pytest.mark.parametrize("cid,query,must_name", REAL,
                             ids=[r[0] for r in REAL])
    def test_the_chosen_group_names_the_subject(self, cid, query, must_name):
        chosen = E.guideline_topic(query)
        assert must_name.lower() in chosen.lower(), (
            "%s: the lane chose %r, which does not name the subject %r"
            % (cid, chosen, must_name))

    @pytest.mark.parametrize("cid,query,_m", REAL, ids=[r[0] for r in REAL])
    def test_the_chosen_group_contains_a_domain_noun(self, cid, query, _m):
        chosen = E.guideline_topic(query)
        assert E._domain_noun_hits(_terms(chosen)) > 0, (
            "%s: the lane chose %r, which contains no domain noun at all"
            % (cid, chosen))

    def test_the_outcome_group_is_never_chosen(self):
        """The specific shape of the regression: an outcome group that is both
        the longest and the most `_COVERAGE_GENERIC`-dense wins under the old
        rule and must lose under the new one."""
        q = ('(avuls* OR "tooth avulsion") AND '
             '(prognosis OR outcome* OR healing OR survival OR success* OR '
             'efficacy OR "treatment outcome")')
        chosen = E.guideline_topic(q)
        assert "avuls" in chosen.lower()
        assert "prognosis" not in chosen.lower(), (
            "the lane chose the outcome group: %r" % chosen)

    def test_a_tooth_identifier_is_never_chosen(self):
        """The length-tiebreak failure: `tooth #20 OR maxillary right first
        molar ...` is the longest group and names no concept at all."""
        q = ('("dens evaginatus" OR "talon cusp") AND '
             '("tooth #20" OR "maxillary right first molar" OR "mandibular '
             'second premolar" OR "tooth 20" OR "#20")')
        chosen = E.guideline_topic(q)
        assert "dens evaginatus" in chosen.lower(), (
            "the lane chose the tooth identifier: %r" % chosen)


class TestTheVocabularySplit:

    def test_domain_nouns_and_qualifiers_are_disjoint(self):
        overlap = E.DOMAIN_NOUNS & E.GENERIC_QUALIFIERS
        assert not overlap, (
            "a term cannot be both the subject and a qualifier: %s"
            % sorted(overlap))

    def test_the_research_vocabulary_is_not_a_subject(self):
        """The words that made the old rule pick the outcome group. If any of
        these ever counts as a domain noun, the regression is back."""
        for w in ("outcome", "outcomes", "efficacy", "success", "treatment",
                  "management", "tooth", "teeth", "dental", "prognosis",
                  "survival", "healing", "clinical"):
            assert E._domain_noun_hits([w]) == 0, (
                "%r is being counted as an endodontic subject" % w)

    def test_the_real_domain_vocabulary_is_a_subject(self):
        for w in ("pulpitis", "periapical", "root canal", "avulsion",
                  "luxation", "crown fracture", "pulpotomy", "retreatment",
                  "endodontic*", "dens invaginatus", "immature teeth"):
            assert E._domain_noun_hits([w]) > 0, (
                "%r is not being counted as an endodontic subject" % w)

    def test_brand_and_material_names_are_not_subjects(self):
        """Deliberately excluded, and pinned so nobody adds them casually:
        a guideline is indexed by the condition or procedure, not the product.
        Including them selected the materials group over `(pulpotomy OR pulp
        amputation)` on the MTA/Biodentine question."""
        for w in ("mta", "biodentine", "bioceramic", "ah plus", "gutta percha",
                  "totalfill"):
            assert E._domain_noun_hits([w]) == 0, (
                "%r is being counted as an endodontic subject" % w)


class TestTheNoSubjectFallback:

    def test_no_domain_noun_anywhere_ands_two_groups(self):
        """`case-opening-sparse` and `pregnancy` really have no endodontic
        subject in any group. The lane must narrow, not guess: a conjunction
        is tighter than either half, which is the safe direction."""
        q = ("(tooth OR teeth OR dental OR molar) AND "
             "(pain OR ache OR discomfort OR sensitivity) AND "
             "(diagnosis OR etiology OR cause*)")
        out = E.guideline_topic(q)
        assert " AND " in out, (
            "expected a conjunction when no group names a subject, got %r"
            % out)

    def test_the_questions_with_no_subject_are_logged_not_silent(self):
        E.GUIDELINE_TOPIC_NO_SUBJECT.clear()
        q = ("(tooth OR teeth OR dental) AND (pain OR ache) AND "
             "(diagnosis OR etiology)")
        E.guideline_topic(q)
        assert q in E.GUIDELINE_TOPIC_NO_SUBJECT, (
            "a question with no endodontic subject was handled silently")


class TestTheSpeciesGuard:

    def test_the_guideline_lane_carries_an_animal_exclusion(self):
        assert "animals[mh]" in E.GUIDELINE_SPECIES_GUARD
        assert "humans[mh]" in E.GUIDELINE_SPECIES_GUARD

    def test_the_guard_is_the_floor_preserving_form(self):
        """`NOT (animals[mh] NOT humans[mh])` drops animal-only records and
        leaves unindexed ones alone. A bare `AND humans[mh]` would also drop
        every guideline NLM has not yet indexed — 6-18 months of them — which
        is the recall damage ENDO_DOMAIN_FILTER's hybrid shape exists to
        avoid."""
        g = E.GUIDELINE_SPECIES_GUARD
        assert g.strip().startswith("NOT"), g
        assert "AND humans[mh]" not in g, (
            "the guard requires human indexing rather than excluding "
            "animal-only records: %r" % g)

    def test_only_the_guideline_lane_gets_it(self, monkeypatch):
        """Confinement, asserted at the unit level as well as end to end."""
        seen = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"esearchresult": {"idlist": [], "count": "0"}}

        def fake_get(url, params=None, **kw):
            seen[params.get("term", "")] = True
            return _Resp()

        monkeypatch.setattr(E, "ncbi_get", fake_get)
        for lane in ("level1", "level2", "level5", "observational"):
            seen.clear()
            E.fetch_papers("(pulpitis) AND (adult)", "review[pt]", lane, lane,
                           max_results=1)
            assert not any("animals[mh]" in t for t in seen), (
                "the species guard leaked into the %s lane" % lane)
        seen.clear()
        E.fetch_papers("(pulpitis) AND (adult)", "guideline[pt]", "guideline",
                       "guideline", max_results=1)
        assert any("animals[mh]" in t for t in seen), (
            "the guideline lane did not carry the species guard")
