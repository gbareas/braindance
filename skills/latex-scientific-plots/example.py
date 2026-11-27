"""Example: two-panel, single-column figure with all text rendered in LaTeX,
read from files and checked against them.

Run:  python example.py [output_folder]
Out:  example_figure.pdf (vector), example_figure.png (preview) and
      example_figure.check.json (data and style checks)
"""
from pathlib import Path
import sys

import numpy as np
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_figure import check_figure, load_table  # noqa: E402
from style_profile import setup  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
STYLE = setup()  # the house style plus your personal profile; prints which, and whether LaTeX is used

WIDTH = 3.4  # inches: one journal column


def figsize(width_in=WIDTH, ratio=0.618, nrows=1, ncols=1):
    return (width_in, width_in * ratio * nrows / ncols)


def column(table, name):
    return np.array(table[name], dtype=float)


# Data is read from files, never typed into the script.
damping = load_table(HERE / "example_data" / "damping.csv")
spectrum = load_table(HERE / "example_data" / "spectrum.csv")

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize(nrows=2))
sources = []  # one entry per plotted series, for check_figure

# Panel (a): damped oscillations, model curves and measurements
t = np.linspace(0, 10, 400)
t_meas = column(damping, "t_s")
styles = ["-", "--", ":"]
markers = ["o", "s", "^"]
for i, gamma in enumerate([0.1, 0.3, 0.6]):
    label = rf"${gamma}$"
    line, = ax1.plot(t, np.exp(-gamma * t) * np.cos(np.pi * t), styles[i], label=label)
    sources.append({"label": label, "ax": 0, "computed": True})
    ax1.errorbar(t_meas, column(damping, f"x_g{gamma}"), yerr=column(damping, "x_err"),
                 fmt=markers[i], color=line.get_color(), mfc="white", mew=0.8, elinewidth=0.6,
                 gid=f"measured-{gamma}")
    sources.append({"gid": f"measured-{gamma}", "file": "example_data/damping.csv",
                    "x": "t_s", "y": f"x_g{gamma}", "yerr": "x_err"})

ax1.set_xlabel(r"Time $t$ (s)")
ax1.set_ylabel(r"Amplitude $x(t)/x_0$")
ax1.set_xlim(0, 10)
ax1.set_ylim(-1.05, 1.9)  # headroom so the legend covers no data
ax1.legend(title=r"Damping $\gamma$ ($\mathrm{s}^{-1}$)", loc="upper right", ncol=3,
           columnspacing=1.0, handlelength=1.8, title_fontsize=8)
ax1.text(0.02, 0.95, r"(a)", transform=ax1.transAxes, va="top")

# Panel (b): power law on log-log axes
f = column(spectrum, "f_Hz")
ax2.loglog(f, column(spectrum, "S_V2_per_Hz"), "o", mfc="white", mew=0.8, label=r"Data")
ax2.loglog(f, 2e-3 * f ** -1.5, "-", color="k", lw=0.9, label=r"$S \propto f^{-3/2}$")
sources.append({"label": r"Data", "file": "example_data/spectrum.csv", "x": "f_Hz", "y": "S_V2_per_Hz"})
sources.append({"label": r"$S \propto f^{-3/2}$", "computed": True})
ax2.set_xlabel(r"Frequency $f$ (Hz)")
ax2.set_ylabel(r"$S(f)$ ($\mathrm{V}^2\,\mathrm{Hz}^{-1}$)")
ax2.legend(loc="lower left")
ax2.text(0.96, 0.95, r"(b)", transform=ax2.transAxes, va="top", ha="right")

pdf = OUT / "example_figure.pdf"
fig.savefig(pdf)
fig.savefig(OUT / "example_figure.png", dpi=300)
print(f"Saved {pdf} and its PNG preview ({'LaTeX' if STYLE.usetex else 'mathtext fallback'} mode)")

report = check_figure(fig, sources, target={"width_in": WIDTH}, pdf=pdf, script=__file__)
sys.exit(0 if report["ok"] else 1)
