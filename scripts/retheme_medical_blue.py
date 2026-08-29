"""
Re-theme templates/index.html (from ORIGINAL dark theme) -> Option A:
cool white base + Medical Blue accent (UpToDate register), gold Deep-Learning secondary.

All passes in one script:
  1. global role-preserving remap
  2. white text restored in rules with solid accent backgrounds (full ink scale)
  3. dim-text role-collision fix (border shades used as text -> muted ink)
  4. targeted cross-rule fixes (tasks-panel header children)
"""
import re

PATH = r"C:\Users\boser\endo-ai-rag\templates\index.html"

INK = "#131b2c"
INKS = ["#131b2c", "#182234", "#1e2840", "#2f394e", "#4c586c"]
ACCENTS_NEED_WHITE = ["#2563eb", "#1d4ed8", "#1e40af", "#1e3a8a",
                      "#946f2e", "#a5812e", "#0f7a4d", "#c23f3f", "#b45309"]

HEXMAP = {
    # ---- page backgrounds -> cool whites ----
    "#0d1117": "#e4e9f0", "#0d0f17": "#e4e9f0", "#060d18": "#dfe5ee",
    "#080f1c": "#dfe5ee", "#0b1220": "#e7ebf2", "#111318": "#e8ecf2",
    "#0f172a": "#eef1f6", "#0f1520": "#eef1f6",
    # ---- panels / cards ----
    "#13161e": "#f4f6f9", "#131720": "#f4f6f9", "#111827": "#f4f6f9",
    "#161b27": "#f8fafc", "#161c28": "#f8fafc",
    "#1a1f2e": "#fbfcfd", "#1a2030": "#fbfcfd", "#1a2235": "#fbfcfd",
    "#1e2330": "#fcfcfd", "#1e2736": "#ffffff", "#1e293b": "#ffffff",
    "#1f2937": "#ffffff", "#252d3d": "#dee4ec",
    # ---- blue-tinted info panels -> blue tints ----
    "#1e3a5f": "#e5edff", "#2d5282": "#dbe6fd", "#2d4a7a": "#dbe6fd",
    "#1e2d4a": "#eaf0fe", "#2d3f5c": "#e0e9fd", "#0d1a2e": "#f0f4fe",
    "#0f2a3f": "#e8effd",
    # ---- borders -> cool hairlines ----
    "#2d3748": "#d2d9e3", "#374151": "#ccd5e0", "#4a5568": "#b8c2d0",
    "#475569": "#b8c2d0", "#4b5563": "#b8c2d0", "#6b7280": "#768292",
    # ---- light text -> ink scale ----
    "#ffffff": INK, "#fff": INK,
    "#f1f5f9": "#182234", "#e2e8f0": "#1e2840",
    "#cbd5e1": "#2f394e", "#cbd5e0": "#2f394e",
    "#94a3b8": "#4c586c",
    # ---- blues stay blue, deepened for light bg ----
    "#3b82f6": "#2563eb", "#2563eb": "#1d4ed8", "#1d4ed8": "#1e40af",
    "#1e40af": "#1e3a8a", "#60a5fa": "#1d4ed8", "#93c5fd": "#1e40af",
    "#bfdbfe": "#1e3a8a", "#dbeafe": "#e5edff",
    # ---- indigos -> blue family ----
    "#6366f1": "#2563eb", "#818cf8": "#1d4ed8", "#4f46e5": "#1e40af",
    "#a5b4fc": "#1d4ed8", "#7c3aed": "#6d28d9",
    # ---- cyans -> deep clinical cyan ----
    "#0e7490": "#0e7490", "#0891b2": "#0e7490", "#22d3ee": "#0891b2",
    # ---- greens -> clinical green ----
    "#34d399": "#12885a", "#86efac": "#3aa06f", "#10b981": "#0f7a4d",
    "#059669": "#0d6b44", "#047857": "#0b5f3d", "#4ade80": "#2e9663",
    "#065f46": "#e3f5ec", "#134e2e": "#dcefe4", "#132318": "#e9f4ee",
    # ---- reds ----
    "#f87171": "#d05252", "#ef4444": "#c23f3f", "#e05555": "#c74a4a",
    "#fca5a5": "#d98282", "#7f1d1d": "#fbe5e5", "#1a0f0f": "#fdf0f0",
    # ---- ambers ----
    "#fbbf24": "#b45309", "#f59e0b": "#a16207", "#fde68a": "#854d0e",
    "#fcd34d": "#a16207", "#ca8a04": "#a16207",
    "#92400e": "#faf0dc", "#78350f": "#f6ead2", "#fb923c": "#c2661b",
    # ---- learn-mode golds -> muted gold (classic blue+gold secondary) ----
    "#b89860": "#a5812e", "#d4a020": "#946f2e",
    "#e8d8b8": "#7a5f28", "#d4c090": "#8a6d3c",
}

RGBAMAP = {
    (59, 130, 246): (37, 99, 235),
    (96, 165, 250): (37, 99, 235),
    (99, 102, 241): (37, 99, 235),
    (16, 185, 129): (15, 122, 77),
    (239, 68, 68):  (194, 63, 63),
    (245, 158, 11): (161, 98, 7),
    (234, 179, 8):  (161, 98, 7),
    (251, 191, 36): (161, 98, 7),
    (255, 255, 255): (26, 34, 51),
}

TEXT_FIXES = {  # hairline shade used as TEXT -> muted ink
    "#b8c2d0": "#4c586c",
    "#ccd5e0": "#596274",
    "#d2d9e3": "#596274",
}

def main():
    with open(PATH, encoding="utf-8") as fh:
        t = fh.read()

    # pass 1 — two-phase (placeholder) replace; some colors are both source & target
    n_hex = 0
    keys = sorted(HEXMAP, key=len, reverse=True)
    for i, old in enumerate(keys):
        pattern = re.compile(re.escape(old) + r"\b", re.IGNORECASE)
        t, k = pattern.subn(f"\x00{i}\x00", t)
        n_hex += k
    for i, old in enumerate(keys):
        t = t.replace(f"\x00{i}\x00", HEXMAP[old])

    n_rgba = 0
    def rgba_sub(m):
        nonlocal n_rgba
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        rest = m.group(4) or ""
        if (r, g, b) in RGBAMAP:
            nr, ng, nb = RGBAMAP[(r, g, b)]
            n_rgba += 1
            return f"rgba({nr},{ng},{nb}{rest})"
        return m.group(0)
    t = re.sub(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(,[^)]*)?\)", rgba_sub, t)

    # pass 2 — white text in accent-bg rule blocks (full ink scale)
    n_white = 0
    def block_fix(m):
        nonlocal n_white
        block = m.group(0)
        has_accent = any(
            re.search(r"background(-color)?\s*:\s*" + re.escape(a), block, re.I)
            or re.search(r"background\s*:\s*linear-gradient\([^)]*" + re.escape(a), block, re.I)
            for a in ACCENTS_NEED_WHITE
        )
        if has_accent:
            for ink in INKS:
                block, k = re.subn(r"(?<![\w-])(color\s*:\s*)" + re.escape(ink),
                                   r"\g<1>#ffffff", block, flags=re.I)
                n_white += k
        return block
    t = re.sub(r"\{[^{}]*\}", block_fix, t)

    # pass 3 — dim-text role collision
    n_dim = 0
    for old, new in TEXT_FIXES.items():
        t, k = re.subn(r"(?<![\w-])(color\s*:\s*)" + re.escape(old), r"\g<1>" + new, t, flags=re.I)
        n_dim += k
        t, k = re.subn(r"(\.style\.color\s*=\s*['\"])" + re.escape(old), r"\g<1>" + new, t, flags=re.I)
        n_dim += k

    # pass 4 — tasks-panel header children (cross-rule pairing)
    t, k1 = re.subn(r"(\.tasks-panel-title\s*\{[^}]*?color\s*:\s*)#[0-9a-fA-F]{6}",
                    r"\g<1>#ffffff", t, flags=re.S)
    t, k2 = re.subn(r"(\.tasks-panel-subtitle\s*\{[^}]*?color\s*:\s*)rgba\([^)]*\)",
                    r"\g<1>rgba(255,255,255,0.75)", t, flags=re.S)

    with open(PATH, "w", encoding="utf-8") as fh:
        fh.write(t)
    print(f"hex: {n_hex}  rgba: {n_rgba}  white-on-accent: {n_white}  dim-text: {n_dim}  tasks-header: {k1+k2}")

if __name__ == "__main__":
    main()
