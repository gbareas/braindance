"""Synthetic data for the before-and-after examples. Nothing here comes from a real study.

A made-up parameter study of a heated channel: nine training cases on a 3 x 3 grid of
Reynolds number Re and heating ratio q, two validation cases off the grid, plus a
convergence study, a per-case results table and a hyperparameter sweep. Seeded, so the
files are the same on every run.

Usage:  python make_data.py  (writes data/)
"""
import csv
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RNG = np.random.default_rng(20261117)

RE = [1000, 2000, 5000]
Q = [0.5, 1.0, 2.0]
VALIDATION = [(1500, 0.75), (3500, 1.5)]


def write_csv(name, **cols):
    DATA.mkdir(exist_ok=True)
    with open(DATA / f"{name}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for row in zip(*cols.values()):
            w.writerow([f"{v:.6g}" if isinstance(v, float) else v for v in row])


def smooth_noise(ny, nx, ly, lx):
    """Random field with correlation lengths ly, lx (in grid points), zero mean, unit RMS."""
    ky = np.fft.fftfreq(ny)[:, None]
    kx = np.fft.fftfreq(nx)[None, :]
    spectrum = np.exp(-(ky * ly) ** 2 - (kx * lx) ** 2)
    field = np.real(np.fft.ifft2(np.fft.fft2(RNG.standard_normal((ny, nx))) * spectrum))
    return (field - field.mean()) / field.std()


def peak_location(re, q):
    """Where the temperature peak sits across the channel, y/h in (0, 2)."""
    return 2.0 / (1.0 + np.exp(-2.2 * (np.log(re / 2000) + 1.6 * np.log(q))))


def profile(y, re, q):
    y0 = peak_location(re, q)
    width = 0.08 + 0.12 / q
    height = 1.0 - 0.25 * np.log10(re / 1000)
    return 0.35 + 0.3 * y / 2 + height * np.exp(-0.5 * ((y - y0) / width) ** 2)


def overview():
    # (a) temperature snapshots of two validation cases
    ny, nx = 96, 288
    y = np.linspace(0, 2, ny)
    for tag, (re, q) in zip(("v1", "v2"), VALIDATION):
        mean = profile(y, re, q)[:, None]
        field = mean * (1 + 0.18 * smooth_noise(ny, nx, 6, 18)) + 0.04 * smooth_noise(ny, nx, 2, 4)
        np.save(DATA / f"field_{tag}.npy", np.clip(field, 0, None) / field.max())
    # (b) the design: training grid and validation cases
    cases = [(re, q) for re in RE for q in Q]
    write_csv("design", case=[f"c{i + 1}" for i in range(9)] + ["v1", "v2"],
              Re=[float(c[0]) for c in cases + VALIDATION], q=[float(c[1]) for c in cases + VALIDATION],
              role=["training"] * 9 + ["validation"] * 2)
    # (c) mean profiles of every case
    y = np.linspace(0, 2, 201)
    cols = {"y": y}
    for i, (re, q) in enumerate(cases + VALIDATION):
        name = f"c{i + 1}" if i < 9 else f"v{i - 8}"
        cols[name] = profile(y, re, q) / profile(y, re, q).max()
    write_csv("profiles", **cols)


def convergence():
    n = np.array([16, 32, 64, 128, 256, 512])
    schemes = {"upwind": (1, 0.9), "central": (2, 2.5), "compact": (4, 40.0)}
    rows = {"N": [], "scheme": [], "seed": [], "error": []}
    for scheme, (order, c) in schemes.items():
        for seed in range(5):
            jitter = np.exp(0.12 * RNG.standard_normal(n.size) * (1 + 0.6 * (n == n.min())))
            err = np.maximum(c * (1.0 / n) ** order * jitter, 3e-10 * np.exp(0.3 * RNG.standard_normal(n.size)))
            for N, e in zip(n, err):
                rows["N"].append(int(N)), rows["scheme"].append(scheme), rows["seed"].append(seed)
                rows["error"].append(float(e))
    write_csv("convergence", **rows)


def results_table():
    cases = [f"c{i + 1}" for i in range(9)]
    base = 30 + 12 * RNG.random(9)
    new = base + RNG.normal(-1.0, 2.6, 9)
    write_csv("results", case=cases, baseline_pct=[float(round(v, 2)) for v in base],
              proposed_pct=[float(round(v, 2)) for v in new],
              runtime_s=[float(round(v, 1)) for v in 40 + 25 * RNG.random(9)])


def sweep():
    lr = [1e-4, 3e-4, 1e-3, 3e-3]
    width = [32, 64, 128, 256]
    li, wi = np.meshgrid(np.arange(4), np.arange(4))
    gain_a = 7.5 - 1.6 * (li - 1.2) ** 2 + 0.8 * wi + RNG.normal(0, 0.6, (4, 4))
    gain_b = 4.0 - 3.0 * (li - 2.1) ** 2 + 2.0 * wi - 6.0 * (wi == 0) + RNG.normal(0, 0.9, (4, 4))
    np.save(DATA / "sweep_model_a.npy", np.round(gain_a, 1))   # rows: width, columns: learning rate
    np.save(DATA / "sweep_model_b.npy", np.round(gain_b, 1))
    write_csv("sweep_axes", index=list(range(4)), learning_rate=lr, width=width)


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    overview()
    convergence()
    results_table()
    sweep()
    print(f"wrote {DATA}")
