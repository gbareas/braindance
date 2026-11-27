"""Tests for the personal style profile and the colour checks that keep it readable.

Run with `python tests/test_style_profile.py` (numpy, matplotlib, PyYAML) or with pytest.
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

SKILL = Path(__file__).resolve().parents[1] / "skills" / "latex-scientific-plots"
sys.path.insert(0, str(SKILL))
import colours as C  # noqa: E402
import style_profile as SP  # noqa: E402
from check_figure import check_figure  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="style_profile_"))
OKABE_ITO = SP.HOUSE_PALETTE
TAB10 = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22",
         "#17becf"]


def write(name, text):
    p = TMP / name
    p.write_text(text, encoding="utf-8")
    return p


class personal:
    """Point BRAINDANCE_PROFILE at a file (or 'none') for the duration of a block."""

    def __init__(self, value):
        self.value = str(value)

    def __enter__(self):
        self.old = os.environ.get("BRAINDANCE_PROFILE")
        os.environ["BRAINDANCE_PROFILE"] = self.value

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("BRAINDANCE_PROFILE", None)
        else:
            os.environ["BRAINDANCE_PROFILE"] = self.old


def found(out, check, level=None):
    return [f for f in out["findings"] if f["check"] == check and (level is None or f["level"] == level)]


# ---- colour science ----

def test_ciede2000_matches_sharma_reference_pairs():
    pairs = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
             ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615),
             ((50, 2.5, 0), (61, -5, 29), 22.8977),
             ((50, 2.5, 0), (73, 25, -18), 27.1492),
             ((50, 2.5, 0), (56, -27, -3), 31.9030)]
    for a, b, expected in pairs:
        assert abs(float(C.delta_e(a, b)) - expected) < 1e-4, (a, b)


def test_lab_round_trip_and_white():
    rgb = np.array([[0.2, 0.5, 0.8], [1, 1, 1], [0, 0, 0]])
    lab = C.rgb_to_lab(rgb)
    assert abs(lab[1, 0] - 100) < 1e-6 and abs(lab[2, 0]) < 1e-6
    back = C.linear_to_srgb(C.lab_to_linear(lab))
    assert np.allclose(back, rgb, atol=1e-6)


def test_okabe_ito_passes_and_tab10_red_green_fails():
    assert C.check_palette(OKABE_ITO)["ok"]
    res = C.check_palette(TAB10)
    assert not res["ok"] and res["safe_prefix"] == 2
    assert (1, 2) in {(i, j) for i, j, _, _ in res["clashes"]}  # orange / green


def test_suggestion_keeps_hues_and_passes():
    mine = ["#c0392b", "#27ae60", "#2980b9", "#8e44ad"]
    res = C.check_palette(mine)
    assert not res["ok"]
    sug = C.suggest_palette(mine)
    assert sug["check"]["ok"], sug
    for old, new in zip(mine, sug["colours"]):
        h_old = C._lch(C.rgb_to_lab(C.to_rgb(old)))[2]
        h_new = C._lch(C.rgb_to_lab(C.to_rgb(new)))[2]
        assert abs((h_old - h_new + 180) % 360 - 180) < 4, (old, new)
    # colours not in a clash are left alone
    clashing = {k for i, j, _, _ in res["clashes"] for k in (i, j)}
    for k in set(range(len(mine))) - clashing:
        assert sug["colours"][k] == mine[k]


def test_suggestion_respects_keep():
    mine = ["#c0392b", "#27ae60", "#2980b9", "#8e44ad"]
    sug = C.suggest_palette(mine, keep=[2])           # blue / purple clash: purple has to move
    assert sug["colours"][2] == mine[2] and sug["colours"][3] != mine[3]
    assert sug["check"]["ok"], sug
    sug = C.suggest_palette(mine, keep=[2, 3])        # both kept: nothing can move, and the result says so
    assert sug["colours"] == mine and not sug["check"]["ok"]


def test_colormap_lightness():
    for name in ("viridis", "cividis", "magma", "Blues"):
        assert C.check_colormap(name, "sequential")["ok"], name
    for name in ("RdBu_r", "coolwarm", "BrBG"):
        assert C.check_colormap(name, "diverging")["ok"], name
    assert not C.check_colormap("jet", "sequential")["ok"]
    assert not C.check_colormap("Spectral", "sequential")["ok"]
    assert not C.check_colormap("bwr", "diverging")["ok"]


# ---- profiles ----

def test_no_profile_is_the_house_style():
    with personal("none"):
        prof = SP.load_profile()
    assert prof.is_house and prof.palette == OKABE_ITO and prof.font["preset"] == "computer-modern"


def test_layers_personal_then_paper():
    p = write("me.yaml", "name: Mine\npalette: ['#c0392b', '#27ae60']\nkeep: [0]\nfont: helvetica\n"
                         "rc: {xtick.direction: out, axes.grid: true}\n")
    with personal(p):
        prof = SP.load_profile()
        assert prof.name == "Mine" and prof.palette == ["#c0392b", "#27ae60"] and prof.keep == [0]
        assert prof.font["preset"] == "helvetica" and prof.rc["xtick.direction"] == "out"
        # the paper overrides one rc key and the font, and keeps the rest of the personal profile
        prof = SP.load_profile({"font": "times", "rc": {"axes.grid": False}})
        assert prof.font["preset"] == "times" and prof.rc == {"xtick.direction": "out", "axes.grid": False}
        assert prof.palette == ["#c0392b", "#27ae60"] and len(prof.sources) == 2
        # a new palette drops `keep`, whose indices belonged to the old one
        prof = SP.load_profile({"palette": ["#000000", "#E69F00", "#56B4E9"]})
        assert prof.keep == []
        # personal: false pins the paper's look for every co-author
        prof = SP.load_profile({"font": "times", "personal": False})
        assert prof.palette == OKABE_ITO and prof.rc == {} and prof.sources == ["figures.yaml profile"]


def test_paper_profile_can_be_a_file():
    write("lab.yaml", "name: Lab\nfont: times\n")
    with personal("none"):
        prof = SP.load_profile("lab.yaml", base_dir=TMP)
    assert prof.name == "Lab" and prof.font["preset"] == "times"


def test_bad_profiles_are_refused_with_the_reason():
    cases = [({"pallete": ["#000"]}, "unknown key"), ({"palette": ["#zzz"]}, "palette"),
             ({"palette": "#000000"}, "list of colours"), ({"font": "comic"}, "not a preset"),
             ({"rc": {"xtick.dirction": "out"}}, "not matplotlib settings"),
             ({"colormaps": {"sequential": "nope"}}, "no colormap"),
             ({"palette": ["#000", "#fff"], "keep": [5]}, "outside")]
    for data, words in cases:
        try:
            SP.validate(data)
        except SP.ProfileError as exc:
            assert words in str(exc), (data, exc)
        else:
            raise AssertionError(f"accepted {data}")
    with personal(TMP / "missing.yaml"):
        try:
            SP.load_profile()
        except SP.ProfileError as exc:
            assert "does not exist" in str(exc)
        else:
            raise AssertionError("a missing BRAINDANCE_PROFILE file was ignored")


def test_setup_applies_palette_rc_and_cmap_but_not_usetex():
    p = write("look.yaml", "palette: ['#123456', '#abcdef']\ncolormaps: {sequential: cividis}\n"
                           "rc: {xtick.direction: out, axes.spines.top: false, text.usetex: true}\n")
    with personal(p):
        prof = SP.setup(quiet=True)
    rc = matplotlib.rcParams
    assert [c["color"] for c in rc["axes.prop_cycle"]] == ["#123456", "#abcdef"]
    assert rc["xtick.direction"] == "out" and rc["axes.spines.top"] is False and rc["image.cmap"] == "cividis"
    assert rc["text.usetex"] == (shutil.which("latex") is not None) == prof.usetex
    assert SP.active() is prof


def test_mplstyle_in_profile():
    write("mine.mplstyle", "axes.linewidth: 1.5\nlines.linewidth: 2.0\n")
    p = write("withstyle.yaml", "mplstyle: mine.mplstyle\nrc: {lines.linewidth: 1.8}\n")
    with personal(p):
        SP.setup(quiet=True)
    assert matplotlib.rcParams["axes.linewidth"] == 1.5 and matplotlib.rcParams["lines.linewidth"] == 1.8


def test_check_profile_suggests_a_palette():
    p = write("clash.yaml", "palette: ['#c0392b', '#27ae60', '#2980b9', '#8e44ad']\n")
    prof = SP.resolve(SP.read_profile(p), [str(p)])
    ok, lines, sug = SP.check_profile(prof)
    assert not ok and sug and sug["check"]["ok"]
    assert any("first 3" in ln for ln in lines)
    assert SP.main(["check", str(p), "--swatch", str(TMP / "swatch.png")]) == 1
    assert (TMP / "swatch.png").stat().st_size > 1000
    assert SP.main(["check", str(write("fine.yaml", "font: times\n"))]) == 0


def test_init_writes_a_profile_that_loads():
    path = TMP / "cfg" / "profile.yaml"
    assert SP.main(["init", str(path)]) == 0
    prof = SP.resolve(SP.read_profile(path), [str(path)])
    assert prof.palette == [c.lower() for c in OKABE_ITO] and prof.rc == {}


# ---- the checker reads the profile ----

T = np.linspace(0, 1, 11)


def _two_series(colours, styles=("-", "-"), markers=("", "")):
    fig, ax = plt.subplots(figsize=(3.4, 2.1))
    for k, (c, ls, mk) in enumerate(zip(colours, styles, markers)):
        ax.plot(T, T * (k + 1), linestyle=ls, marker=mk or "None", color=c, label=f"s{k}")
    ax.legend(loc="upper left")
    return fig


def _run(fig, **kw):
    out = check_figure(fig, [{"label": "s0", "computed": True}, {"label": "s1", "computed": True}],
                       target={"width_in": 3.4}, quiet=True, **kw)
    plt.close(fig)
    return out


def test_colour_vision_clash_warns_only_when_colour_is_all_that_differs():
    with personal("none"):
        SP.setup(quiet=True)
    out = _run(_two_series(["#ff7f0e", "#2ca02c"]))          # tab10 orange / green: merge for protans
    w = found(out, "colour-vision", "warn")
    assert w and "protan" in w[0]["message"], out["findings"]
    out = _run(_two_series(["#ff7f0e", "#2ca02c"], styles=("-", "--"), markers=("o", "s")))
    assert not found(out, "colour-vision", "warn") and found(out, "colour-vision", "info")
    out = _run(_two_series(["#0072B2", "#D55E00"]))          # Okabe-Ito blue / vermillion
    assert not found(out, "colour-vision")


def test_scatter_and_bars_are_checked_too():
    fig, ax = plt.subplots(figsize=(3.4, 2.1))
    ax.scatter(T, T, color="#ff7f0e", label="s0")
    ax.scatter(T, T + 1, color="#2ca02c", label="s1")
    assert found(_run(fig), "colour-vision", "warn")
    fig, ax = plt.subplots(figsize=(3.4, 2.1))
    ax.bar([0, 1], [1, 2], color="#ff7f0e", label="s0")
    ax.bar([2, 3], [1, 2], color="#2ca02c", label="s1", hatch="//")
    assert found(_run(fig), "colour-vision", "info") and not found(_run_bars_plain(), "colour-vision", "info")


def _run_bars_plain():
    fig, ax = plt.subplots(figsize=(3.4, 2.1))
    ax.bar([0, 1], [1, 2], color="#0072B2", label="s0")
    ax.bar([2, 3], [1, 2], color="#D55E00", label="s1")
    return _run(fig)


def test_pdf_fonts_are_judged_against_the_profile():
    if not shutil.which("pdffonts"):
        print("      (skipped: poppler-utils not installed)")
        return
    with personal("none"):
        house = SP.setup(quiet=True)
    plt.rcParams.update({"text.usetex": False})  # same fonts on every machine
    pdf = TMP / "sans.pdf"
    fig = _two_series(["#0072B2", "#D55E00"])
    fig.axes[0].set_xlabel("Time (s)", family="DejaVu Sans")
    fig.savefig(pdf)
    out = _run(fig, pdf=pdf, profile=house)
    assert any("DejaVu" in f["message"] and "computer-modern" in f["message"] for f in found(out, "pdf-fonts", "warn"))
    # a profile that declares DejaVu as its font accepts it
    mine = SP.resolve({"font": {"family": "sans-serif", "sans-serif": ["DejaVu Sans"],
                                "pdf_fonts": ["DejaVu", "cmr", "Cmr"]}}, ["test"])
    fig = _two_series(["#0072B2", "#D55E00"])
    fig.axes[0].set_xlabel("Time (s)", family="DejaVu Sans")
    fig.savefig(pdf)
    out = _run(fig, pdf=pdf, profile=mine)
    assert not found(out, "pdf-fonts", "warn"), out["findings"]
    assert out["measured"]["profile"]["font"] == "custom"
    # a custom font without pdf_fonts is listed, not checked
    loose = SP.resolve({"font": {"family": "sans-serif", "sans-serif": ["DejaVu Sans"]}}, ["test"])
    fig = _two_series(["#0072B2", "#D55E00"])
    fig.savefig(pdf)
    out = _run(fig, pdf=pdf, profile=loose)
    assert found(out, "pdf-fonts", "info") and not found(out, "pdf-fonts", "warn")


def test_report_records_the_profile():
    p = write("rec.yaml", "name: Recorded\npalette: ['#123456', '#c0392b']\n")
    with personal(p):
        SP.setup(quiet=True)
    out = _run(_two_series(["#123456", "#c0392b"]))
    prof = out["measured"]["profile"]
    assert prof["name"] == "Recorded" and prof["palette"] == ["#123456", "#c0392b"] and str(p) in prof["sources"]


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
