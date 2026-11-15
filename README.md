# braindance

A plotting agent that turns raw data into publication-quality figures, with captions.

Scope for now: **the plotting agent only**. It starts from a study of the plotting agent in Google Research's
[PaperOrchestra](https://github.com/google-research/paper-orchestra), compared against our own agent (kept on
the work laptop), with the goal of building a better one.

## Status

- [x] Reference architecture documented (`docs/reference-plotting-agent.md`)
- [ ] Our existing agent documented (`docs/our-agent.md`, to be filled in from the work laptop)
- [ ] Side-by-side comparison (`docs/comparison.md`, template: `docs/comparison-template.md`)
- [ ] Standalone implementation (provider-agnostic, Claude-compatible, sandboxed code execution)

## Layout

- `docs/` - analysis and design notes
- `reference/paper-orchestra/` - verbatim copies (original paths kept, source commit in SOURCE_COMMIT.txt) of the PaperOrchestra plotting code and its dependencies (Apache-2.0, Copyright 2026 Google LLC), for study only
