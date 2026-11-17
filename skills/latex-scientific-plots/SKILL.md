---
name: latex-scientific-plots
description: Use when making scientific plots or figures for papers, theses, posters or slides, especially when all text and numbers must render in LaTeX. Produces publication-ready matplotlib figures sized to journal columns, exported as vector PDF, with the plotted values checked against the source data.
---

# Publication-ready scientific figures with LaTeX text

Every figure made with this skill must look like it was typeset together with the paper: all text, labels, tick numbers, legends and annotations render in LaTeX (Computer Modern serif), at sizes that match the document, and the figure is exported as a vector PDF at its final printed size. The numbers in the figure must be the numbers in the data: every figure is checked against its source files before anyone looks at it.

Files in this skill's folder, `${CLAUDE_SKILL_DIR}`:

- `latex-paper.mplstyle`: the house style.
- `check_figure.py`: measured checks on the data and the style (section 9).
- `chart-choice.md`: which chart suits which data, and the rules that hold for any chart. Read it before choosing a chart type, unless the user has already fixed one.
- `figproject.py`: the figures of a LaTeX manuscript as a project (section 0.1): sizes measured from the document, a figure record, a caption index, a before/after comparison and a preview build.
- `example.py` with `example_data/`: a full working example.

## 0. Data comes from files

- Read every plotted value from a file (CSV, TSV, `.npy`). Never type data values into the script.
- If the numbers arrive in the conversation, in a table or in a log, first save them to a CSV next to the script, show the user that file, and plot from it.
- If the script computes what it plots (means, normalised curves, histograms), also write the plotted values to a CSV next to the figure and declare that file as the source, so the figure can be checked against it and the values can be handed to a journal as source data.
- Give each data series a legend label or a `gid` so the checker can find it: `ax.errorbar(..., gid="run-1")`.

## 0.1 Figures for a LaTeX manuscript: start from the document

When the figures belong to a manuscript you can see (a `.tex` file), measure it instead of guessing sizes from the table in section 2:

```bash
python "${CLAUDE_SKILL_DIR}/figproject.py" init path/to/main.tex      # once, and after changing the class
```

This compiles the manuscript's preamble to read the text width, `\linewidth` inside `figure` and `figure*`, and the body and caption font sizes, then lists every `\includegraphics` with the width it is printed at, the file it includes now, and where the figure is cited. It writes two files next to `main.tex`:

- `figures.yaml`, the record: the measured target, `output_dir` (where new figures go, default `braindance_figures/`, so the current figures are never overwritten), a free-form `style` section for the encoding shared by every figure of the paper, and one entry per figure. Put the colours, markers and line styles you choose in `style`, and read them from there in every script, so a series looks the same in every figure.
- `FIGURES.md`, the index: one line per figure with its printed width, the scale its current file is printed at, and the result of the checks on the new version, then every caption, read from the `.tex` (the `.tex` stays the source of truth). Show it to the user.

In the plotting script, use the project instead of `figsize` from section 2 and `savefig` from section 7:

```python
import sys
sys.path.insert(0, "${CLAUDE_SKILL_DIR}")
from figproject import Project

proj = Project("path/to/figures.yaml")              # or main.tex, or its folder
proj.setup()                                        # section 1, done for you
colours = proj.style("field")                       # the shared encoding, if set
proj.write_csv("spectrum_data", f_Hz=f, S=S)        # values computed in the script (section 0)
fig, ax = plt.subplots(figsize=(proj.width("spectrum"), 2.4))   # the printed width of that figure
...
proj.finish(fig, "spectrum", sources=[{"label": "Data", "file": "spectrum_data.csv", "x": "f_Hz", "y": "S"}],
            script=__file__)
```

`width(name)` is the width the manuscript prints that figure at (its `\includegraphics` file name without extension); for a figure the manuscript does not include yet, give a fraction of `\linewidth`: `proj.width("new_fig", 1.0)`. `finish()` saves the PDF and a 300 dpi PNG to `output_dir`, runs the measured checks of section 9.1 against the printed width with `sources` resolved in `output_dir/source_data/`, records the script, sources and result in `figures.yaml`, and updates `FIGURES.md`. It stops the script on a `fail`. Save the canvas as it is (`setup()` does): the figure is already the printed size, so never crop it with `bbox_inches="tight"`.

After the figures are redrawn, show the user the result in two ways:

```bash
python "${CLAUDE_SKILL_DIR}/figproject.py" compare path/to/figures.yaml   # before_after.pdf in output_dir
python "${CLAUDE_SKILL_DIR}/figproject.py" preview path/to/figures.yaml   # preview.pdf: the manuscript with the new figures
```

`compare` puts each current figure next to its new version, both at the printed width, with a table of scale factors and character sizes; add `--before DIR` for figures the manuscript does not include, and `--png DIR` for one image per figure (before above after, same printed width) to show in slides, e-mails or a README. `preview` compiles a copy of the manuscript with the new figures in place and reports the page each figure lands on; the manuscript folder is not touched. Never replace the user's figure files yourself: they decide when the new versions go in.

## 1. Setup (do this first, every time)

Use the bundled style file `${CLAUDE_SKILL_DIR}/latex-paper.mplstyle` and check whether a LaTeX installation is available. If it is not, fall back to matplotlib's built-in mathtext with Computer Modern so the output still looks like LaTeX.

```python
import shutil
import matplotlib as mpl
import matplotlib.pyplot as plt

plt.style.use("${CLAUDE_SKILL_DIR}/latex-paper.mplstyle")

HAS_LATEX = shutil.which("latex") is not None
if HAS_LATEX:
    mpl.rcParams.update({
        "text.usetex": True,
        "text.latex.preamble": r"\usepackage{amsmath}\usepackage{amssymb}\usepackage{siunitx}",
    })
else:
    # Fallback: no LaTeX on this machine. mathtext + Computer Modern looks the same for most figures.
    mpl.rcParams.update({
        "text.usetex": False,
        "mathtext.fontset": "cm",
        "font.family": "serif",
        "font.serif": ["cmr10"],              # Computer Modern, ships with matplotlib
        "axes.formatter.use_mathtext": True,  # required with cmr10 (minus signs, ticks)
    })
```

Tell the user which mode was used. With the fallback, `\SI{}`, `\text{}` and other package commands are not available: use plain math such as `$t\ (\mathrm{s})$` instead.

## 2. Figure size: always the final printed size

Never scale a figure after export; create it at the width it will have in the document so fonts come out at the true size.

| Target | Width (inches) |
|---|---|
| Single column (Elsevier, APS/REVTeX, IEEE) | 3.4–3.5 |
| Double column / full page width | 7.0–7.2 |
| Nature single / double column | 3.5 / 7.2 (89 mm / 183 mm) |
| A4 thesis text width (approx.) | 6.0 |
| Beamer slide (16:9) | 5.0 |

Height: width × 0.62 (golden ratio) by default, or whatever the data needs. Helper:

```python
def figsize(width_in=3.4, ratio=0.618, nrows=1, ncols=1):
    return (width_in, width_in * ratio * nrows / ncols)
```

If the user has a LaTeX document, measure it with `figproject.py init` (section 0.1) instead of using this table.

## 3. Fonts and sizes

- Body font size in the figure must match the paper's caption or body text: 8–9 pt for journals, 10–11 pt for theses, larger for slides. The style file sets 9 pt labels, 8 pt ticks and legend.
- Use only one font family (serif, Computer Modern). Never mix in sans-serif.
- Panel labels and legends must never overlap data: add headroom with `set_ylim`, use `ncol`, or move the label to an empty corner.
- Do not put a title on the axes for papers; the caption does that job. Use panel labels instead: `(a)`, `(b)`, placed with `ax.text(0.02, 0.95, r"(a)", transform=ax.transAxes, va="top")`.

## 4. Everything in LaTeX

- Every axis label is a raw string with math where appropriate: `r"$E_\mathrm{kin}$ (\si{\electronvolt})"` (usetex) or `r"$E_\mathrm{kin}$ (eV)"` (fallback).
- Variables in italic math (`$x$`, `$\omega$`), units and descriptive subscripts upright (`\mathrm{}`): `$T_\mathrm{eff}$`, not `$T_{eff}$`.
- Units in parentheses or brackets after the quantity, consistently through the whole paper: `Time $t$ (s)`.
- Tick numbers must render in LaTeX too. With usetex this is automatic; with the fallback `axes.formatter.use_mathtext` handles it. For scientific notation use `ax.ticklabel_format(style="sci", scilimits=(-2, 3), useMathText=True)`.
- Prefer folding a scale factor into the label, `$T$ ($10^4$ K)`, over matplotlib's floating `×10^4` offset text, which often collides with legends or titles above the axes.
- Log axes: keep the default `$10^{n}$` labels; never show `1e-3`.
- Legends, colorbar labels, annotations and text boxes follow the same rules.
- Use `\%` for percent signs and escape `_`, `&`, `#` in plain text when usetex is on.

## 5. Colors, markers and lines

- Default color cycle is colorblind-safe (Okabe–Ito): `#0072B2` blue, `#D55E00` vermillion, `#009E73` green, `#CC79A7` purple, `#E69F00` orange, `#56B4E9` sky blue, `#F0E442` yellow, `#000000` black.
- Also vary line style or marker between series so the figure works in grayscale.
- Colormaps: `viridis`/`cividis` for sequential data, `RdBu_r` or `coolwarm` for diverging data centered on a meaningful zero. Never `jet` or `rainbow`.
- Line width 1.0–1.5 pt, marker size 3–4 pt, error bars with small caps (`capsize=2`).

## 6. Axes and layout

- Ticks point inward, on all four sides, with minor ticks on (set by the style file).
- Use `fig, ax = plt.subplots(..., layout="constrained")` so nothing is clipped. For multi-panel figures use `sharex`/`sharey` and remove duplicate labels.
- Legend without frame, placed where it covers no data; use `ncol` or put it outside if crowded.
- Keep axis limits tight to the data, with no wasted white space.

## 7. Export

```python
for _ in range(3):
    fig.draw_without_rendering()  # let constrained layout settle, or the first file saved can differ from the second
fig.savefig("figure.pdf", bbox_inches="tight", pad_inches=0.02)  # vector, for LaTeX
fig.savefig("figure.png", dpi=600, bbox_inches="tight")          # only if a raster preview is needed
```

- PDF is the default (vector, fonts embedded as Type 1 or Type 42; the style file sets `pdf.fonttype: 42`). Use `.pgf` only if the user wants the text typeset by their own document.
- For heavy scatter plots or images, use `rasterized=True` on that artist only, keeping text and axes as vectors.
- In LaTeX include it with `\includegraphics[width=\columnwidth]{figure.pdf}` (width equal to the size the figure was created at).

## 8. Final checklist before handing over

1. Created at final width; nothing will be rescaled.
2. Every piece of text and every number renders in LaTeX/Computer Modern.
3. Units present and upright; variables italic.
4. Colorblind-safe colors plus distinct line styles or markers.
5. No title on the axes (unless it is a slide or the user asked for one); panel labels on multi-panel figures.
6. Saved as vector PDF; open the file or a PNG preview and check that no label is clipped or overlapping.
7. Every series is declared in `sources` and `check_figure` reports no `fail`.

## 9. Check, then review (always, before handing the figure to the user)

A figure is not done when the script runs; it is done when it passes the measured checks and then the review.

### 9.1 Measured checks

End every plotting script with a call to `check_figure`, after the PDF is saved:

```python
import sys
sys.path.insert(0, "${CLAUDE_SKILL_DIR}")
from check_figure import check_figure

check_figure(
    fig,
    sources=[
        # a series read from a file: found by legend label or gid, compared column by column
        {"label": r"Data", "file": "spectrum.csv", "x": "f_Hz", "y": "S"},
        {"gid": "run-1", "file": "runs.csv", "x": "t_s", "y": "T_K", "yerr": "T_err", "y_scale": 1e-4},
        # a fit, model or guide line computed in the script
        {"label": r"Fit", "computed": True},
    ],
    target={"width_in": 3.4},   # the width from section 2
    pdf="figure.pdf",
    script=__file__,
)
```

- Paths in `file` are relative to the script. `x_scale` and `y_scale` are the factors between the file and the axis (the same factor must appear in the axis label). Add `"ax": 1` when the same label occurs in two panels.
- `"allow_subset": True` acknowledges that only some rows are plotted, and `"allow_clipped": True` that points lie outside the axis limits on purpose. Use them only when the user asked for that selection, and say so in the caption.
- Bars: give the category column as `x`; the checker compares it with the tick labels. Images: `{"gid": "map", "file": "field.npy"}`.
- The report is printed and written next to the PDF as `figure.check.json`.

What the levels mean:

- `fail`: the figure is wrong or unreadable (values differ from the file, a declared series is missing, points are hidden by the limits or a log axis, text under 6 pt, a rainbow colormap, fonts not embedded). Fix the script and run again. Never hand over or send to review a figure with a `fail`, and never make a `fail` go away by editing the declaration instead of the plot.
- `warn`: look at it (legend or label on data, overlapping text, axes title, floating offset text, width off target, series that differ only by colour, a font that is not Computer Modern, undeclared series, data typed into the script). Fix it unless there is a reason, and give the reason to the reviewer.

### 9.2 Review

1. Save the PDF and a 300 dpi PNG preview.
2. Get a review:
   - **If a `figure-reviewer` subagent is available** (Claude Code; it is named `braindance:figure-reviewer` when installed as a plugin), hand off to it with the script path, the figure paths, the path of the `.check.json` report and the round number.
   - **Otherwise**, review it yourself: open the PNG, look at it as a whole and then region by region, and go through the checklist in section 8 plus: nothing overlaps or is clipped, fonts readable at final size, labels match the data, and the chart type suits the data (`chart-choice.md`).
3. If the verdict is REVISE, apply every Blocking and Major fix by going back through this skill (sections 0–7), re-render, run the measured checks again, and review again with the next round number.
4. Stop at PASS, or after **3 rounds**. If it still fails after round 3, hand over the best version and tell the user which issues remain and why.
5. Tell the user briefly what the checks and the review changed (for example "moved the legend off the data, made units upright").

A full working example is in `${CLAUDE_SKILL_DIR}/example.py`: it reads `example_data/`, declares every series and runs the checks.
