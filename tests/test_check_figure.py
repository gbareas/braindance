"""Tests for check_figure: each one breaks a figure in one way and expects that check to fire.

Run with `python tests/test_check_figure.py` (no dependencies beyond numpy and matplotlib) or with pytest.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "latex-scientific-plots"))
from check_figure import Report, check_figure, check_pdf, check_script  # noqa: E402

plt.rcParams.update({"text.usetex": False, "mathtext.fontset": "cm", "font.family": "serif",
                     "font.serif": ["cmr10"], "axes.formatter.use_mathtext": True, "font.size": 9,
                     "figure.figsize": (3.4, 2.1), "figure.constrained_layout.use": True,
                     "pdf.fonttype": 42})

TMP = Path(tempfile.mkdtemp(prefix="check_figure_"))
T = np.linspace(0.0, 10.0, 21)
A = np.exp(-0.2 * T)
B = np.exp(-0.5 * T)
ERR = np.full(T.size, 0.03)
np.savetxt(TMP / "runs.csv", np.column_stack([T, A, B, ERR]), delimiter=",",
           header="t_s,a,b,err", comments="")
SRC_A = {"label": "A", "file": "runs.csv", "x": "t_s", "y": "a"}
SRC_B = {"label": "B", "file": "runs.csv", "x": "t_s", "y": "b"}


def run(fig, sources, **kw):
    kw.setdefault("target", {"width_in": 3.4})
    out = check_figure(fig, sources, base_dir=TMP, quiet=True, **kw)
    plt.close(fig)
    return out


def found(out, check, level=None):
    return [f for f in out["findings"] if f["check"] == check and (level is None or f["level"] == level)]


def base_fig(ya=A, yb=B, la="A", lb="B"):
    fig, ax = plt.subplots()
    ax.plot(T, ya, "-o", label=la)
    ax.plot(T, yb, "--s", label=lb)
    ax.set_xlabel(r"Time $t$ (s)")
    ax.set_ylabel(r"Amplitude $x$")
    ax.set_ylim(-0.05, 1.6)
    ax.legend(loc="upper right", ncol=2)
    return fig, ax


# ---- data ----

def test_clean_figure_passes():
    fig, _ = base_fig()
    out = run(fig, [SRC_A, SRC_B])
    assert out["ok"], out["findings"]
    assert len(found(out, "values", "info")) == 2
    assert not [f for f in out["findings"] if f["level"] == "warn"], out["findings"]


def test_scale_factor_is_named():
    fig, ax = base_fig(ya=A * 1e3)
    ax.set_ylim(-50, 1600)
    out = run(fig, [SRC_A, SRC_B])
    msg = found(out, "values", "fail")[0]["message"]
    assert not out["ok"] and "1000 x source" in msg
    fig, ax = base_fig(ya=A * 1e3)
    ax.set_ylim(-50, 1600)
    assert run(fig, [dict(SRC_A, y_scale=1e3), SRC_B])["ok"]


def test_swapped_labels_are_named():
    fig, _ = base_fig(la="B", lb="A")
    out = run(fig, [SRC_A, SRC_B])
    assert not out["ok"]
    assert any("swapped" in f["message"] for f in found(out, "values", "fail"))


def test_single_wrong_value():
    y = A.copy()
    y[7] += 0.01
    fig, _ = base_fig(ya=y)
    msg = found(run(fig, [SRC_A, SRC_B]), "values", "fail")[0]["message"]
    assert "1 of 21 values differ" in msg and "index 7" in msg


def test_dropped_points_fail_unless_declared():
    keep = A > 0.3
    fig, ax = plt.subplots()
    ax.plot(T[keep], A[keep], "o", label="A")
    out = run(fig, [SRC_A])
    assert "source has 21" in found(out, "values", "fail")[0]["message"]
    fig, ax = plt.subplots()
    ax.plot(T[keep], A[keep], "o", label="A")
    out = run(fig, [dict(SRC_A, allow_subset=True)])
    assert out["ok"] and found(out, "subset", "info")


def test_points_hidden_by_limits():
    fig, ax = base_fig()
    ax.set_xlim(0, 6)
    out = run(fig, [SRC_A, SRC_B])
    assert not out["ok"] and "8 of 21" in found(out, "hidden-by-limits", "fail")[0]["message"]


def test_nonpositive_on_log_axis():
    fig, ax = plt.subplots()
    ax.plot(T, A, "o", label="A")
    ax.set_xscale("log")  # T starts at 0
    assert found(run(fig, [SRC_A]), "log-axis", "fail")


def test_declared_series_missing_and_undeclared_series():
    fig, ax = plt.subplots()
    ax.plot(T, A, "o", label="A")
    ax.plot(T, 0.5 * A, "-", label="half")
    out = run(fig, [SRC_A, SRC_B])
    assert found(out, "series-missing", "fail") and found(out, "unverified", "warn")
    fig, ax = plt.subplots()
    ax.plot(T, A, "o", label="A")
    assert found(run(fig, []), "unverified", "fail")
    fig, ax = plt.subplots()
    ax.plot(T, A, "o", label="A")
    ax.plot(T, 0.5 * A, "-", label="half")
    assert run(fig, [SRC_A, {"label": "half", "computed": True}])["ok"]


def test_error_bars_checked_by_gid():
    fig, ax = plt.subplots()
    ax.errorbar(T, A, yerr=ERR, fmt="o", gid="run-a")
    src = {"gid": "run-a", "file": "runs.csv", "x": "t_s", "y": "a", "yerr": "err"}
    assert run(fig, [src])["ok"]
    fig, ax = plt.subplots()
    ax.errorbar(T, A, yerr=2 * ERR, fmt="o", gid="run-a")
    out = run(fig, [src])
    assert "2 x source" in found(out, "error-bars", "fail")[0]["message"]


def test_bars_and_category_order():
    (TMP / "scores.csv").write_text("method,score\nbaseline,0.61\nours,0.74\noracle,0.90\n")
    src = {"label": "Score", "file": "scores.csv", "x": "method", "y": "score"}
    fig, ax = plt.subplots()
    ax.bar(["baseline", "ours", "oracle"], [0.61, 0.74, 0.90], label="Score")
    assert run(fig, [src])["ok"]
    fig, ax = plt.subplots()
    ax.bar(["ours", "baseline", "oracle"], [0.61, 0.74, 0.90], label="Score")
    assert found(run(fig, [src]), "categories", "fail")
    fig, ax = plt.subplots()
    ax.bar(["baseline", "ours", "oracle"], [0.61, 0.47, 0.90], label="Score")
    assert found(run(fig, [src]), "values", "fail")


def test_image_values():
    z = np.arange(12.0).reshape(3, 4)
    np.save(TMP / "z.npy", z)
    src = {"gid": "map", "file": "z.npy"}
    fig, ax = plt.subplots()
    ax.imshow(z, gid="map")
    assert run(fig, [src])["ok"]
    fig, ax = plt.subplots()
    ax.imshow(z.T, gid="map")
    assert found(run(fig, [src]), "values", "fail")


# ---- style ----

def test_small_font_and_bad_colormap_fail():
    fig, ax = base_fig()
    ax.text(0.5, 0.5, "tiny", transform=ax.transAxes, fontsize=4)
    assert found(run(fig, [SRC_A, SRC_B]), "font-size", "fail")
    z = np.arange(12.0).reshape(3, 4)
    np.save(TMP / "z.npy", z)
    for cmap, bad in (("jet", True), ("gist_rainbow_r", True), ("viridis", False), ("RdBu_r", False)):
        fig, ax = plt.subplots()
        ax.imshow(z, cmap=cmap, gid="map")
        assert bool(found(run(fig, [{"gid": "map", "file": "z.npy"}]), "colormap", "fail")) is bad, cmap


def test_legend_on_data_title_offset_width_and_colour_only():
    fig, ax = plt.subplots(figsize=(5.0, 3.0))
    ax.plot(T, A * 1e6, "-", label="A")
    ax.plot(T, B * 1e6, "-", label="B")
    ax.set_title("Decay")
    ax.legend(loc="upper left")  # sits on the start of both curves
    out = run(fig, [dict(SRC_A, y_scale=1e6), dict(SRC_B, y_scale=1e6)])
    assert out["ok"]  # all of these are warnings, not failures
    for check in ("covers-data", "axes-title", "offset-text", "width", "colour-only"):
        assert found(out, check, "warn"), check


def test_overlapping_text():
    fig, ax = base_fig()
    ax.text(0.02, 0.5, "first label", transform=ax.transAxes)
    ax.text(0.04, 0.5, "second label", transform=ax.transAxes)
    assert found(run(fig, [SRC_A, SRC_B]), "text-overlap", "warn")


# ---- script and PDF ----

def test_typed_in_data_is_flagged():
    script = TMP / "plot.py"
    script.write_text("import numpy as np\ny = np.array([0.61, 0.74, 0.9, 0.5, 0.4, 0.3, 0.2, 0.1])\n"
                      "ticks = [0, 5, 10]\n")
    rep = Report()
    check_script(rep, script)
    assert [f for f in rep.findings if f["check"] == "typed-in-data" and "line 2" in f["message"]]


def test_pdf_fonts_and_width():
    if not shutil.which("pdffonts"):
        return
    fig, _ = base_fig()
    pdf = TMP / "fig.pdf"
    fig.savefig(pdf)
    out = run(fig, [SRC_A, SRC_B], pdf=pdf)
    assert out["ok"] and out["measured"]["pdf_fonts"], out
    assert abs(out["measured"]["pdf_width_in"] - 3.4) < 0.05
    assert not found(out, "pdf-fonts"), out["findings"]
    assert Path(out["report_path"]).exists()
    # a sans-serif label is a font that is not Computer Modern
    fig, ax = base_fig()
    ax.set_xlabel("Time (s)", family="DejaVu Sans")
    fig.savefig(pdf)
    out = run(fig, [SRC_A, SRC_B], pdf=pdf)
    assert any("DejaVu" in f["message"] for f in found(out, "pdf-fonts", "warn"))
    rep = Report()
    check_pdf(rep, TMP / "missing.pdf")
    assert rep.count("fail") == 1


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(exc).__name__}: {str(exc)[:600]}")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
