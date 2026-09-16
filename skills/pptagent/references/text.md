# External visual review

Set `mode: text`, configure an OpenAI-compatible chat completions endpoint in
`visual.base_url` and `visual.model`, and set the configured API key variable.
The CLI reads the skill's `.env`; `--env` and `--config` override those paths.

`review-slides` sends the current slide renders to the visual model;
`review-deck` sends contact sheets. Both validate the response and record the
same evidence used by host review. A response must include `verdict` (`pass`,
`fail`, or `unjudgeable`), a nonempty `summary`, and an `issues` list. Each issue
requires `severity` (`blocker`, `major`, `minor`), a positive `slide` number,
`description`, and `suggested_fix`. A pass with major or blocker issues is
rejected. Invalid JSON is surfaced for correction, not silently repaired.

OpenCode can expose these operations as `review_slides` and `review_deck` MCP
tools. Use those tools when present; otherwise run the matching CLI commands.

Follow the normal authoring and delivery workflow. A missing key or failed
visual call is a failed review, never an implicit pass.
