"""Learn a draft style profile from a researcher's past work.

Reads figure PDFs, whole paper PDFs, matplotlib scripts and .mplstyle / matplotlibrc
files, and writes a profile with a comment on every entry saying where it came from:

  palette     the colours of data (lines, markers, bars, fills), in the order they are
              usually used, from colour literals and colour lists in scripts and from
              the drawings in PDFs (text is ignored, so coloured links do not count)
  colormaps   matched against matplotlib's colormaps, from images and vector meshes
              in PDFs and from cmap= in scripts; a rainbow map is reported, not adopted
  rc          ticks (direction, sides, minor), frames, grid, line and frame widths, from
              the geometry of the axes in PDFs; any setting from scripts and style files
  font        reported only: the profile keeps Computer Modern unless the user asks

A setting is written only when the evidence agrees (by default 70 % of what was
observed) and when it differs from the house style. Typography the document decides
(font sizes, figure size) is never learned.

    python style_profile.py learn paper.pdf fig*.pdf plot_*.py my.mplstyle -o profile.yaml --preview p.png
"""
from __future__ import annotations

import ast
import datetime as _dt
import math
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import colours as C

AGREE = 0.7          # fraction of observations that must agree before a setting is written
SAME_COLOUR = 3.0    # dE00 under which two colours are the same colour
CHROMA_MIN = 12.0    # below this (C* in CIELAB) a colour is a grey: text, frames, grids
CMAP_MATCH = 3.0     # dE00 to a colormap sample for a colour to count as on the map
MAX_PALETTE = 10

# Settings the document decides, or that the user has asked to keep: never learned.
NOT_TASTE = re.compile(r"^(font\.|text\.|mathtext\.|figure\.(figsize|dpi)|savefig\.|pdf\.|ps\.|svg\.|backend"
                       r"|.*labelsize$|.*titlesize$|legend\.(title_)?fontsize$|axes\.prop_cycle$|image\.cmap$"
                       r"|interactive$|toolbar$|webagg|keymap\.|animation\.|path\.|agg\.|docstring|date\."
                       r"|figure\.(constrained_layout|autolayout|subplot)|lines\.markersize$)")

_SVG = "{http://www.w3.org/2000/svg}"
_SKIP_TAGS = {f"{_SVG}{t}" for t in ("defs", "symbol", "clipPath", "mask", "pattern", "use", "image", "text")}


# ──────────────────────────────────────────────────────────────────────────
# Evidence
# ──────────────────────────────────────────────────────────────────────────

class Evidence:
    """Everything observed, before deciding."""

    def __init__(self):
        self.units = []                         # (kind, name): a PDF page or a script
        self.colour_uses = []                   # (unit index, hex, rank in that unit, weight)
        self.palettes = []                      # (source, [hex, ...]) explicit colour lists
        self.cmaps = Counter()                  # name -> number of units that use it
        self.cmap_where = defaultdict(list)
        self.rc_explicit = defaultdict(list)    # key -> [(value, source)]
        self.axes_votes = defaultdict(list)     # key -> [value per axes]
        self.widths = defaultdict(list)         # key -> [value per unit]
        self.fonts = Counter()                  # family -> number of PDFs
        self.n_pdfs = 0
        self.notes = []

    def unit(self, kind, name):
        self.units.append((kind, name))
        return len(self.units) - 1


# ──────────────────────────────────────────────────────────────────────────
# PDF drawings, through pdftocairo's SVG
# ──────────────────────────────────────────────────────────────────────────

def _parse_colour(v):
    if not v or v == "none":
        return None
    v = v.strip()
    m = re.match(r"rgb\(\s*([\d.]+)(%?)\s*,\s*([\d.]+)(%?)\s*,\s*([\d.]+)(%?)\s*\)", v)
    if m:
        vals = [float(m.group(i)) / (100.0 if m.group(i + 1) else 255.0) for i in (1, 3, 5)]
        return np.clip(vals, 0, 1)
    try:
        return C.to_rgb(v)
    except ValueError:
        return None


def _parse_transform(t):
    M = np.eye(3)
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", t or ""):
        a = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        if name == "matrix" and len(a) == 6:
            T = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        elif name == "translate":
            T = np.array([[1, 0, a[0]], [0, 1, a[1] if len(a) > 1 else 0], [0, 0, 1]])
        elif name == "scale":
            sy = a[1] if len(a) > 1 else a[0]
            T = np.diag([a[0], sy, 1.0])
        else:
            continue
        M = M @ T
    return M


def _subpaths(d):
    """Absolute points of each subpath; curves are kept as their end points. Also whether only lines were used."""
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d or "")
    subs, cur, straight = [], [], True
    x = y = 0.0
    start = (0.0, 0.0)
    i, cmd = 0, None
    nargs = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7}
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(start)
                    subs.append(cur)
                cur = []
                x, y = start
                continue
        if cmd is None:
            break
        n = nargs[cmd.upper()]
        if i + n > len(toks):
            break
        a = [float(v) for v in toks[i:i + n]]
        i += n
        rel = cmd.islower()
        U = cmd.upper()
        if U == "M":
            if cur:
                subs.append(cur)
            x, y = (x + a[0], y + a[1]) if rel else (a[0], a[1])
            start = (x, y)
            cur = [(x, y)]
            cmd = "l" if rel else "L"  # further pairs are line-tos
            continue
        if U == "H":
            x = x + a[0] if rel else a[0]
        elif U == "V":
            y = y + a[0] if rel else a[0]
        else:
            x, y = (x + a[-2], y + a[-1]) if rel else (a[-2], a[-1])
            if U != "L":
                straight = False
        cur.append((x, y))
    if cur:
        subs.append(cur)
    return subs, straight


def _walk(el, M, style, out):
    if el.tag in _SKIP_TAGS:
        return
    st = dict(style)
    for k in ("fill", "stroke", "stroke-width", "fill-opacity", "stroke-opacity"):
        if el.get(k) is not None:
            st[k] = el.get(k)
    for item in (el.get("style") or "").split(";"):
        if ":" in item:
            k, v = item.split(":", 1)
            st[k.strip()] = v.strip()
    if el.get("transform"):
        M = M @ _parse_transform(el.get("transform"))
    if el.tag == f"{_SVG}path":
        subs, straight = _subpaths(el.get("d"))
        if subs:
            pts = [np.array([(M @ [px, py, 1])[:2] for px, py in s]) for s in subs]
            scale = math.sqrt(abs(np.linalg.det(M[:2, :2]))) or 1.0
            out.append({
                "subs": pts, "straight": straight,
                "stroke": _parse_colour(st.get("stroke")), "fill": _parse_colour(st.get("fill", "black")),
                "width": float(st.get("stroke-width", 1.0)) * scale,
                "stroke_alpha": float(st.get("stroke-opacity", 1)), "fill_alpha": float(st.get("fill-opacity", 1)),
            })
    for child in el:
        _walk(child, M, st, out)


def _page_paths(pdf, page, tmp):
    svg = Path(tmp) / f"p{page}.svg"
    res = subprocess.run(["pdftocairo", "-svg", "-f", str(page), "-l", str(page), str(pdf), str(svg)],
                         capture_output=True, text=True, timeout=120)
    if res.returncode != 0 or not svg.exists():
        return []
    root = ET.parse(svg).getroot()
    out = []
    _walk(root, np.eye(3), {"fill": "none"}, out)
    return out


def _lab(rgb):
    return C.rgb_to_lab(np.asarray(rgb, dtype=float))


def _chroma(lab):
    return float(np.hypot(lab[1], lab[2]))


def _segments(paths, dark=True):
    """Straight segments of achromatic stroked paths: (x0, y0, x1, y1, width, L*)."""
    segs = []
    for p in paths:
        if p["stroke"] is None or not p["straight"] or p["stroke_alpha"] < 0.3:
            continue
        lab = _lab(p["stroke"])
        if _chroma(lab) > CHROMA_MIN or (dark and lab[0] > 50):
            continue
        for s in p["subs"]:
            for a, b in zip(s[:-1], s[1:]):
                if np.hypot(*(b - a)) > 0.05:
                    segs.append((a[0], a[1], b[0], b[1], p["width"], lab[0]))
    return segs


def _axes_frames(segs):
    """Axes found from a left and a bottom spine that meet at a corner (SVG y points down)."""
    vert = [s for s in segs if abs(s[0] - s[2]) < 0.3 and abs(s[1] - s[3]) >= 30 and s[5] < 40]
    hor = [s for s in segs if abs(s[1] - s[3]) < 0.3 and abs(s[0] - s[2]) >= 30 and s[5] < 40]
    frames = []
    for v in vert:
        vx, vy0, vy1 = v[0], min(v[1], v[3]), max(v[1], v[3])
        for h in hor:
            hy, hx0, hx1 = h[1], min(h[0], h[2]), max(h[0], h[2])
            if abs(hx0 - vx) < 1.5 and abs(hy - vy1) < 1.5:
                f = {"x0": vx, "x1": hx1, "top": vy0, "bottom": hy, "spine_w": [v[4], h[4]]}
                if not any(abs(f["x0"] - g["x0"]) < 1 and abs(f["bottom"] - g["bottom"]) < 1 for g in frames):
                    frames.append(f)
    return frames


def _ticks_on(segs, f, edge):
    """Short segments touching one edge of an axes frame: [(direction, length, width, position)]."""
    out = []
    horiz_edge = edge in ("bottom", "top")
    line = f[edge] if horiz_edge else f["x0" if edge == "left" else "x1"]
    lo, hi = (f["x0"], f["x1"]) if horiz_edge else (f["top"], f["bottom"])
    inside_sign = {"bottom": -1, "top": 1, "left": 1, "right": -1}[edge]  # towards the plot area
    for x0, y0, x1, y1, w, _ in segs:
        if horiz_edge:
            if abs(x0 - x1) > 0.3:
                continue
            pos, a, b = x0, y0, y1
        else:
            if abs(y0 - y1) > 0.3:
                continue
            pos, a, b = y0, x0, x1
        length = abs(b - a)
        if not 0.8 <= length <= 12 or not lo - 0.5 <= pos <= hi + 0.5:
            continue
        da, db = a - line, b - line
        if abs(da) < 0.6 or abs(db) < 0.6:
            far = db if abs(da) < 0.6 else da
            direction = "in" if np.sign(far) == inside_sign else "out"
        elif np.sign(da) != np.sign(db) and min(abs(da), abs(db)) > 0.6:
            direction = "inout"
        else:
            continue
        out.append((direction, length, w, pos))
    return out


def _edge_has_spine(segs, f, edge):
    if edge == "top":
        return any(abs(s[1] - s[3]) < 0.3 and abs(s[1] - f["top"]) < 1 and abs(s[0] - s[2]) > 0.8 * (f["x1"] - f["x0"])
                   and s[5] < 40 for s in segs)
    return any(abs(s[0] - s[2]) < 0.3 and abs(s[0] - f["x1"]) < 1 and abs(s[1] - s[3]) > 0.8 * (f["bottom"] - f["top"])
               and s[5] < 40 for s in segs)


def _split_ticks(ticks):
    """(major, minor) by length; minor only if there are two clear lengths."""
    if len(ticks) < 2:
        return ticks, []
    lens = np.array([t[1] for t in ticks])
    if lens.max() / lens.min() < 1.3:
        return ticks, []
    cut = math.sqrt(lens.max() * lens.min())
    return [t for t in ticks if t[1] >= cut], [t for t in ticks if t[1] < cut]


def _evenly_spaced(minor):
    pos = np.sort([t[3] for t in minor])
    gaps = np.diff(pos)
    gaps = gaps[gaps > 0.3]
    if len(gaps) < 3:
        return False
    # minor ticks of a linear axis repeat evenly; on a log axis they bunch up towards each decade
    return float(np.median(np.abs(gaps - np.median(gaps)))) < 0.08 * float(np.median(gaps))


def _grid_lines(paths, f):
    """Long straight lines inside the frame, parallel to an edge, not on it."""
    w, h = f["x1"] - f["x0"], f["bottom"] - f["top"]
    lines = []
    for p in paths:
        if p["stroke"] is None or not p["straight"]:
            continue
        lab = _lab(p["stroke"])
        if _chroma(lab) > CHROMA_MIN:
            continue
        for s in p["subs"]:
            for a, b in zip(s[:-1], s[1:]):
                if abs(a[1] - b[1]) < 0.3 and abs(a[0] - b[0]) > 0.9 * w and f["top"] + 1 < a[1] < f["bottom"] - 1:
                    lines.append(("y", p["width"], lab[0], p["stroke"], p["stroke_alpha"]))
                elif abs(a[0] - b[0]) < 0.3 and abs(a[1] - b[1]) > 0.9 * h and f["x0"] + 1 < a[0] < f["x1"] - 1:
                    lines.append(("x", p["width"], lab[0], p["stroke"], p["stroke_alpha"]))
    return lines


_CMAP_LABS = None


def _cmap_labs():
    """CIELAB samples of every continuous matplotlib colormap, computed once."""
    global _CMAP_LABS
    if _CMAP_LABS is None:
        import matplotlib as mpl
        _CMAP_LABS = {}
        for name in mpl.colormaps:
            cm = mpl.colormaps[name]
            if name.endswith("_r") or getattr(cm, "N", 256) < 64:
                continue  # reversed maps hold the same colours; qualitative maps are palettes, not colormaps
            _CMAP_LABS[name] = C.rgb_to_lab(cm(np.linspace(0, 1, 160))[:, :3])
    return _CMAP_LABS


def _cmap_fit(labs, samples):
    d = C.delta_e(labs[:, None, :], samples[None, :, :])
    near = d.min(axis=1) < CMAP_MATCH
    idx = d.argmin(axis=1)
    span = float(np.percentile(idx, 95) - np.percentile(idx, 5)) / (len(samples) - 1)
    return float(np.mean(near)), span, near


def _match_cmap(rgbs, prefer=()):
    """The matplotlib colormap these colours lie on, or None. rgbs: (n, 3) distinct colours.

    Returns (name, on-map mask, the colours tested). `prefer` names are tried first (a page's
    panels usually share one map)."""
    rgbs = np.asarray(rgbs, dtype=float)
    if len(rgbs) > 200:
        rgbs = rgbs[np.random.default_rng(0).choice(len(rgbs), 200, replace=False)]
    labs = C.rgb_to_lab(rgbs)
    if np.median(np.hypot(labs[:, 1], labs[:, 2])) < 5:
        return None  # a grey image: a photo, a mask or a grey map, not a choice of colours
    maps = _cmap_labs()
    for name in prefer:
        if name in maps:
            frac, span, near = _cmap_fit(labs, maps[name])
            if frac >= 0.9 and span >= 0.3:
                return name, near, rgbs
    quick = labs[:: max(1, len(labs) // 30)]
    best = None
    for name, samples in maps.items():
        if _cmap_fit(quick, samples)[0] < 0.7:
            continue
        frac, span, near = _cmap_fit(labs, samples)
        if frac >= 0.9 and span >= 0.3 and (best is None or (frac, span) > best[0]):
            best = ((frac, span), name, near)
    return None if best is None else (best[1], best[2], rgbs)


def _page_images(pdf, page, tmp):
    import matplotlib.image as mpimg
    prefix = Path(tmp) / f"img{page}"
    subprocess.run(["pdfimages", "-png", "-f", str(page), "-l", str(page), str(pdf), str(prefix)],
                   capture_output=True, timeout=120)
    out = []
    for f in sorted(Path(tmp).glob(f"img{page}-*.png")):
        try:
            a = mpimg.imread(f)
        except Exception:  # noqa: BLE001 - an image we cannot read is not evidence
            continue
        if a.ndim != 3 or a.shape[0] * a.shape[1] < 64:
            continue
        rgb = a[..., :3].reshape(-1, 3)
        if rgb.dtype != np.float32 and rgb.max() > 1:
            rgb = rgb / 255.0
        uniq = np.unique(np.round(rgb * 255).astype(int), axis=0) / 255.0
        if len(uniq) >= 12:
            out.append(uniq)
        f.unlink()
    return out


def _pdf_fonts(pdf):
    if not shutil.which("pdffonts"):
        return []
    res = subprocess.run(["pdffonts", str(pdf)], capture_output=True, text=True)
    names = []
    for line in res.stdout.splitlines()[2:]:
        if line.strip():
            names.append(line.split()[0].split("+")[-1])
    return names


def _font_family(names):
    fams = Counter()
    for n in names:
        low = n.lower()
        if low.startswith(("cm", "sfrm", "sfti", "lm", "ec", "msam", "msbm")):
            fams["Computer Modern"] += 1
        elif any(k in low for k in ("helvetica", "arial", "nimbussan", "nimbus sans", "heros", "liberationsans",
                                    "arimo")):
            fams["Helvetica/Arial"] += 1
        elif any(k in low for k in ("times", "termes", "nimbusrom", "newtx", "stix")):
            fams["Times"] += 1
        elif "dejavu" in low:
            fams["DejaVu Sans (matplotlib's default)"] += 1
        else:
            fams[re.sub(r"[-,].*", "", n)] += 1
    return fams.most_common(1)[0][0] if fams else None


def read_pdf(ev, pdf, max_pages=60):
    if not shutil.which("pdftocairo"):
        ev.notes.append(f"{pdf.name}: poppler-utils (pdftocairo) not installed; PDF not read")
        return
    info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", info)
    n_pages = min(int(m.group(1)) if m else 1, max_pages)
    ev.n_pdfs += 1
    fam = _font_family(_pdf_fonts(pdf))
    if fam:
        ev.fonts[fam] += 1
    with tempfile.TemporaryDirectory() as tmp:
        for page in range(1, n_pages + 1):
            paths = _page_paths(pdf, page, tmp)
            images = _page_images(pdf, page, tmp)
            name = pdf.name if n_pages == 1 else f"{pdf.name} p.{page}"
            _read_drawing(ev, name, paths, images)


def _read_drawing(ev, name, paths, images):
    segs = _segments(paths, dark=False)
    frames = [f for f in _axes_frames(segs)
              if (f["x1"] - f["x0"]) / max(f["bottom"] - f["top"], 1e-9) < 6
              and (f["bottom"] - f["top"]) / max(f["x1"] - f["x0"], 1e-9) < 6]  # not colorbars
    # colours of data, in drawing order
    uses = []
    fills = []
    data_widths = []
    for p in paths:
        if p["stroke"] is not None and p["stroke_alpha"] > 0.05:
            n_pts = sum(len(s) for s in p["subs"])
            length = sum(float(np.sum(np.hypot(*np.diff(s, axis=0).T))) for s in p["subs"] if len(s) > 1)
            lab = _lab(p["stroke"])
            if _chroma(lab) >= CHROMA_MIN and (n_pts >= 3 or length >= 8):
                uses.append((p["stroke"], length))
                closed = all(len(s) > 2 and np.allclose(s[0], s[-1], atol=0.05) for s in p["subs"])
                if n_pts >= 3 and p["fill"] is None and not closed and length >= 10:
                    data_widths.append(p["width"])  # a data line, not the outline of a marker or bar
        if p["fill"] is not None and p["fill_alpha"] > 0.05:
            lab = _lab(p["fill"])
            if _chroma(lab) >= CHROMA_MIN and lab[0] < 97:
                fills.append(p["fill"])
    # many distinct fill colours: a colormap drawn as vector cells
    distinct = np.unique(np.round(np.array(fills) * 255).astype(int), axis=0) / 255.0 if fills else np.zeros((0, 3))
    on_map = set()
    sources = list(images)
    if len(distinct) >= 20:
        sources.append(distinct)
    unit = None
    found = []
    for rgbs in sources:
        m = _match_cmap(rgbs, prefer=found)
        if m:
            found.append(m[0])
            unit = ev.unit("pdf", name) if unit is None else unit
            if name not in ev.cmap_where[m[0]]:  # an image and its colorbar are one use
                ev.cmaps[m[0]] += 1
                ev.cmap_where[m[0]].append(name)
            if rgbs is distinct:
                on_map |= {tuple(np.round(c * 255).astype(int)) for c, ok in zip(m[2], m[1]) if ok}
    uses += [(c, 1.0) for c in fills if tuple(np.round(c * 255).astype(int)) not in on_map]
    if not uses and not frames:
        return
    unit = ev.unit("pdf", name) if unit is None else unit
    _record_colours(ev, unit, [C.to_hex(c) for c, _ in uses], [w for _, w in uses])
    if data_widths:
        ev.widths["lines.linewidth"].append(float(np.median(data_widths)))
    _read_axes(ev, paths, segs, frames)


def _read_axes(ev, paths, segs, frames):
    dark = [s for s in segs if s[5] < 60]
    for f in frames:
        ticks = {e: _ticks_on(dark, f, e) for e in ("bottom", "top", "left", "right")}
        if len(ticks["bottom"]) + len(ticks["left"]) < 2:
            continue  # a box, not a plot
        ev.widths["axes.linewidth"].append(float(np.median(f["spine_w"])))
        ev.axes_votes["axes.spines.top"].append(_edge_has_spine(dark, f, "top"))
        ev.axes_votes["axes.spines.right"].append(_edge_has_spine(dark, f, "right"))
        for axis, main, other in (("x", "bottom", "top"), ("y", "left", "right")):
            major, minor = _split_ticks(ticks[main])
            if major:
                ev.axes_votes[f"{axis}tick.direction"].append(Counter(t[0] for t in major).most_common(1)[0][0])
                ev.widths[f"{axis}tick.major.size"].append(float(np.median([t[1] for t in major])))
                ev.widths[f"{axis}tick.major.width"].append(float(np.median([t[2] for t in major])))
                ev.axes_votes[f"{axis}tick.{other}"].append(len(ticks[other]) >= max(1, len(ticks[main]) // 2))
                if minor and _evenly_spaced(minor):
                    ev.axes_votes[f"{axis}tick.minor.visible"].append(True)
                elif not minor:
                    ev.axes_votes[f"{axis}tick.minor.visible"].append(False)
                # uneven minor ticks: a log axis, which shows them whatever the setting; no vote
        grid = _grid_lines(paths, f)
        has_grid = sum(1 for g in grid if g[0] == "y") >= 3 or sum(1 for g in grid if g[0] == "x") >= 3
        ev.axes_votes["axes.grid"].append(has_grid)
        if has_grid:
            ev.widths["grid.linewidth"].append(float(np.median([g[1] for g in grid])))
            ev.axes_votes["grid.color"].append(C.to_hex(np.median([g[3] for g in grid], axis=0)))
            ev.widths["grid.alpha"].append(float(np.median([g[4] for g in grid])))


def _record_colours(ev, unit, hexes, weights):
    """Colours of one unit, each with its rank: the order of first appearance among the unit's distinct colours."""
    weight = defaultdict(float)
    for h, w in zip(hexes, weights):
        weight[h] += w
    firsts, rank = [], {}
    for h in weight:  # dicts keep first-appearance order
        lab = _lab(C.to_rgb(h))
        r = next((r for f, r in firsts if C.delta_e(lab, f) < SAME_COLOUR), None)
        if r is None:
            r = len(firsts)
            firsts.append((lab, r))
        rank[h] = r
    for h, w in weight.items():
        ev.colour_uses.append((unit, h, rank[h], w))


# ──────────────────────────────────────────────────────────────────────────
# Scripts and style files
# ──────────────────────────────────────────────────────────────────────────

_COLOUR_KW = {"color", "c", "colors", "facecolor", "edgecolor", "mfc", "mec", "markerfacecolor", "markeredgecolor",
              "ecolor", "fc", "ec"}


def _is_colour(s):
    if not isinstance(s, str) or re.fullmatch(r"C\d", s) or s.lower() in ("none", "auto", "inherit"):
        return False
    try:
        C.to_rgb(s)
        return True
    except ValueError:
        return False


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def read_rc_file(ev, path, source=None):
    """A .mplstyle or matplotlibrc file: key: value lines."""
    import matplotlib as mpl
    source = source or Path(path).name
    try:
        rc = mpl.rc_params_from_file(str(path), use_default_template=False, fail_on_error=False)
    except Exception as exc:  # noqa: BLE001
        ev.notes.append(f"{Path(path).name}: could not read ({exc})")
        return
    _add_rc(ev, dict(rc), source)


def _add_rc(ev, rc, source):
    from cycler import Cycler
    for k, v in rc.items():
        if k == "axes.prop_cycle" and isinstance(v, Cycler) and "color" in v.keys:
            cols = [c for c in v.by_key()["color"] if _is_colour(c)]
            if cols:
                ev.palettes.append((source, [C.to_hex(C.to_rgb(c)) for c in cols]))
        elif k == "image.cmap":
            ev.cmaps[str(v)] += 1
            ev.cmap_where[str(v)].append(source)
        elif not NOT_TASTE.match(k):
            ev.rc_explicit[k].append((v, source))


def read_script(ev, path):
    import matplotlib as mpl
    import matplotlib.style as mstyle
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        ev.notes.append(f"{Path(path).name}: could not read ({exc})")
        return
    name = Path(path).name
    unit = ev.unit("script", name)
    colours, rc = [], {}
    for node in ast.walk(tree):
        # explicit colour lists: colours = ['#...', ...] or cycler(color=[...])
        if isinstance(node, (ast.List, ast.Tuple)) and len(node.elts) >= 3:
            vals = [_literal(e) for e in node.elts]
            if all(_is_colour(v) for v in vals):
                ev.palettes.append((name, [C.to_hex(C.to_rgb(v)) for v in vals]))
        if isinstance(node, ast.Call):
            fn = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            for kw in node.keywords:
                v = _literal(kw.value)
                if kw.arg in _COLOUR_KW and _is_colour(v):
                    colours.append(C.to_hex(C.to_rgb(v)))
                elif kw.arg == "cmap" and isinstance(v, str) and v in mpl.colormaps and name not in ev.cmap_where[v]:
                    ev.cmaps[v] += 1
                    ev.cmap_where[v].append(name)
            # rcParams.update({...}) and rc("group", key=value)
            if fn == "update" and isinstance(node.func, ast.Attribute) and "rcParams" in ast.unparse(node.func.value):
                d = _literal(node.args[0]) if node.args else None
                if isinstance(d, dict):
                    rc.update(d)
            if fn == "rc" and node.args and isinstance(_literal(node.args[0]), str):
                group = _literal(node.args[0])
                for kw in node.keywords:
                    v = _literal(kw.value)
                    if v is not None:
                        rc[f"{group}.{kw.arg}"] = v
            # style.use('ggplot') or style.use('my.mplstyle')
            if fn == "use" and node.args and "style" in ast.unparse(node.func):
                v = _literal(node.args[0])
                for s in (v if isinstance(v, list) else [v]):
                    if not isinstance(s, str):
                        continue
                    p = (Path(path).parent / s).expanduser()
                    if p.is_file():
                        read_rc_file(ev, p, f"{name} -> {p.name}")
                    elif s in mstyle.library:
                        _add_rc(ev, dict(mstyle.library[s]), f"{name} -> style {s}")
        # rcParams["key"] = value
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and "rcParams" in ast.unparse(t.value):
                    k, v = _literal(t.slice), _literal(node.value)
                    if isinstance(k, str) and v is not None:
                        rc[k] = v
    valid = {}
    for k, v in rc.items():
        if k in mpl.rcParams:
            try:
                valid[k] = mpl.rcParams.validate[k](v)
            except (ValueError, TypeError):
                continue
    _add_rc(ev, valid, name)
    _record_colours(ev, unit, colours, [1.0] * len(colours))


# ──────────────────────────────────────────────────────────────────────────
# Deciding
# ──────────────────────────────────────────────────────────────────────────

def _house_rc():
    import matplotlib as mpl
    from style_profile import HOUSE_STYLE
    rc = dict(mpl.rcParamsDefault)
    rc.update(dict(mpl.rc_params_from_file(str(HOUSE_STYLE), use_default_template=False)))
    return rc


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= 0.15 * max(abs(b), 1e-9)
    if isinstance(a, str) and isinstance(b, str) and _is_colour(a) and _is_colour(b):
        return C.to_hex(C.to_rgb(a)) == C.to_hex(C.to_rgb(b))
    return str(a) == str(b)


def _clusters(ev):
    """Colours used across units, merged when they are the same colour."""
    totals = Counter()
    for _, h, _, w in ev.colour_uses:
        totals[h] += w
    reps = []
    for h, _ in totals.most_common():
        lab = _lab(C.to_rgb(h))
        if _chroma(lab) < CHROMA_MIN:
            continue
        if not any(C.delta_e(lab, _lab(C.to_rgb(r))) < SAME_COLOUR for r in reps):
            reps.append(h)
    info = {r: {"units": set(), "ranks": [], "weight": 0.0} for r in reps}
    for unit, h, rank, w in ev.colour_uses:
        lab = _lab(C.to_rgb(h))
        for r in reps:
            if C.delta_e(lab, _lab(C.to_rgb(r))) < SAME_COLOUR:
                info[r]["units"].add(unit)
                info[r]["ranks"].append(rank)
                info[r]["weight"] += w
                break
    return info


def _cmap_kind(name):
    """'diverging' when the middle of the map is clearly lighter or darker than both ends."""
    import matplotlib as mpl
    L = C.rgb_to_lab(mpl.colormaps[name](np.linspace(0, 1, 65))[:, :3])[:, 0]
    mid = L[32]
    return "diverging" if (mid - L[0] > 15 and mid - L[-1] > 15) or (L[0] - mid > 15 and L[-1] - mid > 15) \
        else "sequential"


def decide(ev, agree=AGREE):
    import matplotlib as mpl
    from colours import check_colormap
    house = _house_rc()
    out = {"palette": None, "palette_note": "", "colormaps": {}, "cmap_notes": [], "rc": {}, "rc_notes": {},
           "same_as_house": [], "undecided": [], "font_note": ""}

    # palette: an explicit list wins (the most common one); else the colours used, most used first
    n_units = len(ev.units)
    if ev.palettes:
        lists = [tuple(p) for _, p in ev.palettes]
        # a list that starts another one supports it: a style's cycle extended in a script is one palette
        support = {cand: sum(1 for p in lists if cand[:len(p)] == p) for cand in set(lists)}
        best = max(support, key=lambda c: (support[c], len(c)))
        where = sorted({s for s, p in ev.palettes if best[:len(p)] == tuple(p)})
        out["palette"] = list(best)[:MAX_PALETTE]
        out["palette_note"] = f"the colour list in {', '.join(where)}"
    else:
        info = _clusters(ev)
        min_units = 1 if n_units <= 2 else max(2, math.ceil(0.2 * n_units))
        kept = [(r, d) for r, d in info.items() if len(d["units"]) >= min_units]
        kept.sort(key=lambda rd: (-len(rd[1]["units"]), float(np.mean(rd[1]["ranks"]))))
        out["palette_rare"] = [(r, sorted(ev.units[u][1] for u in d["units"])) for r, d in info.items()
                               if len(d["units"]) < min_units][:5]
        if kept:
            out["palette"] = [r for r, _ in kept[:MAX_PALETTE]]
            out["palette_units"] = {r: len(d["units"]) for r, d in kept[:MAX_PALETTE]}
            out["palette_note"] = (f"the colours of data in {n_units} figure(s) and script(s), most used first; "
                                   f"a colour needed {min_units} of them to count")

    # colormaps
    from style_profile import HOUSE_COLORMAPS
    for name, n in ev.cmaps.most_common():
        where = ", ".join(sorted(set(ev.cmap_where[name]))[:4]) + (" and more" if n > 4 else "")
        base = name[:-2] if name.endswith("_r") else name
        if base in C.BAD_CMAPS:  # a rule, not taste
            out["cmap_notes"].append(f"{name} (used in {n}: {where}) is not kept: "
                                     + check_colormap(name, "sequential")["problem"])
            continue
        kind = _cmap_kind(name)
        if kind in out["colormaps"]:
            out["cmap_notes"].append(f"{name} ({kind}) is also used, in {n}: {where}")
            continue
        chk = check_colormap(name, kind)
        note = f"used in {n}: {where}" + ("" if chk["ok"] else f"; note: {chk['problem']}")
        out["colormaps"][kind] = (name, note)

    for kind in list(out["colormaps"]):
        if out["colormaps"][kind][0] == HOUSE_COLORMAPS[kind]:
            out["same_as_house"].append(f"colormaps.{kind}")
            del out["colormaps"][kind]

    # rc: explicit settings from scripts and style files
    for key, vals in sorted(ev.rc_explicit.items()):
        cnt = Counter(str(v) for v, _ in vals)
        val_s, n = cnt.most_common(1)[0]
        value = next(v for v, _ in vals if str(v) == val_s)
        srcs = sorted({s for v, s in vals if str(v) == val_s})
        if n / len(vals) < agree:
            out["undecided"].append(f"{key}: set to different values ({dict(cnt)})")
            continue
        if _same(value, house.get(key)):
            out["same_as_house"].append(key)
            continue
        out["rc"][key] = value
        out["rc_notes"][key] = f"set in {', '.join(srcs[:3])}" + (" and more" if len(srcs) > 3 else "")

    # rc: from the axes in PDFs (explicit settings win)
    for key, votes in sorted(ev.axes_votes.items()):
        if key in out["rc"] or not votes or key == "grid.color":
            continue
        val, n = Counter(votes).most_common(1)[0]
        if n / len(votes) < agree:
            out["undecided"].append(f"{key}: {dict(Counter(map(str, votes)))} over {len(votes)} axes")
            continue
        if _same(val, house.get(key)):
            out["same_as_house"].append(key)
            continue
        out["rc"][key] = val
        out["rc_notes"][key] = f"{n} of {len(votes)} axes"
    grid_on = out["rc"].get("axes.grid", house.get("axes.grid"))
    for key, vals in sorted(ev.widths.items()):
        if key in out["rc"] or not vals or (key.startswith("grid.") and not grid_on):
            continue
        med = float(np.median(vals))
        spread = float(np.median(np.abs(np.array(vals) - med)))
        value = round(med, 2) if key == "grid.alpha" else round(med * 10) / 10
        if spread > 0.25 * max(med, 1e-9):
            out["undecided"].append(f"{key}: varies ({min(vals):.2g} to {max(vals):.2g})")
            continue
        if _same(value, house.get(key)):
            out["same_as_house"].append(key)
            continue
        out["rc"][key] = value
        out["rc_notes"][key] = f"median of {len(vals)}"
    if grid_on and ev.axes_votes.get("grid.color") and "grid.color" not in out["rc"]:
        val, n = Counter(ev.axes_votes["grid.color"]).most_common(1)[0]
        if not _same(val, house.get("grid.color")):
            out["rc"]["grid.color"] = val
            out["rc_notes"]["grid.color"] = f"{n} of {len(ev.axes_votes['grid.color'])} axes with a grid"
    # keep only settings matplotlib accepts, in the form it accepts
    for key in list(out["rc"]):
        try:
            mpl.rcParams.validate[key](out["rc"][key])
        except (ValueError, TypeError, KeyError):
            out["undecided"].append(f"{key}: value {out['rc'][key]!r} not accepted by matplotlib")
            del out["rc"][key]

    if ev.fonts:
        fam, n = ev.fonts.most_common(1)[0]
        out["font_note"] = f"your PDFs used {fam} ({n} of {ev.n_pdfs})"
    return out


# ──────────────────────────────────────────────────────────────────────────
# Entry point and output
# ──────────────────────────────────────────────────────────────────────────

def gather(paths):
    ev = Evidence()
    for p in paths:
        p = Path(p).expanduser()
        if not p.is_file():
            ev.notes.append(f"{p}: not found")
            continue
        suf = p.suffix.lower()
        if suf == ".pdf":
            read_pdf(ev, p)
        elif suf == ".py":
            read_script(ev, p)
        elif suf == ".mplstyle" or p.name == "matplotlibrc":
            ev.unit("style", p.name)
            read_rc_file(ev, p)
        else:
            ev.notes.append(f"{p.name}: not a PDF, .py, .mplstyle or matplotlibrc; skipped")
    return ev


def _yaml_scalar(v):
    import yaml
    return yaml.safe_dump(v, default_flow_style=True, width=1000).strip().removesuffix("...").strip()


def render(decision, ev, inputs, name="Learned style"):
    """The draft profile as YAML text with a comment on every entry."""
    from colours import check_palette, describe, suggest_palette
    today = _dt.date.today().isoformat()
    shown = ", ".join(Path(p).name for p in inputs[:6]) + (f" and {len(inputs) - 6} more" if len(inputs) > 6 else "")
    L = [f"# Learned by braindance on {today} from {len(inputs)} file(s): {shown}",
         f"# ({len(ev.units)} figure page(s) and script(s) with evidence.) Every entry says where it came from;",
         "# edit freely, then check with:  python style_profile.py check <this file> --swatch swatch.png",
         "", f"name: {_yaml_scalar(name)}", ""]
    pal = decision["palette"]
    if pal:
        L.append(f"# palette: {decision['palette_note']}")
        units = decision.get("palette_units")
        if units:
            L.append("#   " + ", ".join(f"{c} in {units[c]}" for c in pal))
        L.append("palette: [" + ", ".join(f"'{c}'" for c in pal) + "]")
        res = check_palette(pal)
        if not res["ok"]:
            sug = suggest_palette(pal)
            L.append("# " + describe(res).replace("\n", "\n# "))
            L.append("# the nearest palette with the same hues (not applied; your choice):")
            L.append("#   palette: [" + ", ".join(f"'{c}'" for c in sug["colours"]) + "]")
        if decision.get("palette_rare"):
            L.append("# seen in one figure only, so left out (add them if they are yours): "
                     + "; ".join(f"{c} ({', '.join(w[:2])})" for c, w in decision["palette_rare"]))
    else:
        L.append("# palette: no colours of data found; the house palette stays")
    L.append("")
    cms = decision["colormaps"]
    if cms:
        L.append("colormaps:")
        for kind, (cm, note) in cms.items():
            L.append(f"  {kind}: {cm}   # {note}")
    for n in decision["cmap_notes"]:
        L.append(f"# colormap {n}")
    L.append("")
    note = decision["font_note"]
    L.append("# font: Computer Modern, as always unless you ask for another"
             + (f"; {note}. To change it: font: helvetica, times, or a mapping" if note and
                not note.startswith("your PDFs used Computer Modern") else (f"; {note}" if note else "")))
    L.append("font: computer-modern")
    L.append("")
    if decision["rc"]:
        L.append("rc:")
        for k, v in decision["rc"].items():
            L.append(f"  {k}: {_yaml_scalar(v)}   # {decision['rc_notes'][k]}")
    else:
        L.append("rc: {}")
    if decision["same_as_house"]:
        L.append("# already as in the house style: " + ", ".join(sorted(set(decision["same_as_house"]))))
    if decision["undecided"]:
        L.append("# not set, the evidence does not agree:")
        L += [f"#   {u}" for u in decision["undecided"]]
    if ev.notes:
        L.append("# notes:")
        L += [f"#   {n}" for n in ev.notes]
    return "\n".join(L) + "\n"


def learn(paths, name="Learned style"):
    """(profile YAML text, decision, evidence) for the given files."""
    paths = [str(p) for p in paths]
    ev = gather(paths)
    decision = decide(ev)
    return render(decision, ev, paths, name), decision, ev


def preview(profile, path):
    """A sample figure drawn with the profile: lines and markers in palette order, and its colormaps."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from style_profile import setup
    setup(profile, quiet=True)
    n = min(len(profile.palette), 6)
    x = np.linspace(0, 4, 40)
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.1), layout="constrained",
                             gridspec_kw={"width_ratios": [1.6, 1, 1]})
    markers = ["o", "s", "^", "D", "v", "P"]
    for k in range(n):
        axes[0].plot(x, np.exp(-0.25 * x) * np.cos(2 * x + k * 0.5) + 0.6 * k, marker=markers[k], markevery=6,
                     label=f"{k + 1}")
    axes[0].set_xlabel(r"Time $t$ (s)")
    axes[0].set_ylabel(r"Signal $x$")
    axes[0].legend(ncol=min(n, 3), loc="upper right", fontsize=7)
    axes[0].set_ylim(top=0.6 * n + 1.6)
    yy, xx = np.mgrid[-2:2:60j, -2:2:60j]
    for ax, kind, z in ((axes[1], "sequential", np.exp(-(xx ** 2 + yy ** 2))),
                        (axes[2], "diverging", xx * np.exp(-(xx ** 2 + yy ** 2) / 2))):
        lim = np.abs(z).max()
        im = ax.pcolormesh(xx, yy, z, cmap=profile.cmap(kind), shading="auto",
                           **({"vmin": -lim, "vmax": lim} if kind == "diverging" else {}))
        ax.set_aspect("equal")
        ax.set_xlabel(r"$x$")
        fig.colorbar(im, ax=ax, shrink=0.8)
        title = f"{kind}: {profile.cmap(kind)}"
        ax.set_title(title.replace("_", r"\_") if plt.rcParams["text.usetex"] else title, fontsize=7)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path
