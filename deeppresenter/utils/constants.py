"""deeppresenter 全局常量定义"""

import logging
import os
from pathlib import Path

# ============ Path ============
PACKAGE_DIR = Path(__file__).parent.parent

# ============ Logging ===========
LOGGING_LEVEL = int(os.getenv("DEEPPRESENTER_LOG_LEVEL", logging.INFO))
MAX_LOGGING_LENGTH = int(os.getenv("DEEPPRESENTER_MAX_LOGGING_LENGTH", 1024))

# ============ Agent  ============
RETRY_TIMES = int(os.getenv("RETRY_TIMES", 10))
MAX_TOOLCALL_PER_TURN = int(os.getenv("MAX_TOOLCALL_PER_TURN", 7))
MAX_RETRY_INTERVAL = int(os.getenv("MAX_RETRY_INTERVAL", 60))
# count in chars, this is about the first 4 page of a dual-column paper
TOOL_CUTOFF_LEN = int(os.getenv("TOOL_CUTOFF_LEN", 4096))
ASYNC_TOOL_TIMEOUT = int(os.getenv("ASYNC_TOOL_TIMEOUT", 5))
MAX_SUBAGENT_TURNS = int(os.getenv("MAX_SUBAGENT_TURNS", 10))
# count in tokens
CONTEXT_LENGTH_LIMIT = int(os.getenv("CONTEXT_LENGTH_LIMIT", 200_000))
CUTOFF_WARNING = "NOTE: Output truncated (showing first {line} lines). Use `read_file` with `offset` parameter to continue reading from {resource_id}."

# ============ Environment ============
PIXEL_MULTIPLE = int(os.getenv("PIXEL_MULTIPLE", 16))
MCP_CONNECT_TIMEOUT = int(os.getenv("MCP_CONNECT_TIMEOUT", 120))
MCP_CALL_TIMEOUT = int(os.getenv("MCP_CALL_TIMEOUT", 1800))
WORKSPACE_BASE = Path(
    os.getenv(
        "DEEPPRESENTER_WORKSPACE_BASE",
        str(Path.home() / ".cache/deeppresenter"),
    )
)
TOOL_CACHE = PACKAGE_DIR / ".tools.json"

GLOBAL_ENV_LIST = [
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "PYTHONWARNINGS",
]

# ============ Webview ============
PDF_OPTIONS = {
    "print_background": True,
    "landscape": False,
    "margin": {"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
    "prefer_css_page_size": False,
    "display_header_footer": False,
    "scale": 1,
    "page_ranges": "1",
}

# ============ Additional Agent Prompt ===========

AGENT_PROMPT = """
<Environment>
Current time: {time}
Working directory: {workspace}
Platform: Debian Linux container

Pre-installed tools:
- Python 3.13, Node.js, imagemagic, mermaid-cli (mmdc), curl, wget, and other common utilities
- python-pptx, matplotlib, plotly, and other common packages
You can freely install any required tools, packages, or command-line utilities to complete the task
</Environment>

<Task Guidelines>
- Exploration Principle: A warning is issued at 10% remaining computation budget, Until then, explore thoroughly and give your best effort.
- Max Length: Tool Call Output exceeding {cutoff_len} characters will be truncated at the preceding line break. Full content is saved locally and accessible via `read_file` with `offset`.
- Tool Call Principle:
    1. Every response must include reasoning content and a valid tool call.
    2. All tool calls are processed in parallel; do not emit tool calls with interdependencies in the same turn.
- Toolcall Limit: You can calling up to {max_toolcall_per_turn} tools per turn.
</Task Guidelines>
"""

# Long-context understanding and multi-perspective retrieval
MA_RESEACHER_PROMPT = """
<Guide on Subagents>
You can use subagents to execute multiple complex tasks in parallel. They have the same capabilities as you, but start with empty context.
The subagent tool accepts a minimal `task` and a `context_file`.
Use `delegate_subagent` when the research task involves multiple independent topics or objects, such as several technologies, products, companies, markets, papers, events, regions, or case studies.
For parallel research, create delegation files for each sub-topic containing research goals, information requirements, and output format, then batch call subagents.
Before calling a subagent, write the complete delegation brief to a local file yourself.
Put the complete background, source paths, constraints, expected deliverables, and handoff format into that file.
Keep `task` short and action-oriented.
In general, you should use subagents in scenarios that can be parallelized at scale without information loss. For example:
1. Long-document understanding: for a document with 20,000 lines, you can assign each agent 1,000 lines and launch 20 subagents in parallel.
2. Multi-perspective retrieval: analyze one subject from multiple aspects, such as a car's exterior design, configuration and pricing, and development history.
</Guide on Subagents>
"""

# Generate multiple pages in parallel after defining the global CSS
MA_RRESENTER_PROMPT = """
<Guide on Subagents>
You can use subagents to execute multiple complex tasks in parallel. They have the same capabilities as you, but start with empty context.
Therefore, you should first define a global visual theme, including a detailed design specification such as the background and accent colors.
The subagent tool accepts a minimal `task` and a `context_file`.
Use `delegate_subagent` when the manuscript contains 3 or more slides, so slide HTML files can be generated in parallel: first create delegation files for each slide containing the design plan, page content, output path, and constraints, then batch call subagents.
Do not use `delegate_subagent` when the manuscript contains fewer than 3 slides; generate standalone HTML files page by page to `slides/slide_{page_number:02d}.html`, immediately call `inspect_slide` after each generation for quality checks, and fix issues before proceeding to the next page.
Before calling a subagent, write the shared visual system, manuscript excerpt, slide scope, constraints, output path, and handoff requirements into a local file.
Keep `task` as a short action such as "Generate slide 1 according to the global visual system".
</Guide on Subagents>
"""


OFFLINE_PROMPT = """
<Offline Mode>
- You are operating in offline mode without internet access. All network-dependent tools have been removed.
- Focus on the available tools and adjust your plan accordingly.
</Offline Mode>
"""

CONTEXT_MODE_PROMPT = """
<Context Mode>
- You are operating in limited working context. When approaching the limit, you will be asked to compact history into a local summary, then continue.
- To minimize information loss, save files, images, and intermediate results immediately after generation or retrieval—do not defer.
- After compaction, only the first few messages, recent messages, and your saved summary will remain—all other context will be discarded.
</Context Mode>
"""


HALF_BUDGET_NOTICE_MSG = {
    "text": "<NOTICE>You have used about half of your working budget. Now focused on the core task and skipping unnecessary steps or explorations.</NOTICE>",
    "type": "text",
}
URGENT_BUDGET_NOTICE_MSG = {
    "text": "<URGENT>Working budget nearly exhausted. You must finish the core task and call `finalize` now, or your work will fail. Skip extras like inspection and validation.</URGENT>",
    "type": "text",
}
HIST_LOST_MSG = {
    "text": "<NOTICE>History between this point and the following message has been compacted into a summary</NOTICE>",
    "type": "text",
}

CONTINUE_MSG = {
    "text": "<NOTICE>History has been compacted. Refer to the saved summary and continue your work</NOTICE>",
    "type": "text",
}

LAST_ITER_MSG = {
    "text": "<URGENT>Working budget nearly exhausted. You must finish the core task and call `finalize` now, or your work will fail. Skip extras like inspection and validation.</URGENT>",
    "type": "text",
}

MEMORY_COMPACT_MSG = """
You have reached the context length limit for this conversation. Immediately extract key information from the tool interaction history, generate a complete state summary, and save it to the working directory to ensure seamless continuation in subsequent conversations.

<summary_requirements>
All information must be recorded with specific details. Do not use references like "as mentioned above" or "see previous section". Only extract information from tool interactions in the current session; do not record information provided by the user or system instructions.

1. Collected Information & Data
   - Factual data, evidence, research findings
   - Key source materials and references

2. Uncertainties & Open Issues
   - Information gaps, unverified assumptions, identified limitations

3. Generated Artifacts
   - Intermediate files, code, images/charts: path + purpose

4. Next Steps
   - Work completed so far and outcomes achieved
   - Remaining tasks and suggested execution order
   - Pending items that were planned/started but not yet finished

5. Lessons Learned (if applicable)
   - Issues encountered during tool calls and their solutions
   - Operations to avoid
</summary_requirements>

<important>
- Use {language} as the primary language. The summary must be detailed enough for any successor to fully understand current progress and continue work without reviewing history.
- Complete the summary generation in this turn. Do not plan multi-turn generation, or history will be lost. Save directly to the working directory.
</important>
"""
