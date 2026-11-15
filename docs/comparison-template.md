# Our agent vs. PaperOrchestra plotting agent

Fill in the "Ours" column from the work-laptop agent (do not paste anything confidential; summarize).

| Aspect | PaperOrchestra | Ours |
|---|---|---|
| Inputs (data format, spec) | markdown logs + figure spec | |
| Stages / steps | retrieve, plan, style, render, critic x3, caption | |
| Model(s) and provider | Gemini text + image model | |
| Render method | matplotlib via exec(); image model for diagrams | |
| Code sandboxing | none (in-process exec) | |
| Critic | LLM sees image + description + raw data | |
| Acceptance / revert logic | none | |
| Programmatic data check | none | |
| Few-shot examples | retrieval from reference set | |
| Output formats | JPEG base64 | |
| Captioning | yes, LLM | |
| Parallelism | 5 figures at once | |
| Failure handling | silent None, loop continues | |
| Cost / speed | many LLM calls per figure | |

## Questions to answer about our agent

- What kinds of plots does our data produce?
- Single prompt or multi-step? Does it execute code?
- What is the main pain point: quality, reliability, speed or cost?

## Candidate improvements (to evaluate after the comparison)

- Accept/revert per critic round using a score
- Programmatic data-fidelity check (re-read the plotted data from the figure code and diff against source)
- Sandboxed execution (subprocess, timeout, no network)
- Provider-agnostic LLM layer (including Claude via the `claude` CLI on a subscription)
- Vector output (PDF/SVG) and consistent house style
- Edit code instead of regenerating it each round
