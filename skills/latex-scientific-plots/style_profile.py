"""Personal style: the researcher's own look, layered on the house style.

What makes a figure correct and readable is fixed and checked for everyone (values
equal the data, printed width, text of 6 pt or more, no rainbow colormaps, series
that stay apart for colour-blind readers). What is taste belongs to the researcher:
the colours, the colormaps, the font, ticks, frames, grids and line weights.

Layers, each overriding the one before:

  1. the house style          latex-paper.mplstyle, next to this file
  2. the personal profile     $BRAINDANCE_PROFILE, else ~/.config/braindance/profile.yaml
                              (BRAINDANCE_PROFILE=none ignores it)
  3. the paper                `profile:` in a manuscript's figures.yaml, inline or a file;
                              `personal: false` there pins one look for every co-author
  4. the figure               whatever the script sets after setup()

A profile (every key optional):

    name: My style
    palette: ['#1b4f72', '#c0392b', '#7d9c3a', '#8e44ad']   # colour cycle, in order
    keep: [0]                  # palette entries `check` must never change
    colormaps: {sequential: cividis, diverging: RdBu_r}
    font: computer-modern      # times, helvetica, or a mapping (see FONT_PRESETS)
    mplstyle: ~/my.mplstyle    # your own style file, applied after the house style
    rc:                        # any matplotlib rcParams, applied last
      xtick.direction: out
      axes.spines.top: false

In a plotting script:

    from style_profile import setup
    style = setup()                         # house style + your profile
    style.palette, style.cmap("diverging")

From the shell:

    python style_profile.py init     # write a starter profile to edit
    python style_profile.py show     # the resolved profile and where each part came from
    python style_profile.py check    # palette, colormaps and font; suggests a fix that keeps your hues
    python style_profile.py learn paper.pdf fig*.pdf plot.py --preview p.png
                                     # a draft profile from past figures, papers and scripts
"""
from __future__ import annotations

import copy
import os
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))  # for colours.py
HOUSE_STYLE = SKILL_DIR / "latex-paper.mplstyle"
HOUSE_PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000", "#F0E442"]
HOUSE_COLORMAPS = {"sequential": "viridis", "diverging": "RdBu_r"}

_LATEX_BASE = r"\usepackage{amsmath}\usepackage{amssymb}\usepackage{siunitx}"
# Math symbol and extension fonts LaTeX takes from Computer Modern or AMS whatever the text font.
_MATH_SYMBOL_FONTS = ("cmsy", "cmex", "cmmi", "msam", "msbm", "eufm", "rsfs", "stmary")

FONT_PRESETS = {
    "computer-modern": {
        "family": "serif",
        "usetex": {"font.family": "serif", "text.latex.preamble": _LATEX_BASE},
        "fallback": {"font.family": "serif", "font.serif": ["cmr10"], "mathtext.fontset": "cm",
                     "axes.formatter.use_mathtext": True},
        "pdf_fonts": ("cm", "sfrm", "sfti", "sfbx", "lm", "ec", "msam", "msbm", "eufm", "rsfs"),
    },
    "times": {
        "family": "serif",
        "usetex": {"font.family": "serif", "font.serif": ["Times"],
                   "text.latex.preamble": _LATEX_BASE.replace(r"\usepackage{amssymb}", "")
                   + r"\usepackage{newtxtext,newtxmath}"},
        "fallback": {"font.family": "serif", "mathtext.fontset": "stix",
                     "font.serif": ["STIXGeneral", "Nimbus Roman", "TeX Gyre Termes", "Times New Roman"]},
        "pdf_fonts": ("NewTX", "tx", "TeXGyreTermes", "NimbusRom", "Times", "STIX"),
    },
    "helvetica": {
        "family": "sans-serif",
        "usetex": {"font.family": "sans-serif", "font.sans-serif": ["Helvetica"],
                   "text.latex.preamble": _LATEX_BASE + r"\usepackage{sansmath}\sansmath"},
        "fallback": {"font.family": "sans-serif", "mathtext.fontset": "stixsans",
                     "font.sans-serif": ["Helvetica", "Arial", "Nimbus Sans", "TeX Gyre Heros", "Liberation Sans",
                                         "Arimo"]},
        "pdf_fonts": ("Helvetica", "Arial", "NimbusSan", "Nimbus Sans", "TeXGyreHeros", "LiberationSans",
                      "Arimo", "uhv", "STIX"),
    },
}

KNOWN_KEYS = {"name", "palette", "keep", "colormaps", "font", "mplstyle", "rc", "personal"}
FONT_KEYS = {"preset", "family", "serif", "sans-serif", "latex_preamble", "mathtext_fontset", "pdf_fonts"}
# setup() owns these: they depend on the machine (LaTeX installed or not) or on the canvas being the printed size
_OWNED_RC = {"text.usetex"}

_ACTIVE = None


class ProfileError(ValueError):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Finding and merging profiles
# ──────────────────────────────────────────────────────────────────────────

def personal_path():
    """The personal profile file, or None when BRAINDANCE_PROFILE=none. The file need not exist."""
    env = os.environ.get("BRAINDANCE_PROFILE")
    if env is not None:
        return None if env.strip().lower() in ("", "none", "off", "0") else Path(env).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "braindance" / "profile.yaml"


def _yaml():
    try:
        import yaml
    except ImportError as exc:
        raise ProfileError("PyYAML is needed to read a style profile: pip install pyyaml") from exc
    return yaml


def read_profile(path):
    path = Path(path).expanduser()
    data = _yaml().safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: a profile is a mapping of keys such as palette, font, rc")
    return validate(data, str(path), base_dir=path.parent)


def validate(data, where="profile", base_dir=None):
    """Check a profile's keys and values; returns a normalised copy."""
    from matplotlib.colors import to_hex
    data = copy.deepcopy(dict(data))
    unknown = set(data) - KNOWN_KEYS
    if unknown:
        raise ProfileError(f"{where}: unknown key(s) {sorted(unknown)}; known keys are {sorted(KNOWN_KEYS)}")
    if "palette" in data:
        pal = data["palette"]
        if isinstance(pal, str) or not isinstance(pal, (list, tuple)) or not pal:
            raise ProfileError(f"{where}: palette is a list of colours, e.g. ['#1b4f72', '#c0392b']")
        try:
            data["palette"] = [to_hex(c) for c in pal]
        except ValueError as exc:
            raise ProfileError(f"{where}: palette: {exc}") from None
    if "keep" in data:
        n = len(data.get("palette") or [])
        keep = data["keep"]
        if not isinstance(keep, (list, tuple)) or not all(isinstance(k, int) for k in keep):
            raise ProfileError(f"{where}: keep is a list of palette indices, e.g. [0, 2]")
        if n and any(not -n <= k < n for k in keep):
            raise ProfileError(f"{where}: keep {keep} points outside the {n}-colour palette")
    if "colormaps" in data:
        import matplotlib as mpl
        cms = data["colormaps"]
        if not isinstance(cms, dict) or set(cms) - {"sequential", "diverging"}:
            raise ProfileError(f"{where}: colormaps is a mapping with keys sequential and diverging")
        for kind, name in cms.items():
            if name not in mpl.colormaps:
                raise ProfileError(f"{where}: colormaps.{kind}: no colormap named {name!r}")
    if "font" in data:
        f = data["font"]
        if isinstance(f, str):
            if f not in FONT_PRESETS:
                raise ProfileError(f"{where}: font {f!r} is not a preset; presets are {sorted(FONT_PRESETS)}, "
                                   "or give a mapping with family, serif or sans-serif, latex_preamble, "
                                   "mathtext_fontset and pdf_fonts")
        elif isinstance(f, dict):
            bad = set(f) - FONT_KEYS
            if bad:
                raise ProfileError(f"{where}: unknown font key(s) {sorted(bad)}; known are {sorted(FONT_KEYS)}")
            if "preset" in f and f["preset"] not in FONT_PRESETS:
                raise ProfileError(f"{where}: font.preset {f['preset']!r}; presets are {sorted(FONT_PRESETS)}")
            if f.get("family", "serif") not in ("serif", "sans-serif"):
                raise ProfileError(f"{where}: font.family is serif or sans-serif")
        else:
            raise ProfileError(f"{where}: font is a preset name or a mapping")
    if "rc" in data:
        import matplotlib as mpl
        if not isinstance(data["rc"], dict):
            raise ProfileError(f"{where}: rc is a mapping of matplotlib rcParams")
        bad = [k for k in data["rc"] if k not in mpl.rcParams]
        if bad:
            raise ProfileError(f"{where}: rc: not matplotlib settings: {bad}")
    if "mplstyle" in data:
        p = Path(str(data["mplstyle"])).expanduser()
        if not p.is_absolute() and base_dir is not None:
            p = Path(base_dir) / p
        if not p.is_file():
            raise ProfileError(f"{where}: mplstyle {data['mplstyle']!r} not found")
        data["mplstyle"] = str(p.resolve())
    return data


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k in ("rc", "colormaps") and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        elif k == "font" and isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = {**out[k], **v}
        elif k == "palette" and "keep" not in over:
            out[k] = v
            out.pop("keep", None)  # indices of the old palette mean nothing for the new one
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_profile(paper=None, base_dir=None, personal=True):
    """Resolve the layers into one profile.

    paper     the `profile` entry of a figures.yaml: a mapping, or a path to a profile file
              (relative to base_dir). `personal: false` in it ignores the personal profile.
    personal  False to ignore the personal profile (e.g. for examples that show the house style).
    """
    layers = []
    if isinstance(paper, (str, Path)):
        p = Path(paper).expanduser()
        if not p.is_absolute() and base_dir is not None:
            p = Path(base_dir) / p
        paper = read_profile(p)
        paper_where = str(p)
    elif paper:
        paper = validate(paper, "figures.yaml profile", base_dir=base_dir)
        paper_where = "figures.yaml profile"
    use_personal = personal and not (paper and paper.get("personal") is False)
    if use_personal:
        p = personal_path()
        if p is not None and p.is_file():
            layers.append((str(p), read_profile(p)))
        elif p is not None and os.environ.get("BRAINDANCE_PROFILE"):
            raise ProfileError(f"BRAINDANCE_PROFILE points to {p}, which does not exist")
    if paper:
        layers.append((paper_where, {k: v for k, v in paper.items() if k != "personal"}))
    merged = {}
    for _, layer in layers:
        merged = _merge(merged, layer)
    return resolve(merged, [w for w, _ in layers])


def resolve(raw, sources=()):
    """Fill in the house defaults; the result is what setup() applies and the checker reads."""
    font = raw.get("font", "computer-modern")
    if isinstance(font, str):
        font = {"preset": font}
    if "preset" in font:
        name = font["preset"]
    elif set(font) & {"family", "serif", "sans-serif", "mathtext_fontset"}:
        name = "custom"
    else:  # only additions (latex_preamble, pdf_fonts) to the house font
        name = "computer-modern"
    preset = FONT_PRESETS.get(name)
    if preset is None:
        family = font.get("family", "serif")
        usetex = {"font.family": family, "text.latex.preamble": _LATEX_BASE + font.get("latex_preamble", "")}
        fallback = {"font.family": family, "mathtext.fontset": font.get("mathtext_fontset", "custom"),
                    "axes.formatter.use_mathtext": True}
        if font.get(family):
            usetex[f"font.{family}"] = list(font[family])
            fallback[f"font.{family}"] = list(font[family])
            if fallback["mathtext.fontset"] == "custom":
                fallback.update({"mathtext.rm": font[family][0], "mathtext.it": f"{font[family][0]}:italic",
                                 "mathtext.bf": f"{font[family][0]}:bold"})
        pdf_fonts = tuple(font.get("pdf_fonts") or ())
        resolved_font = {"preset": "custom", "family": family, "usetex": usetex, "fallback": fallback,
                         "pdf_fonts": pdf_fonts}
    else:
        resolved_font = copy.deepcopy({"preset": name, **preset})
        if font.get("latex_preamble"):
            resolved_font["usetex"]["text.latex.preamble"] += font["latex_preamble"]
        if font.get("pdf_fonts"):
            resolved_font["pdf_fonts"] = tuple(resolved_font["pdf_fonts"]) + tuple(font["pdf_fonts"])
    return Profile(
        name=raw.get("name") or ("house style" if not sources else Path(sources[-1]).stem),
        sources=list(sources),
        palette=list(raw.get("palette") or HOUSE_PALETTE),
        keep=list(raw.get("keep") or []),
        colormaps={**HOUSE_COLORMAPS, **(raw.get("colormaps") or {})},
        font=resolved_font,
        mplstyle=raw.get("mplstyle"),
        rc=dict(raw.get("rc") or {}),
        custom_palette="palette" in raw,
    )


class Profile:
    """A resolved profile: the house style with every layer applied."""

    def __init__(self, name, sources, palette, keep, colormaps, font, mplstyle, rc, custom_palette):
        self.name, self.sources, self.palette, self.keep = name, sources, palette, keep
        self.colormaps, self.font, self.mplstyle, self.rc = colormaps, font, mplstyle, rc
        self.custom_palette = custom_palette
        self.usetex = None

    @property
    def is_house(self):
        return not self.sources

    def cmap(self, kind="sequential"):
        return self.colormaps[kind]

    def pdf_font_prefixes(self):
        """Font names (prefixes) the saved PDF may contain; empty means not declared."""
        own = tuple(self.font.get("pdf_fonts") or ())
        return own + _MATH_SYMBOL_FONTS if own else ()

    def summary(self):
        """What the measured-check report records, so the reviewer knows the researcher's choices."""
        return {"name": self.name, "sources": self.sources or ["house style"], "font": self.font["preset"],
                "font_family": self.font["family"], "palette": self.palette, "colormaps": self.colormaps,
                "rc": {k: str(v) for k, v in self.rc.items()}, "mplstyle": self.mplstyle}

    def __repr__(self):
        return f"Profile({self.name!r}, font={self.font['preset']}, palette={self.palette})"


# ──────────────────────────────────────────────────────────────────────────
# Applying
# ──────────────────────────────────────────────────────────────────────────

def setup(profile=None, *, paper=None, base_dir=None, personal=True, quiet=False):
    """Apply the house style, then the profile. Returns the Profile; `.usetex` says how text is set.

    profile   a Profile, a path to a profile file, or None to resolve the layers
    paper     the `profile` entry of a figures.yaml (see load_profile)
    """
    global _ACTIVE
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from cycler import cycler

    if profile is None:
        profile = load_profile(paper, base_dir=base_dir, personal=personal)
    elif not isinstance(profile, Profile):
        profile = resolve(read_profile(profile), [str(profile)])

    plt.style.use(str(HOUSE_STYLE))
    has_latex = shutil.which("latex") is not None
    mpl.rcParams.update(profile.font["usetex"] if has_latex else profile.font["fallback"])
    mpl.rcParams["text.usetex"] = has_latex
    mpl.rcParams["axes.prop_cycle"] = cycler(color=profile.palette)
    mpl.rcParams["image.cmap"] = profile.colormaps["sequential"]
    if profile.mplstyle:
        plt.style.use(profile.mplstyle)
    rc = {k: v for k, v in profile.rc.items() if k not in _OWNED_RC}
    mpl.rcParams.update(rc)
    mpl.rcParams["text.usetex"] = has_latex
    profile.usetex = has_latex
    _ACTIVE = profile

    if not quiet:
        where = ", ".join(profile.sources) if profile.sources else "no personal profile"
        mode = "LaTeX" if has_latex else "mathtext (no LaTeX installed)"
        print(f"style: {profile.name} ({where}); font {profile.font['preset']}, text by {mode}")
        if profile.custom_palette:
            from colours import check_palette
            res = check_palette(profile.palette)
            if not res["ok"]:
                print(f"style: only the first {res['safe_prefix']} palette colours stay apart for colour-blind "
                      f"readers; run `python {Path(__file__).name} check` for the nearest palette that works")
        for k in profile.rc:
            if k in _OWNED_RC:
                print(f"style: ignored rc {k}: set from whether LaTeX is installed")
    return profile


def active():
    """The profile applied by the last setup(), or None if setup() was not called."""
    return _ACTIVE


# ──────────────────────────────────────────────────────────────────────────
# Checking a profile
# ──────────────────────────────────────────────────────────────────────────

def check_profile(profile):
    """Palette, colormaps and font of a profile. Returns (ok, lines, suggestion or None)."""
    from colours import check_colormap, check_palette, describe, suggest_palette
    lines, ok = [], True
    res = check_palette(profile.palette)
    lines.append(f"palette ({len(profile.palette)} colours): " + describe(res).replace("\n", "\n  "))
    suggestion = None
    if not res["ok"]:
        ok = False
        suggestion = suggest_palette(profile.palette, keep=profile.keep)
    for kind, name in profile.colormaps.items():
        r = check_colormap(name, kind)
        lines.append(f"colormaps.{kind} {name}: " + ("lightness runs the right way" if r["ok"] else r["problem"]))
        ok &= r["ok"]
    lines += _check_font(profile)
    return ok, lines, suggestion


def _check_font(profile):
    import re
    import subprocess
    f = profile.font
    pre = f["usetex"].get("text.latex.preamble", "")
    out = []
    if shutil.which("kpsewhich"):
        pkgs = [p.strip() for grp in re.findall(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}", pre) for p in grp.split(",")]
        missing = []
        for p in pkgs:
            res = subprocess.run(["kpsewhich", f"{p}.sty"], capture_output=True, text=True)
            if not res.stdout.strip():
                missing.append(p)
        out.append(f"font {f['preset']} ({f['family']}): " + (f"LaTeX packages not installed: {missing}" if missing
                   else "LaTeX packages installed" if pkgs else "no LaTeX packages needed"))
    if f["preset"] == "custom" and not f.get("pdf_fonts"):
        out.append("font: give pdf_fonts (font name prefixes as pdffonts prints them) so the checker can tell a "
                   "stray font from yours; until then fonts are listed, not checked")
    return out


def swatch(profile, path, suggestion=None):
    """A PNG of the palette as seen by each reader, the suggested palette below it."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from colours import VISIONS, simulate, to_rgb
    rows = [("yours", profile.palette)] + ([("suggested", suggestion["colours"])] if suggestion else [])
    cols = list(VISIONS) + ["grey"]
    with plt.rc_context({"text.usetex": False, "font.family": "sans-serif", "font.size": 8}):
        fig, axes = plt.subplots(len(rows), len(cols), figsize=(1.6 * len(cols), 1.0 * len(rows) + 0.3),
                                 squeeze=False, layout="constrained")
        for r, (label, pal) in enumerate(rows):
            rgb = np.array([to_rgb(c) for c in pal])
            for c, vision in enumerate(cols):
                ax = axes[r, c]
                if vision == "grey":
                    from colours import rgb_to_lab
                    L = rgb_to_lab(rgb)[:, 0] / 100
                    img = np.repeat(L[:, None], 3, axis=1)
                else:
                    img = simulate(rgb, vision)
                ax.imshow(img[None, :, :], aspect="auto")
                ax.set_xticks([]), ax.set_yticks([])
                if r == 0:
                    ax.set_title(vision, fontsize=8)
                if c == 0:
                    ax.set_ylabel(label, fontsize=8)
        fig.savefig(path, dpi=150)
        plt.close(fig)
    return path


_TEMPLATE = """\
# braindance personal style profile. Every key is optional: what is missing comes
# from the house style. Check it with:  python style_profile.py check
#
# Taste lives here. Correctness does not: the measured checks (values equal the data,
# printed width, text of 6 pt or more, no rainbow colormaps, colours that stay apart
# for colour-blind readers) apply whatever this file says.

name: {name}

# Colour cycle, in the order series get them. Your own colours are welcome:
# `check` tells you if two of them merge for colour-blind readers and suggests the
# nearest palette with the same hues.
palette: {palette}
# keep: [0]            # palette entries `check` must never change

colormaps:
  sequential: viridis  # cividis, magma, Blues, ...
  diverging: RdBu_r    # coolwarm, BrBG, RdYlBu, ...

# Computer Modern unless you want otherwise: times, helvetica, or a mapping:
#   font: {{family: sans-serif, sans-serif: [Fira Sans], latex_preamble: '\\\\usepackage{{FiraSans}}',
#          pdf_fonts: [FiraSans]}}
font: computer-modern

# mplstyle: ~/my.mplstyle   # your own matplotlib style file, applied after the house style

# Any matplotlib setting, applied last. Examples of common personal choices:
rc: {{}}
#   xtick.direction: out
#   ytick.direction: out
#   xtick.top: false
#   ytick.right: false
#   axes.spines.top: false
#   axes.spines.right: false
#   axes.grid: true
#   grid.alpha: 0.3
#   lines.linewidth: 1.5
"""


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="The personal style profile: write, show and check it.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="write a starter profile")
    p_init.add_argument("path", nargs="?", help="default: the personal profile path")
    p_init.add_argument("--force", action="store_true")
    p_show = sub.add_parser("show", help="the resolved profile and where it came from")
    p_check = sub.add_parser("check", help="check palette, colormaps and font; suggest a palette that works")
    for p in (p_show, p_check):
        p.add_argument("path", nargs="?", help="a profile file or figures.yaml (default: the personal profile)")
    p_check.add_argument("--swatch", help="write a PNG of the palette as each reader sees it")
    p_learn = sub.add_parser("learn", help="a draft profile from past figures (PDF), papers (PDF), scripts (.py) "
                             "and style files (.mplstyle)")
    p_learn.add_argument("files", nargs="+")
    p_learn.add_argument("-o", "--output", help="where to write it (default: the personal profile, if there is none "
                         "yet)")
    p_learn.add_argument("--name", default="Learned style")
    p_learn.add_argument("--preview", help="also draw a sample figure with the learned profile to this PNG")
    p_learn.add_argument("--force", action="store_true", help="overwrite the output file")
    args = ap.parse_args(argv)

    if args.cmd == "learn":
        from learn_style import learn, preview
        out = Path(args.output).expanduser() if args.output else personal_path()
        if out is None:
            raise SystemExit("BRAINDANCE_PROFILE=none; give -o")
        if out.exists() and not args.force:
            raise SystemExit(f"{out} exists; give another path with -o, or --force to overwrite it")
        text, decision, ev = learn(args.files, name=args.name)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        prof = resolve(read_profile(out), [str(out)])  # the draft must load like any profile
        print(text)
        print(f"wrote {out}")
        if args.preview:
            print(f"preview: {preview(prof, args.preview)}")
        return 0

    if args.cmd == "init":
        path = Path(args.path).expanduser() if args.path else personal_path()
        if path is None:
            raise SystemExit("BRAINDANCE_PROFILE=none; give a path")
        if path.exists() and not args.force:
            raise SystemExit(f"{path} exists; edit it, or pass --force to overwrite")
        path.parent.mkdir(parents=True, exist_ok=True)
        pal = "[" + ", ".join(f"'{c}'" for c in HOUSE_PALETTE) + "]"
        path.write_text(_TEMPLATE.format(name="My style", palette=pal), encoding="utf-8")
        print(f"wrote {path}")
        return 0

    if args.path and Path(args.path).name.endswith((".yaml", ".yml")) and Path(args.path).name == "figures.yaml":
        rec = _yaml().safe_load(Path(args.path).read_text(encoding="utf-8")) or {}
        prof = load_profile(rec.get("profile"), base_dir=Path(args.path).resolve().parent)
    elif args.path:
        prof = resolve(read_profile(args.path), [str(Path(args.path).expanduser())])
    else:
        prof = load_profile()

    if args.cmd == "show":
        import json
        print(json.dumps(prof.summary(), indent=2))
        return 0

    ok, lines, suggestion = check_profile(prof)
    print(f"profile: {prof.name} ({', '.join(prof.sources) or 'house style'})")
    for ln in lines:
        print("  " + ln)
    if suggestion:
        print("\n  nearest palette with your hues (only lightness and chroma move):")
        for old, new, m in zip(prof.palette, suggestion["colours"], suggestion["moved"]):
            print(f"    {old} -> {new}" + (f"   moved {m}" if m > 0.05 else "   unchanged"))
        from colours import describe
        print("  " + describe(suggestion["check"]).replace("\n", "\n  "))
        if not suggestion["check"]["ok"]:
            kept = set(prof.keep)
            stuck = [(i, j) for i, j, _, _ in suggestion["check"]["clashes"]]
            if any(i in kept and j in kept for i, j in stuck):
                print("  two colours you keep clash with each other: release one from `keep`")
            else:
                print("  these hues are too close to separate by lightness alone: move one of them apart in the "
                      "cycle (series get colours in order) or replace it")
        print("\n  to use it, set in the profile:\n    palette: [" + ", ".join(f"'{c}'" for c in suggestion["colours"])
              + "]")
    if args.swatch:
        print(f"\n  swatch: {swatch(prof, args.swatch, suggestion)}")
    return 0 if ok else 1


if __name__ == "__main__":
    import style_profile  # one copy of the module, so Profile and the active profile are shared with check_figure

    sys.exit(style_profile.main())
