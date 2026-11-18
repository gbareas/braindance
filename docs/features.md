# Features

- **House style.** All text and numbers in LaTeX (Computer Modern), figures created at the printed column width, colourblind-safe colours, vector PDF.
- **Measured checks** (`check_figure.py`). The values drawn equal the values in the source files, every declared series is in the figure, no point is hidden by axis limits or a log axis. It also measures width, font sizes, overlapping text, legends or labels sitting on data, colormaps, and the fonts and page size of the saved PDF.
- **Manuscript projects** (`figproject.py`). Point it at the main `.tex` file: it compiles the preamble to measure the text width, `\linewidth` in `figure` and `figure*`, and the font sizes, then records every figure with the width it is printed at in `figures.yaml`, and writes `FIGURES.md`, an index of the figures with their captions. Plotting scripts take their width and shared colours from the record, and every check result is written back to it. Two commands show the result: `compare` (each current figure next to its new version at print size) and `preview` (the manuscript compiled with the new figures, nothing overwritten).
- **Chart choice** (`chart-choice.md`). Which chart suits which data and the rules that hold for any chart, adapted from [From Data to Viz](https://www.data-to-viz.com).
- **Review loop** (`figure-reviewer`). A separate agent looks at the rendered figure, the script and the check report, and returns PASS or a ranked list of fixes, for up to three rounds.

