"""Tests for learn_style: past work drawn in a known style must give that style back.

Run with `python tests/test_learn_style.py` or with pytest. Needs poppler-utils (pdftocairo, pdfimages);
the paper test also needs pdflatex.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib

os.environ["BRAINDANCE_PROFILE"] = "none"
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "latex-scientific-plots"))
sys.path.insert(0, str(HERE))
import colours as C  # noqa: E402
import learn_style as LS  # noqa: E402
import style_profile as SP  # noqa: E402
from learn_fixtures import STYLE, make_figures  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="learn_style_"))
HAS_POPPLER = all(shutil.which(t) for t in ("pdftocairo", "pdfimages", "pdfinfo"))
_cache = {}


def learned(paths, key):
    if key not in _cache:
        text, decision, ev = LS.learn(paths)
        path = TMP / f"{key}.yaml"
        path.write_text(text)
        _cache[key] = (SP.resolve(SP.read_profile(path), [str(path)]), decision, text)
    return _cache[key]


def personal_figures():
    folder = TMP / "personal"
    if not folder.exists():
        folder.mkdir()
        make_figures(folder)
    return sorted(folder.glob("past_*.pdf"))


def skip_without_poppler():
    if not HAS_POPPLER:
        print("      (skipped: poppler-utils not installed)")
        return True
    return False


# ---- figures in a personal style ----

def test_palette_and_its_order_are_recovered():
    if skip_without_poppler():
        return
    prof, decision, text = learned(personal_figures(), "personal")
    # the fifth colour is used in one figure only: left out, and said so
    assert prof.palette == STYLE["palette"][:4], prof.palette
    assert STYLE["palette"][4] in text and "one figure only" in text


def test_ticks_frames_and_widths_are_recovered():
    if skip_without_poppler():
        return
    prof, decision, _ = learned(personal_figures(), "personal")
    for key, value in STYLE["rc"].items():
        assert key in prof.rc, (key, decision["undecided"])
        got = prof.rc[key]
        assert (abs(got - value) < 0.11) if isinstance(value, float) else got == value, (key, got, value)
    assert "axes.grid" not in prof.rc  # no grid, as in the house style


def test_colormap_from_an_image_and_font_is_only_reported():
    if skip_without_poppler():
        return
    prof, decision, text = learned(personal_figures(), "personal")
    assert prof.colormaps["sequential"] == "magma"
    assert prof.font["preset"] == "computer-modern" and "DejaVu" in text


def test_house_style_figures_learn_nothing_new():
    if skip_without_poppler():
        return
    folder = TMP / "house"
    folder.mkdir(exist_ok=True)
    rc = {k: v for k, v in matplotlib.rc_params_from_file(str(SP.HOUSE_STYLE), use_default_template=False).items()
          if not k.startswith(("text.", "font.", "mathtext."))}
    house = {"palette": SP.HOUSE_PALETTE, "cmap": "viridis",
             "rc": {k: rc[k] for k in ("xtick.direction", "ytick.direction", "xtick.top", "ytick.right",
                                       "xtick.minor.visible", "ytick.minor.visible", "lines.linewidth",
                                       "axes.linewidth", "xtick.major.width", "ytick.major.width")}}
    paths = make_figures(folder, house)
    prof, decision, _ = learned(paths, "house")
    assert prof.rc == {}, (prof.rc, decision["rc_notes"])
    assert prof.palette == [c.lower() for c in SP.HOUSE_PALETTE[:4]], prof.palette
    assert prof.colormaps == SP.HOUSE_COLORMAPS


def test_grid_is_learned():
    if skip_without_poppler():
        return
    folder = TMP / "grid"
    folder.mkdir(exist_ok=True)
    style = {**STYLE, "rc": {**STYLE["rc"], "grid.color": "#dddddd", "grid.linewidth": 0.5}}
    paths = make_figures(folder, style, grid=True)
    prof, decision, _ = learned(paths, "grid")
    assert prof.rc.get("axes.grid") is True, decision["undecided"]
    assert prof.rc.get("grid.color") == "#dddddd" and abs(prof.rc.get("grid.linewidth") - 0.5) < 0.11, prof.rc


def test_a_paper_with_coloured_links_and_a_table():
    if skip_without_poppler() or not shutil.which("pdflatex"):
        print("      (skipped: needs pdflatex)")
        return
    figs = personal_figures()
    paper = TMP / "paper"
    paper.mkdir(exist_ok=True)
    for f in figs[:2]:
        shutil.copy(f, paper / f.name)
    body = "\n".join(rf"\begin{{figure}}\centering\includegraphics[width=\linewidth]{{{f.name}}}"
                     rf"\caption{{Figure \ref{{s}} with a \href{{https://example.org}}{{link}}.}}\end{{figure}}"
                     for f in figs[:2])
    tex = (r"\documentclass{article}\usepackage{graphicx,booktabs}"
           r"\usepackage[colorlinks,linkcolor=red,urlcolor=green!60!black,citecolor=blue]{hyperref}"
           r"\begin{document}\section{Intro}\label{s}Text with a \href{https://example.org}{green link} "
           r"and a reference to Section~\ref{s}. " * 3
           + r"\begin{table}[h]\centering\begin{tabular}{lrr}\toprule a & b & c\\\midrule 1 & 2 & 3\\"
             r"4 & 5 & 6\\\bottomrule\end{tabular}\end{table}" + body + r"\end{document}")
    (paper / "paper.tex").write_text(tex)
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "paper.tex"], cwd=paper, capture_output=True)
    pdf = paper / "paper.pdf"
    assert pdf.exists()
    prof, decision, _ = learned([pdf], "paper")
    # only the figures' colours: not the red, green and blue of the links
    for c in prof.palette:
        assert min(float(C.delta_e(C.rgb_to_lab(C.to_rgb(c)), C.rgb_to_lab(C.to_rgb(s)))) for s in STYLE["palette"]) < 3, \
            (c, prof.palette)
    assert prof.palette[:3] == STYLE["palette"][:3]
    assert prof.rc.get("xtick.direction") == "out" and prof.rc.get("axes.spines.top") is False, prof.rc


# ---- scripts and style files ----

def test_scripts_and_style_files():
    style = TMP / "mine.mplstyle"
    style.write_text("axes.grid: True\ngrid.alpha: 0.3\nfont.family: sans-serif\nfont.size: 12\n"
                     "axes.prop_cycle: cycler('color', ['2a9d8f', 'e76f51', '264653'])\n")
    script = TMP / "plot_a.py"
    script.write_text(
        "import matplotlib.pyplot as plt\nimport matplotlib as mpl\n"
        "plt.style.use('mine.mplstyle')\n"
        "plt.rcParams.update({'xtick.direction': 'out', 'axes.spines.right': False, 'figure.figsize': (8, 6)})\n"
        "mpl.rc('lines', linewidth=2.2)\n"
        "plt.rcParams['ytick.direction'] = 'out'\n"
        "COLOURS = ['#2a9d8f', '#e76f51', '#264653', '#e9c46a']\n"
        "fig, ax = plt.subplots()\nax.imshow([[1, 2]], cmap='cividis')\nax.plot([1, 2], color='#e76f51')\n")
    other = TMP / "plot_b.py"
    other.write_text("import matplotlib.pyplot as plt\nplt.style.use('ggplot')\n"
                     "plt.rcParams.update({'xtick.direction': 'out'})\nplt.pcolormesh([[1]], cmap='jet')\n")
    prof, decision, text = learned([script, other], "scripts")
    assert prof.palette == ["#2a9d8f", "#e76f51", "#264653", "#e9c46a"], prof.palette  # the explicit list
    assert prof.rc["xtick.direction"] == "out" and prof.rc["ytick.direction"] == "out"
    assert prof.rc["axes.spines.right"] is False and prof.rc["lines.linewidth"] == 2.2
    assert prof.rc["grid.alpha"] == 0.3
    assert prof.colormaps["sequential"] == "cividis"
    assert "jet" in text and "not kept" in text and "jet" not in prof.colormaps.values()
    # typography and fonts are the document's, never learned
    for key in prof.rc:
        assert not key.startswith(("font.", "text.", "figure.figsize")) and not key.endswith("size") \
            or key.startswith(("xtick.major", "ytick.major")), key
    assert prof.font["preset"] == "computer-modern"
    # ggplot (one script) and mine.mplstyle disagree on the grid: not set
    assert "axes.grid" in text


def test_learn_command_writes_a_loadable_profile_and_preview():
    if skip_without_poppler():
        return
    out = TMP / "cli" / "profile.yaml"
    png = TMP / "cli" / "preview.png"
    assert SP.main(["learn", *map(str, personal_figures()), "-o", str(out), "--preview", str(png)]) == 0
    assert SP.read_profile(out)["palette"] and png.stat().st_size > 5000
    try:
        SP.main(["learn", str(personal_figures()[0]), "-o", str(out)])
    except SystemExit as exc:
        assert "exists" in str(exc)
    else:
        raise AssertionError("an existing profile was overwritten without --force")


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(exc).__name__}: {str(exc)[:900]}")
    plt.close("all")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
