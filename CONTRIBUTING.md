# Contributing

Bug reports, failing examples and small fixes are welcome.

## Set up

```bash
git clone https://github.com/gbareas/braindance
cd braindance
python -m pip install -e . pytest  # pytest is optional
sudo apt-get install poppler-utils   # pdffonts and pdfinfo, used by the PDF checks
```

A LaTeX installation is optional. Without it, figures use matplotlib's mathtext with Computer Modern, which is what CI exercises.

## Run the tests

```bash
export MPLBACKEND=Agg
python tests/test_check_figure.py
python tests/test_figproject.py
python skills/latex-scientific-plots/example.py
```

The tests are plain scripts that print `ok` per test and exit non-zero on failure.

## Making a change

- Open an issue first for anything larger than a small fix.
- Add a test for a new check or a bug fix. A check should have a figure that fails it and one that passes.
- A `fail` in `check_figure` means the figure is wrong or unreadable, so it must come with a test showing a real mistake. Use `warn` when a judgement is needed.
- Keep `SKILL.md` and the README in step with behaviour changes, and add a line to `CHANGELOG.md` under Unreleased.
- Do not vendor third-party code. Link to it and cite the commit instead.
