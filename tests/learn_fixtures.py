"""Past work in a known style, for testing that learn_style recovers it."""
import numpy as np

STYLE = {
    "palette": ["#1b4f72", "#c0392b", "#7d9c3a", "#8e44ad", "#d68910"],
    "rc": {"xtick.direction": "out", "ytick.direction": "out", "xtick.top": False, "ytick.right": False,
           "axes.spines.top": False, "axes.spines.right": False, "xtick.minor.visible": False,
           "ytick.minor.visible": False, "lines.linewidth": 1.8, "axes.linewidth": 1.0,
           "xtick.major.size": 5.0, "ytick.major.size": 5.0, "xtick.major.width": 1.0, "ytick.major.width": 1.0},
    "cmap": "magma",
}


def make_figures(folder, style=STYLE, grid=False):
    """Six figure PDFs drawn with `style`; returns their paths."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from cycler import cycler
    rng = np.random.default_rng(1)
    rc = {**style["rc"], "axes.prop_cycle": cycler(color=style["palette"]), "image.cmap": style["cmap"],
          "pdf.fonttype": 42, "axes.grid": grid, "text.usetex": False}
    out = []
    x = np.linspace(0, 10, 60)
    with plt.rc_context(rc):
        fig, ax = plt.subplots(figsize=(3.4, 2.2))
        for k in range(3):
            ax.plot(x, np.sin(x + k), label=f"run {k}")
        ax.legend()
        out.append(fig)

        fig, axes = plt.subplots(1, 2, figsize=(6.8, 2.4))
        for ax in axes:
            for k in range(4):
                ax.errorbar(x[::6], np.cos(x[::6] / 2 + k) + k, yerr=0.1, marker="os^D"[k], capsize=2)
        out.append(fig)

        fig, ax = plt.subplots(figsize=(3.4, 2.4))
        for k in range(5):
            ax.scatter(rng.normal(k, 0.4, 40), rng.normal(0, 1, 40), s=8)
        out.append(fig)

        fig, ax = plt.subplots(figsize=(3.4, 2.6))
        im = ax.imshow(rng.random((20, 30)).cumsum(axis=1), aspect="auto")
        fig.colorbar(im)
        out.append(fig)

        fig, ax = plt.subplots(figsize=(3.4, 2.2))
        for k in range(3):
            ax.bar(np.arange(4) + 0.25 * k, rng.random(4) + 0.5, width=0.25)
        out.append(fig)

        fig, ax = plt.subplots(figsize=(3.4, 2.4))
        f = np.logspace(0, 3, 40)
        ax.loglog(f, f ** -1.5)
        ax.loglog(f, 2 * f ** -1.2)
        out.append(fig)

    paths = []
    for i, fig in enumerate(out):
        p = folder / f"past_{i}.pdf"
        fig.savefig(p)
        plt.close(fig)
        paths.append(p)
    return paths
