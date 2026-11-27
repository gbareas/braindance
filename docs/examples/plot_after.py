"""The "after" figures: the same data, drawn with braindance.

Widths come from paper/figures.yaml (made by `figproject.py init paper/main.tex`), the house
style from the skill, and every figure goes through the measured checks, which compare the
plotted values with the files in paper/braindance_figures/source_data/.

Usage:  python plot_after.py  (reads data/, writes paper/braindance_figures/)
"""
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, NullFormatter, NullLocator

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
sys.path.insert(0, str(HERE.parents[1] / "skills" / "latex-scientific-plots"))
import figproject  # noqa: E402

P = figproject.Project(HERE / "paper")

# One encoding for the whole paper: heating ratio q by colour and marker, Re by line style.
Q_STYLE = {0.5: ("#56B4E9", "o"), 1.0: ("#E69F00", "s"), 2.0: ("#CC79A7", "^")}
RE_LINE = {1000: "-", 2000: "--", 5000: ":"}
SCHEMES = {"upwind": ("#0072B2", "o"), "central": ("#D55E00", "s"), "compact": ("#009E73", "D")}


def read_csv(name):
    with open(DATA / f"{name}.csv", newline="") as fh:
        return list(csv.DictReader(fh))


def panel_label(ax, text):
    """Panel heading above the top-left corner, outside the data."""
    return ax.annotate(text, xy=(0, 1), xycoords="axes fraction", xytext=(0, 3), textcoords="offset points",
                       ha="left", va="bottom", fontsize=9)


def text_colour_on(rgba):
    r, g, b = rgba[:3]
    return "white" if 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.45 else "black"


def overview():
    name = "overview"
    width = P.width(name)
    design = read_csv("design")
    prof = read_csv("profiles")
    y = np.array([float(r["y"]) for r in prof])
    fig = plt.figure(figsize=(width, 4.1))
    top, bottom, key = fig.subfigures(3, 1, height_ratios=[1.0, 1.55, 0.13])
    sources = []

    # (a) fields, one colour scale, true aspect ratio of the 6h x 2h domain
    axes = top.subplots(1, 2, sharey=True)
    for ax, tag in zip(axes, ("v1", "v2")):
        field = np.load(DATA / f"field_{tag}.npy")
        im = ax.imshow(field, origin="lower", cmap="inferno", vmin=0, vmax=1, extent=(0, 6, 0, 2),
                       interpolation="nearest", gid=f"field-{tag}", rasterized=True)
        P.write_npy(f"{name}_field_{tag}", field)
        sources.append({"gid": f"field-{tag}", "file": f"{name}_field_{tag}.npy"})
        row = next(r for r in design if r["case"] == tag)
        ax.text(0.02, 0.96, rf"{tag}: $Re={float(row['Re']):.0f}$, $q={float(row['q']):g}$",
                transform=ax.transAxes, ha="left", va="top", fontsize=8, color="white")
        ax.set_xlabel(r"$x/h$")
        ax.set_xticks([0, 2, 4, 6])
        ax.set_yticks([0, 1, 2])
    axes[0].set_ylabel(r"$y/h$")
    panel_label(axes[0], "(a)")
    cb = top.colorbar(im, ax=axes, pad=0.02, aspect=10)
    cb.set_label(r"$T/T_\mathrm{max}$")
    cb.ax.minorticks_off()

    # (b) design and (c) profiles share the encoding
    ax_b, ax_c = bottom.subplots(1, 2, width_ratios=[1.0, 2.3])
    training = [r for r in design if r["role"] == "training"]
    for q, (colour, marker) in Q_STYLE.items():
        sel = [r for r in training if float(r["q"]) == q]
        ax_b.plot([float(r["Re"]) for r in sel], [q] * len(sel), ls="none", marker=marker, color=colour, ms=5,
                  mec="black", mew=0.4, gid=f"design-q{q}")
        P.write_csv(f"{name}_design_q{q}", Re=[float(r["Re"]) for r in sel], q=[q] * len(sel))
        sources.append({"gid": f"design-q{q}", "file": f"{name}_design_q{q}.csv", "x": "Re", "y": "q"})
    val = [r for r in design if r["role"] == "validation"]
    ax_b.plot([float(r["Re"]) for r in val], [float(r["q"]) for r in val], ls="none", marker="*", ms=8,
              color="black", gid="design-val")
    P.write_csv(f"{name}_design_val", Re=[float(r["Re"]) for r in val], q=[float(r["q"]) for r in val])
    sources.append({"gid": "design-val", "file": f"{name}_design_val.csv", "x": "Re", "y": "q"})
    for r in design:
        ax_b.annotate(rf"$\mathrm{{{r['case']}}}$", (float(r["Re"]), float(r["q"])), xytext=(4, 3),
                      textcoords="offset points", fontsize=7)
    ax_b.set(xscale="log", yscale="log", xlim=(700, 8000), ylim=(0.38, 2.8), xlabel=r"$Re$", ylabel=r"$q$")
    ax_b.xaxis.set_major_locator(FixedLocator([1000, 2000, 5000]))
    ax_b.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:.0f}$"))
    ax_b.xaxis.set_minor_formatter(NullFormatter())
    ax_b.yaxis.set_major_locator(FixedLocator(list(Q_STYLE)))
    ax_b.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:g}$"))
    ax_b.yaxis.set_minor_locator(NullLocator())
    panel_label(ax_b, "(b)")

    cases = {r["case"]: (float(r["Re"]), float(r["q"])) for r in design}
    for case, (re, q) in cases.items():
        values = np.array([float(r[case]) for r in prof])
        if case.startswith("c"):
            colour, marker = Q_STYLE[q]
            offset = {1000: 0, 2000: 7, 5000: 14}[int(re)]   # stagger the markers of the three Re
            ax_c.plot(y, values, color=colour, ls=RE_LINE[int(re)], lw=1.0, marker=marker, ms=3.2,
                      markevery=(offset, 21), mec="black", mew=0.3, gid=f"profile-{case}")
        else:
            ax_c.plot(y, values, color="black", lw=1.6, gid=f"profile-{case}")
            peak = int(np.argmax(values))
            ax_c.annotate(rf"$\mathrm{{{case}}}$", (y[peak], values[peak]), xytext=(4, 2),
                          textcoords="offset points", fontsize=8)
        P.write_csv(f"{name}_profile_{case}", y=y, T=values)
        sources.append({"gid": f"profile-{case}", "file": f"{name}_profile_{case}.csv", "x": "y", "y": "T"})
    low = min(float(r[c]) for r in prof for c in cases)
    ax_c.set(xlim=(0, 2), ylim=(np.floor(20 * low) / 20, 1.08), xlabel=r"$y/h$", ylabel=r"$\overline{T}/\overline{T}_\mathrm{max}$")
    panel_label(ax_c, "(c)")

    handles = ([Line2D([], [], color=c, marker=m, mec="black", mew=0.4, label=rf"$q={q:g}$")
                for q, (c, m) in Q_STYLE.items()]
               + [Line2D([], [], color="0.3", ls=ls, label=rf"$Re={re}$") for re, ls in RE_LINE.items()]
               + [Line2D([], [], color="black", lw=1.6, marker="*", ms=7, label="validation")])
    key.legend(handles=handles, loc="center", ncol=7, frameon=False, columnspacing=1.0,
                  handlelength=1.8, handletextpad=0.4)
    P.finish(fig, name, sources, script=__file__)


def convergence():
    name = "convergence"
    width = P.width(name)
    rows = read_csv("convergence")
    fig, ax = plt.subplots(figsize=(width, 2.9))
    sources = []
    for scheme, (colour, marker) in SCHEMES.items():
        sel = [r for r in rows if r["scheme"] == scheme]
        n = np.array(sorted({int(r["N"]) for r in sel}))
        err = np.array([[float(r["error"]) for r in sel if int(r["N"]) == k] for k in n])
        mean, lo, hi = err.mean(1), err.min(1), err.max(1)
        ax.errorbar(n, mean, yerr=[mean - lo, hi - mean], color=colour, marker=marker, ms=4, lw=1.0, capsize=2,
                    label=scheme, gid=f"conv-{scheme}")
        P.write_csv(f"{name}_{scheme}", N=n, mean=mean, min=lo, max=hi)
        sources.append({"label": scheme, "file": f"{name}_{scheme}.csv", "x": "N", "y": "mean"})
    for order, c, n_end, where in ((1, 0.45, 512, "above"), (2, 0.6, 512, "above"), (4, 4.0, 128, "below")):
        n = np.array([16, n_end])
        ax.plot(n, c * n ** -float(order), color="0.45", lw=0.8, ls=(0, (4, 3)), gid=f"slope-{order}")
        sources.append({"gid": f"slope-{order}", "computed": True})
        ax.annotate(rf"$N^{{-{order}}}$", (n_end, c * n_end ** -float(order)), xytext=(4, 0),
                    textcoords="offset points", fontsize=8, color="0.3", va="center")
    ax.set(xscale="log", yscale="log", xlim=(12, 900), ylim=(1e-10, 1),
           xlabel=r"Grid points $N$", ylabel=r"$L_2$ error")
    ax.xaxis.set_major_locator(FixedLocator([16, 32, 64, 128, 256, 512]))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:.0f}$"))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.xaxis.set_minor_locator(NullLocator())
    ax.legend(loc="lower left", title="mean and range over 5 runs", title_fontsize=8)
    P.finish(fig, name, sources, script=__file__)


def results_table():
    name = "results_table"
    width = P.width(name)
    rows = read_csv("results")
    base = np.array([float(r["baseline_pct"]) for r in rows])
    new = np.array([float(r["proposed_pct"]) for r in rows])
    runtime = np.array([float(r["runtime_s"]) for r in rows])
    delta = (base - new)[:, None]
    n = len(rows)
    P.write_csv(f"{name}_rows", case=[r["case"] for r in rows], baseline_pct=base, proposed_pct=new,
                delta_pp=delta[:, 0], runtime_s=runtime)
    P.write_npy(f"{name}_delta", delta)
    vmax = np.abs(delta).max()
    norm, cmap = Normalize(-vmax, vmax), plt.get_cmap("RdBu")

    fig, ax = plt.subplots(figsize=(width, 2.9))
    ax.pcolormesh([2.5, 3.5], np.arange(n + 1) - 0.5, delta, cmap=cmap, norm=norm, edgecolors="white",
                  linewidth=0.6, gid="delta")
    headers = ["case", "baseline\n(\\%)", "proposed\n(\\%)", r"$\Delta$" "\n(pp)", "run time\n(s)"]
    for j, text in enumerate(headers):
        ax.text(j, -1.3, text, ha="center", va="center", fontsize=8, linespacing=1.1)
    for i, r in enumerate(rows):
        case = r["case"]
        ax.text(0, i, rf"$c_{{{case[1:]}}}$", ha="center", va="center", fontsize=8)
        ax.text(1, i, rf"${base[i]:.2f}$", ha="center", va="center", fontsize=8)
        ax.text(2, i, rf"${new[i]:.2f}$", ha="center", va="center", fontsize=8)
        ax.text(3, i, rf"${delta[i, 0]:+.2f}$", ha="center", va="center", fontsize=8,
                color=text_colour_on(cmap(norm(delta[i, 0]))))
        ax.text(4, i, rf"${runtime[i]:.1f}$", ha="center", va="center", fontsize=8)
    ax.axhline(-0.5, color="black", lw=0.5)
    ax.axhline(-2.1, color="black", lw=0.8)
    ax.axhline(n - 0.5, color="black", lw=0.8)
    ax.set(xlim=(-0.5, 4.5), ylim=(n - 0.5, -2.15), xticks=[], yticks=[])
    for side in ax.spines.values():
        side.set_visible(False)
    P.finish(fig, name, [{"gid": "delta", "file": f"{name}_delta.npy"}], script=__file__)


def sweep():
    name = "sweep"
    width = P.width(name)
    info = read_csv("sweep_axes")
    lr = [float(r["learning_rate"]) for r in info]
    widths = [int(r["width"]) for r in info]
    grids = {tag: np.load(DATA / f"sweep_model_{tag}.npy") for tag in ("a", "b")}
    vmax = max(np.abs(g).max() for g in grids.values())
    norm, cmap = Normalize(-vmax, vmax), plt.get_cmap("RdBu")

    def lr_label(v):
        mant, exp = f"{v:.0e}".split("e")
        return rf"${mant}\times10^{{{int(exp)}}}$" if mant != "1" else rf"$10^{{{int(exp)}}}$"

    fig, axes = plt.subplots(1, 2, figsize=(width, 2.75), sharey=True)
    sources = []
    edges = np.arange(5) - 0.5
    for ax, (tag, grid) in zip(axes, grids.items()):
        mesh = ax.pcolormesh(edges, edges, grid, cmap=cmap, norm=norm, edgecolors="white", linewidth=1.2,
                             gid=f"gain-{tag}")
        P.write_npy(f"{name}_{tag}", grid)
        sources.append({"gid": f"gain-{tag}", "file": f"{name}_{tag}.npy"})
        for i in range(4):
            for j in range(4):
                ax.text(j, i, rf"${grid[i, j]:+.1f}$", ha="center", va="center", fontsize=8,
                        color=text_colour_on(cmap(norm(grid[i, j]))))
        ax.set_xticks(range(4), [lr_label(v) for v in lr])
        ax.set_yticks(range(4), [rf"${w}$" for w in widths])
        ax.tick_params(which="both", length=0)
        ax.minorticks_off()
        ax.set_aspect("equal")
        ax.set_xlabel("Learning rate")
        for side in ax.spines.values():
            side.set_visible(False)
        panel_label(ax, f"({tag}) model {tag.upper()}")
    axes[0].set_ylabel("Network width")
    cb = fig.colorbar(mesh, ax=axes, shrink=0.9, pad=0.02, aspect=20)
    cb.set_label("Gain over baseline (pp)")
    cb.ax.minorticks_off()
    P.finish(fig, name, sources, script=__file__)


if __name__ == "__main__":
    P.setup(personal=False)  # the README shows the house style, whoever rebuilds it
    overview()
    convergence()
    results_table()
    sweep()
