# Task and source contract

Keep the task workspace separate from the skill:

```text
task.json                 slides, aspect_ratio, language
slides/slideNN.html        editable slide sources, numbered from 1
assets/                   local images, CSS, fonts, and other resources
qa/                       generated renders and contact sheets
workspace-state.json      render, review, and build evidence (CLI-managed)
answer.pptx                editable deliverable
final-report.json          latest acceptance result
```

Supported canvases are `16:9` (1280x720), `4:3` (960x720), and `A1`
(2244x3178). Use `init` to create a task or write `task.json` directly:

```json
{"slides": 5, "aspect_ratio": "16:9", "language": "zh"}
```

All render dependencies must be local under `assets/` or `slides/`; use
relative paths. Download remote images before authoring. Ordinary hyperlinks
may point to websites. CSS and scripts can be inline. Shared resources are
hashed together, so changing any of them invalidates all slide reviews.
Do not edit the CLI-managed evidence files to bypass review.

The converter supports static HTML/CSS. The body must resolve to the requested
pixel dimensions in its default 1280x720 browser viewport; explicit dimensions
in inline or local CSS are the simplest choice. Prefer `p`, `h1`–`h6`, or list elements for text;
put backgrounds, borders, and shadows on wrapping `div` elements. Keep each
text element's content on one source line, since export can preserve newlines
that a browser collapses. The scaffold demonstrates these constraints.

Give positioned text containers an explicit width with spare room, especially
for mixed Chinese/Latin headings. Font metrics can differ after PPTX export;
a tightly fitted browser heading can wrap and overlap the next element.
Check the exported deck as well as the HTML renders.

Research notes and a manuscript are optional working aids. Keep provenance for
externally checkable claims and reused assets in an appropriate form; no fixed
notes schema is required. Revise existing content when the user asks, even if
an earlier PPTX has already been built.
