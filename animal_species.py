"""The species named by an animal-subject detection (item E, 2026-09-08).

`detect_animal_subject` returns a reason like "title: in dogs" or
"abstract: bovine pulp". The context line shown to the model needs the SPECIES
out of that, because "ANIMAL STUDY" alone tells a clinician less than
"ANIMAL STUDY (dog)": the distance from a dog model to a human molar is not the
distance from a bovine incisor used as a bench substrate.

A SEPARATE MODULE ON PURPOSE. The first attempt appended this to
`animal_subjects.py` through a shell heredoc, and the heredoc ate the
backslashes in `r"\\b%s\\b"` — leaving two literal BACKSPACE bytes (`\\x08`) in
the pattern. It was invisible to `grep`, `inspect.getsource` rendered it as a
plain substring match, and the function silently returned "unspecified" for
every input while looking correct in every view of it. Written with the file
tools instead, which is the standing instruction for exactly this reason.
"""
import re

# Canonical species name -> the cues that name it. Ordered so that the more
# specific cue wins where two could fire.
_SPECIES_CANON = [
    ("dog", ("dog", "dogs", "canine", "beagle")),
    ("rat", ("rat", "rats")),
    ("mouse", ("mouse", "mice", "murine")),
    ("monkey", ("monkey", "monkeys", "primate", "primates", "macaque",
                "baboon")),
    ("bovine", ("bovine", "cow", "cows", "cattle", "calf", "calves")),
    ("pig", ("pig", "pigs", "porcine", "swine", "minipig")),
    ("sheep", ("sheep", "ovine", "lamb", "lambs")),
    ("rabbit", ("rabbit", "rabbits")),
    ("cat", ("cat", "cats", "feline")),
    ("ferret", ("ferret", "ferrets")),
    ("horse", ("horse", "horses", "equine")),
    ("guinea pig", ("guinea pig", "guinea-pig", "guinea pigs")),
    ("hamster", ("hamster", "hamsters")),
]


def species_from_reason(reason: str) -> str:
    """The species named in a `detect_animal_subject` reason, or "unspecified".

    Never guesses beyond the cue that actually fired. A veterinary-journal hit
    names no species, and "unspecified" is the honest label for it — inventing
    one would put a species in front of a clinician that the paper never named.

    Word-bounded, so "cat" does not fire inside "indicate" and "rat" does not
    fire inside "stratified".
    """
    r = (reason or "").lower()
    for canon, cues in _SPECIES_CANON:
        for cue in cues:
            if re.search(r"\b%s\b" % re.escape(cue), r):
                return canon
    return "unspecified"
