"""Measured checks for a matplotlib figure, run before the figure is reviewed.

Two families of checks:

  data   The numbers drawn are the numbers in the source files, every declared
         series is in the figure, and no point is hidden by axis limits or a
         log axis.
  style  Width, font sizes, overlapping text, legend or labels on data, axes
         titles, offset text, colormaps, series that differ only by colour, and
         the fonts and page size of the saved PDF.

In a plotting script, after everything is drawn and the PDF is saved:

    from check_figure import check_figure
    check_figure(
        fig,
        sources=[
            {"label": "Data", "file": "spectrum.csv", "x": "f_Hz", "y": "S"},
            {"gid": "run1", "file": "run1.csv", "x": "t", "y": "T", "y_scale": 1e-4},
            {"label": "Fit", "computed": True},
        ],
        target={"width_in": 3.4},
        pdf="figure.pdf",
        script=__file__,
    )

From the shell, for the checks that need no live figure:

    python check_figure.py --pdf figure.pdf --script plot.py --width 3.4

Levels: "fail" means the figure is wrong or unreadable and must be fixed;
"warn" means look at it and fix it unless there is a reason; "info" is a
measurement. The report is printed and, when a PDF path or `out` is given,
written as JSON next to the figure.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

BAD_CMAPS = {"jet", "rainbow", "gist_rainbow", "nipy_spectral", "gist_ncar"}
CM_FONT_PREFIXES = ("cm", "sfrm", "sfti", "sfbx", "lm", "ec", "msam", "msbm", "eufm", "rsfs")


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.findings = []
        self.measured = {}

    def add(self, level, family, check, message, where=""):
        self.findings.append(
            {"level": level, "family": family, "check": check, "where": where, "message": message}
        )

    def count(self, level):
        return sum(f["level"] == level for f in self.findings)

    def as_dict(self):
        return {
            "ok": self.count("fail") == 0,
            "summary": {lv: self.count(lv) for lv in ("fail", "warn", "info")},
            "measured": self.measured,
            "findings": self.findings,
        }

    def text(self):
        d = self.as_dict()
        s = d["summary"]
        lines = [f"check_figure: {'OK' if d['ok'] else 'FAIL'}  "
                 f"({s['fail']} fail, {s['warn']} warn, {s['info']} info)"]
        order = {"fail": 0, "warn": 1, "info": 2}
        for f in sorted(self.findings, key=lambda f: order[f["level"]]):
            where = f" [{f['where']}]" if f["where"] else ""
            lines.append(f"  {f['level'].upper():4} {f['family']:5} {f['check']}{where}: {f['message']}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Reading source files
# --------------------------------------------------------------------------

def load_table(path):
    """Read a delimited text file with a header row into {column name: list of str}."""
    path = Path(path)
    delim = {".csv": ",", ".tsv": "\t"}.get(path.suffix.lower())
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    if not rows:
        raise ValueError(f"{path} has no data rows")
    if delim:
        parsed = list(csv.reader(rows, delimiter=delim))
    else:
        parsed = [ln.split() for ln in rows]
    header = [h.strip() for h in parsed[0]]
    body = parsed[1:]
    return {name: [r[i].strip() if i < len(r) else "" for r in body] for i, name in enumerate(header)}


def _column(table, key, path):
    if isinstance(key, int):
        names = list(table)
        if not -len(names) <= key < len(names):
            raise KeyError(f"{path} has {len(names)} columns, no index {key}")
        return table[names[key]]
    if key not in table:
        raise KeyError(f"{path} has no column {key!r}; columns are {list(table)}")
    return table[key]


def _to_float(values):
    out = np.empty(len(values))
    for i, v in enumerate(values):
        v = v.strip()
        if v.lower() in ("", "nan", "na", "null", "none"):
            out[i] = np.nan
        else:
            try:
                out[i] = float(v)
            except ValueError:
                raise ValueError(f"non-numeric value {v!r}") from None
    return out


def load_array(path, key=None):
    """Read a 2D array for images: .npy, .npz (with key) or a headerless delimited file."""
    path = Path(path)
    if path.suffix == ".npy":
        return np.load(path)
    if path.suffix == ".npz":
        data = np.load(path)
        return data[key if key is not None else data.files[0]]
    return np.loadtxt(path, delimiter="," if path.suffix.lower() == ".csv" else None)


# --------------------------------------------------------------------------
# Reading the numbers back out of the figure
# --------------------------------------------------------------------------

def _label_of(artist):
    lab = artist.get_label() if hasattr(artist, "get_label") else ""
    lab = "" if lab is None else str(lab)
    return "" if lab.startswith("_") else lab


def _errors_from_bars(barlinecols, x, y):
    """Half-lengths of error bars from their line segments. Returns (xerr, yerr)."""
    xerr = yerr = None
    for lc in barlinecols:
        segs = lc.get_segments()
        if not len(segs):
            continue
        segs = np.asarray([s for s in segs if len(s) == 2], dtype=float)
        if not len(segs):
            continue
        vertical = np.allclose(segs[:, 0, 0], segs[:, 1, 0], equal_nan=True)
        if vertical:
            lo, hi = segs[:, :, 1].min(axis=1), segs[:, :, 1].max(axis=1)
            yerr = (hi - lo) / 2.0
        else:
            lo, hi = segs[:, :, 0].min(axis=1), segs[:, :, 0].max(axis=1)
            xerr = (hi - lo) / 2.0
    return xerr, yerr


def series_in_axes(ax, ax_index=0):
    """Every data-carrying artist in an axes, with the numbers it draws."""
    from matplotlib.collections import PathCollection, QuadMesh
    from matplotlib.container import BarContainer, ErrorbarContainer

    out, used = [], set()

    for cont in ax.containers:
        if isinstance(cont, ErrorbarContainer):
            data_line, caplines, barlinecols = cont.lines
            for a in (data_line, *caplines, *barlinecols):
                if a is not None:
                    used.add(id(a))
            if data_line is None:
                continue
            x = np.asarray(data_line.get_xdata(orig=False), dtype=float)
            y = np.asarray(data_line.get_ydata(orig=False), dtype=float)
            xerr, yerr = _errors_from_bars(barlinecols, x, y)
            out.append({
                "kind": "errorbar", "artist": data_line, "ax": ax_index,
                "label": _label_of(cont) or _label_of(data_line),
                "gid": data_line.get_gid() or "", "x": x, "y": y, "xerr": xerr, "yerr": yerr,
            })
        elif isinstance(cont, BarContainer):
            patches = list(cont.patches)
            for p in patches:
                used.add(id(p))
            horizontal = getattr(cont, "orientation", "vertical") == "horizontal"
            if horizontal:
                pos = np.array([p.get_y() + p.get_height() / 2 for p in patches])
                val = np.array([p.get_width() for p in patches])
            else:
                pos = np.array([p.get_x() + p.get_width() / 2 for p in patches])
                val = np.array([p.get_height() for p in patches])
            out.append({
                "kind": "bar", "artist": cont, "ax": ax_index, "label": _label_of(cont),
                "gid": (patches[0].get_gid() or "") if patches else "",
                "x": pos, "y": val, "horizontal": horizontal, "patches": patches,
            })

    for line in ax.lines:
        if id(line) in used:
            continue
        if line.get_transform() != ax.transData:
            continue  # axhline, axvline and other guides not drawn in data coordinates
        x = np.asarray(line.get_xdata(orig=False), dtype=float)
        y = np.asarray(line.get_ydata(orig=False), dtype=float)
        if x.size < 1:
            continue
        out.append({"kind": "line", "artist": line, "ax": ax_index, "label": _label_of(line),
                    "gid": line.get_gid() or "", "x": x, "y": y})

    for coll in ax.collections:
        if id(coll) in used:
            continue
        if isinstance(coll, QuadMesh):
            arr = coll.get_array()
            out.append({"kind": "image", "artist": coll, "ax": ax_index, "label": _label_of(coll),
                        "gid": coll.get_gid() or "", "z": None if arr is None else np.ma.filled(arr, np.nan)})
        elif isinstance(coll, PathCollection):
            if coll.get_offset_transform() != ax.transData:
                continue
            off = np.ma.filled(coll.get_offsets(), np.nan)
            if len(off):
                out.append({"kind": "scatter", "artist": coll, "ax": ax_index, "label": _label_of(coll),
                            "gid": coll.get_gid() or "", "x": off[:, 0].astype(float),
                            "y": off[:, 1].astype(float)})

    for im in ax.images:
        arr = im.get_array()
        out.append({"kind": "image", "artist": im, "ax": ax_index, "label": _label_of(im),
                    "gid": im.get_gid() or "", "z": None if arr is None else np.ma.filled(arr, np.nan)})
    return out


def _colorbar_axes(fig):
    """Axes that hold a colourbar: their colour ramp is not data."""
    out = set()
    for ax in fig.get_axes():
        if ax.get_label() == "<colorbar>":
            out.add(ax)
        for art in list(ax.images) + list(ax.collections):
            cb = getattr(art, "colorbar", None)
            if cb is not None:
                out.add(cb.ax)
    return out


def _all_series(fig):
    skip = _colorbar_axes(fig)
    return [s for i, ax in enumerate(fig.get_axes()) if ax not in skip for s in series_in_axes(ax, i)]


def _name(s):
    ident = s["gid"] or s["label"] or f"unlabelled {s['kind']}"
    return f"ax{s['ax']} {ident!r}"


# --------------------------------------------------------------------------
# Data checks
# --------------------------------------------------------------------------

def _same(plotted, source, rtol):
    plotted, source = np.asarray(plotted, float).ravel(), np.asarray(source, float).ravel()
    if plotted.shape != source.shape:
        return False
    finite = np.isfinite(source)
    scale = np.nanmax(np.abs(source[finite])) if finite.any() else 1.0
    return bool(np.allclose(plotted, source, rtol=rtol, atol=rtol * scale, equal_nan=True))


def _constant_factor(plotted, source):
    plotted, source = np.asarray(plotted, float).ravel(), np.asarray(source, float).ravel()
    if plotted.shape != source.shape:
        return None
    ok = np.isfinite(plotted) & np.isfinite(source) & (source != 0)
    if ok.sum() < 2:
        return None
    ratio = plotted[ok] / source[ok]
    if np.allclose(ratio, ratio[0], rtol=1e-6) and not np.isclose(ratio[0], 1.0):
        return float(ratio[0])
    return None


def _describe_mismatch(plotted, source):
    plotted, source = np.asarray(plotted, float).ravel(), np.asarray(source, float).ravel()
    if plotted.shape != source.shape:
        return f"figure has {plotted.size} points, source has {source.size}"
    k = _constant_factor(plotted, source)
    if k is not None:
        return (f"plotted = {k:.6g} x source at every point; declare the scale factor "
                f"and state it in the axis label, or fix the script")
    if _same(np.sort(plotted), np.sort(source), 1e-6):
        return "same values but in a different order"
    diff = np.abs(plotted - source)
    i = int(np.nanargmax(diff))
    n_bad = int(np.sum(~np.isclose(plotted, source, rtol=1e-6, equal_nan=True)))
    return (f"{n_bad} of {source.size} values differ; largest at index {i}: "
            f"plotted {plotted[i]:.6g}, source {source[i]:.6g}")


def _is_subset(px, py, sx, sy):
    def keys(a, b):
        return {(float(f"{u:.9g}"), float(f"{v:.9g}")) for u, v in zip(a, b)}
    return keys(px, py) <= keys(sx, sy)


def _norm_text(t):
    return re.sub(r"\\mathrm|\\text|\\,|[\\${}\s]", "", str(t)).lower()


def _check_visibility(rep, ax, s, allow_clipped=False, declared=True):
    if s["kind"] == "image" or "x" not in s:
        return
    x, y = s["x"], s["y"]
    where = _name(s)
    finite = np.isfinite(x) & np.isfinite(y)
    n_nan = int((~finite).sum())
    if n_nan:
        rep.add("warn", "data", "missing-values", f"{n_nan} of {x.size} points are NaN or infinite "
                "and are not drawn", where)
    hidden_log = np.zeros(x.size, bool)
    if ax.get_xscale() == "log":
        hidden_log |= finite & (x <= 0)
    if ax.get_yscale() == "log":
        hidden_log |= finite & (y <= 0)
    if hidden_log.any():
        rep.add("fail", "data", "log-axis", f"{int(hidden_log.sum())} of {x.size} points are zero or "
                "negative and cannot be drawn on the log axis", where)
    if s["kind"] == "bar":
        return
    (x0, x1), (y0, y1) = sorted(ax.get_xlim()), sorted(ax.get_ylim())
    tx, ty = 1e-9 * (x1 - x0), 1e-9 * (y1 - y0)
    outside = finite & ~hidden_log & ((x < x0 - tx) | (x > x1 + tx) | (y < y0 - ty) | (y > y1 + ty))
    if outside.any():
        level = "info" if allow_clipped else ("fail" if declared else "warn")
        rep.add(level, "data", "hidden-by-limits", f"{int(outside.sum())} of {x.size} points lie outside "
                f"the axis limits x=[{x0:.4g}, {x1:.4g}], y=[{y0:.4g}, {y1:.4g}]", where)


def _find(series, decl):
    cands = series
    if "ax" in decl:
        cands = [s for s in cands if s["ax"] == decl["ax"]]
    if decl.get("gid"):
        return [s for s in cands if s["gid"] == decl["gid"]]
    if decl.get("label") is not None:
        return [s for s in cands if s["label"] == decl["label"]]
    return []


def check_data(rep, fig, sources, base_dir=".", rtol=1e-6):
    axes = fig.get_axes()
    series = _all_series(fig)
    matched = set()
    loaded = []  # (declaration, source x, source y) for the swapped-label hint
    base_dir = Path(base_dir)

    for decl in sources or []:
        ident = decl.get("gid") or decl.get("label") or "?"
        found = _find(series, decl)
        if not found:
            rep.add("fail", "data", "series-missing",
                    "declared in sources but not found in the figure (matched by gid, then legend label)",
                    repr(ident))
            continue
        if len(found) > 1:
            rep.add("warn", "data", "ambiguous", f"{len(found)} artists match; set a unique gid on the "
                    "one that carries the data, or give the axes index with 'ax'", repr(ident))
        s = found[0]
        matched.update(id(f["artist"]) for f in found)
        ax = axes[s["ax"]]
        where = _name(s)

        if decl.get("computed"):
            _check_visibility(rep, ax, s, decl.get("allow_clipped", True))
            rep.add("info", "data", "computed", "declared as computed in the script (fit, model or "
                    "guide line); not compared with a file", where)
            continue

        path = Path(decl["file"])
        path = path if path.is_absolute() else base_dir / path
        try:
            if s["kind"] == "image":
                src_z = np.asarray(load_array(path, decl.get("key")), float) * decl.get("z_scale", 1.0)
                plotted = np.asarray(s["z"], float)
                if plotted.size != src_z.size or not _same(plotted, src_z, rtol):
                    rep.add("fail", "data", "values", f"image values differ from {path.name}: "
                            + _describe_mismatch(plotted, src_z), where)
                else:
                    rep.add("info", "data", "values", f"{src_z.size} values match {path.name}", where)
                continue
            table = load_table(path)
            cols = {}
            for k in ("x", "y", "xerr", "yerr"):
                if decl.get(k) is not None:
                    cols[k] = _column(table, decl[k], path.name)
        except (OSError, KeyError, ValueError) as exc:
            rep.add("fail", "data", "source-unreadable", str(exc), where)
            continue

        ok = True
        src = {}
        for k in ("x", "y", "xerr", "yerr"):
            if k not in cols:
                continue
            scale = decl.get(f"{k}_scale", decl.get(f"{k[0]}_scale", 1.0))
            if s["kind"] == "bar" and k == "x":
                try:
                    src[k] = _to_float(cols[k]) * scale
                except ValueError:
                    src[k] = cols[k]  # category names, checked against tick labels below
                continue
            try:
                src[k] = _to_float(cols[k]) * scale
            except ValueError as exc:
                rep.add("fail", "data", "source-unreadable", f"column {decl[k]!r} of {path.name}: {exc}", where)
                ok = False
        if not ok or "y" not in src:
            if ok:
                rep.add("fail", "data", "declaration", "a file source needs at least a 'y' column", where)
            continue
        loaded.append((decl, src["x"] if isinstance(src.get("x"), np.ndarray) else None, src["y"]))

        # bars with category names on the axis: compare names with the tick labels under each bar
        if s["kind"] == "bar" and isinstance(src.get("x"), list):
            axis = ax.yaxis if s.get("horizontal") else ax.xaxis
            ticks = {round(float(loc), 6): lab.get_text() for loc, lab in
                     zip(axis.get_majorticklocs(), axis.get_majorticklabels())}
            names = [ticks.get(round(float(p), 6), "") for p in s["x"]]
            if len(names) == len(src["x"]) and [_norm_text(n) for n in names] != [_norm_text(n) for n in src["x"]]:
                rep.add("fail", "data", "categories", f"bar labels {names} do not match column "
                        f"{decl['x']!r} of {path.name} {src['x']}", where)
                ok = False
            src.pop("x")

        subset = False
        for k in ("x", "y"):
            if k not in src:
                continue
            if _same(s[k], src[k], rtol):
                continue
            if (decl.get("allow_subset") and "x" in src and len(s["x"]) < len(src["x"])
                    and _is_subset(s["x"], s["y"], src["x"], src["y"])):
                subset = True
                continue
            msg = _describe_mismatch(s[k], src[k])
            for other, ox, oy in loaded[:-1]:
                o = oy if k == "y" else ox
                if o is not None and _same(s[k], o, rtol):
                    msg += (f". The plotted values match the series declared as "
                            f"{(other.get('gid') or other.get('label'))!r}: labels may be swapped")
            rep.add("fail", "data", "values", f"{k} differs from column {decl[k]!r} of {path.name}: {msg}", where)
            ok = False
        for k in ("xerr", "yerr"):
            if k not in src:
                continue
            got = s.get(k)
            if got is None:
                rep.add("fail", "data", "error-bars", f"{k} declared from column {decl[k]!r} but the "
                        "artist draws no such error bars", where)
                ok = False
            elif not _same(got, src[k], max(rtol, 1e-6)):
                rep.add("fail", "data", "error-bars", f"{k} differs from column {decl[k]!r} of {path.name}: "
                        + _describe_mismatch(got, src[k]), where)
                ok = False
        if subset:
            rep.add("info", "data", "subset", f"{len(s['x'])} of {len(src['x'])} source rows are plotted "
                    "(allow_subset)", where)
        if ok:
            what = "+".join(k for k in ("x", "y", "xerr", "yerr") if k in src)
            rep.add("info", "data", "values", f"{len(s['y'])} points match {path.name} ({what})", where)
        _check_visibility(rep, ax, s, decl.get("allow_clipped", False))

    undeclared = [s for s in series if id(s["artist"]) not in matched]
    for s in undeclared:
        _check_visibility(rep, axes[s["ax"]], s, declared=False)
    if undeclared:
        level = "fail" if not sources else "warn"
        names = ", ".join(_name(s) for s in undeclared[:8]) + (" ..." if len(undeclared) > 8 else "")
        rep.add(level, "data", "unverified", f"{len(undeclared)} data artist(s) have no entry in sources, "
                f"so their values were not checked: {names}")
    rep.measured["series_in_figure"] = len(series)
    rep.measured["series_declared"] = len(sources or [])


# --------------------------------------------------------------------------
# Style checks on the live figure
# --------------------------------------------------------------------------

def _texts(fig):
    """(description, Text) for every text that is actually drawn."""
    out = []
    for i, ax in enumerate(fig.get_axes()):
        if not ax.get_visible():
            continue
        for nm, t in (("title", ax.title), ("left title", ax._left_title), ("right title", ax._right_title),
                      ("x label", ax.xaxis.label), ("y label", ax.yaxis.label),
                      ("x offset text", ax.xaxis.get_offset_text()),
                      ("y offset text", ax.yaxis.get_offset_text())):
            out.append((f"ax{i} {nm}", t))
        for axis_name, axis in (("x", ax.xaxis), ("y", ax.yaxis)):
            # compare in the axis' own scale: on a log axis a linear margin can exceed the lower limit
            scale = axis.get_transform()
            lo, hi = sorted(scale.transform(np.asarray(axis.get_view_interval(), dtype=float)))
            pad = 1e-9 * (hi - lo)
            for major, ticks in ((True, axis.get_major_ticks()), (False, axis.get_minor_ticks())):
                for tick in ticks:
                    with np.errstate(all="ignore"):
                        loc = float(scale.transform(np.array([tick.get_loc()], dtype=float))[0])
                    if not (np.isfinite(loc) and lo - pad <= loc <= hi + pad):
                        continue
                    for lab in (tick.label1, tick.label2):
                        if lab.get_visible():
                            out.append((f"ax{i} {axis_name} tick label", lab))
        for t in ax.texts:
            out.append((f"ax{i} text", t))
        leg = ax.get_legend()
        if leg is not None:
            out.append((f"ax{i} legend title", leg.get_title()))
            out += [(f"ax{i} legend entry", t) for t in leg.get_texts()]
    for t in fig.texts:
        out.append(("figure text", t))
    for leg in fig.legends:
        out += [("figure legend entry", t) for t in leg.get_texts()]
    return [(d, t) for d, t in out if t.get_visible() and t.get_text().strip()]


def _overlap(a, b, min_px=1.0):
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    return w > min_px and h > min_px


def _data_hits(ax, s, bbox):
    """How a series' drawn data falls inside a display-space box: (points inside, line crosses)."""
    from matplotlib.path import Path as MplPath
    if s["kind"] == "image":
        return 0, False
    if s["kind"] == "bar":
        n = sum(_overlap(p.get_window_extent(), bbox) for p in s["patches"])
        return n, False
    xy = np.column_stack([s["x"], s["y"]])
    with np.errstate(all="ignore"):
        disp = ax.transData.transform(xy)
    disp = disp[np.isfinite(disp).all(axis=1)]
    if not len(disp):
        return 0, False
    inside = ((disp[:, 0] > bbox.x0) & (disp[:, 0] < bbox.x1) &
              (disp[:, 1] > bbox.y0) & (disp[:, 1] < bbox.y1))
    crosses = False
    art = s["artist"]
    has_line = s["kind"] in ("line", "errorbar") and art.get_linestyle() not in ("None", "none", "", " ")
    if has_line and len(disp) > 1:
        crosses = bool(MplPath(disp).intersects_bbox(bbox, filled=False))
    has_marker = s["kind"] == "scatter" or art.get_marker() not in ("None", "none", "", " ", None)
    return (int(inside.sum()) if has_marker else 0), crosses


def check_style(rep, fig, target=None):
    import matplotlib as mpl

    target = dict(target or {})
    min_font = target.get("min_font_pt", 6.0)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer() if hasattr(fig.canvas, "get_renderer") else fig._get_renderer()
    axes = fig.get_axes()

    # size
    w, h = (float(v) for v in fig.get_size_inches())
    rep.measured.update(figure_width_in=round(w, 3), figure_height_in=round(h, 3))
    if "width_in" in target:
        if abs(w - target["width_in"]) > 0.01:
            rep.add("warn", "style", "width", f"figure is {w:.2f} in wide, target is "
                    f"{target['width_in']:.2f} in; it will be rescaled in the document")
    else:
        rep.add("info", "style", "width", f"figure is {w:.2f} in wide; no target width was given")

    # text: sizes, canvas, overlaps
    texts = _texts(fig)
    sizes = [t.get_fontsize() for _, t in texts]
    if sizes:
        rep.measured.update(font_min_pt=round(min(sizes), 2), font_max_pt=round(max(sizes), 2))
        small = sorted({(d, round(t.get_fontsize(), 1)) for d, t in texts if t.get_fontsize() < min_font})
        if small:
            rep.add("fail", "style", "font-size", f"text below {min_font:g} pt: "
                    + ", ".join(f"{d} ({sz:g} pt)" for d, sz in small[:6]))
    boxes = []
    for d, t in texts:
        try:
            bb = t.get_window_extent(renderer)
        except Exception:  # a string LaTeX cannot typeset
            rep.add("fail", "style", "text-render", f"could not typeset {t.get_text()!r}", d)
            continue
        if bb.width > 0 and bb.height > 0:
            boxes.append((d, t, bb))
    canvas = fig.bbox
    off = [(d, t.get_text()) for d, t, bb in boxes
           if bb.x0 < canvas.x0 - 1 or bb.x1 > canvas.x1 + 1 or bb.y0 < canvas.y0 - 1 or bb.y1 > canvas.y1 + 1]
    if off:
        rep.add("warn", "style", "off-canvas", "text extends beyond the figure, so a tight bounding box "
                "will make the saved figure larger than its nominal size: "
                + ", ".join(f"{d} {txt!r}" for d, txt in off[:5]))
    legends = [(f"ax{i} legend", ax.get_legend()) for i, ax in enumerate(axes) if ax.get_legend() is not None]
    legends += [("figure legend", leg) for leg in fig.legends]
    for owner in getattr(fig, "subfigs", []):
        legends += [("figure legend", leg) for leg in owner.legends]
    cut = []
    for d, leg in legends:
        bb = leg.get_window_extent(renderer)
        if bb.x0 < canvas.x0 - 1 or bb.x1 > canvas.x1 + 1 or bb.y0 < canvas.y0 - 1 or bb.y1 > canvas.y1 + 1:
            cut.append(d)
    if cut:
        rep.add("fail", "style", "legend-cut", "legend extends beyond the figure and is cut off in the saved "
                "file: " + ", ".join(cut) + "; use fewer columns or a smaller legend")
    pairs = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _overlap(boxes[i][2], boxes[j][2]):
                pairs.append(f"{boxes[i][0]} {boxes[i][1].get_text()!r} / {boxes[j][0]} {boxes[j][1].get_text()!r}")
    if pairs:
        rep.add("warn", "style", "text-overlap", f"{len(pairs)} pair(s) of text overlap: " + "; ".join(pairs[:6]))

    # per-axes checks
    colorbar_axes = _colorbar_axes(fig)
    for i, ax in enumerate(axes):
        series = [] if ax in colorbar_axes else series_in_axes(ax, i)
        for nm, t in (("title", ax.title), ("left title", ax._left_title), ("right title", ax._right_title)):
            if t.get_text().strip() and not target.get("allow_title"):
                rep.add("warn", "style", "axes-title", f"axes has a {nm} {t.get_text()!r}; in a paper the "
                        "caption does this job", f"ax{i}")
        for axis_name, axis in (("x", ax.xaxis), ("y", ax.yaxis)):
            txt = axis.get_offset_text().get_text().strip()
            if txt and axis.get_offset_text().get_visible():
                rep.add("warn", "style", "offset-text", f"floating offset {txt!r} on the {axis_name} axis; "
                        "fold the factor into the axis label", f"ax{i}")

        # legend and free text sitting on data
        covers = []
        leg = ax.get_legend()
        if leg is not None:
            covers.append(("legend", leg.get_window_extent(renderer)))
        covers += [(f"text {t.get_text()!r}", t.get_window_extent(renderer)) for t in ax.texts
                   if t.get_visible() and t.get_text().strip()]
        for what, bb in covers:
            hits = []
            for s in series:
                n, crosses = _data_hits(ax, s, bb)
                if n or crosses:
                    ident = s["gid"] or s["label"] or f"unlabelled {s['kind']}"
                    hits.append(f"{ident!r} ({n} point(s)" + (", line passes through)" if crosses else ")"))
            if hits:
                rep.add("warn", "style", "covers-data", f"{what} overlaps data: " + ", ".join(hits[:5]), f"ax{i}")

        # colormaps
        for art in list(ax.images) + list(ax.collections):
            if getattr(art, "get_array", None) is None or art.get_array() is None:
                continue
            name = getattr(art.get_cmap(), "name", "")
            if (name[:-2] if name.endswith("_r") else name) in BAD_CMAPS:
                rep.add("fail", "style", "colormap", f"colormap {name!r} is not perceptually uniform; use "
                        "viridis or cividis (sequential) or RdBu_r (diverging)", f"ax{i}")

        # series told apart by colour alone: same line style, marker and line width, different colours
        # (series of one colour, such as reference lines labelled in place, are not told apart by colour)
        labelled = [s for s in series if s["kind"] in ("line", "errorbar") and (s["label"] or s["gid"])]
        seen = {}
        for s in labelled:
            a = s["artist"]
            ls = a.get_linestyle()
            ls = "None" if ls in ("None", "none", "", " ") else ls
            mk = a.get_marker()
            mk = "None" if mk in ("None", "none", "", " ", None) else str(mk)
            lw = round(float(a.get_linewidth()), 1) if ls != "None" else None
            colour = mpl.colors.to_hex(a.get_color())
            seen.setdefault((ls, mk, lw), []).append((s["gid"] or s["label"], colour))
        for (ls, mk, lw), members in seen.items():
            if len(members) > 1 and len({c for _, c in members}) > 1:
                rep.add("warn", "style", "colour-only", f"series {[n for n, _ in members]} share line style "
                        f"{ls!r}, marker {mk!r} and line width, so they differ only by colour and merge in "
                        "greyscale", f"ax{i}")

    rep.measured["usetex"] = bool(mpl.rcParams["text.usetex"])


# --------------------------------------------------------------------------
# Checks on the saved PDF and on the script
# --------------------------------------------------------------------------

def _run(cmd):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def check_pdf(rep, pdf, target=None):
    pdf = Path(pdf)
    target = target or {}
    if not pdf.exists():
        rep.add("fail", "style", "pdf", f"{pdf} does not exist; save a vector PDF")
        return
    if pdf.suffix.lower() != ".pdf":
        rep.add("warn", "style", "pdf", f"{pdf.name} is not a PDF; papers need vector output")
        return
    if not shutil.which("pdffonts"):
        rep.add("info", "style", "pdf", "poppler-utils not installed; PDF fonts and page size not checked")
        return

    out = _run(["pdfinfo", str(pdf)])
    m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", out or "")
    if m:
        w, h = float(m.group(1)) / 72.0, float(m.group(2)) / 72.0
        rep.measured.update(pdf_width_in=round(w, 3), pdf_height_in=round(h, 3))
        if "width_in" in target and abs(w - target["width_in"]) / target["width_in"] > 0.02:
            rep.add("warn", "style", "pdf-width", f"saved PDF is {w:.2f} in wide, target is "
                    f"{target['width_in']:.2f} in ({100 * (w / target['width_in'] - 1):+.0f}%); at "
                    r"\includegraphics[width=\columnwidth] every font is scaled by the same factor")

    out = _run(["pdffonts", str(pdf)])
    fonts = []
    for line in (out or "").splitlines()[2:]:
        m = re.match(r"(\S+)\s+(.*?)\s+(\S+)\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$", line)
        if m:
            fonts.append({"name": m.group(1).split("+")[-1], "type": m.group(2).strip(), "embedded": m.group(4)})
    rep.measured["pdf_fonts"] = sorted({f["name"] for f in fonts})
    if out is not None and not fonts:
        rep.add("warn", "style", "pdf-fonts", "the PDF contains no fonts: text was converted to outlines "
                "or the figure is a raster image")
    not_embedded = sorted({f["name"] for f in fonts if f["embedded"] != "yes"})
    if not_embedded:
        rep.add("fail", "style", "pdf-fonts", f"fonts not embedded: {', '.join(not_embedded)}")
    type3 = sorted({f["name"] for f in fonts if "Type 3" in f["type"]})
    if type3:
        rep.add("warn", "style", "pdf-fonts", f"Type 3 (bitmap) fonts: {', '.join(type3)}; set pdf.fonttype to 42")
    other = sorted({f["name"] for f in fonts if not f["name"].lower().startswith(CM_FONT_PREFIXES)})
    if other:
        rep.add("warn", "style", "pdf-fonts", f"fonts that are not Computer Modern: {', '.join(other)}; "
                "some text is not rendered in the document font")

    out = _run(["pdfimages", "-list", str(pdf)])
    if out is not None:
        n = max(0, len(out.strip().splitlines()) - 2)
        rep.measured["pdf_raster_images"] = n


def _is_number(node):
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        node = node.operand
    return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def check_script(rep, script, min_literals=8):
    """Flag data typed into the script instead of read from a file."""
    script = Path(script)
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        rep.add("warn", "data", "script", f"could not read {script}: {exc}")
        return
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            flat = []
            for el in node.elts:
                flat += el.elts if isinstance(el, (ast.List, ast.Tuple)) else [el]
            if len(flat) >= min_literals and all(_is_number(e) for e in flat):
                hits.append((node.lineno, len(flat)))
    if hits:
        rep.add("warn", "data", "typed-in-data", "numeric data typed into the script at "
                + ", ".join(f"line {ln} ({n} numbers)" for ln, n in hits[:6])
                + "; save it to a file and read it, so it can be checked against the source", script.name)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def check_figure(fig, sources=None, *, target=None, pdf=None, script=None, base_dir=None,
                 out=None, rtol=1e-6, quiet=False):
    """Run every check on a drawn figure. Returns the report as a dict.

    sources   list of declarations, one per plotted series (see the module docstring).
              Keys: label or gid (and ax) to find the artist; file with x, y, xerr, yerr
              columns and optional x_scale, y_scale; or computed=True for fits and guide
              lines. allow_subset / allow_clipped acknowledge a deliberate selection.
              For images: file (.npy, .npz with key, or a headerless matrix) and z_scale.
    target    {"width_in": 3.4, "min_font_pt": 6, "allow_title": False}
    pdf       path of the saved PDF, for font and page-size checks
    script    path of the plotting script (__file__), scanned for typed-in data
    base_dir  folder that relative source paths are resolved against
              (default: the script's folder, else the current folder)
    """
    rep = Report()
    if base_dir is None:
        base_dir = Path(script).resolve().parent if script else Path.cwd()
    check_data(rep, fig, sources, base_dir, rtol)
    check_style(rep, fig, target)
    if pdf:
        check_pdf(rep, pdf, target)
    if script:
        check_script(rep, script)
    result = rep.as_dict()
    if out is None and pdf:
        out = Path(pdf).with_suffix(".check.json")
    if out:
        Path(out).write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
        result["report_path"] = str(out)
    if not quiet:
        print(rep.text())
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="Checks that need no live figure: PDF fonts and size, typed-in data.")
    ap.add_argument("--pdf")
    ap.add_argument("--script")
    ap.add_argument("--width", type=float, help="target width in inches")
    args = ap.parse_args(argv)
    if not (args.pdf or args.script):
        ap.error("give --pdf and/or --script")
    rep = Report()
    target = {"width_in": args.width} if args.width else {}
    if args.pdf:
        check_pdf(rep, args.pdf, target)
    if args.script:
        check_script(rep, args.script)
    print(rep.text())
    return 0 if rep.as_dict()["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
