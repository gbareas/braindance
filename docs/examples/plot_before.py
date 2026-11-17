"""The "before" figures: drawn the way many first drafts are, with matplotlib defaults.

Each figure is drawn on a large canvas and later shrunk by \\includegraphics[width=\\linewidth],
which is where most of the problems come from: text ends up at 3-5 pt. On top of that, the
usual habits: sans-serif fonts, a rainbow colormap, a title on the axes, a legend box over
the data, plain-text labels, one colour scale per panel. Nothing here uses braindance.

Usage:  python plot_before.py  (reads data/, writes paper/figures/)
"""
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "paper" / "figures"


def read_csv(name):
    with open(DATA / f"{name}.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return rows


def overview():
    design = read_csv("design")
    prof = read_csv("profiles")
    y = np.array([float(r["y"]) for r in prof])
    fig = plt.figure(figsize=(15, 4.6))
    gs = fig.add_gridspec(1, 4, width_ratios=[1.6, 1.6, 1.2, 2.2], wspace=0.35)
    for k, tag in enumerate(("v1", "v2")):
        ax = fig.add_subplot(gs[k])
        im = ax.imshow(np.load(DATA / f"field_{tag}.npy"), origin="lower", cmap="jet", aspect="auto",
                       extent=(0, 6, 0, 2))
        ax.set_title(f"case {tag}")
        ax.set_xlabel("x/h")
        ax.set_ylabel("y/h")
        fig.colorbar(im, ax=ax)
    ax = fig.add_subplot(gs[2])
    colours = {"0.5": "red", "1.0": "green", "2.0": "blue"}
    for r in design:
        if r["role"] == "training":
            ax.scatter(float(r["Re"]), float(r["q"]), s=120, c=colours[str(float(r["q"]))])
        else:
            ax.scatter(float(r["Re"]), float(r["q"]), s=200, marker="*", c="purple")
    ax.set_xlabel("Re")
    ax.set_ylabel("q")
    ax.set_title("Parameter space")
    ax.grid(True)
    ax = fig.add_subplot(gs[3])
    for i in range(9):
        ax.plot(y, [float(r[f"c{i + 1}"]) for r in prof], label=f"case {i + 1}")
    for tag in ("v1", "v2"):
        ax.plot(y, [float(r[tag]) for r in prof], "k--", label=f"validation {tag}")
    ax.set_xlabel("y/h")
    ax.set_ylabel("T_mean/T_max")
    ax.set_title("Mean temperature profiles")
    ax.legend(loc="center right")
    ax.grid(True)
    fig.savefig(OUT / "overview.pdf", bbox_inches="tight")


def convergence():
    rows = read_csv("convergence")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for scheme in ("upwind", "central", "compact"):
        sel = [r for r in rows if r["scheme"] == scheme]
        n = sorted({int(r["N"]) for r in sel})
        err = np.array([[float(r["error"]) for r in sel if int(r["N"]) == k] for k in n])
        ax.errorbar(n, err.mean(1), yerr=err.std(1), marker="o", capsize=4, label=scheme)
    n = np.array([16, 512])
    ax.plot(n, 0.9 / n, "k:", label="1st order")
    ax.plot(n, 2.5 / n ** 2, "k--", label="2nd order")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("N (grid points)")
    ax.set_ylabel("L2 error")
    ax.set_title("Grid convergence")
    ax.legend()
    ax.grid(True, which="both")
    fig.savefig(OUT / "convergence.pdf", bbox_inches="tight")


def results_table():
    rows = read_csv("results")
    delta = np.array([float(r["baseline_pct"]) - float(r["proposed_pct"]) for r in rows])
    cells = [[r["case"], f"{float(r['baseline_pct']):.2f}%", f"{float(r['proposed_pct']):.2f}%",
              f"{d:+.2f}", f"{float(r['runtime_s']):.1f} s"] for r, d in zip(rows, delta)]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.axis("off")
    table = ax.table(cellText=cells, colLabels=["case", "baseline error", "proposed error", "gain (pp)", "runtime"],
                     loc="center", cellLoc="center")
    cmap = plt.get_cmap("jet")
    for i, d in enumerate(delta):
        table[i + 1, 3].set_facecolor(cmap((d - delta.min()) / (delta.max() - delta.min())))
    table.scale(1, 1.6)
    ax.set_title("Results per case")
    fig.savefig(OUT / "results_table.pdf", bbox_inches="tight")


def sweep():
    axes_info = read_csv("sweep_axes")
    lr = [r["learning_rate"] for r in axes_info]
    width = [r["width"] for r in axes_info]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    for ax, tag in zip(axes, ("a", "b")):
        gain = np.load(DATA / f"sweep_model_{tag}.npy")
        im = ax.imshow(gain, origin="lower", cmap="jet")
        for i in range(4):
            for j in range(4):
                ax.text(j, i, f"{gain[i, j]:.1f}", ha="center", va="center")
        ax.set_xticks(range(4), lr)
        ax.set_yticks(range(4), width)
        ax.set_xlabel(f"learning rate (model {tag.upper()})")
        ax.set_ylabel("width")
        fig.colorbar(im, ax=ax, label="gain")
    fig.savefig(OUT / "sweep.pdf", bbox_inches="tight")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcdefaults()
    overview()
    convergence()
    results_table()
    sweep()
    print(f"wrote {OUT}")
