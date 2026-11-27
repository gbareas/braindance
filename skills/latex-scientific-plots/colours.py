"""Colour science for checking a palette instead of replacing it.

A researcher's own colours are kept; what is checked is whether they still work for
every reader:

  - colour-vision deficiency: each colour is simulated as seen with protanopia,
    deuteranopia and tritanopia (Machado, Oliveira and Fernandes 2009, severity 1),
    and every pair must stay apart by at least MIN_DE (CIEDE2000);
  - greyscale: the lightness L* of every pair, for printing in black and white;
  - colormaps: lightness must change monotonically along a sequential map and
    symmetrically about the centre of a diverging one.

When a palette fails, `suggest_palette` returns the nearest palette that passes: every
colour keeps its hue, only its lightness and chroma move, and colours that already
work, or that the researcher marks with `keep`, are not touched.

    python colours.py '#1f77b4' '#ff7f0e' '#2ca02c' '#d62728'    # check, and suggest a fix
"""
from __future__ import annotations

import itertools
import sys

import numpy as np

# Pairs closer than this (CIEDE2000) under any simulated vision are hard to tell apart as
# thin lines and small markers. Calibrated so all eight Okabe-Ito colours pass (worst pair 10.9) and
# the red-green pairs of matplotlib's tab10 fail (tests/test_colours.py).
MIN_DE = 10.0
# Lightness difference below which two colours print as the same grey.
MIN_GREY_DL = 10.0

VISIONS = ("normal", "protan", "deutan", "tritan")

# Machado et al. (2009), severity 1.0, applied to linear RGB.
_CVD = {
    "protan": np.array([[0.152286, 1.052583, -0.204868],
                        [0.114503, 0.786281, 0.099216],
                        [-0.003882, -0.048116, 1.051998]]),
    "deutan": np.array([[0.367322, 0.860646, -0.227968],
                        [0.280085, 0.672501, 0.047413],
                        [-0.011820, 0.042940, 0.968881]]),
    "tritan": np.array([[1.255528, -0.076749, -0.178779],
                        [-0.078411, 0.930809, 0.147602],
                        [0.004733, 0.691367, 0.303900]]),
}

_M_RGB_XYZ = np.array([[0.4124564, 0.3575761, 0.1804375],
                       [0.2126729, 0.7151522, 0.0721750],
                       [0.0193339, 0.1191920, 0.9503041]])
_M_XYZ_RGB = np.linalg.inv(_M_RGB_XYZ)
_WHITE = _M_RGB_XYZ @ np.ones(3)  # D65


# ──────────────────────────────────────────────────────────────────────────
# Conversions
# ──────────────────────────────────────────────────────────────────────────

def to_rgb(colour):
    """Any matplotlib colour spec to an sRGB triple in [0, 1]."""
    from matplotlib.colors import to_rgb as _to_rgb
    return np.array(_to_rgb(colour), dtype=float)


def to_hex(rgb):
    rgb = np.clip(np.asarray(rgb, dtype=float), 0, 1)
    return "#" + "".join(f"{int(round(v * 255)):02x}" for v in rgb)


def srgb_to_linear(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.abs(c) ** (1 / 2.4) * np.sign(c) - 0.055)


def _f(t):
    d = 6 / 29
    return np.where(t > d ** 3, np.cbrt(t), t / (3 * d * d) + 4 / 29)


def _finv(t):
    d = 6 / 29
    return np.where(t > d, t ** 3, 3 * d * d * (t - 4 / 29))


def linear_to_lab(lin):
    xyz = np.asarray(lin, dtype=float) @ _M_RGB_XYZ.T / _WHITE
    fx, fy, fz = _f(xyz[..., 0]), _f(xyz[..., 1]), _f(xyz[..., 2])
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)


def lab_to_linear(lab):
    lab = np.asarray(lab, dtype=float)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    xyz = np.stack([_finv(fx), _finv(fy), _finv(fz)], axis=-1) * _WHITE
    return xyz @ _M_XYZ_RGB.T


def rgb_to_lab(rgb):
    return linear_to_lab(srgb_to_linear(rgb))


def simulate(rgb, vision):
    """sRGB colour(s) as seen with the given vision; 'normal' returns them unchanged."""
    rgb = np.asarray(rgb, dtype=float)
    if vision == "normal":
        return rgb
    lin = srgb_to_linear(rgb) @ _CVD[vision].T
    return np.clip(linear_to_srgb(np.clip(lin, 0, 1)), 0, 1)


def delta_e(lab1, lab2):
    """CIEDE2000 colour difference (Sharma, Wu and Dalal 2005)."""
    L1, a1, b1 = np.moveaxis(np.asarray(lab1, dtype=float), -1, 0)
    L2, a2, b2 = np.moveaxis(np.asarray(lab2, dtype=float), -1, 0)
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp = L2 - L1
    dCp = C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0.0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lpm = (L1 + L2) / 2
    Cpm = (C1p + C2p) / 2
    hsum = h1p + h2p
    hpm = np.where(np.abs(h1p - h2p) > 180, np.where(hsum < 360, hsum + 360, hsum - 360), hsum) / 2
    hpm = np.where(C1p * C2p == 0, hsum, hpm)
    T = (1 - 0.17 * np.cos(np.radians(hpm - 30)) + 0.24 * np.cos(np.radians(2 * hpm))
         + 0.32 * np.cos(np.radians(3 * hpm + 6)) - 0.20 * np.cos(np.radians(4 * hpm - 63)))
    dtheta = 30 * np.exp(-(((hpm - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cpm ** 7 / (Cpm ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / np.sqrt(20 + (Lpm - 50) ** 2)
    Sc = 1 + 0.045 * Cpm
    Sh = 1 + 0.015 * Cpm * T
    Rt = -np.sin(np.radians(2 * dtheta)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


# ──────────────────────────────────────────────────────────────────────────
# Palettes
# ──────────────────────────────────────────────────────────────────────────

def _labs(rgbs):
    """{vision: Lab array (n, 3)} for an (n, 3) array of sRGB colours."""
    return {v: rgb_to_lab(simulate(rgbs, v)) for v in VISIONS}


def pair_distances(colours):
    """{(i, j): {vision: dE00, ..., 'grey_dL': |dL*|}} for every pair of colours."""
    rgbs = np.array([to_rgb(c) for c in colours])
    labs = _labs(rgbs)
    out = {}
    for i, j in itertools.combinations(range(len(rgbs)), 2):
        d = {v: float(delta_e(labs[v][i], labs[v][j])) for v in VISIONS}
        d["grey_dL"] = float(abs(labs["normal"][i, 0] - labs["normal"][j, 0]))
        out[(i, j)] = d
    return out


def check_palette(colours, min_de=MIN_DE, min_grey=MIN_GREY_DL, background="#ffffff"):
    """How well a colour cycle works for every reader.

    Returns a dict with:
      clashes      pairs closer than min_de under some vision: (i, j, vision, dE)
      grey_merges  pairs closer than min_grey in lightness: (i, j, dL)
      safe_prefix  how many colours from the start of the cycle are free of clashes;
                   a figure with that many series or fewer is safe
      faint        colours with too little contrast against the background
      worst        the smallest dE per vision
    """
    colours = list(colours)
    pairs = pair_distances(colours)
    clashes, grey = [], []
    worst = {v: float("inf") for v in VISIONS}
    for (i, j), d in pairs.items():
        for v in VISIONS:
            worst[v] = min(worst[v], d[v])
        v_min = min(VISIONS, key=lambda v: d[v])
        if d[v_min] < min_de:
            clashes.append((i, j, v_min, round(d[v_min], 1)))
        if d["grey_dL"] < min_grey:
            grey.append((i, j, round(d["grey_dL"], 1)))
    safe = len(colours)
    for i, j, _, _ in clashes:
        safe = min(safe, j)
    bg = rgb_to_lab(to_rgb(background))
    faint = []
    for i, c in enumerate(colours):
        d = min(float(delta_e(rgb_to_lab(simulate(to_rgb(c), v)), bg)) for v in VISIONS)
        if d < 2 * min_de:
            faint.append((i, round(d, 1)))
    return {
        "colours": [to_hex(to_rgb(c)) for c in colours],
        "ok": not clashes,
        "clashes": clashes,
        "grey_merges": grey,
        "safe_prefix": safe,
        "faint": faint,
        "worst": {v: (round(w, 1) if np.isfinite(w) else None) for v, w in worst.items()},
        "min_de": min_de,
    }


def _lch(lab):
    return np.array([lab[0], np.hypot(lab[1], lab[2]), np.degrees(np.arctan2(lab[2], lab[1])) % 360])


def _from_lch(L, C, h):
    lab = np.array([L, C * np.cos(np.radians(h)), C * np.sin(np.radians(h))])
    return lab_to_linear(lab)


def _variants(rgb, dl_max=36, dl_step=3, chroma_scales=(0.6, 0.75, 0.9, 1.0, 1.15, 1.3)):
    """Colours with the same hue and a different lightness or chroma, inside the sRGB gamut."""
    L, C, h = _lch(rgb_to_lab(rgb))
    out = []
    for dl in np.arange(-dl_max, dl_max + 1e-9, dl_step):
        for s in chroma_scales:
            Ln = L + dl
            if not 5 <= Ln <= 95:
                continue
            lin = _from_lch(Ln, C * s, h)
            if np.all(lin >= -1e-6) and np.all(lin <= 1 + 1e-6):
                out.append(linear_to_srgb(np.clip(lin, 0, 1)))
    return out


def _min_pair(labs_by_vision, idx=None):
    """Smallest dE over visions for all pairs (or the pairs that include index idx)."""
    n = labs_by_vision["normal"].shape[0]
    best = float("inf")
    pairs = ((idx, j) for j in range(n) if j != idx) if idx is not None else itertools.combinations(range(n), 2)
    for i, j in pairs:
        for v in VISIONS:
            best = min(best, float(delta_e(labs_by_vision[v][i], labs_by_vision[v][j])))
    return best


def suggest_palette(colours, keep=(), min_de=MIN_DE, max_sweeps=12):
    """The nearest palette, hue by hue, in which no pair clashes for any reader.

    Each colour keeps its hue; lightness and chroma move as little as possible. Colours in
    `keep` (indices) are never changed. Returns a dict with the new colours, how far each
    moved from the original (dE00 in normal vision) and the check of the result, which may
    still have clashes when the hues themselves are too close (then reorder or drop one).
    """
    orig = np.array([to_rgb(c) for c in colours])
    n = len(orig)
    cur = orig.copy()
    orig_lab = rgb_to_lab(orig)
    keep = {int(k) % n for k in keep} if n else set()
    variants = [None if i in keep else [orig[i], *_variants(orig[i])] for i in range(n)]

    def score(rgbs):
        labs = _labs(rgbs)
        sep = min(_min_pair(labs), min_de) if n > 1 else min_de
        moved = float(np.sum(delta_e(orig_lab, labs["normal"])))
        return sep, -moved

    best = score(cur)
    for _ in range(max_sweeps):
        improved = False
        labs = _labs(cur)
        # work on the colours that take part in the worst clashes first
        order = sorted((i for i in range(n) if i not in keep), key=lambda i: _min_pair(labs, i))
        for i in order:
            for cand in variants[i]:
                trial = cur.copy()
                trial[i] = cand
                s = score(trial)
                if s > best:
                    best, cur, improved = s, trial, True
        if not improved or best[0] >= min_de and not _can_move_back(cur, orig, keep, min_de):
            break
    labs = _labs(cur)
    moved = delta_e(orig_lab, labs["normal"])
    return {
        "colours": [to_hex(c) for c in cur],
        "moved": [round(float(m), 1) for m in moved],
        "check": check_palette([to_hex(c) for c in cur], min_de),
    }


def _can_move_back(cur, orig, keep, min_de):
    """True if some changed colour could return to its original and the palette still pass."""
    for i in range(len(cur)):
        if i in keep or np.allclose(cur[i], orig[i]):
            continue
        trial = cur.copy()
        trial[i] = orig[i]
        if _min_pair(_labs(trial)) >= min_de:
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────
# Colormaps
# ──────────────────────────────────────────────────────────────────────────

BAD_CMAPS = {"jet", "rainbow", "gist_rainbow", "nipy_spectral", "gist_ncar"}


def check_colormap(cmap, kind="sequential", n=64):
    """Whether lightness runs the right way through a colormap.

    sequential  L* rises (or falls) monotonically from end to end
    diverging   L* is symmetric about the centre, peaking (or dipping) there
    Returns {"ok": bool, "problem": str or None, "L": [...], "name": str}.
    """
    import matplotlib as mpl
    cm = mpl.colormaps[cmap] if isinstance(cmap, str) else cmap
    name = getattr(cm, "name", str(cmap))
    rgb = cm(np.linspace(0, 1, n))[:, :3]
    L = rgb_to_lab(rgb)[:, 0]
    base = name[:-2] if name.endswith("_r") else name
    out = {"name": name, "L": [round(float(v), 1) for v in L[:: max(1, n // 8)]], "ok": True, "problem": None}
    if base in BAD_CMAPS:
        out.update(ok=False, problem=f"{name} has bands of lightness that create edges the data does not have")
        return out
    dL = np.diff(L)
    if kind == "sequential":
        span = abs(L[-1] - L[0])
        sign = np.sign(L[-1] - L[0]) or 1.0
        backwards = float(np.sum(np.clip(-sign * dL, 0, None)))
        if span < 30:
            out.update(ok=False, problem=f"{name} spans only {span:.0f} in lightness; a sequential map needs a "
                       "clear dark-to-light run (viridis spans about 80)")
        elif backwards > 3:
            out.update(ok=False, problem=f"lightness in {name} turns back by {backwards:.0f} along the map, so "
                       "two different values can look alike")
    elif kind == "diverging":
        half = n // 2
        left, right = L[:half], L[::-1][:half]
        asym = float(np.max(np.abs(left - right)))
        centre = L[half - 1: half + 1].mean()
        ends = (L[0] + L[-1]) / 2
        if asym > 12:
            out.update(ok=False, problem=f"the two halves of {name} differ in lightness by up to {asym:.0f}, so "
                       "equal distances from the centre do not look equal")
        elif abs(centre - ends) < 20:
            out.update(ok=False, problem=f"the centre of {name} is not clearly lighter or darker than its ends")
    else:
        raise ValueError(f"kind must be 'sequential' or 'diverging', not {kind!r}")
    return out


# ──────────────────────────────────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────────────────────────────────

def describe(result, names=None):
    cs = result["colours"]
    nm = names or cs
    lines = []
    if result["ok"]:
        lines.append(f"all {len(cs)} colours stay apart for every reader (worst dE00 "
                     + ", ".join(f"{v} {w}" for v, w in result["worst"].items() if w is not None) + ")")
    else:
        lines.append(f"the first {result['safe_prefix']} colour(s) are safe for every reader; these pairs clash "
                     f"(dE00 below {result['min_de']:g}):")
        for i, j, v, d in result["clashes"]:
            lines.append(f"  {nm[i]} / {nm[j]}: {d} with {v} vision" if v != "normal"
                         else f"  {nm[i]} / {nm[j]}: {d} even with normal vision")
    if result["grey_merges"]:
        lines.append("same grey when printed in black and white (tell them apart by marker or line style): "
                     + ", ".join(f"{nm[i]} / {nm[j]} (dL* {d})" for i, j, d in result["grey_merges"]))
    if result["faint"]:
        lines.append("faint against the background: " + ", ".join(f"{nm[i]} (dE00 {d})" for i, d in result["faint"]))
    return "\n".join(lines)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Check a colour cycle for colour-blind and greyscale readers.")
    ap.add_argument("colours", nargs="+", help="colours in cycle order, e.g. '#1f77b4' tab:orange C2")
    ap.add_argument("--keep", default="", help="comma-separated indices never to change, e.g. 0,2")
    args = ap.parse_args(argv)
    res = check_palette(args.colours)
    print(describe(res))
    if not res["ok"]:
        keep = [int(k) for k in args.keep.split(",") if k.strip()]
        sug = suggest_palette(args.colours, keep=keep)
        print("\nnearest palette with the same hues:")
        for old, new, m in zip(res["colours"], sug["colours"], sug["moved"]):
            print(f"  {old} -> {new}" + (f"  (moved {m})" if m > 0.05 else "  (unchanged)"))
        print(describe(sug["check"]))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
