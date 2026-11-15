# Reference: PaperOrchestra plotting agent

Source: https://github.com/google-research/paper-orchestra
Files: `methods/agents/plotting_agent.py`, `utils/paper_banana_utils.py` (copies in `../reference/`).
Based on the PaperBanana approach. Default models: Gemini (text/code) and a Gemini image model (diagrams).

## Where it sits in the full pipeline

PaperOrchestra is a fixed sequence of agents, each reading files and writing files for the next:

1. **OutlineAgent** - one LLM call from idea + experimental log + LaTeX template + guidelines. Produces `outline.json`
   including a `plotting_plan` (list of figures).
2. **HybridLiteratureAgent** - parallel search (Gemini + Google Search), verification and date cutoff via Semantic
   Scholar, BibTeX + citation map, then an LLM writes Intro and Related Work citing only verified papers.
3. **SectionWritingAgent** - one big call filling the remaining sections; the experimental log is the source of
   truth for tables.
4. **ContentRefinementAgent** - up to 3 rounds: compile, LLM review score, rewrite, recompile, re-review. Accepts a
   revision only if the overall score rises; reverts and stops if it drops or sub-scores degrade.
5. **PlottingAgent** (optional, `--use_plotting`) - described below.

Reusable patterns: file handoffs between stages, external grounding (search, compilation), critic loop with
revert, parallel fan-out, retries of the whole pipeline (3x).

## Plotting agent

Entry: `PlottingAgent.run(outline_json_path, raw_materials_dir, output_filepath)`.
It reads `plotting_plan` from the outline and processes each figure with `process_single_figure`, 5 figures in
parallel (ThreadPoolExecutor).

Figure spec fields: `figure_id`, `title`, `plot_type` (plot | diagram), `data_source`, `objective`, `aspect_ratio`.

```
figure spec
  |
  1 Retriever   LLM picks top-10 similar examples from a reference set (PaperBananaBench ref.json;
  |             up to 200 candidates for diagrams are put in one prompt)
  2 Planner     LLM writes a "detailed description" of the figure, guided by the examples
  3 Stylist     LLM rewrites the description to follow a house style
  4 Visualizer  plot:    LLM writes matplotlib code -> exec() -> JPEG (base64, 300 dpi)
  |             diagram: image model renders directly from the description
  5 Critic      up to 3 rounds. LLM sees image + description + raw data, returns
  |             {critic_suggestions, revised_description}. "No changes needed." -> stop,
  |             otherwise regenerate from the revised description
  6 Captioner   LLM writes the caption from the final image + description
  -> {figure_id, title, description, caption, critic_history, image_path}
```

Raw material selection: markdown files in `raw_materials` whose name matches the spec's `data_source`
("idea" / "experiment"); falls back to `experimental_log.md` and `idea_sparse.md`.

### Critic rules (plot critic prompt)

- Data fidelity: all values correct, none hallucinated or omitted, aligned with the visual intent.
- Text QA: typos, unclear labels, axis and legend text.
- No figure caption text inside the image.
- Layout: overlaps, clutter; remove redundant text legends.
- Generation failures: if the plot is missing (system notice), simplify the description instead of repeating it.

### Design traits

- The **description (prose) is the state**, not the code. Code is regenerated from scratch each round.
- The critic checks data fidelity, but only by an LLM looking at the image.
- Two rendering paths: code execution for plots, image model for diagrams.

### Weaknesses observed

1. Retriever needs the PaperBanana dataset at `../PaperBanana`; if missing it silently proceeds without examples.
2. Retrieval puts up to 200 candidates into one prompt (expensive, unscalable).
3. Regenerating code every round can regress earlier fixes; no accept/revert check (unlike the content refinement
   agent).
4. No programmatic check that plotted values match the source data.
5. `exec()` runs generated code in-process, unsandboxed.
6. Failures are silent: a failed exec returns `None` and the loop carries on.
7. Hard-coded to Gemini (`call_gemini_*`), not provider-agnostic.
8. Images are returned as base64 and written as JPEG; no vector output (PDF/SVG), which matters for papers.

## Notes from review

Reviewed: pipeline orchestration, outline, literature, section writing, content refinement loop, plotting agent
and its helper functions. Not read in detail: the critic loop's remaining prompts (diagram variants), the format
review prompt, and `generate_figure_caption` internals.
