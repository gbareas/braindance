"""Rebuild the before-and-after examples of the README from scratch.

Runs, with the Python that runs this script:
  1. make_data.py                      synthetic data            -> data/
  2. plot_before.py                    the "before" figures      -> paper/figures/
  3. figproject.py init paper/main.tex measure the manuscript    -> paper/figures.yaml, paper/FIGURES.md
  4. plot_after.py                     the braindance figures    -> paper/braindance_figures/
  5. figproject.py compare --png       one image per figure      -> images/
  6. figproject.py preview             the manuscript compiled with the new figures

Needs numpy, matplotlib, PyYAML, pdflatex and poppler-utils.

Usage:  python build.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIGPROJECT = HERE.parents[1] / "skills" / "latex-scientific-plots" / "figproject.py"

STEPS = [
    ["make_data.py"],
    ["plot_before.py"],
    [str(FIGPROJECT), "init", "paper/main.tex"],
    ["plot_after.py"],
    [str(FIGPROJECT), "compare", "paper", "--png", "images"],
    [str(FIGPROJECT), "preview", "paper"],
]

if __name__ == "__main__":
    for step in STEPS:
        print(f"\n$ python {' '.join(Path(step[0]).name if i == 0 else a for i, a in enumerate(step))}", flush=True)
        subprocess.run([sys.executable, *step], cwd=HERE, check=True)
