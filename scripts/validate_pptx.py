"""
Structural validation for a generated .pptx — the checks PowerPoint runs
before it shows "PowerPoint found a problem with content".

python-pptx will happily WRITE a file that PowerPoint then refuses to open
cleanly, and the COM render path tolerated it too (Presentations.Open repairs
silently and returns a usable object), so nothing in the pipeline noticed.

Checks, in the order PowerPoint tends to fail on:
  1. every part is well-formed XML
  2. every r:id referenced in a part exists in that part's .rels
  3. every .rels target resolves to a part that is actually in the zip
  4. no XML-illegal control characters in any text
  5. [Content_Types].xml covers every part extension

Usage:  python scripts/validate_pptx.py <file.pptx> [more.pptx ...]
Exit 1 if any problem is found.
"""
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

# XML 1.0 forbids these outright — they cannot be escaped, only removed.
# This is the set that silently rides in from PDF-scraped abstracts and
# LLM output and then makes PowerPoint offer to "repair" the file.
ILLEGAL_CHARS = re.compile(
    r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
)

# NOTE the * — an EMPTY r:id="" is legal in exactly one place (a media
# hlinkClick) and illegal everywhere else, so it must be captured, not skipped.
# The first version of this file used + and silently ignored every empty
# reference it was written to find.
R_ID = re.compile(r'r:(?:id|embed|link|pict|dm|lo|qs|cs)="([^"]*)"')

# Elements whose attributes are required by the schema. PowerPoint does not
# repair these — it refuses the file outright with "corrupted and unreadable",
# which is how the narrated decks shipped broken while the base decks were fine.
REQUIRED_ATTRS = [
    ("p:tn", "val", "a time-node reference with no val"),
    ("p:spTgt", "spid", "a shape target with no spid"),
]

# p:bldP is a PARAGRAPH build: it only means anything on a shape with a text
# body. Pointed at a picture (an audio shape) it is invalid.
BLDP = re.compile(r'<p:bldP[^>]*spid="(\d+)"')
PIC_IDS = re.compile(r'<p:pic>.*?<p:cNvPr id="(\d+)"', re.S)


def rels_path_for(part: str) -> str:
    p = Path(part)
    return str(p.parent / "_rels" / (p.name + ".rels")).replace("\\", "/")


def validate(path: str) -> list:
    problems = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())

        # 1 + 4: every XML part parses, and carries no illegal control chars.
        for name in sorted(names):
            if not name.endswith((".xml", ".rels")):
                continue
            raw = z.read(name)
            text = raw.decode("utf-8", "replace")
            # Scan for illegal characters BEFORE parsing. A raw control char
            # makes the parser fail with "not well-formed (invalid token)",
            # which says nothing about where it came from; naming the byte and
            # quoting its context points straight at the source text that
            # carried it in.
            illegal = False
            for m in ILLEGAL_CHARS.finditer(text):
                illegal = True
                ctx = text[max(0, m.start() - 40):m.start() + 40]
                problems.append(
                    f"{name}: illegal XML char {hex(ord(m.group()))} at "
                    f"offset {m.start()} — ...{ctx!r}...")
            if illegal:
                continue
            try:
                ET.fromstring(raw)
            except ET.ParseError as e:
                problems.append(f"{name}: not well-formed XML — {e}")
                continue

        # 2: every r:id used in a part is declared in that part's .rels.
        for name in sorted(n for n in names if n.endswith(".xml")):
            used = set(R_ID.findall(z.read(name).decode("utf-8", "replace")))
            # r:id="" is legal in exactly one place — an hlinkClick carrying
            # action="ppaction://media", which PowerPoint itself writes on
            # audio shapes. It is a deliberate "no target", not a dangling ref.
            used.discard("")
            if not used:
                continue
            rp = rels_path_for(name)
            declared = set()
            if rp in names:
                try:
                    root = ET.fromstring(z.read(rp))
                    declared = {r.get("Id") for r in root}
                except ET.ParseError:
                    problems.append(f"{rp}: not well-formed XML")
            missing = used - declared
            if missing:
                problems.append(
                    f"{name}: references undeclared relationship id(s) "
                    f"{sorted(missing)} (rels: {rp if rp in names else 'MISSING'})")

        # 3: every internal .rels target exists in the package.
        for name in sorted(n for n in names if n.endswith(".rels")):
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            base = Path(name).parent.parent
            for rel in root:
                if (rel.get("TargetMode") or "") == "External":
                    continue
                target = rel.get("Target") or ""
                if target.startswith("/"):
                    resolved = target.lstrip("/")
                else:
                    resolved = str((base / target)).replace("\\", "/")
                    while "/../" in resolved:
                        resolved = re.sub(r"[^/]+/\.\./", "", resolved, count=1)
                if resolved not in names:
                    problems.append(
                        f"{name}: relationship {rel.get('Id')} targets "
                        f"'{target}' which is not in the package")

        # 4b: schema-required attributes that PowerPoint refuses outright.
        for name in sorted(n for n in names if n.endswith(".xml")):
            xml = z.read(name).decode("utf-8", "replace")
            for tag, attr, why in REQUIRED_ATTRS:
                for m in re.finditer(r"<" + re.escape(tag) + r"(\s[^>]*)?/?>", xml):
                    attrs = m.group(1) or ""
                    if f'{attr}="' not in attrs:
                        problems.append(f"{name}: <{tag}> without @{attr} — {why}")
            pic_ids = set(PIC_IDS.findall(xml))
            for spid in BLDP.findall(xml):
                if spid in pic_ids:
                    problems.append(
                        f"{name}: <p:bldP spid=\"{spid}\"> targets a picture; "
                        f"a paragraph build needs a text body")

        # 5: content types cover every extension present.
        if "[Content_Types].xml" not in names:
            problems.append("[Content_Types].xml is missing")
        else:
            ct = z.read("[Content_Types].xml").decode("utf-8", "replace")
            defaults = set(re.findall(r'Extension="([^"]+)"', ct, re.I))
            overrides = set(re.findall(r'PartName="([^"]+)"', ct))
            for n in names:
                if n.startswith("_rels") or n == "[Content_Types].xml":
                    continue
                ext = Path(n).suffix.lstrip(".").lower()
                if ext and ext not in {d.lower() for d in defaults} \
                        and ("/" + n) not in overrides:
                    problems.append(
                        f"[Content_Types].xml: no Default for '.{ext}' and no "
                        f"Override for /{n}")
    return problems


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    bad = 0
    for path in argv:
        problems = validate(path)
        size = Path(path).stat().st_size // 1024
        if problems:
            bad = 1
            print(f"\nFAIL  {path}  ({size} KB)  {len(problems)} problem(s)")
            for p in problems[:25]:
                print(f"   - {p}")
            if len(problems) > 25:
                print(f"   ... and {len(problems) - 25} more")
        else:
            print(f"OK    {path}  ({size} KB)")
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
