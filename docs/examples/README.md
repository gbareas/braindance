# Before-and-after examples

The images in `images/` (shown in the main README) come from this folder. Everything here is synthetic:
`make_data.py` invents a small parameter study of a heated channel, a grid-convergence study, a results table
and a hyperparameter sweep. No figure shows real results.

- `plot_before.py` draws each figure the way many first drafts are made: matplotlib defaults, a large canvas,
  a rainbow colormap, titles on the axes, a legend over the data, plain-text labels, one colour scale per panel.
- `paper/main.tex` is a one-page article that includes those figures at `\linewidth`, so LaTeX shrinks them.
- `plot_after.py` draws the same data with braindance: the width of each figure comes from `paper/figures.yaml`
  (measured from `main.tex` by `figproject.py init`), and every figure passes the measured checks, which compare
  the plotted values with the data.
- `figproject.py compare paper --png images` stacks each old figure above its new version, both at the width
  the manuscript prints them, so text sizes compare as a reader sees them.

Rebuild everything with

```bash
python build.py
```

It needs numpy, matplotlib, PyYAML, pdflatex and poppler-utils, and writes `data/`, `paper/figures/`,
`paper/braindance_figures/` (with `before_after.pdf` and `preview.pdf`), `paper/figures.yaml`,
`paper/FIGURES.md` and `images/`. Only `images/` is kept in git.
