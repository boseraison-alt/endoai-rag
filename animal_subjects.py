"""
Animal-subject detection (WORKLIST C2).

A canine study — "Vital pulp therapy in dogs ... a 25-year retrospective
study", *J Am Vet Med Assoc* — was sitting in the clinical hierarchy at 59.8
and retrievable as human clinical evidence. Nothing in this codebase kept
veterinary or animal-experiment work out of the tiers that answer "what
happens in a patient". A dog's tooth is not a patient's tooth, and a
retrospective cohort of dogs is not a retrospective cohort of people, however
well the study was done.

Animal-subject papers are routed to the `invitro` tier (LEVEL_SCORES 15,
between case series and expert opinion), which is where this project already
puts evidence that is real about a mechanism and silent about a patient.

WHY THIS LIVES IN ITS OWN MODULE
--------------------------------
It is the sibling of `endo_ai.detect_in_vitro` and reads like it deliberately.
It is not IN endo_ai.py only because that file was being edited concurrently
by two other workstreams when this landed; nothing about the classifier
depends on where it sits, and `from animal_subjects import
detect_animal_subject` works from endo_ai, the scripts and the tests alike.

PRECISION MATTERS FAR MORE THAN RECALL — measured, not assumed
-------------------------------------------------------------
The asymmetry is the same as `detect_in_vitro`'s and sharper. Leaving one
animal study at Level II shows a clinician one weak paper; demoting a real
human trial into a bench tier removes the best evidence there is from the
answer. So every rule below either fires on language that CANNOT describe a
human study, or does not fire.

Four traps, each found by reading the 2,311 real library rows rather than by
imagining what an animal paper says (`scripts/classify_animal_subjects.py`
prints the same evidence):

1. **"canine" is a human tooth.** 32 rows in this library contain it; ONE is
   an animal study ("a histomorphological study in canine model"). The rest
   are "maxillary canines", "two-rooted mandibular canines", "incisors and
   canines". Bare `canine` is therefore NEVER a cue here — only `canine
   model` / `canine mandible` are.

2. **Systematic reviews of human trials name animal studies in their
   exclusion criteria.** "Animal studies, reviews, and studies with less than
   10 patients per arm were excluded"; "eligibility criteria included in
   vitro or animal studies". 13 of the 17 rows in this library matching
   /animal (model|stud)/ are human evidence syntheses saying what they threw
   away. Cues are ignored inside exclusion / eligibility / search-strategy
   language, and the `animal study` cue must be self-referential ("an animal
   study", "in an animal model") — never a bare plural.

3. **Animal-derived MATERIALS are used on human patients.** "Deproteinized
   bovine bone mineral", "bovine-derived xenograft", "fetal bovine serum",
   "whole bovine milk" (an avulsed-tooth storage medium), "sheep blood agar".
   Two of those sit in genuine human RCTs in this library. Species words are
   therefore only cues in anatomical constructions (`bovine incisors`,
   `bovine pulp`), never on their own.

4. **Ordinary words.** A real false positive in this library is "the
   FlashDent, which uses a mouse-driven cursor". `\\b` handles "rat" inside
   other words; `mouse` needs its own veto.

And one non-trap worth stating: a study OF animal studies is not an animal
study. "Animal Experiments in Periodontal and Peri-Implant Research: Are There
Any Changes?" is a bibliometric survey. It names dogs and rats only in
reporting what others published, so the self-referential rules below decline
it — the same lesson as PMID 39885347 in HANDOVER.md ("a design cue read off
the wrong paper").
"""

import re

# ── Species named as the study's own subjects ────────────────────────────
#
# Every alternative below is a construction that cannot describe a human
# study: a species in an anatomical possessive ("dog teeth", "monkey
# incisors"), a species being counted as material ("Seven dogs", "six mongrel
# dogs", "180 ... male Wistar rats"), a species as the object of "in"
# ("in rats"), a named animal model, or a species referred to as the study's
# own animals ("The dogs were followed up").
_SPECIES = (
    r"dogs?|beagles?|canine\s+model|rats?|mice|mouse|murine|rabbits?|"
    r"monkeys?|macaques?|baboons?|marmosets?|primates?|"
    r"pigs?|piglets?|minipigs?|swine|porcine|"
    r"sheep|lambs?|ewes?|ovine|goats?|caprine|"
    r"cattle|bovine|calf|calves|"
    r"ferrets?|gerbils?|hamsters?|guinea[- ]pigs?|zebrafish|"
    r"felines?|equine|horses?"
)

# Anatomy that makes the species the subject rather than a material source.
_ANIMAL_ANATOMY = (
    r"teeth|tooth|incisors?|molars?|premolars?|canines?|pulps?|dentin(?:e)?|"
    r"jaws?|mandibles?|maxill(?:a|ae|ary)|gingiva|periodont|roots?|muscle|"
    r"skulls?|alveolar\s+bone"
)

# A count immediately before a species: the methods section of an animal
# experiment ("Seven dogs weighing between 15 and 25 kg", "Thirty
# guinea-pigs", "In 6 rabbits", "two adult male mongrel dogs").
_COUNT = (
    r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|eighteen|twenty|thirty|forty|fifty|"
    r"sixty|several|adult|male|female|mongrel|beagle|wistar|sprague[- ]dawley|"
    r"new\s+zealand|c57bl|balb|isogenic|young|healthy|laboratory|germ[- ]free"
)

_ANIMAL_STRONG_RE = re.compile(
    r"(?:"
    # "dog teeth", "rat molars", "monkey incisors", "dogs' teeth"
    rf"\b(?:{_SPECIES})['’]?s?\s+(?:{_ANIMAL_ANATOMY})\b"
    # "in dogs", "in rats", "of monkeys", "in the rabbit"
    rf"|\b(?:in|of)\s+(?:the\s+|a\s+|an\s+)?(?:{_SPECIES})\b"
    # "Seven dogs", "180 ... male Wistar rats", "Thirty guinea-pigs"
    rf"|\b(?:{_COUNT})\s+(?:(?:{_COUNT})\s+){{0,3}}(?:{_SPECIES})\b"
    # "a dog model", "canine model", "murine model", "mouse model of"
    rf"|\b(?:{_SPECIES})\s+model\b"
    # "The dogs were followed up", "The animals were sacrificed"
    rf"|\bthe\s+(?:{_SPECIES}|animals)\s+(?:were|was)\b"
    # Self-referential animal-study language ONLY — never a bare plural, see
    # trap 2. Matches "an animal study", "in an animal model", "this animal
    # experiment", "an animal model of periodontitis".
    r"|\b(?:this|an|a|the\s+present)\s+"
    r"(?:experimental\s+|in\s+vivo\s+)?animal\s+(?:model|study|experiment)\b"
    r"|\banimal\s+model\s+of\b"
    # Animal research ethics/reporting: these exist nowhere else.
    r"|\banimal\s+(?:ethics|care\s+and\s+use)\s+committee\b"
    r"|\binstitutional\s+animal\s+care\b|\bIACUC\b|\bARRIVE\s+guidelines\b"
    r"|\bSYRCLE\b"
    r"|\banimals?\s+(?:were|was)\s+"
    r"(?:sacrificed|euthani[sz]ed|killed|anesthetized|anaesthetized)\b"
    r")",
    re.IGNORECASE)

# Journals that only publish animal work. Checked against the journal field,
# which is metadata rather than prose and so needs no self-reference test.
_VET_JOURNAL_HINTS = (
    "veterinar", "javma", "j vet", "journal of veterinary",
    "vet dent", "veterinary dentistry", "am j vet res", "vet surg",
    "lab anim", "laboratory animals", "comp med", "comparative medicine",
    "animal science", "j zoo wildl",
)

# Contexts in which a species word is a MATERIAL, not a subject. Each was
# found in this library sitting inside genuine human clinical research.
_ANIMAL_MATERIAL_RE = re.compile(
    r"\b(?:"
    r"deproteini[sz]ed\s+bovine|bovine[- ]derived|bovine\s+bone\s+mineral|"
    r"(?:fetal|foetal)\s+bovine\s+serum|bovine\s+serum\s+albumin|"
    r"bovine\s+milk|bovine\s+collagen|bovine\s+xenograft|"
    r"porcine[- ]derived|porcine\s+collagen|porcine\s+gelatin|"
    r"sheep\s+blood|horse\s+serum|"
    r"mouse[- ](?:driven|cursor|pointer|click)|"
    r"dog\s+bites?|cat\s+bites?"
    r")",
    re.IGNORECASE)

# Eligibility / search-strategy language. A cue inside one of these windows is
# a description of what the paper EXCLUDED, not of what it studied.
_EXCLUSION_CONTEXT_RE = re.compile(
    r"\b(?:exclu\w*|eligib\w*|inclusion\s+criteria|selection\s+criteria|"
    r"were\s+(?:selected|screened|retrieved|identified)|search\s+(?:strategy|terms)|"
    r"databases\s+were|risk\s+of\s+bias|study\s+designs?)\b",
    re.IGNORECASE)
_EXCLUSION_WINDOW = 110      # characters either side of a cue

# Human-subject language. Deliberately NARROW: veterinary papers call their
# animals "patients" (the JAVMA study's own title says "independent of patient
# age"), and an animal study is approved by an ethics committee too. Only
# phrases that presuppose a human participant veto.
_HUMAN_SUBJECT_RE = re.compile(
    r"\b(?:"
    r"informed\s+consent"
    r"|institutional\s+review\s+board"
    r"|declaration\s+of\s+helsinki"
    r"|human\s+(?:participants?|subjects?|volunteers?|patients?)"
    r"|patients?\s+(?:were|was)\s+(?:randomly\s+|prospectively\s+|consecutively\s+)?"
    r"(?:randomi|recruit|enrol|enroll|allocat|assign|includ|referred)"
    r"|clinicaltrials\.gov|\bNCT\d{6}"
    r"|clinical\s+trial\s+registr"
    r"|ethics\s+committee\s+of\s+the\s+(?:faculty|school|university)\s+of\s+dent"
    r")",
    re.IGNORECASE)

# A case report describes a PATIENT, and its discussion routinely reaches for
# animal work: PMID 41552405, "Case Report: Rare Presentation of Dentin
# Abnormalities in Loeys-Dietz Syndrome Type I", says "deletion of TGFBR1 in
# mouse models is known to affect dentin". That cue is read off somebody
# else's study (HANDOVER: "a design cue read off the wrong paper"), and the
# paper itself is human clinical evidence however weak. This guard only ever
# DECLINES. scripts/classify_invitro.py carries its twin for the same reason.
_CASE_REPORT_TITLE_RE = re.compile(
    r"^\s*(?:a\s+)?case\s+(?:report|of|series)\b"
    r"|^\s*case\s+report\s*:"
    r"|:\s*a\s+case\s+(?:report|series)\b",
    re.IGNORECASE)

# Same idea as _INVITRO_PROTECTED_LEVELS: a design whose label already outranks
# any text cue. A Cochrane review or a Level I synthesis is not reclassified on
# a phrase in its abstract — and those are exactly the rows whose abstracts
# list animal studies as an exclusion. `classic` is a curation label; the
# seminal animal experiments of endodontics (Kakehashi, the monkey and dog
# work of the 1970s-80s) were curated into it deliberately.
_ANIMAL_PROTECTED_LEVELS = {"cochrane", "level1", "classic"}


def _cue_outside_exclusion_language(text: str, match) -> bool:
    """True when this cue is NOT sitting inside eligibility-criteria prose."""
    lo = max(0, match.start() - _EXCLUSION_WINDOW)
    hi = min(len(text), match.end() + _EXCLUSION_WINDOW)
    return not _EXCLUSION_CONTEXT_RE.search(text[lo:hi])


def detect_animal_subject(title: str, abstract: str, journal: str = "",
                          level_key: str = "") -> tuple:
    """Return (is_animal_subject, reason). Deliberately conservative.

    Fires on a veterinary journal, or on a cue that names a non-human species
    as this study's OWN subject. Vetoed by human-subject language, by
    animal-derived-material contexts, and by exclusion-criteria prose; never
    touches a protected design tier.

    The reason string is returned so a migration can print WHY each row moved
    and a human can audit the decision rather than trusting a boolean — this
    classifier's whole risk is false positives, and a count cannot show them.
    """
    if level_key in _ANIMAL_PROTECTED_LEVELS:
        return False, "protected tier"

    jl = (journal or "").lower()
    for hint in _VET_JOURNAL_HINTS:
        if hint in jl:
            return True, f"veterinary journal: {hint}"

    if _CASE_REPORT_TITLE_RE.search(title or ""):
        return False, "case report — any animal cue is background prose"

    text = f"{title or ''}\n{abstract or ''}"
    if not text.strip():
        return False, "no text"

    # Blank out animal-derived-material phrases before looking for subjects,
    # so "whole bovine milk" cannot supply the "bovine" in "bovine incisors".
    scrubbed = _ANIMAL_MATERIAL_RE.sub(lambda m: " " * len(m.group(0)), text)

    if _HUMAN_SUBJECT_RE.search(scrubbed):
        return False, "human-subject language override"

    for m in _ANIMAL_STRONG_RE.finditer(scrubbed):
        if _cue_outside_exclusion_language(scrubbed, m):
            cue = " ".join(m.group(0).split())
            where = "title" if m.start() < len(title or "") else "abstract"
            return True, f"{where}: {cue[:44]}"

    return False, "no self-referential animal-subject cue"
