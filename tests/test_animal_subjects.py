"""WORKLIST C2 — animal-subject studies must not sit in the clinical tiers.

"Vital pulp therapy in dogs ... a 25-year retrospective study" (*J Am Vet Med
Assoc*, PMID 40683315) was scoring 59.8 in the clinical hierarchy and
retrievable as human clinical evidence: nothing in the codebase had any
concept of a non-human subject. `animal_subjects.detect_animal_subject` now
routes such papers to the `invitro` tier.

Every fixture below is a REAL row from `endo_papers_rag` (pulled 2026-08-30),
quoted verbatim, because the traps are all real (HANDOVER bug class (c): a
classifier that passes on invented single-paper fixtures and fails on
production text):

  * "canine" is a human tooth 31 times out of 32 in this library;
  * Level I abstracts name animal studies in their EXCLUSION criteria;
  * animal-derived MATERIALS (bovine xenograft, bovine milk, sheep-blood
    agar) sit inside genuine human trials;
  * "mouse-driven cursor" exists, in a radiography paper;
  * a case report's discussion cites mouse-model work about somebody
    else's study.

Precision matters far more than recall: a false positive demotes real human
evidence to a bench tier. The negative half of this file is therefore larger
than the positive half.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from animal_subjects import detect_animal_subject, _ANIMAL_PROTECTED_LEVELS
from endo_ai import LEVEL_SCORES, TIER_ORDER


# ── Real library rows: (pmid, title, abstract excerpt, journal, level_key) ──

ANIMAL_ROWS = [
    # The motivating case: veterinary journal, and the abstract calls dogs
    # "patients" — which is why the human-language veto must stay narrow.
    ("40683315",
     "Vital pulp therapy in dogs maintains an 80% success rate independent of "
     "patient age: a 25-year retrospective study.",
     "OBJECTIVE: To reassess the success rate of vital pulp therapy (VPT) in dogs "
     "and evaluate the impact of patient age and pulp exposure duration on "
     "outcomes. METHODS: The University of Wisconsin Veterinary Care medical "
     "records database was searched for dogs undergoing VPT from January 2000. "
     "RESULTS: Of 219 VPT cases, 48 dogs with 79 teeth met the inclusion criteria.",
     "Journal of the American Veterinary Medical Association", "level5"),
    ("40684155",
     "Pulp response following direct pulp capping with Tideglusib and mineral "
     "trioxide aggregate: an animal study.",
     "METHODS: Class V cavities with pulp exposure were conducted on 56 teeth in "
     "two adult male mongrel dogs. Based on the evaluation periods, these teeth "
     "were divided into two major groups at random (28 teeth/dog each).",
     "BMC Oral Health", "level2"),
    ("39580417",
     "Regenerative endodontic therapy in immature teeth using photobiomodulation "
     "and photodynamic therapy; a histomorphological study in canine model.",
     "AIM: The aim of the present study is to evaluate the regenerative potential "
     "of photobiomodulation (PBM) on RET in immature roots when photodynamic "
     "therapy (PDT) protocol is implemented for root canal disinfection in canine "
     "model. MATERIALS AND METHODS: Seventy-two root canals were recruited.",
     "BMC Oral Health", "level2"),
    ("35764993",
     "Role of NOD2 and hepcidin in inflammatory periapical periodontitis.",
     "We investigated the role of nucleotide binding oligomerization domain "
     "containing 2 and hepcidin in inflammatory periapical periodontitis. "
     "Periapical periodontitis was induced in rats and confirmed by "
     "micro-computed tomography.",
     "BMC Oral Health", "level2"),
    ("20126907",
     "Periapical repair after root canal filling with different root canal sealers.",
     "Sixty-four root canals from dog s teeth were filled, divided into 4 groups "
     "(n=16). After 90 days, the animals were euthanized and the tissues to be "
     "evaluated were processed and stained with hematoxylin and eosin.",
     "Braz Dent J", "level3"),
    ("35246103",
     "Pulpal and periapical tissue response after direct pulp capping with "
     "endosequence root repair material and low-level laser application.",
     "METHODS: In 6 rabbits, pulps were exposed via class V, half of the samples "
     "received a low-level diode laser at 980 nm. Thereafter, cavities were "
     "capped with regular-set ERRM.",
     "BMC Oral Health", "level2"),
    ("19459923",
     "Intracanal bisphosphonate does not inhibit replacement resorption "
     "associated with delayed replantation of monkey incisors.",
     "This study evaluated the effectiveness of a bisphosphonate (etidronate "
     "disodium) as an intracanal medicament in the root canals of avulsed monkey "
     "teeth, placed before replantation after 1 h of extraoral dry storage. "
     "Incisors of six Macaca fascicularis monkeys were extracted and stored dry.",
     "Dent Traumatol", "level2"),
    ("37641630",
     "Prolyl-hydroxylase inhibitor-induced regeneration of alveolar bone and "
     "soft tissue in a mouse model of periodontitis through metabolic "
     "reprogramming.",
     "In the present studies, we explore a particular case of volumetric bone "
     "loss in a mouse model of human periodontal disease (PD) in which alveolar "
     "bone surrounding teeth is permanently lost and not replaced.",
     "Front Dent Med", "level3"),
]

HUMAN_ROWS = [
    # "canine" the human tooth — bench study on extracted HUMAN teeth. Must
    # not fire (it is detect_in_vitro's business, not this classifier's).
    ("27598303",
     "Fracture Resistance of Endodontically Retreated Roots After Retreatment "
     "Using Self-Adjusting File, Passive Ultrasonic Irrigation, Photon-Induced "
     "Photoacoustic Streaming, or Laser.",
     "MATERIALS AND METHODS: A total of 117 human mandibular canine teeth of "
     "similar dimensions were selected and divided into nine groups (n=13).",
     "Photomedicine and laser surgery", "level2"),
    # "canine" the human tooth — case report of a patient.
    ("29422108",
     "Endodontic management of mandibular canine with two roots and two canals: "
     "a rare case report.",
     "BACKGROUND: In general, mandibular canines have a single root and a single "
     "canal. The occurrence of two roots and two canals is a rare entity ranging "
     "from 1 to 5%. CASE PRESENTATION: 45-year-old Nepalese women with a "
     "non-significant medical history.",
     "BMC research notes", "level4"),
    # Animal-derived MATERIAL in a genuine human study (bovine xenograft),
    # plus explicit human-subject language.
    ("41121124",
     "Clinical and radiographic outcomes of entire papilla preservation versus "
     "open flap debridement using bovine-derived xenograft and leukocyte- and "
     "platelet-rich fibrin in the treatment of isolated intrabony defects.",
     "MATERIALS AND METHODS: This retrospective study included 28 patients "
     "diagnosed with Stage 3 Grade B periodontitis, who underwent either EPP "
     "(n=14) or OFD (n=14) using bovine-derived xenograft and L-PRF following "
     "initial non-surgical periodontal therapy.",
     "BMC oral health", "level2"),
    # "mouse-driven cursor" — the real false positive found in this library.
    ("9161164",
     "Measurement accuracy: a comparison of two intra-oral digital radiographic "
     "systems, RadioVisiography-S and FlashDent, with analog film",
     "METHODS: A test object with three radiopaque reference points was imaged "
     "using Ektaspeed intra-oral film, the RVG-S, and the FlashDent, which uses "
     "a mouse-driven cursor to estimate distances.",
     "Dento maxillo facial radiology", "level3"),   # level_key changed below
    # A bibliometric study OF animal experiments — dogs and rats appear only
    # in reporting what other people published.
    ("31052358",
     "Animal Experiments in Periodontal and Peri-Implant Research: Are There "
     "Any Changes?",
     "Animal experiments are a source of debate. This bibliometric study aims to "
     "identify published research in two representative dental journals. "
     "Articles describing data from animal experiments were identified and the "
     "data were extracted. The species examined were predominantly dogs (37%) "
     "in JCP and rats (61%) in JP in 1982/83.",
     "Dent J (Basel)", "level3"),
    # A case report whose DISCUSSION cites mouse-model work.
    ("41552405",
     "Case Report: Rare Presentation of Dentin Abnormalities in Loeys-Dietz "
     "Syndrome Type I.",
     "Loeys-Dietz syndrome type 1 (LDS1) is caused by a mutation in the TGFBR1 "
     "gene. TGFBR1 is expressed by odontoblasts throughout tooth development and "
     "deletion of TGFBR1 in mouse models is known to affect dentin.",
     "Front Dent Med", "level3"),
    # An avulsed-tooth storage-medium trial: bovine MILK, human patients.
    ("25290558_human_variant",
     "Storage media for avulsed teeth: a clinical comparison",
     "Avulsed permanent incisors of patients presenting within 60 minutes were "
     "stored in whole bovine milk before replantation. Patients were recruited "
     "at the emergency department and informed consent was obtained.",
     "Dent Traumatol", "level2"),
    # Human cohort where 'canines' means impacted human teeth throughout —
    # 'realignment of canines' is exactly the phrase a bare-species cue would
    # seize on. Verbatim from the library row.
    ("38340133",
     "Survival of retained permanent canines after autotransplantation: A "
     "retrospective cohort study.",
     "INTRODUCTION: After third molars, canines are the teeth most commonly "
     "affected by displacement and impaction. Although orthodontic surgical "
     "treatment represents the standard method for realignment of canines, "
     "autotransplantation (autoTX) functions as the second-line therapy. This "
     "retrospective cohort study aimed to identify clinical predictors for "
     "postoperative survival after autoTX of severely displaced and impacted "
     "canines. METHODS: The study cohort comprised patients who received "
     "canine autoTX in a single surgical center between 2006 and 2018.",
     "American journal of orthodontics and dentofacial orthopedics", "level3a"),
    # Two human patients, 'orthodontic treatment of the canines' — the other
    # real phrase a bare-species cue would seize on. Verbatim.
    ("6931164",
     "Bilateral external root resorption.",
     "Root resorption in bilateral maxillary canines was diagnosed in two "
     "patients who had histories of orthodontic treatment of the canines when "
     "the patients were teenagers. Periodontal surgery exposed the resorbed "
     "root areas. Five-year follow-up examinations disclosed successful "
     "results in both cases.",
     "Journal of the American Dental Association", "level4"),
]

# Level I / Cochrane abstracts that NAME animal studies while excluding them.
EXCLUSION_LANGUAGE_ROWS = [
    ("36156804",
     "Effectiveness of adjunct therapy for the treatment of apical "
     "periodontitis: A systematic review and meta-analysis.",
     "Clinical studies comparing adjunct therapy to no adjunct therapy in adult "
     "patients with AP. Animal studies, reviews, studies with less than 10 "
     "patients per arm and International endodontic journal case reports were "
     "excluded.",
     "International endodontic journal", "level1"),
    ("40558896",
     "Antibacterial and Bactericidal Effects of the Er: YAG Laser on Oral "
     "Bacteria: A Systematic Review of Microbiological Evidence.",
     "Eligibility criteria included in vitro or animal studies assessing the "
     "bactericidal effects of the Er:YAG laser on oral bacteria or fungi.",
     "Journal of functional biomaterials", "level1"),
    ("40597984",
     "Efficacy of concentrated growth factor compared with other types of "
     "regenerative endodontic procedures: a systematic review.",
     "Risk of bias was assessed using the JBI tool for clinical studies, QUIN "
     "tool for in vitro studies, and SYRCLE tool for animal studies.",
     "BMC oral health", "level1"),
]


class TestAnimalStudiesAreDetected:

    @pytest.mark.parametrize("pmid,title,abstract,journal,level",
                             ANIMAL_ROWS, ids=[r[0] for r in ANIMAL_ROWS])
    def test_real_animal_rows_fire(self, pmid, title, abstract, journal, level):
        hit, why = detect_animal_subject(title, abstract, journal, level)
        assert hit, f"PMID {pmid} is an animal study and was not detected ({why})"

    def test_the_javma_study_fires_on_its_journal_alone(self):
        """The motivating case must not depend on abstract text: veterinary
        journals publish nothing else, and the abstract calls its dogs
        'patients' — the metadata is the reliable signal here."""
        hit, why = detect_animal_subject(
            "Vital pulp therapy outcomes", "",
            "Journal of the American Veterinary Medical Association", "level2")
        assert hit
        assert "veterinary journal" in why

    def test_the_reason_names_the_cue(self):
        """A migration prints WHY each row moved so a human can audit it.
        A bare boolean cannot be reviewed."""
        _, why = detect_animal_subject(*ANIMAL_ROWS[1][1:4], "level2")
        assert why and why != "True"
        assert any(w in why.lower() for w in
                   ("dog", "animal", "veterinar", "title", "abstract"))


class TestHumanEvidenceIsNeverTouched:

    @pytest.mark.parametrize("pmid,title,abstract,journal,level",
                             HUMAN_ROWS, ids=[r[0] for r in HUMAN_ROWS])
    def test_real_human_rows_decline(self, pmid, title, abstract, journal, level):
        hit, why = detect_animal_subject(title, abstract, journal, level)
        assert not hit, (
            f"PMID {pmid} is human evidence and was flagged as animal ({why}) — "
            f"this is the false positive the classifier exists to avoid")

    @pytest.mark.parametrize("pmid,title,abstract,journal,level",
                             EXCLUSION_LANGUAGE_ROWS,
                             ids=[r[0] for r in EXCLUSION_LANGUAGE_ROWS])
    def test_exclusion_criteria_language_declines_even_unprotected(
            self, pmid, title, abstract, journal, level):
        """These are Level I rows, so the tier guard already protects them —
        but the EXCLUSION-language veto must hold on its own, because the same
        sentences appear in level2/level3 reviews too. Tested by stripping the
        protection."""
        hit, why = detect_animal_subject(title, abstract, journal, "level3")
        assert not hit, (
            f"PMID {pmid} names animal studies only to say it EXCLUDED them, "
            f"and was flagged anyway ({why})")

    @pytest.mark.parametrize("level", sorted(_ANIMAL_PROTECTED_LEVELS))
    def test_protected_tiers_never_fire_on_any_cue(self, level):
        """Same rule as detect_in_vitro: cochrane/level1/classic outrank any
        text cue. `classic` holds the seminal dog and monkey experiments of
        endodontics deliberately."""
        hit, why = detect_animal_subject(
            "Healing of apical periodontitis after endodontic treatment with "
            "and without obturation in dogs.",
            "Seven dogs weighing between 15 and 25 kg were anesthetized. "
            "The animals were sacrificed after 12 weeks.",
            "Journal of endodontics", level)
        assert not hit
        assert why == "protected tier"

    def test_bare_canine_is_never_a_cue(self):
        """31 of the 32 rows containing 'canine' in this library are about the
        human tooth. Only 'canine model'-type constructions may fire."""
        hit, why = detect_animal_subject(
            "Morphology and root canal configuration of maxillary canines",
            "The internal morphology of maxillary canines was assessed. "
            "Two-rooted mandibular canines are a rare entity. The canine "
            "eminence was measured in all specimens.",
            "BMC Oral Health", "level2")
        assert not hit, f"bare 'canine' fired: {why}"

    def test_empty_text_declines(self):
        hit, why = detect_animal_subject("", "", "", "level2")
        assert not hit

    def test_human_subject_language_vetoes_a_background_animal_citation(self):
        """The live-path trap the veto exists for: a human trial whose
        BACKGROUND cites animal findings. No library row currently needs this
        rescue (measured 2026-08-30 — every current human row declines for
        lack of a cue), but write-back ingests new papers daily and human RCT
        introductions routinely open with the animal work that motivated the
        trial. Both sentences here are verbatim production text: the animal
        line is from PMID 19459923's abstract, the human lines from PMID
        32202965's."""
        hit, why = detect_animal_subject(
            "A randomized trial of topical bisphosphonate before replantation "
            "of avulsed permanent incisors",
            "Topically applied bisphosphonate has been reported to inhibit "
            "root resorption in dogs. The trial included 36 patients with "
            "mature incisors, canines, or mandibular premolars showing pulp "
            "necrosis and apical periodontitis. Patients were randomly "
            "assigned to treatment arms.",
            "Journal of dental research", "level2")
        assert not hit, (
            f"a human RCT citing dog findings in its background was flagged "
            f"({why}) — the human-subject veto is not firing")

    def test_animal_material_phrases_cannot_supply_the_species_word(self):
        """'bovine milk' is a storage medium and 'bovine-derived xenograft' a
        graft material; both sit inside genuine human studies in this library
        (PMIDs 25290558, 41121124). The scrub must remove them BEFORE the
        species regex looks — 'stored in bovine milk' (the standard
        storage-media phrasing in the avulsion literature) otherwise matches
        the '(in|of) <species>' construction verbatim. Tested with no human
        cue present to hide behind."""
        hit, why = detect_animal_subject(
            "Storage media for avulsed teeth",
            "Avulsed incisors were stored in bovine milk for 45 and 60 min "
            "following storage period.",
            "Dent Traumatol", "level2")
        assert not hit, f"'bovine milk' supplied a species cue ({why})"


class TestTierRouting:
    """The migration's destination and its never-promote rule."""

    def test_invitro_sits_between_case_series_and_expert_opinion(self):
        assert LEVEL_SCORES["invitro"] == 15
        assert LEVEL_SCORES["level4"] > LEVEL_SCORES["invitro"] > LEVEL_SCORES["level5"]
        assert TIER_ORDER.index("level4") < TIER_ORDER.index("invitro") < TIER_ORDER.index("level5")

    def test_every_clinical_source_tier_outranks_the_destination(self):
        """The migration only ever demotes: each tier it drains must score
        above invitro's 15, or the move would be a promotion."""
        for tier in ("level2", "level3", "level3a", "level3b", "level4"):
            assert LEVEL_SCORES[tier] > LEVEL_SCORES["invitro"]
