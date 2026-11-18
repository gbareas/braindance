# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `pyproject.toml`: `pip install git+https://github.com/gbareas/braindance` installs `check_figure`, `figproject`, the house style, and the commands `braindance-check` and `braindance-figs`.
- Demo GIF at the top of the README, `CONTRIBUTING.md`, issue and pull request templates.
- Banner, rendered with Blender by `docs/make_banner_blender.py`: animated `docs/banner.gif` in the README, still `docs/banner.jpg` for the social preview.
- `figproject.apply_style()`: the house style with a Computer Modern fallback when LaTeX is not installed, usable without a `Project`.

### Changed
- README shortened to pitch, demo, install, quick start and links; the feature details and the before-and-after gallery moved to `docs/features.md` and `docs/gallery.md`.

## [0.1.0]

### Added
- Claude Code plugin: the `latex-scientific-plots` skill and the `figure-reviewer` agent.
- `check_figure.py`: measured checks of plotted values against source files, and of size, fonts, overlaps and colormaps.
- `figproject.py`: per-manuscript figure record (`figures.yaml`), caption index (`FIGURES.md`), `compare` and `preview`.
- Chart-choice rules, a worked example, synthetic before-and-after examples.
- MIT licence and a CI workflow running the tests and the worked example.
