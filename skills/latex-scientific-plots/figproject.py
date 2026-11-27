"""The figures of a LaTeX manuscript as a project.

Measures the document, keeps a record of every figure, writes a caption index,
and builds a before/after comparison and a preview of the manuscript with the
new figures in place.

    python figproject.py init path/to/main.tex [--output-dir DIR]
        Compile the manuscript's preamble to measure the text and column
        widths, the width of \\linewidth inside figure and figure*, and the
        body and caption font sizes. List every figure with the width it is
        printed at and the file it currently includes. Write figures.yaml and
        FIGURES.md next to main.tex. Run it again after changing the class.
    python figproject.py index [figures.yaml]
        Re-read the .tex files and rewrite the figure list and FIGURES.md,
        keeping the measured target. Run it after editing figures or captions.
    python figproject.py compare [figures.yaml] [--before DIR] [--after DIR]
        before_after.pdf: every figure as the manuscript includes it now next
        to its new version, both at the printed width, with a table of scale
        factors and glyph sizes.
    python figproject.py preview [figures.yaml] [--figures DIR]
        Compile a copy of the manuscript with the new figures in place and
        report the page each figure lands on. The manuscript is not touched.

In a plotting script:

    from figproject import Project
    proj = Project("path/to/figures.yaml")      # or the .tex, or its folder
    proj.setup()
    fig, ax = plt.subplots(figsize=(proj.width("spectrum"), 2.2))
    ...
    proj.finish(fig, "spectrum", sources=[...], script=__file__)

finish() saves the PDF and a PNG preview to the output folder, runs
check_figure against the printed width, and records the script, the source
files and the check result in figures.yaml.

The .tex files stay the source of truth: captions are read from them for
FIGURES.md and are never stored in figures.yaml.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np

SKILL_DIR = Path(__file__).resolve().parent
RECORD_NAME = "figures.yaml"
INDEX_NAME = "FIGURES.md"
DEFAULT_OUTPUT = "braindance_figures"
GRAPHICS_EXT = [".pdf", ".png", ".jpg", ".jpeg", ".eps"]
PT_PER_IN = 72.27
FIGURE_ENVS = ["figure", "figure*", "wrapfigure", "SCfigure", "sidewaysfigure", "sidewaysfigure*"]
CONTAINER_ENVS = ["minipage", "subfigure"]
REF_COMMANDS = r"(?:ref|cref|Cref|autoref|Autoref|vref|Vref|fref|Fref|nameref|cpageref|Cpageref|pageref)"
KEEP_FIELDS = ("script", "sources", "check", "output", "drawn_width_in", "notes")
OUTPUT_NAMES = {"before_after", "preview"}


def _today():
    return _dt.date.today().isoformat()


def _yaml():
    try:
        import yaml
    except ImportError:
        raise SystemExit("figproject needs PyYAML: pip install pyyaml") from None
    return yaml


# ──────────────────────────────────────────────────────────────────────────
# Reading the manuscript
# ──────────────────────────────────────────────────────────────────────────

_COMMENT = re.compile(r"((?:^|[^\\])(?:\\\\)*)%.*")
_INPUT = re.compile(r"\\(input|include|subfile)\s*\{([^}]*)\}")
_BEGIN_DOC = re.compile(r"\\begin\s*\{document\}")


def strip_comment(line):
    """A line without its comment; escaped percent signs are kept."""
    return _COMMENT.sub(r"\1", line)


def _blank(text, pattern):
    """Replace every match by as many newlines as it spans, so line numbers stay valid."""
    return re.sub(pattern, lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)


class Source:
    """The manuscript with \\input and \\include expanded and comments removed.

    Every line keeps its origin, so positions can be reported as file:line.
    """

    def __init__(self, main):
        self.main = Path(main).resolve()
        self.root = self.main.parent
        self.lines, self.origin = [], []
        self._expand(self.main, 0)
        text = "\n".join(self.lines)
        text = _blank(text, r"\\begin\{comment\}.*?\\end\{comment\}")
        text = _blank(text, r"\\iffalse\b.*?\\fi\b")
        self.text = text
        self.starts, pos = [], 0
        for line in text.split("\n"):
            self.starts.append(pos)
            pos += len(line) + 1
        m = _BEGIN_DOC.search(text)
        self.body_start = m.end() if m else 0
        self.preamble = text[:m.start()] if m else ""

    def _resolve_input(self, name):
        for cand in (name, name + ".tex"):
            p = (self.root / cand)
            if p.is_file():
                return p
        return None

    def _expand(self, path, depth):
        rel = os.path.relpath(path, self.root)
        raw = Path(path).read_text(encoding="utf-8", errors="replace").split("\n")
        for i, line in enumerate(raw, start=1):
            line = strip_comment(line)
            pos = 0
            for m in _INPUT.finditer(line):
                child = self._resolve_input(m.group(2).strip()) if depth < 20 else None
                if child is None:
                    continue
                self.lines.append(line[pos:m.start()])
                self.origin.append((rel, i))
                self._expand(child, depth + 1)
                pos = m.end()
            self.lines.append(line[pos:])
            self.origin.append((rel, i))

    def where(self, offset):
        """'file:line' of a position in the expanded text."""
        k = bisect.bisect_right(self.starts, offset) - 1
        f, n = self.origin[max(k, 0)]
        return f"{Path(f).as_posix()}:{n}"


def raw_preamble(main):
    """The text of main.tex before \\begin{document}, exactly as written."""
    raw = Path(main).read_text(encoding="utf-8", errors="replace")
    out = []
    for line in raw.split("\n"):
        m = _BEGIN_DOC.search(strip_comment(line))
        if m:
            out.append(line[:m.start()])
            return "\n".join(out)
        out.append(line)
    raise ValueError(f"{main} has no \\begin{{document}}; give the main file of the manuscript")


def read_group(text, i, open_="{", close="}"):
    """Content of the bracketed group starting at text[i]; returns (content, end index)."""
    if i >= len(text) or text[i] != open_:
        raise ValueError(f"expected {open_!r} at {i}")
    depth, j, brace = 0, i, 0
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if open_ == "[":
            if c == "{":
                brace += 1
            elif c == "}":
                brace -= 1
        if brace == 0 and c == open_:
            depth += 1
        elif brace == 0 and c == close:
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    raise ValueError("unbalanced group")


def _skip_ws(text, i):
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def read_args(text, i, n_optional_max=3, n_mandatory=1):
    """Read up to n_optional_max [..] groups, then n_mandatory {..} groups, from text[i]."""
    opts, args = [], []
    i = _skip_ws(text, i)
    while len(opts) < n_optional_max and i < len(text) and text[i] == "[":
        val, i = read_group(text, i, "[", "]")
        opts.append(val)
        i = _skip_ws(text, i)
    for _ in range(n_mandatory):
        i = _skip_ws(text, i)
        val, i = read_group(text, i)
        args.append(val)
    return opts, args, i


def env_spans(text, names, start=0):
    """(name, begin, content start, content end, end) for each environment, outermost first."""
    pat = re.compile(r"\\(begin|end)\s*\{(%s)\}" % "|".join(re.escape(n) for n in names))
    stack, spans = [], []
    for m in pat.finditer(text, start):
        if m.group(1) == "begin":
            stack.append((m.group(2), m.start(), m.end()))
            continue
        for k in range(len(stack) - 1, -1, -1):
            if stack[k][0] == m.group(2):
                name, s, inner = stack.pop(k)
                spans.append((name, s, inner, m.start(), m.end()))
                break
    return sorted(spans, key=lambda x: x[1])


_LENGTH = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+))?\s*(\\[A-Za-z]+|pt|bp|in|cm|mm|pc|dd)\s*$")
_UNITS = {"pt": 1.0, "bp": PT_PER_IN / 72.0, "in": PT_PER_IN, "cm": PT_PER_IN / 2.54,
          "mm": PT_PER_IN / 25.4, "pc": 12.0, "dd": 1238 / 1157}


def length_pt(expr, ctx):
    """A TeX length such as 0.98\\linewidth or 8.5cm in points, or None if it cannot be evaluated."""
    if expr is None:
        return None
    expr = expr.strip()
    while expr.startswith("{") and expr.endswith("}"):
        expr = expr[1:-1].strip()
    m = _LENGTH.match(expr)
    if not m:
        return None
    k = float(m.group(1)) if m.group(1) else 1.0
    unit = m.group(2)
    if unit in _UNITS:
        return k * _UNITS[unit]
    value = ctx.get(unit[1:])
    return None if value is None else k * value


def keyvals(opts):
    """Parse 'width=0.5\\linewidth, angle=90' into a dict, splitting at top-level commas."""
    out, depth, cur = {}, 0, ""
    for c in opts + ",":
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        if c == "," and depth == 0:
            if cur.strip():
                k, _, v = cur.partition("=")
                out[k.strip()] = v.strip()
            cur = ""
        else:
            cur += c
    return out


def graphicspath(preamble):
    m = re.search(r"\\graphicspath\s*\{", preamble)
    if not m:
        return []
    inner, _ = read_group(preamble, m.end() - 1)
    return re.findall(r"\{([^{}]*)\}", inner)


def resolve_graphic(root, name, paths):
    """The file \\includegraphics{name} finds, searching like graphicx: current folder, then \\graphicspath."""
    cands = [name] if Path(name).suffix.lower() in GRAPHICS_EXT else [name + e for e in GRAPHICS_EXT]
    for folder in ["", *paths]:
        for cand in cands:
            p = Path(root) / folder / cand
            if p.is_file():
                return p
    return None


def native_size_in(path):
    """(width, height) in inches at which LaTeX includes the file at its natural size."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        out = _run(["pdfinfo", str(path)])
        m = re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", out or "")
        if m:
            return float(m.group(1)) / 72.0, float(m.group(2)) / 72.0
        m = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", path.read_bytes())
        if m:
            x0, y0, x1, y1 = (float(v) for v in m.groups())
            return (x1 - x0) / 72.0, (y1 - y0) / 72.0
        return None
    if path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        try:
            from PIL import Image
        except ImportError:
            return None
        with Image.open(path) as im:
            dpi = im.info.get("dpi", (72, 72))
            return im.width / float(dpi[0] or 72), im.height / float(dpi[1] or 72)
    return None


def _run(cmd, **kw):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=kw.pop("timeout", 120), **kw)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def scan_figures(src, target):
    """Every \\includegraphics inside a figure environment, with the width it is printed at."""
    text = src.text
    base = {
        "figure": target.get("figure_linewidth_pt"),
        "figure*": target.get("figure_star_linewidth_pt"),
        "SCfigure": target.get("figure_linewidth_pt"),
        "sidewaysfigure": None, "sidewaysfigure*": None,
    }
    ctx0 = {"textwidth": target.get("textwidth_pt"), "columnwidth": target.get("columnwidth_pt")}
    paths = graphicspath(src.preamble)
    figures = env_spans(text, FIGURE_ENVS, src.body_start)
    figures = [f for f in figures if not any(o[1] < f[1] and f[4] <= o[4] for o in figures)]
    containers = env_spans(text, CONTAINER_ENVS, src.body_start)
    labels_cited = _citations(src)

    entries, number, seen = [], 0, {}
    for env, s, inner, es, e in figures:
        boxes = [c for c in containers if inner <= c[1] and c[4] <= es]

        def box_of(p, kinds=("minipage", "subfigure")):
            """The innermost minipage or subfigure holding position p, or None."""
            inside = [c for c in boxes if c[0] in kinds and c[2] <= p < c[3]]
            return max(inside, key=lambda c: c[1]) if inside else None

        # Captions, numbered as LaTeX does: a \caption in a minipage takes a figure number of its
        # own; one in a subfigure environment is a sub-caption and does not.
        captions = []
        for m in re.finditer(r"\\caption(?![A-Za-z])(\*?)", text[:es]):
            if m.start() < inner or box_of(m.start(), ("subfigure",)):
                continue
            try:
                _, args, end = read_args(text, m.end(), 1, 1)
            except ValueError:
                continue
            numbered = not m.group(1)
            if numbered:
                number += 1
            captions.append({"pos": m.start(), "end": end, "box": box_of(m.start(), ("minipage",)),
                             "number": number if numbered else None, "text": " ".join(args[0].split())})
        labels = [(m.start(), box_of(m.start(), ("minipage",)), m.group(1).strip())
                  for m in re.finditer(r"\\label\s*\{([^}]*)\}", text[:es])
                  if m.start() >= inner and not box_of(m.start(), ("subfigure",))]
        for c in captions:
            after = [l for l in labels if l[1] == c["box"] and l[0] >= c["pos"]]
            same = [l for l in labels if l[1] == c["box"]]
            c["label"] = (after or same or [(None, None, None)])[0][2]
        main_caption = next((c for c in captions if c["box"] is None), captions[0] if captions else None)

        lw_env = base.get(env)
        if env == "wrapfigure":
            try:
                _, args, _ = read_args(text, inner, 1, 2)
                lw_env = length_pt(args[1], {**ctx0, "linewidth": target.get("figure_linewidth_pt")})
            except ValueError:
                lw_env = None

        includes = list(re.finditer(r"\\includegraphics\*?", text[inner:es]))
        for k, m in enumerate(includes):
            pos = inner + m.start()
            own = box_of(pos, ("minipage",))
            cap = next((c for c in captions if own is not None and c["box"] == own), main_caption) or {}
            try:
                opts, args, _ = read_args(text, inner + m.end(), 2, 1)
            except ValueError:
                continue
            name = args[0].strip()
            lw = lw_env
            for c in sorted((c for c in boxes if c[2] <= pos < c[3]), key=lambda c: c[1]):
                try:
                    n_opt = 3 if c[0] == "minipage" else 1
                    _, cargs, _ = read_args(text, c[2], n_opt, 1)
                    lw = length_pt(cargs[0], {**ctx0, "linewidth": lw, "hsize": lw})
                except ValueError:
                    lw = None
            kv = keyvals(opts[-1]) if opts else {}
            ctx = {**ctx0, "linewidth": lw, "hsize": lw}
            found = resolve_graphic(src.root, name, paths)
            native = native_size_in(found) if found else None
            width_pt = length_pt(kv.get("width"), ctx)
            if width_pt is None and native:
                if "scale" in kv:
                    try:
                        width_pt = float(kv["scale"]) * native[0] * PT_PER_IN
                    except ValueError:
                        pass
                elif "height" in kv and length_pt(kv["height"], ctx):
                    width_pt = length_pt(kv["height"], ctx) * native[0] / native[1]
                elif not kv.get("width"):
                    width_pt = native[0] * PT_PER_IN
            key = Path(name).stem if Path(name).suffix.lower() in GRAPHICS_EXT else Path(name).name
            if key in seen:
                seen[key] += 1
                key = f"{key}_{seen[key]}"
            else:
                seen[key] = 1
            width_in = round(width_pt / PT_PER_IN, 4) if width_pt else None
            entries.append({
                "name": key,
                "figure": cap.get("number"),
                "panel": f"{k + 1} of {len(includes)}" if len(includes) > 1 else None,
                "label": cap.get("label"),
                "env": env,
                "include": opts[-1] if opts else "",
                "file": name,
                "path": Path(os.path.relpath(found, src.root)).as_posix() if found else None,
                "width_in": width_in,
                "linewidth_in": round(lw / PT_PER_IN, 4) if lw else None,
                "native_width_in": round(native[0], 4) if native else None,
                "printed_scale": round(width_in / native[0], 4) if (width_in and native) else None,
                "defined_at": src.where(s),
                "cited_at": labels_cited.get(cap.get("label"), []) if cap.get("label") else [],
                "caption": cap.get("text"),
            })
    return entries


def _citations(src):
    out = {}
    for m in re.finditer(r"\\%s\*?\s*\{([^}]*)\}" % REF_COMMANDS, src.text):
        for lab in m.group(1).split(","):
            out.setdefault(lab.strip(), []).append(src.where(m.start()))
    return out


# ──────────────────────────────────────────────────────────────────────────
# Measuring the document
# ──────────────────────────────────────────────────────────────────────────

_PROBE_DEFS = r"""
\makeatletter
\def\braindancereport#1#2{\typeout{BRAINDANCE:#1=#2}}
\def\braindancesize{\f@size}
\def\braindancetwocol{\if@twocolumn yes\else no\fi}
\DeclareRobustCommand\braindancecaption{\braindancereport{caption}{\f@size}}
\makeatother
"""
_PROBE_BODY = r"""
\begin{document}
\braindancereport{textwidth}{\the\textwidth}
\braindancereport{columnwidth}{\the\columnwidth}
\braindancereport{body}{\braindancesize}
\braindancereport{twocolumn}{\braindancetwocol}
\begin{figure}\braindancereport{figure}{\the\linewidth}\rule{1pt}{1pt}\caption{\braindancecaption}\end{figure}
\begin{figure*}\braindancereport{figurestar}{\the\linewidth}\rule{1pt}{1pt}\caption{x}\end{figure*}
\end{document}
"""


def detect_engine(main):
    raw = Path(main).read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^\s*%\s*!\s*TEX\s+(?:TS-)?program\s*=\s*(\w+)", raw, flags=re.M | re.I)
    if m and m.group(1).lower() in ("pdflatex", "xelatex", "lualatex"):
        return m.group(1).lower()
    pre = "\n".join(strip_comment(l) for l in raw_preamble(main).split("\n"))
    if re.search(r"\\usepackage(\[[^\]]*\])?\{[^}]*\b(fontspec|unicode-math)\b", pre):
        return "xelatex"
    return "pdflatex"


def measure(main, timeout=180):
    """Compile the manuscript's preamble with a probe body and read the layout back."""
    main = Path(main).resolve()
    engine = detect_engine(main)
    if not shutil.which(engine):
        raise RuntimeError(f"{engine} is not installed; give --textwidth (and --columnwidth) instead")
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "braindance_probe.tex"
        probe.write_text(raw_preamble(main) + _PROBE_DEFS + _PROBE_BODY, encoding="utf-8")
        env = {**os.environ, "max_print_line": "10000"}
        res = subprocess.run([engine, "-interaction=nonstopmode", f"-output-directory={tmp}", str(probe)],
                             cwd=main.parent, capture_output=True, text=True, timeout=timeout, env=env)
        found = dict(re.findall(r"BRAINDANCE:(\w+)=([^\n]*)", res.stdout))
    if "textwidth" not in found:
        tail = "\n".join(res.stdout.splitlines()[-25:])
        raise RuntimeError(f"could not measure the layout of {main.name}; give --textwidth instead.\n{tail}")
    pt = lambda k: float(found[k].replace("pt", "")) if k in found else None  # noqa: E731
    num = lambda k: float(found[k]) if k in found else None  # noqa: E731
    return {
        "measured": _today(),
        "engine": engine,
        "twocolumn": found.get("twocolumn") == "yes",
        "textwidth_pt": pt("textwidth"),
        "columnwidth_pt": pt("columnwidth"),
        "figure_linewidth_pt": pt("figure") or pt("columnwidth"),
        "figure_star_linewidth_pt": pt("figurestar") or pt("textwidth"),
        "body_font_pt": num("body"),
        "caption_font_pt": num("caption"),
    }


def given_target(textwidth, columnwidth=None):
    tw = length_pt(textwidth, {})
    cw = length_pt(columnwidth, {}) if columnwidth else tw
    if tw is None or cw is None:
        raise SystemExit(f"cannot read the length {textwidth!r}; write it like 468pt, 16.5cm or 6.5in")
    return {"measured": "given", "engine": None, "twocolumn": cw < tw, "textwidth_pt": tw, "columnwidth_pt": cw,
            "figure_linewidth_pt": cw, "figure_star_linewidth_pt": tw, "body_font_pt": None, "caption_font_pt": None}


def describe_document(src):
    m = re.search(r"\\documentclass\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}", src.preamble)
    j = re.search(r"\\journal\s*\{", src.preamble)
    journal = " ".join(read_group(src.preamble, j.end() - 1)[0].split()) if j else None
    return {"documentclass": m.group(2).strip() if m else None,
            "class_options": " ".join((m.group(1) or "").split()) if m else None,
            "journal": journal}


# ──────────────────────────────────────────────────────────────────────────
# The record and the index
# ──────────────────────────────────────────────────────────────────────────

_RECORD_HEADER = """\
# braindance figure record for {main}
#
# Written by figproject.py. The target and the figure list are measured from the
# manuscript: rerun `figproject.py init {main}` after changing the document class,
# `figproject.py index` after editing figures. Captions live in the .tex files.
#
# You can edit:
#   output_dir  where new figures are written (relative to this file)
#   style       the encoding shared by every figure of the paper, so a series keeps
#               its colour, marker and line style from figure to figure. Free-form,
#               for example
#                 style:
#                   field:
#                     u: {{colour: '#0072B2', marker: o, label: "$u'$"}}
#   profile     the look of this paper's figures, on top of each author's personal
#               profile (~/.config/braindance/profile.yaml): the keys of a style
#               profile (palette, colormaps, font, rc, mplstyle), or the path of a
#               profile file. Add `personal: false` to ignore personal profiles, so
#               every co-author draws the same figures, for example
#                 profile: {{font: helvetica, personal: false}}
#   notes       under a figure, anything the next person should know
#
"""


def _entry_fields(e):
    return {k: e[k] for k in ("figure", "panel", "label", "env", "include", "file", "path", "width_in",
                              "linewidth_in", "native_width_in", "printed_scale", "defined_at", "cited_at")}


def merge_record(old, main_name, target, figs, output_dir=None):
    old = old or {}
    figures = {}
    old_figs = old.get("figures") or {}
    for e in figs:
        entry = {"in_manuscript": True, **_entry_fields(e)}
        for k in KEEP_FIELDS:
            if k in old_figs.get(e["name"], {}):
                entry[k] = old_figs[e["name"]][k]
        figures[e["name"]] = entry
    for name, entry in old_figs.items():
        if name in figures:
            continue
        kept = {k: entry[k] for k in KEEP_FIELDS if k in entry}
        if kept:
            figures[name] = {"in_manuscript": False, **kept}
    return {
        "manuscript": main_name,
        "updated": _today(),
        "output_dir": output_dir or old.get("output_dir") or DEFAULT_OUTPUT,
        "target": target,
        "style": old.get("style") or {},
        **({"profile": old["profile"]} if old.get("profile") else {}),
        "figures": figures,
    }


def save_record(path, record):
    yaml = _yaml()
    text = _RECORD_HEADER.format(main=record["manuscript"])
    text += yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100, default_flow_style=None)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_record(path):
    return _yaml().safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _fmt_in(v):
    return "?" if v is None else f"{v:.2f} in"


def write_index(path, record, figs):
    t = record["target"]
    doc = record.get("document") or {}
    lines = [
        f"# Figures in {record['manuscript']}",
        "",
        f"Generated by braindance on {_today()} from the .tex files, which hold the captions; do not edit this file.",
        "Regenerate it with `python figproject.py index`.",
        "",
    ]
    cls = doc.get("documentclass")
    if cls:
        opts = f"[{doc['class_options']}]" if doc.get("class_options") else ""
        lines.append(f"- Document class: `{cls}{opts}`" + (f", for *{doc['journal']}*" if doc.get("journal") else ""))
    tw = t.get("textwidth_pt")
    if tw:
        lines.append(f"- Text width {tw:g} pt ({tw / PT_PER_IN:.2f} in); \\linewidth is "
                     f"{t['figure_linewidth_pt']:g} pt in `figure` and {t['figure_star_linewidth_pt']:g} pt in `figure*`")
    if t.get("body_font_pt"):
        cap = f", captions {t['caption_font_pt']:g} pt" if t.get("caption_font_pt") else ""
        lines.append(f"- Body text {t['body_font_pt']:g} pt{cap}; figure text should be 7 to 9 pt once printed")
    lines += ["", "| Fig. | Label | File | Printed width | Current file drawn at | New version |",
              "|---|---|---|---|---|---|"]
    record_figs = record.get("figures", {})
    for e in figs:
        num = str(e["figure"]) if e["figure"] else "-"
        if e["panel"]:
            num += f" ({e['panel']})"
        if e["native_width_in"] and e["printed_scale"]:
            drawn = f"{_fmt_in(e['native_width_in'])}, printed at {100 * e['printed_scale']:.0f} %"
        else:
            drawn = "file not found" if not e["path"] else "?"
        chk = record_figs.get(e["name"], {}).get("check")
        new = f"{chk['fail']} fail, {chk['warn']} warn ({chk['date']})" if chk else "-"
        lines.append(f"| {num} | `{e['label'] or '-'}` | `{e['file']}` | {_fmt_in(e['width_in'])} "
                     f"(`{e['include'] or 'natural size'}`) | {drawn} | {new} |")
    done = set()
    for e in figs:
        key = (e["figure"], e["defined_at"])
        if key in done:
            continue
        done.add(key)
        group = [g for g in figs if (g["figure"], g["defined_at"]) == key]
        title = f"Fig. {e['figure']}" if e["figure"] else "Unnumbered figure"
        lines += ["", f"## {title}" + (f" - `{e['label']}`" if e["label"] else ""), ""]
        lines.append(f"- Defined at `{e['defined_at']}`, environment `{e['env']}`")
        lines.append("- Files: " + ", ".join(f"`{g['file']}`" for g in group))
        if e["cited_at"]:
            lines.append("- Cited at " + ", ".join(f"`{c}`" for c in e["cited_at"]))
        else:
            lines.append("- Not cited in the text")
        lines += ["", "> " + (e["caption"] or "(no caption)")]
    extras = [n for n, f in record_figs.items() if not f.get("in_manuscript")]
    if extras:
        lines += ["", "## Figures made for this project but not in the manuscript", ""]
        for n in extras:
            chk = record_figs[n].get("check")
            lines.append(f"- `{n}`" + (f": {chk['fail']} fail, {chk['warn']} warn ({chk['date']})" if chk else ""))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def init(main, output_dir=None, textwidth=None, columnwidth=None, quiet=False):
    """Measure the manuscript and write figures.yaml and FIGURES.md next to it."""
    main = Path(main).resolve()
    src = Source(main)
    target = given_target(textwidth, columnwidth) if textwidth else measure(main)
    record_path = main.parent / RECORD_NAME
    old = load_record(record_path) if record_path.exists() else None
    figs = scan_figures(src, target)
    record = merge_record(old, main.name, target, figs, output_dir)
    record = {"manuscript": record.pop("manuscript"), "document": describe_document(src), **record}
    save_record(record_path, record)
    write_index(main.parent / INDEX_NAME, record, figs)
    if not quiet:
        _print_summary(record, figs, record_path)
    return record_path


def index(record_path, quiet=False):
    """Re-read the .tex files, keeping the measured target."""
    record_path = find_record(record_path)
    old = load_record(record_path)
    main = record_path.parent / old["manuscript"]
    src = Source(main)
    figs = scan_figures(src, old["target"])
    record = merge_record(old, main.name, old["target"], figs)
    record = {"manuscript": record.pop("manuscript"), "document": describe_document(src), **record}
    save_record(record_path, record)
    write_index(record_path.parent / INDEX_NAME, record, figs)
    if not quiet:
        _print_summary(record, figs, record_path)
    return record


def _print_summary(record, figs, record_path):
    t = record["target"]
    print(f"wrote {record_path} and {record_path.parent / INDEX_NAME}")
    print(f"text width {t['textwidth_pt']:g} pt, figure {t['figure_linewidth_pt']:g} pt, "
          f"figure* {t['figure_star_linewidth_pt']:g} pt"
          + (f", body {t['body_font_pt']:g} pt" if t.get("body_font_pt") else ""))
    for e in figs:
        scale = f"{100 * e['printed_scale']:.0f} %" if e["printed_scale"] else "?"
        print(f"  Fig. {e['figure'] or '-':>2}  {e['name']:<32} printed {_fmt_in(e['width_in']):>8}, "
              f"current file printed at {scale}")


def find_record(path=None):
    """figures.yaml from a path to it, to the .tex next to it, to its folder, or searching upward from here."""
    if path is None:
        for d in [Path.cwd(), *Path.cwd().parents]:
            if (d / RECORD_NAME).is_file():
                return (d / RECORD_NAME).resolve()
        raise FileNotFoundError(f"no {RECORD_NAME} here or above; run: python figproject.py init <main.tex>")
    p = Path(path)
    if p.is_dir():
        p = p / RECORD_NAME
    elif p.suffix == ".tex":
        p = p.parent / RECORD_NAME
    if not p.is_file():
        raise FileNotFoundError(f"{p} not found; run: python figproject.py init <main.tex>")
    return p.resolve()


# ──────────────────────────────────────────────────────────────────────────
# Plotting scripts
# ──────────────────────────────────────────────────────────────────────────

class Project:
    """What a plotting script needs from the manuscript: widths, shared style, output folder, checks."""

    def __init__(self, path=None):
        self.record_path = find_record(path)
        self.dir = self.record_path.parent
        self.record = load_record(self.record_path)
        self.main = self.dir / self.record["manuscript"]
        self.out = (self.dir / self.record.get("output_dir", DEFAULT_OUTPUT)).resolve()
        self.source_dir = self.out / "source_data"
        self.target = self.record["target"]

    # sizes
    def linewidth(self, star=False):
        """\\linewidth inside figure (or figure*), in inches."""
        return self.target["figure_star_linewidth_pt" if star else "figure_linewidth_pt"] / PT_PER_IN

    def width(self, name, default=None, star=False):
        """Width in inches the manuscript prints figure `name` at.

        For a figure the manuscript does not include, give `default`, a fraction
        of \\linewidth in figure (or figure* with star=True).
        """
        entry = (self.record.get("figures") or {}).get(name) or {}
        if entry.get("in_manuscript") and entry.get("width_in"):
            return float(entry["width_in"])
        if default is not None:
            return default * self.linewidth(star)
        included = [n for n, f in (self.record.get("figures") or {}).items() if f.get("in_manuscript")]
        raise KeyError(f"{name!r} is not included in {self.main.name}; give a fraction of the line width, "
                       f"e.g. width({name!r}, 1.0). Included figures: {', '.join(included)}")

    def style(self, group=None):
        style = self.record.get("style") or {}
        return style if group is None else style.get(group, {})

    # drawing
    def setup(self, personal=True, quiet=False):
        """Apply the house style, the personal profile and this paper's `profile`.

        Returns True if text is typeset with LaTeX; the applied profile is `self.profile`.
        personal=False ignores the personal profile (as `personal: false` in figures.yaml does).
        """
        import matplotlib as mpl
        sys.path.insert(0, str(SKILL_DIR))
        from style_profile import setup as style_setup
        self.profile = style_setup(paper=self.record.get("profile"), base_dir=self.dir, personal=personal,
                                   quiet=quiet)
        # the canvas is the printed size: save it as it is, never cropped or padded
        mpl.rcParams["savefig.bbox"] = "standard"
        return self.profile.usetex

    # source data
    def write_csv(self, name, **columns):
        """Write equal-length columns to source_data/<name>.csv; returns the path."""
        self.source_dir.mkdir(parents=True, exist_ok=True)
        cols = {k: (list(v) if isinstance(v, (list, tuple)) else list(np.asarray(v).tolist()))
                for k, v in columns.items()}
        lengths = {k: len(v) for k, v in cols.items()}
        if len(set(lengths.values())) > 1:
            raise ValueError(f"{name}: columns have different lengths {lengths}")
        path = self.source_dir / f"{name}.csv"
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols.keys())
            for row in zip(*cols.values()):
                w.writerow([repr(float(v)) if isinstance(v, (float, np.floating)) else v for v in row])
        return path

    def write_npy(self, name, array):
        self.source_dir.mkdir(parents=True, exist_ok=True)
        path = self.source_dir / f"{name}.npy"
        np.save(path, np.asarray(array))
        return path

    def read_csv(self, name):
        with open(self.source_dir / f"{name}.csv", newline="") as fh:
            rows = list(csv.reader(fh))
        return {h: [r[i] for r in rows[1:]] for i, h in enumerate(rows[0])}

    # saving and checking
    def finish(self, fig, name, sources=None, script=None, width_in=None, allow_title=False, png_dpi=300):
        """Save PDF and PNG, run the measured checks, record the result. Stops the script on a fail."""
        import matplotlib.pyplot as plt
        sys.path.insert(0, str(SKILL_DIR))
        from check_figure import check_figure

        self.out.mkdir(parents=True, exist_ok=True)
        pdf, png = self.out / f"{name}.pdf", self.out / f"{name}.png"
        settle_layout(fig)
        fig.savefig(pdf)
        fig.savefig(png, dpi=png_dpi)
        drawn = float(fig.get_size_inches()[0])
        print(f"saved {pdf}")
        if width_in is None:
            entry = (self.record.get("figures") or {}).get(name) or {}
            width_in = entry.get("width_in") if entry.get("in_manuscript") else None
        target = {"width_in": width_in} if width_in else {}
        if allow_title:
            target["allow_title"] = True
        result = check_figure(fig, sources=sources, target=target, pdf=pdf, script=script, base_dir=self.source_dir,
                              profile=getattr(self, "profile", None))
        plt.close(fig)
        self._record_result(name, result, script, sources, drawn, pdf)
        try:
            index(self.record_path, quiet=True)
        except Exception as exc:  # the figure is saved; a stale index is not worth stopping for
            print(f"figproject: could not update {INDEX_NAME}: {exc}", file=sys.stderr)
        if not result["ok"]:
            raise SystemExit(f"{name}: measured checks failed")
        return result

    def _rel(self, p):
        return Path(os.path.relpath(Path(p).resolve(), self.dir)).as_posix()

    def _record_result(self, name, result, script, sources, drawn, pdf):
        record = load_record(self.record_path)
        figures = record.setdefault("figures", {}) or {}
        record["figures"] = figures
        entry = figures.setdefault(name, {"in_manuscript": False})
        if script:
            entry["script"] = self._rel(script)
        entry["output"] = self._rel(pdf)
        entry["drawn_width_in"] = round(drawn, 4)
        files = sorted({str(s["file"]) for s in (sources or []) if s.get("file")})
        entry["sources"] = files
        s = result["summary"]
        entry["check"] = {"fail": s["fail"], "warn": s["warn"], "date": _today(),
                          "profile": (result.get("measured", {}).get("profile") or {}).get("name"),
                          "report": self._rel(Path(result.get("report_path", pdf.with_suffix(".check.json"))))}
        save_record(self.record_path, record)
        self.record = record


# ──────────────────────────────────────────────────────────────────────────
# Before and after
# ──────────────────────────────────────────────────────────────────────────

def settle_layout(fig, max_draws=6, tol=1e-4):
    """Draw until the axes stop moving.

    The constrained layout engine is not always converged after one draw (axes with a fixed aspect next to a
    colourbar, for example), so the first file saved can be laid out differently from the second: text cut off at
    the edge of the PDF while the PNG saved right after it is fine. Drawing until positions are stable makes every
    file and the measured checks see the same layout.
    """
    def positions():
        return [ax.get_position().bounds for ax in fig.axes]
    before = positions()
    for _ in range(max_draws):
        fig.draw_without_rendering()
        now = positions()
        if len(now) == len(before) and all(abs(a - b) <= tol for p, q in zip(now, before) for a, b in zip(p, q)):
            return True
        before = now
    return False


def glyph_sizes(pdf):
    """Font sizes (pt) set by the Tf operators of a PDF's content streams; approximate."""
    data = Path(pdf).read_bytes()
    sizes = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, flags=re.S):
        try:
            content = zlib.decompress(m.group(1))
        except zlib.error:
            content = m.group(1)
        sizes += [float(v) for v in re.findall(rb"/[^\s/]+\s+([\d.]+)\s+Tf", content)]
    return [v for v in sizes if v > 0]


def _latex_doc(target, body):
    tw = target["textwidth_pt"]
    paper = "a4paper" if tw <= 595 - 72 else f"paperwidth={tw + 144:.1f}pt,paperheight={(tw + 144) * 1.414:.1f}pt"
    return (r"\documentclass[10pt]{article}" "\n"
            rf"\usepackage[{paper},textwidth={tw:.2f}pt,vmargin=2cm]{{geometry}}" "\n"
            r"\usepackage{graphicx,booktabs,longtable}\pagestyle{plain}\setlength{\parindent}{0pt}" "\n"
            r"\begin{document}" "\n" + body + "\n" r"\end{document}" "\n")


def _compile(tex_text, name, out_pdf, runs=2, timeout=300):
    with tempfile.TemporaryDirectory() as tmp:
        tex = Path(tmp) / f"{name}.tex"
        tex.write_text(tex_text, encoding="utf-8")
        for _ in range(runs):
            res = subprocess.run(["pdflatex", "-interaction=nonstopmode", tex.name], cwd=tmp,
                                 capture_output=True, text=True, timeout=timeout)
        built = Path(tmp) / f"{name}.pdf"
        if not built.exists():
            raise RuntimeError(res.stdout[-3000:])
        Path(out_pdf).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(built, out_pdf)
    return Path(out_pdf)


def _pick(folder, name):
    for ext in GRAPHICS_EXT:
        p = Path(folder) / f"{name}{ext}"
        if p.is_file():
            return p
    return None


def _stack_image(old, new, printed, scale_b, gb, ga, out_png, dpi):
    """One PNG: the old figure above the new one, both at the printed width, so text sizes compare as printed."""
    small = lambda g, k: rf", smallest text {k * min(g):.1f}\,pt" if g else ""  # noqa: E731
    drawn = (rf"drawn {printed / scale_b:.2f}\,in wide, printed at {100 * scale_b:.0f}\,\%"
             if abs(scale_b - 1) > 0.02 else "drawn at the printed size")
    body = (rf"\begin{{minipage}}{{{printed:.4f}in}}"
            rf"\textbf{{Before}}: {drawn}{small(gb, scale_b)}.\par\smallskip"
            rf"\includegraphics[width={printed:.4f}in]{{{old}}}\par\bigskip"
            rf"\textbf{{After}}: drawn at the printed size, {printed:.2f}\,in{small(ga, 1.0)}.\par\smallskip"
            rf"\includegraphics[width={printed:.4f}in]{{{new}}}\end{{minipage}}")
    tex = (r"\documentclass[border=8pt,10pt]{standalone}\usepackage{graphicx}" "\n"
           r"\begin{document}" + body + r"\end{document}" "\n")
    with tempfile.TemporaryDirectory() as tmp:
        pdf = _compile(tex, "stack", Path(tmp) / "stack.pdf", runs=1)
        _run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", str(pdf), str(Path(tmp) / "stack")])
        Path(out_png).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(tmp) / "stack.png", out_png)
    return Path(out_png)


def compare(record_path=None, before=None, after=None, out=None, png=None, dpi=150):
    """Build before_after.pdf, and with `png` a folder one image per figure. Returns the PDF path and the table rows."""
    proj = Project(record_path)
    after = Path(after).resolve() if after else proj.out
    before = Path(before).resolve() if before else None
    out = Path(out) if out else after / "before_after.pdf"
    figs = proj.record.get("figures") or {}
    in_paper = sorted((n for n, f in figs.items() if f.get("in_manuscript")),
                      key=lambda n: (figs[n].get("figure") or 10 ** 6, figs[n].get("panel") or ""))
    extras = sorted(p.stem for p in after.glob("*.pdf") if p.stem not in figs or not figs[p.stem].get("in_manuscript"))

    rows, pages, table = [], [], []
    for name in in_paper + extras:
        if name in OUTPUT_NAMES:
            continue
        new = _pick(after, name)
        if new is None:
            continue
        entry = figs.get(name, {})
        used = bool(entry.get("in_manuscript"))
        old = _pick(before, name) if before else None
        if old is None and used and entry.get("path"):
            old = proj.dir / entry["path"]
        if old is None or not old.is_file() or old.resolve() == new.resolve():
            continue
        new_w = native_size_in(new)[0]
        printed = float(entry["width_in"]) if used and entry.get("width_in") else new_w
        old_size = native_size_in(old)
        scale_b, scale_a = printed / old_size[0], printed / new_w
        gb = glyph_sizes(old) if old.suffix.lower() == ".pdf" else []
        ga = glyph_sizes(new)
        report = after / f"{name}.check.json"
        s = json.loads(report.read_text())["summary"] if report.exists() else None
        rng = lambda g, k: f"{k * min(g):.1f}--{k * max(g):.1f}" if g else "n/a"  # noqa: E731
        num = str(entry.get("figure")) if entry.get("figure") else "-"
        table.append(dict(name=name, figure=entry.get("figure"), before_scale=scale_b, after_scale=scale_a,
                          before_glyphs=(scale_b * min(gb), scale_b * max(gb)) if gb else None,
                          after_glyphs=(scale_a * min(ga), scale_a * max(ga)) if ga else None,
                          checks=s))
        if png:
            table[-1]["png"] = str(_stack_image(old, new, printed, scale_b, gb, [scale_a * g for g in ga],
                                                Path(png) / f"{name}.png", dpi))
        rows.append(rf"\texttt{{\detokenize{{{name}}}}} & {num} & {100 * scale_b:.0f}\,\% & {rng(gb, scale_b)} & "
                    rf"{100 * scale_a:.0f}\,\% & {rng(ga, scale_a)} & "
                    + (f"{s['fail']} / {s['warn']}" if s else "--") + r" \\")
        where = (rf"Fig.~{num} of the manuscript, \texttt{{\detokenize{{\includegraphics[{entry.get('include', '')}]}}}}, "
                 rf"printed {printed:.2f}\,in wide" if used else
                 rf"not in the manuscript; both shown {printed:.2f}\,in wide, the width the new version is drawn at")
        pages.append(rf"""
\clearpage
\section*{{\texttt{{\detokenize{{{name}}}}}}}
{where}.

\medskip\textbf{{Before}}: \texttt{{\detokenize{{{os.path.relpath(old, proj.dir)}}}}}, printed at {100 * scale_b:.0f}\,\% of the size it was drawn at.\par\smallskip
\includegraphics[width={printed:.4f}in]{{{old}}}

\bigskip\textbf{{After}}: \texttt{{\detokenize{{{os.path.relpath(new, proj.dir)}}}}}, drawn at the printed size.\par\smallskip
\includegraphics[width={printed:.4f}in]{{{new}}}
""")
    if not rows:
        raise SystemExit("no figure has both a current and a new version; check --before and --after")
    doc = proj.record.get("document") or {}
    title = doc.get("journal") or proj.main.name
    body = rf"""\section*{{Figures before and after}}
Manuscript \texttt{{\detokenize{{{proj.main.name}}}}}{f" for {title}" if doc.get("journal") else ""}.
Each page shows the figure as the manuscript includes it now and the new version, both at the width they are printed
(text width {proj.target['textwidth_pt']:g}\,pt), so text sizes compare as a reader will see them.

\medskip
``Scale'' is the factor between the size a figure was drawn at and the size it is printed at.
``Glyphs'' is the range of character sizes on the printed page in points, from the smallest subscript to the largest
text, read from the font-size operators inside each PDF (approximate). ``Checks'' counts the failures and warnings of
the measured checks on the new version.

{{\footnotesize
\begin{{longtable}}{{@{{}}lcrrrrc@{{}}}}
\toprule
 & & \multicolumn{{2}}{{c}}{{before}} & \multicolumn{{2}}{{c}}{{after}} & checks \\
figure & Fig. & scale & glyphs (pt) & scale & glyphs (pt) & fail / warn \\
\midrule
\endhead
{chr(10).join(rows)}
\bottomrule
\end{{longtable}}
}}
{''.join(pages)}"""
    _compile(_latex_doc(proj.target, body), "before_after", out)
    print(f"wrote {out} ({len(rows)} figures)")
    return out, table


# ──────────────────────────────────────────────────────────────────────────
# Preview the manuscript with the new figures
# ──────────────────────────────────────────────────────────────────────────

def _labels_from_aux(folder):
    labels = {}
    for aux in Path(folder).rglob("*.aux"):
        for m in re.finditer(r"\\newlabel\{([^}]*)\}\{\{([^}]*)\}\{([^}]*)\}", aux.read_text(errors="replace")):
            labels[m.group(1)] = (m.group(2), m.group(3))
    return labels


def preview(record_path=None, figures=None, out=None, timeout=900):
    """Compile a copy of the manuscript with the new figures; returns a report dict."""
    proj = Project(record_path)
    figures = Path(figures).resolve() if figures else proj.out
    out = Path(out) if out else figures / "preview.pdf"
    root = proj.main.parent
    engine = proj.target.get("engine") or detect_engine(proj.main)
    record_figs = proj.record.get("figures") or {}
    replaced, skipped = [], []
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "manuscript"
        skip_out = [figures.name] if figures.parent == root else []
        shutil.copytree(root, work, ignore=shutil.ignore_patterns(
            ".git", "*.aux", "*.log", "*.fls", "*.fdb_latexmk", "*.synctex.gz", "*.out", *skip_out))
        for name, entry in record_figs.items():
            if not entry.get("in_manuscript"):
                continue
            new = _pick(figures, name)
            if new is None:
                continue
            if not entry.get("path"):
                skipped.append((name, "the file the manuscript includes was not found"))
                continue
            old = work / entry["path"]
            inc_ext = Path(entry["file"]).suffix.lower()
            if inc_ext in GRAPHICS_EXT and inc_ext != new.suffix.lower():
                skipped.append((name, f"the manuscript asks for a {inc_ext} file, the new version is {new.suffix}"))
                continue
            for ext in GRAPHICS_EXT:
                old.with_suffix(ext).unlink(missing_ok=True)
            shutil.copy(new, old.with_suffix(new.suffix))
            replaced.append(name)

        main = work / proj.main.name
        flag = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}[engine]
        env = {**os.environ, "max_print_line": "10000"}
        if shutil.which("latexmk"):
            subprocess.run(["latexmk", flag, "-interaction=nonstopmode", "-f", main.name], cwd=work,
                           capture_output=True, text=True, timeout=timeout, env=env)
        else:
            for k in range(3):
                subprocess.run([engine, "-interaction=nonstopmode", main.name], cwd=work, capture_output=True,
                               text=True, timeout=timeout, env=env)
                if k == 0 and shutil.which("bibtex"):
                    subprocess.run(["bibtex", main.stem], cwd=work, capture_output=True, text=True, timeout=120)
        built = main.with_suffix(".pdf")
        log = main.with_suffix(".log").read_text(errors="replace") if main.with_suffix(".log").exists() else ""
        if not built.exists():
            raise RuntimeError("the manuscript did not compile:\n" + "\n".join(log.splitlines()[-30:]))
        labels = _labels_from_aux(work)
        info = _run(["pdfinfo", str(built)]) or ""
        m = re.search(r"Pages:\s+(\d+)", info)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(built, out)

    errors = [l for l in log.splitlines() if l.startswith("! ")]
    report = {
        "pdf": str(out),
        "pages": int(m.group(1)) if m else None,
        "replaced": replaced,
        "skipped": skipped,
        "errors": errors,
        "float_too_large": len(re.findall(r"Float too large", log)),
        "missing_files": re.findall(r"File `([^']+)' not found", log),
        "figures": [],
    }
    seen = set()
    for name, entry in sorted(((n, e) for n, e in record_figs.items() if e.get("in_manuscript")),
                              key=lambda x: (x[1].get("figure") or 10 ** 6)):
        lab = entry.get("label")
        num, page = labels.get(lab, (None, None)) if lab else (None, None)
        report["figures"].append({"name": name, "label": lab, "figure": num, "page": page,
                                  "new": name in replaced})
        seen.add(name)
    return report


def print_preview(report):
    print(f"wrote {report['pdf']} ({report['pages']} pages)")
    for f in report["figures"]:
        print(f"  Fig. {f['figure'] or '?':>3} on page {f['page'] or '?':>3}  {f['name']:<32} "
              + ("new version" if f["new"] else "current version"))
    for name, why in report["skipped"]:
        print(f"  not replaced: {name}: {why}")
    for key, label in (("errors", "LaTeX errors"), ("missing_files", "missing files")):
        if report[key]:
            print(f"  {label}: " + "; ".join(report[key][:5]))
    if report["float_too_large"]:
        print(f"  {report['float_too_large']} float(s) too large for the page")


# ──────────────────────────────────────────────────────────────────────────
# Command line
# ──────────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="measure the manuscript, write figures.yaml and FIGURES.md")
    p.add_argument("main", help="the main .tex file")
    p.add_argument("--output-dir", help=f"where new figures go, relative to main.tex (default {DEFAULT_OUTPUT})")
    p.add_argument("--textwidth", help="skip the measurement and use this text width, e.g. 468pt")
    p.add_argument("--columnwidth", help="with --textwidth, the column width of a two-column layout")
    p = sub.add_parser("index", help="re-read the .tex files, rewrite FIGURES.md")
    p.add_argument("record", nargs="?")
    p = sub.add_parser("compare", help="before_after.pdf of the current and the new figures")
    p.add_argument("record", nargs="?")
    p.add_argument("--before", help="folder with the old versions (default: what the manuscript includes)")
    p.add_argument("--after", help="folder with the new versions (default: output_dir)")
    p.add_argument("--out", help="the PDF to write (default: <after>/before_after.pdf)")
    p.add_argument("--png", metavar="DIR", help="also write one PNG per figure, before above after, to DIR")
    p.add_argument("--dpi", type=int, default=150, help="resolution of the PNGs (default 150)")
    p = sub.add_parser("preview", help="compile a copy of the manuscript with the new figures")
    p.add_argument("record", nargs="?")
    p.add_argument("--figures", help="folder with the new figures (default: output_dir)")
    p.add_argument("--out", help="the PDF to write (default: <figures>/preview.pdf)")
    args = ap.parse_args(argv)

    if args.cmd == "init":
        init(args.main, args.output_dir, args.textwidth, args.columnwidth)
    elif args.cmd == "index":
        index(args.record)
    elif args.cmd == "compare":
        compare(args.record, args.before, args.after, args.out, args.png, args.dpi)
    elif args.cmd == "preview":
        report = preview(args.record, args.figures, args.out)
        print_preview(report)
        return 1 if report["errors"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
