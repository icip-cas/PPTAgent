<div align="right">
  <details>
    <summary>🌐 Language</summary>
    <div align="center">
      <a href="README.md">English</a>
      | <a href="https://translate.google.com/translate?sl=en&amp;tl=zh-CN&amp;u=https%3A%2F%2Fgithub.com%2Ficip-cas%2FPPTAgent%2Fblob%2Fmain%2Fskills%2Fpptagent%2FREADME.md">简体中文</a>
      | <a href="https://translate.google.com/translate?sl=en&amp;tl=zh-TW&amp;u=https%3A%2F%2Fgithub.com%2Ficip-cas%2FPPTAgent%2Fblob%2Fmain%2Fskills%2Fpptagent%2FREADME.md">繁體中文</a>
    </div>
  </details>
</div>

<h1 align="center">
  <img src="../../resource/pptagent.png" width="300" alt="PPTAgent">
</h1>

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>✍️ Work with your agent</h3>
      <p>Use your existing Claude Code, Codex, or OpenCode model and research tools to turn a brief and source material into slides.</p>
    </td>
    <td width="33%" valign="top">
      <h3>🖼️ Review the result</h3>
      <p>Inspect rendered slides and the exported deck. Update the content and check the result before delivery.</p>
    </td>
    <td width="33%" valign="top">
      <h3>📊 Keep it editable</h3>
      <p>Get an editable PPTX and HTML slide sources that your agent can revise in follow-up requests.</p>
    </td>
  </tr>
</table>

> [!TIP]
> You can use a multimodal vision model as a multimodal reviewer and apply for an API token through the [Duanyan (端砚) Token Plan](https://discovery.intern-ai.org.cn/token-plan/home?tabIndex=1). We recommend `deepseek-v4-flash-vision` as the multimodal model. [Setup guide →](#visual-review)

<a id="quick-start"></a>

## Quick Start 🚀

**Requirements:** Linux (including WSL) or macOS, Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/), npm, and LibreOffice available as `libreoffice` on PATH. On macOS, the upstream converter also uses an installed Google Chrome.

<details>
<summary>Linux and macOS system dependencies</summary>

On Debian/Ubuntu, install npm and LibreOffice before continuing:

```bash
sudo apt-get install npm libreoffice-impress
```

On macOS, install Node.js, LibreOffice, and Google Chrome with Homebrew. The
runtime invokes LibreOffice through the `libreoffice` command, so expose the
Homebrew-provided `soffice` command under that name:

```bash
brew install node
brew install --cask libreoffice google-chrome
ln -sf "$(command -v soffice)" "$(brew --prefix)/bin/libreoffice"
```

</details>

From the repository root:

```bash
cd skills/pptagent
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m playwright install --with-deps chromium

# Choose claude, codex, gigacode, or opencode.
.venv/bin/python scripts/install.py --client gigacode
.venv/bin/python scripts/pptagent.py doctor
```

The installer prepares Node dependencies and registers this directory with the selected host. Keep the skill directory in place. Its tools use the local virtual environment, so your host does not need to activate it. `claude`, `codex`, and `gigacode` symlink this directory into the host's skills folder (`~/.claude/skills`, `~/.agents/skills`, and `~/.gigacode/skills` respectively); OpenCode installs a small routing entry at `~/.config/opencode/skills/pptagent`. Restart the client after registration.

### GigaCode Desktop

GigaCode Desktop reads skills from `~/.gigacode/skills` and follows `SKILL.md` like other Claude Code–compatible agents. Register with `--client gigacode`, then restart the client so it re-reads the skill list. Invoke the skill by asking the agent to use `pptagent` for your presentation request. The skill's tools run through the local virtual environment created in Quick Start; the host model and API provider stay in your normal GigaCode Desktop configuration. For a text-only host model, configure the [visual reviewer](#visual-review) first.

<a id="try-atria"></a>

## Try Atria Dawn Preview ✨

The example below connects **Atria Dawn Preview** to Claude Code or Codex to develop the content and author slide HTML. As a text-only model, Atria uses the [text workflow](#visual-review): set `mode: text` and configure a visual model to review the rendered slides.

> [!TIP]
> **Get a free Token Plan:** [Discovery](https://discovery-home.intern-ai.org.cn/) · [Atria](https://api.atria-asi.ai/). Create an API key in the [Atria console](https://api.atria-asi.ai/console/keys), then follow the example below. See the [official Atria integration guide](https://api.atria-asi.ai/docs#agents) for current service details.

### 1. Check your Atria API key

Set your key in the terminal you will use to launch your client, then send a minimal request:

```bash
export ATRIA_API_KEY="<your-atria-api-key>"

curl -X POST https://api.atria-asi.ai/v1/chat/completions \
  -H "Authorization: Bearer $ATRIA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Atria-Dawn-Preview",
    "messages": [{"role": "user", "content": "hi"}]
  }'
```

Check that the response contains an assistant reply in `choices[0].message.content`. This checks your key and Chat Completions access; client integration uses the other Atria interfaces below.

### 2. Configure your client and register the skill

Complete [Quick Start](#quick-start) first, then choose your client. Atria supports all three API formats:

| Client | API | Base URL to configure |
| --- | --- | --- |
| The `curl` example | Chat Completions | `https://api.atria-asi.ai/v1` |
| Claude Code | Messages | `https://api.atria-asi.ai` |
| Codex CLI | Responses | `https://api.atria-asi.ai/v1` |

Use the base URL shown for your client; it appends the API path itself. Keep the model ID exactly `Atria-Dawn-Preview`.

<details open>
<summary><strong>Claude Code · Messages API</strong></summary>

From the repository's `skills/pptagent/` directory, register the skill with Claude Code:

```bash
.venv/bin/python scripts/install.py --client claude
```

This creates `~/.claude/skills/pptagent`. Merge the following fields into `~/.claude/settings.json`, preserving your other settings:

```json
{
  "model": "Atria-Dawn-Preview",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.atria-asi.ai"
  }
}
```

In the terminal where you set `ATRIA_API_KEY`, map the key to Claude Code's gateway credential and launch a new session:

```bash
export ANTHROPIC_AUTH_TOKEN="$ATRIA_API_KEY"
mkdir -p ~/pptagent-demo
cd ~/pptagent-demo
claude
```

The client requests `/v1/messages`. Keep the API key in the launch environment. See [Claude Code settings](https://code.claude.com/docs/en/settings) and [Atria's Claude Code guide](https://api.atria-asi.ai/docs#claude-code).

</details>

<details>
<summary><strong>Codex CLI · Responses API</strong></summary>

From the repository's `skills/pptagent/` directory, register the skill with Codex if you have not already done so:

```bash
.venv/bin/python scripts/install.py --client codex
```

This creates `~/.agents/skills/pptagent`. Merge these settings into `~/.codex/config.toml`. Place `model` and `model_provider` at the top level, before any `[section]` headers; update existing entries instead of duplicating them:

```toml
model = "Atria-Dawn-Preview"
model_provider = "atria"

[model_providers.atria]
name = "Atria"
base_url = "https://api.atria-asi.ai/v1"
env_key = "ATRIA_API_KEY"
wire_api = "responses"
```

In the terminal where you set `ATRIA_API_KEY`, launch a new session:

```bash
mkdir -p ~/pptagent-demo
cd ~/pptagent-demo
codex
```

The client requests `/v1/responses` and reads the key from `ATRIA_API_KEY`. See [Codex custom model providers](https://developers.openai.com/codex/config-advanced/#custom-model-providers) and [Atria's Codex guide](https://api.atria-asi.ai/docs#codex).

</details>

### 3. Start a presentation task

**Set up text-mode visual review before generating the deck:** set `mode: text`, `visual.base_url`, and `visual.model` in the skill's `config.yaml`, and `VISUAL_API_KEY` in its `.env` or environment. Follow the [complete configuration example](#visual-review), then send the [presentation request below](#try-it).

The workflow is **Atria authors HTML → the skill renders images → the external visual model reviews them → Atria fixes reported issues**. The skill also renders and reviews the exported PPTX before final delivery. Its CLI calls the visual API directly and returns structured review results to the text model.

In Claude Code, explicitly invoke `/pptagent` with your request; in Codex, use `$pptagent`. If the skill is unavailable, check the registration path above and start a new client session. The skill's `.env` configures its own tools; set the host's Atria key in the launch terminal as shown above.

<a id="try-it"></a>

## Try It 💬

Open Claude Code or Codex in a separate task folder and ask:

```text
Use the pptagent skill to create a 6-slide presentation on our Q3 results
for a leadership review. Use the files in this folder as source material.
Render and visually review the deck before delivering the editable PPTX.
```

Then iterate in the same task:

```text
Shorten the opening to one slide and make the recommendations more concrete.
Keep the presentation at 6 slides, then rebuild and review the updated deck.
```

**Your deliverable is `answer.pptx`.** The task folder also keeps the HTML slide sources, local assets, rendered previews, and a final review report. Supported layouts are **16:9**, **4:3**, and **A1**.

### From brief to deck

| Step | What happens |
| --- | --- |
| **Write** | Your host agent develops the content and authors HTML slides. |
| **Review** | The host inspects slide renders, or an external visual model reviews them in text mode. |
| **Export** | The converter produces editable PowerPoint slides and checks format constraints. |
| **Deliver** | The exported deck is reviewed, and the CLI verifies that it matches the current sources. |

<a id="configuration"></a>

## Configuration ⚙️

If your host model can view images, start with the default multimodal mode. For text-only models, such as Atria or text models in the GLM family, use `mode: text` and configure an external visual model to review the slides. MinerU and search are optional additions for better PDF extraction and source gathering.

| Capability | When it helps | Where to configure it |
| --- | --- | --- |
| **Visual model** | Detect clipping, overlap, unreadable text, and inconsistent layouts in rendered slides. | The skill's `config.yaml` and `.env`. An external model is optional for a host that can inspect images, and required in text mode. |
| **MinerU — optional** | Extract text, tables, formulas, and figures from scanned or complex PDFs. | The host's document-conversion MCP server, using `MINERU_API_KEY` or `MINERU_API_URL`. |
| **Search — optional** | Find recent facts, supporting sources, and images for research-heavy presentations. | The host's existing search tools or a search MCP server, using Tavily or SerpAPI. |

Your authoring model, such as [Atria](#try-atria), stays in the host's configuration. The skill directly configures visual review; document parsing and retrieval are tools your host can call while preparing the slides.

<a id="visual-review"></a>

### Visual review

| Mode | Visual reviewer | Setup |
| --- | --- | --- |
| **Multimodal — default** | An image-capable host model using its image viewer | Uses the defaults; no local configuration needed. |
| **Text — for text-only models** | An external visual model | Set `mode: text` and configure an image-capable OpenAI-compatible endpoint and its API key. |

In text mode, the skill sends rendered slides to the visual API and returns review results to your host model. The optional document and search MCP servers below help the host gather source material.

For first-time text-mode setup, run these commands from `skills/pptagent/`. If you already have local configuration files, edit those instead of replacing them:

```bash
cp config.example.yaml config.yaml
cp .env.example .env
chmod 600 .env
```

You can use a multimodal vision model as a multimodal reviewer and apply for an API token through the [Duanyan (端砚) Token Plan](https://discovery.intern-ai.org.cn/token-plan/home?tabIndex=1). We recommend `deepseek-v4-flash-vision` as the multimodal model.

Edit `config.yaml` as follows, replacing `base_url` with the OpenAI-compatible API base URL shown in your Duanyan console:

```yaml
mode: text

visual:
  base_url: "<OpenAI-compatible API base URL from the Duanyan console>"
  model: "deepseek-v4-flash-vision"
  api_key_env: VISUAL_API_KEY
  timeout_seconds: 300

delivery:
  mode: strict
```

Set your Duanyan API key in the skill's `.env`:

```dotenv
VISUAL_API_KEY=<your-duanyan-api-key>
```

The Token Plan link opens the service console; it is not an API endpoint. Use the console's exact model ID if it differs from `deepseek-v4-flash-vision`. The reviewer must accept image inputs through an OpenAI-compatible Chat Completions API. Set `base_url` to the API prefix, including `/v1` when required; the skill appends `/chat/completions`. `api_key_env` names the environment variable containing the key. Existing environment variables take precedence over `.env`.

Run `.venv/bin/python scripts/pptagent.py doctor` from the skill directory to check local dependencies and required settings. It does not make an API request; the first `review-slides` call checks the actual endpoint. See the [text-mode guide](references/text.md) for the review response format.

### OpenCode setup

Complete [Quick Start](#quick-start), using `--client opencode`. Confirm that
OpenCode discovers the skill:

```bash
opencode debug skill
```

The host model and API provider remain in your normal OpenCode configuration.
For a text-only host, first configure the visual endpoint above, then initialize
a separate presentation workspace:

```bash
.venv/bin/python scripts/pptagent.py init \
  --workspace /absolute/path/to/pptagent-demo \
  --slides 6
```

Create `opencode.json` in that workspace. Replace the three absolute paths:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "pptagent-visual": {
      "type": "local",
      "command": [
        "/absolute/path/to/PPTAgent/skills/pptagent/.venv/bin/python",
        "/absolute/path/to/PPTAgent/skills/pptagent/scripts/visual_mcp.py",
        "--workspace",
        "/absolute/path/to/pptagent-demo"
      ],
      "enabled": true,
      "timeout": 1800000
    }
  }
}
```

Start OpenCode in the workspace and verify the server:

```bash
cd /absolute/path/to/pptagent-demo
opencode mcp list
opencode
```

Ask OpenCode to use the `pptagent` skill. During generation it should call
`review_slides`, fix reported issues, build `answer.pptx`, call `review_deck`,
and run `finalize`. The MCP is a local stdio adapter; it does not open a network
port. It reads `config.yaml` and `.env` from the Skill directory. `--config` and
`--env` can select other files when needed.

OpenCode documentation: [Skills](https://opencode.ai/docs/skills/) and
[MCP servers](https://opencode.ai/docs/mcp-servers/).

### MinerU for source documents · optional

MinerU is useful when a presentation starts from papers, scanned reports, or PDFs with complex tables and equations. It improves the material available to the authoring model. For a short brief or existing Markdown, you can use the host's normal file-reading tools.

The installed `pptagent` package includes the `deeppresenter.tools.any2markdown` MCP server. Its `convert_to_markdown` tool uses MinerU for PDFs when configured:

| Setting | Use |
| --- | --- |
| `MINERU_API_KEY` | Hosted MinerU API token; obtain one from [MinerU](https://mineru.net/apiManage/docs). PDF files are uploaded to that service for parsing. |
| `MINERU_API_URL` | Optional self-hosted parsing endpoint. The adapter posts a multipart `pdf` field and expects a ZIP of parsed files; use an endpoint matching that contract. |

Choose one: the hosted API key takes precedence if both are set. Without either setting, the conversion tool uses its standard MarkItDown fallback. You can also parse a document through MinerU separately and place the resulting Markdown and images in your task folder.

After connecting the tool, ask: “Convert `report.pdf` into an empty `research/report/` folder, then use its Markdown and figures as sources for the presentation.” Copy figures used in slides into the task's `assets/` directory.

### Research and retrieval · optional

Use your host's existing search tools if they already meet your needs. For additional web and image search, the installed package includes `deeppresenter.tools.search`, which exposes `search_web`, `search_images`, `fetch_url`, and `download_file`.

| Provider | Setting | Use |
| --- | --- | --- |
| [Tavily](https://www.tavily.com/) | `TAVILY_API_KEY` | Web results and images for gathering presentation sources. |
| [SerpAPI](https://serpapi.com/) | `SERPAPI_KEY` | Google web and image search. |

Configure one provider. SerpAPI takes precedence if both keys are present; without either key, this server provides URL fetching and downloading but does not register web/image search. Your host model plans queries and synthesizes the results, so there is no separate `search.model` setting in the skill.

For example: “Find recent primary sources for this topic, record their URLs and dates, and use them to support the presentation's claims.” Search access through a custom model provider depends on the host's available tools; configuring Atria alone does not add a search service.

<details>
<summary><strong>Connect the optional document and search tools · Claude Code / Codex</strong></summary>

These servers use the Python environment installed in [Quick Start](#quick-start). Add only the servers you need. In your presentation task folder, export the workspace and the keys for your chosen services before launching the host:

```bash
export WORKSPACE="$PWD"
export MINERU_API_KEY="<your-mineru-api-key>"
export TAVILY_API_KEY="<your-tavily-api-key>"
```

Update `WORKSPACE` when switching task folders. These MCP servers read their own environment; putting their keys only in the skill's `.env` does not configure them.

**Claude Code:** merge the following into the task folder's `.mcp.json`. Replace the Python paths with the absolute path to your skill's interpreter. Claude Code expands the `${...}` environment references:

```json
{
  "mcpServers": {
    "pptagent-docs": {
      "type": "stdio",
      "command": "/absolute/path/to/PPTAgent/skills/pptagent/.venv/bin/python",
      "args": ["-m", "deeppresenter.tools.any2markdown"],
      "env": {
        "WORKSPACE": "${WORKSPACE}",
        "MINERU_API_KEY": "${MINERU_API_KEY}"
      }
    },
    "pptagent-search": {
      "type": "stdio",
      "command": "/absolute/path/to/PPTAgent/skills/pptagent/.venv/bin/python",
      "args": ["-m", "deeppresenter.tools.search"],
      "env": {
        "WORKSPACE": "${WORKSPACE}",
        "TAVILY_API_KEY": "${TAVILY_API_KEY}"
      }
    }
  }
}
```

**Codex:** add these server tables to `~/.codex/config.toml`, replacing the Python paths. `env_vars` forwards values from the environment in which you launch Codex:

```toml
[mcp_servers.pptagent-docs]
command = "/absolute/path/to/PPTAgent/skills/pptagent/.venv/bin/python"
args = ["-m", "deeppresenter.tools.any2markdown"]
env_vars = ["WORKSPACE", "MINERU_API_KEY"]
startup_timeout_sec = 30
tool_timeout_sec = 1800

[mcp_servers.pptagent-search]
command = "/absolute/path/to/PPTAgent/skills/pptagent/.venv/bin/python"
args = ["-m", "deeppresenter.tools.search"]
env_vars = ["WORKSPACE", "TAVILY_API_KEY"]
startup_timeout_sec = 30
tool_timeout_sec = 120
```

For self-hosted MinerU or SerpAPI, replace the corresponding key name in both the exports and the MCP configuration with `MINERU_API_URL` or `SERPAPI_KEY`. For large PDFs in Claude Code, you can extend the tool timeout before launch with `export MCP_TOOL_TIMEOUT=1800000` (milliseconds).

Start a new host session and check that the tools appear in `/mcp`. Confirm document conversion on a small file or search on a simple query before using a large source set. See the [Claude Code MCP guide](https://code.claude.com/docs/en/mcp) and [Codex MCP guide](https://developers.openai.com/codex/mcp/) for host configuration details.

</details>

### Delivery checks

Strict delivery is the default: the deck must pass review and match the current sources. If the user explicitly accepts an incomplete draft, `delivery.mode: best-effort` permits delivery with the failed checks disclosed. Source changes still require a fresh build.

## More Details 📖

- [Skill instructions](SKILL.md): the workflow followed by your host agent.
- [Task and source contract](references/task-contract.md): workspace layout and authoring guidance.
- [Configuration example](config.example.yaml): available settings.
- [PPTAgent project](../../README.md): current releases, installation, and project history.

<details>
<summary>Installation and existing task notes</summary>

The full skill is this `skills/pptagent/` directory. Python and Node dependencies are declared locally; the installer uses `npm ci`. Pass `--skip-runtime` only when Node dependencies have already been installed.

Existing tasks created with the earlier standalone scripts need fresh renders, reviews, and a build to establish the current evidence format. Use `task.json` for the page count, aspect ratio, and language, and the CLI's `scaffold` command for starter slides. Run `scripts/pptagent.py --help` with the skill's Python interpreter to inspect the available commands.

</details>

---

<p align="center">
  Part of <a href="../../README.md">PPTAgent</a> · <a href="LICENSE">MIT License</a>
</p>
