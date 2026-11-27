"""Tests for figproject: reading a manuscript, the record, the plotting API, compare and preview.

Run with `python tests/test_figproject.py` or with pytest. Tests that compile LaTeX are
skipped when pdflatex is not installed.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import matplotlib

os.environ["BRAINDANCE_PROFILE"] = "none"  # the house style, whatever personal profile the runner has

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "latex-scientific-plots"))
import figproject as fp  # noqa: E402

HAS_LATEX = shutil.which("pdflatex") is not None
TARGET = {"textwidth_pt": 500.0, "columnwidth_pt": 240.0, "figure_linewidth_pt": 240.0,
          "figure_star_linewidth_pt": 500.0, "twocolumn": True, "engine": "pdflatex"}

MAIN = r"""\documentclass[twocolumn]{article}
\usepackage{graphicx}
\usepackage{comment}
\graphicspath{{figs/}}
\begin{document}
Text cites Fig.~\ref{fig:one} and \ref{fig:two,fig:one}. % \ref{fig:one} in a comment
\input{sec}
\begin{figure}\centering
\includegraphics[width=\linewidth]{one}
\caption{First {nested} caption, 50\% of it.}\label{fig:one}
\end{figure}
\begin{comment}
\begin{figure}\includegraphics{ghost}\caption{x}\label{fig:ghost}\end{figure}
\end{comment}
\end{document}
"""
SEC = r"""\begin{figure*}
\begin{minipage}{0.5\linewidth}\includegraphics[width=0.8\linewidth]{two_a}\caption{sub}\end{minipage}%
\begin{minipage}{0.5\linewidth}\includegraphics[scale=0.5]{two_b.pdf}\end{minipage}
% \includegraphics{old}
\caption{Second.}\label{fig:two}
\end{figure*}
"""


def make_manuscript():
    root = Path(tempfile.mkdtemp(prefix="figproject_"))
    (root / "figs").mkdir()
    (root / "main.tex").write_text(MAIN)
    (root / "sec.tex").write_text(SEC)
    for name, w in (("one", 5.0), ("two_a", 3.0), ("two_b", 4.0)):
        fig = plt.figure(figsize=(w, 2.0))
        fig.text(0.5, 0.5, name)
        fig.savefig(root / "figs" / f"{name}.pdf")
        plt.close(fig)
    return root


def scan(root):
    return {e["name"]: e for e in fp.scan_figures(fp.Source(root / "main.tex"), TARGET)}


def test_lengths():
    ctx = {"linewidth": 200.0, "textwidth": 400.0}
    assert fp.length_pt(r"0.5\linewidth", ctx) == 100.0
    assert fp.length_pt(r"\textwidth", ctx) == 400.0
    assert abs(fp.length_pt("1in", ctx) - 72.27) < 1e-9
    assert abs(fp.length_pt("2.54cm", ctx) - 72.27) < 1e-9
    assert fp.length_pt(r"\linewidth-2em", ctx) is None
    assert fp.length_pt(r"{.25\linewidth}", ctx) == 50.0


def test_comments_and_escaped_percent():
    assert fp.strip_comment(r"50\% of it % gone") == r"50\% of it "
    assert fp.strip_comment(r"line\\% comment") == "line\\\\"


def test_scan_numbers_widths_and_citations():
    root = make_manuscript()
    figs = scan(root)
    assert set(figs) == {"one", "two_a", "two_b"}, figs.keys()          # ghost is inside a comment block
    # \input{sec} comes first; the caption in the first minipage takes a number of its own, as in LaTeX
    assert figs["two_a"]["figure"] == 1 and figs["two_a"]["caption"] == "sub" and figs["two_a"]["label"] is None
    assert figs["two_b"]["figure"] == 2 and figs["two_b"]["label"] == "fig:two"
    assert figs["one"]["figure"] == 3
    assert figs["two_a"]["panel"] == "1 of 2"
    # figure* -> 500 pt; minipage 0.5 -> 250 pt; width 0.8\linewidth -> 200 pt
    assert abs(figs["two_a"]["width_in"] - 200 / 72.27) < 1e-3
    # scale=0.5 of a 4 in file
    assert abs(figs["two_b"]["width_in"] - 2.0) < 1e-3
    # \linewidth in figure is the column
    assert abs(figs["one"]["width_in"] - 240 / 72.27) < 1e-3
    assert abs(figs["one"]["printed_scale"] - (240 / 72.27) / 5.0) < 1e-3
    assert figs["one"]["path"] == "figs/one.pdf"
    assert figs["one"]["cited_at"] == ["main.tex:6", "main.tex:6"]
    assert figs["two_a"]["defined_at"] == "sec.tex:1"
    assert figs["one"]["label"] == "fig:one"
    src = fp.Source(root / "main.tex")
    caption = [e for e in fp.scan_figures(src, TARGET) if e["name"] == "one"][0]["caption"]
    assert caption == r"First {nested} caption, 50\% of it."


def test_record_keeps_style_and_results():
    root = make_manuscript()
    fp.init(root / "main.tex", textwidth="500pt", columnwidth="240pt", quiet=True)
    rec = fp.load_record(root / "figures.yaml")
    assert rec["figures"]["one"]["in_manuscript"] and rec["output_dir"] == fp.DEFAULT_OUTPUT
    assert (root / "FIGURES.md").read_text().count("## Fig.") == 3
    rec["style"] = {"run": {"a": {"colour": "#0072B2"}}}
    rec["figures"]["one"]["notes"] = "keep me"
    rec["figures"]["extra"] = {"in_manuscript": False, "script": "x.py"}
    fp.save_record(root / "figures.yaml", rec)
    fp.index(root, quiet=True)
    rec = fp.load_record(root / "figures.yaml")
    assert rec["style"]["run"]["a"]["colour"] == "#0072B2"
    assert rec["figures"]["one"]["notes"] == "keep me"
    assert rec["figures"]["extra"] == {"in_manuscript": False, "script": "x.py"}


def test_paper_profile_is_kept_applied_and_recorded():
    import os
    root = make_manuscript()
    fp.init(root / "main.tex", textwidth="500pt", columnwidth="240pt", quiet=True)
    rec = fp.load_record(root / "figures.yaml")
    rec["profile"] = {"name": "Paper look", "palette": ["#123456", "#c0392b"], "rc": {"xtick.direction": "out"},
                      "personal": False}
    fp.save_record(root / "figures.yaml", rec)
    fp.index(root, quiet=True)                      # re-indexing keeps the profile
    assert fp.load_record(root / "figures.yaml")["profile"]["name"] == "Paper look"
    old = os.environ.get("BRAINDANCE_PROFILE")
    os.environ["BRAINDANCE_PROFILE"] = str(root / "no-such-personal-profile.yaml")  # ignored: personal: false
    try:
        proj = fp.Project(root)
        fig, sources = _draw(proj, "one", proj.width("one"))
        assert plt.rcParams["xtick.direction"] == "out"
        assert [c["color"] for c in plt.rcParams["axes.prop_cycle"]] == ["#123456", "#c0392b"]
        result = proj.finish(fig, "one", sources)
    finally:
        if old is None:
            os.environ.pop("BRAINDANCE_PROFILE", None)
        else:
            os.environ["BRAINDANCE_PROFILE"] = old
    assert result["measured"]["profile"]["name"] == "Paper look"
    assert fp.load_record(root / "figures.yaml")["figures"]["one"]["check"]["profile"] == "Paper look"


def _draw(proj, name, width):
    proj.setup()
    x = np.linspace(0, 1, 11)
    proj.write_csv(f"{name}_data", x=x, y=x ** 2)
    fig, ax = plt.subplots(figsize=(width, 1.6))
    ax.plot(x, x ** 2, "-o", label="data")
    ax.set_xlabel(r"$x$")
    ax.set_ylabel(r"$y$")
    return fig, [{"label": "data", "file": f"{name}_data.csv", "x": "x", "y": "y"}]


def test_project_width_finish_and_record():
    root = make_manuscript()
    fp.init(root / "main.tex", textwidth="500pt", columnwidth="240pt", quiet=True)
    proj = fp.Project(root / "main.tex")
    assert abs(proj.width("one") - 240 / 72.27) < 1e-3
    assert abs(proj.width("new", 0.5) - 120 / 72.27) < 1e-3
    try:
        proj.width("new")
        raise AssertionError("expected KeyError")
    except KeyError:
        pass
    fig, sources = _draw(proj, "one", proj.width("one"))
    script = root / "plot_one.py"
    script.write_text("# plotting script\n")
    result = proj.finish(fig, "one", sources, script=script)
    assert result["ok"], result["findings"]
    assert (proj.out / "one.pdf").exists() and (proj.out / "one.png").exists()
    rec = fp.load_record(root / "figures.yaml")
    entry = rec["figures"]["one"]
    assert entry["script"] == "plot_one.py" and entry["sources"] == ["one_data.csv"]
    assert entry["check"]["fail"] == 0 and entry["in_manuscript"]
    assert "0 fail" in (root / "FIGURES.md").read_text()
    # a figure drawn at the wrong width is warned about
    fig, sources = _draw(proj, "one", 5.0)
    out = proj.finish(fig, "one", sources, script=script)
    assert any(f["check"] == "width" for f in out["findings"]), out["findings"]


def test_layout_settles_before_saving():
    # equal-aspect panels next to a shared colourbar: constrained layout needs more than one draw to converge,
    # and the first file saved used to be laid out differently from the second (titles cut off in the PDF)
    fig, axes = plt.subplots(1, 2, figsize=(6.0, 2.4), layout="constrained")
    for ax in axes:
        mesh = ax.pcolormesh(np.arange(4), np.arange(4), np.arange(9).reshape(3, 3))
        ax.set_aspect("equal")
        ax.set_title("a long panel title that needs room")
        ax.set_xlabel("x")
    fig.colorbar(mesh, ax=axes, shrink=0.9)
    first = [ax.get_position().bounds for ax in fig.axes]
    fig.draw_without_rendering()
    moved = [ax.get_position().bounds for ax in fig.axes] != first
    assert fp.settle_layout(fig)
    settled = [ax.get_position().bounds for ax in fig.axes]
    fig.draw_without_rendering()
    again = [ax.get_position().bounds for ax in fig.axes]
    assert all(abs(a - b) < 1e-4 for p, q in zip(settled, again) for a, b in zip(p, q))
    plt.close(fig)
    print("    (layout moved on the first draw)" if moved else "    (layout converged on the first draw)")


def test_measure_two_columns():
    if not HAS_LATEX:
        print("skip (no pdflatex)")
        return
    root = make_manuscript()
    t = fp.measure(root / "main.tex")
    assert t["twocolumn"] and t["columnwidth_pt"] < t["textwidth_pt"]
    assert t["figure_linewidth_pt"] == t["columnwidth_pt"]
    assert t["figure_star_linewidth_pt"] == t["textwidth_pt"]
    assert t["body_font_pt"] == 10.0 and t["caption_font_pt"] == 10.0
    assert not list(root.glob("braindance_probe.*")), "the probe must not write into the manuscript folder"


def test_compare_and_preview():
    if not HAS_LATEX:
        print("skip (no pdflatex)")
        return
    root = make_manuscript()
    fp.init(root / "main.tex", quiet=True)
    proj = fp.Project(root)
    fig, sources = _draw(proj, "one", proj.width("one"))
    proj.finish(fig, "one", sources)
    pdf, table = fp.compare(root, png=root / "stacked", dpi=60)
    assert pdf.exists() and [r["name"] for r in table] == ["one"]
    assert Path(table[0]["png"]).exists() and Path(table[0]["png"]).parent == root / "stacked"
    assert abs(table[0]["after_scale"] - 1.0) < 0.01 and table[0]["before_scale"] < 0.8
    report = fp.preview(root)
    assert Path(report["pdf"]).exists() and report["replaced"] == ["one"], report
    assert not report["errors"], report["errors"]
    pages = {f["name"]: f for f in report["figures"]}
    assert pages["one"]["new"] and pages["one"]["figure"] == "3" and pages["one"]["page"]
    assert (root / "figs" / "one.pdf").stat().st_size != (proj.out / "one.pdf").stat().st_size  # original untouched


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    sys.exit(1 if failed else 0)
