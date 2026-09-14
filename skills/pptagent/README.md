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

<div align="center">
  <img src="../../resource/pptagent-logo.jpg" width="240px" alt="PPTAgent">
  <h1>PPTAgent Skill</h1>
  <p><strong>Turn your brief into an editable PowerPoint deck with Claude Code or Codex.</strong></p>
  <p>Your agent authors the slides. PPTAgent renders, exports, and checks the result.</p>
  <p>
    <a href="#quick-start">🚀 Quick Start</a> ·
    <a href="#try-atria">✨ Try Atria</a> ·
    <a href="#try-it">💬 Try It</a> ·
    <a href="#configuration">⚙️ Configuration</a> ·
    <a href="../../README.md">🏠 Project Home</a>
  </p>
</div>

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>✍️ Work with your agent</h3>
      <p>Use your existing Claude Code or Codex model and research tools to turn a brief and source material into slides.</p>
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
> **The default mode uses your host agent's image viewer.** It works with your existing host authentication; a separate visual-model API is optional for text-only hosts.

<a id="quick-start"></a>

## Quick Start 🚀

**Requirements:** Linux (including WSL) or macOS, Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/), npm, and LibreOffice available as `libreoffice` on PATH. On macOS, the upstream converter also uses an installed Google Chrome.

<details>
<summary>Linux system dependencies</summary>

On Debian/Ubuntu, install npm and LibreOffice before continuing:

```bash
sudo apt-get install npm libreoffice-impress
```

</details>

From the repository root:

```bash
cd skills/pptagent
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m playwright install --with-deps chromium

# Register with Codex; use --client claude for Claude Code.
.venv/bin/python scripts/install.py --client codex
.venv/bin/python scripts/pptagent.py doctor
```

The installer prepares Node dependencies and registers this directory with the selected host. Keep the skill directory in place. Its tools use the local virtual environment, so your host does not need to activate it.

<a id="try-atria"></a>

## Try Atria Dawn Preview ✨

Use **Atria Dawn Preview** as your coding agent's model to develop the content and author slide HTML with PPTAgent Skill.

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

**Set up visual review before generating the deck.** Atria's published integration guide does not specify image-input support. For this example, configure [text mode](#configuration) with a separate image-capable reviewer. Atria handles authoring through your host; the skill's `visual.*` settings select the reviewer. Then send the [presentation request below](#try-it).

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

| Mode | Visual reviewer | Setup |
| --- | --- | --- |
| **Multimodal — default** | Claude Code or Codex's image viewer | Uses the defaults; no local configuration needed. |
| **Text** | An external visual model | Configure an OpenAI-compatible endpoint and its API key. |

For text mode, run these commands from the skill directory:

```bash
cp config.example.yaml config.yaml
cp .env.example .env
chmod 600 .env
```

Set `mode: text`, fill `visual.base_url` (including `/v1` when required) and `visual.model`, then set `VISUAL_API_KEY` in `.env` or the environment. See the [text-mode guide](references/text.md) for details. Search uses the host's available tools.

Strict delivery is the default: the deck must pass review and match the current sources. If the user explicitly accepts an incomplete draft, `delivery.mode: best-effort` permits delivery with the failed checks disclosed. Source changes still require a fresh build.

## More Details 📖

- [Skill instructions](SKILL.md): the workflow followed by your host agent.
- [Task and source contract](references/task-contract.md): workspace layout and authoring guidance.
- [Configuration example](config.example.yaml): available settings.
- [PPTAgent project](../../README.md): the CLI, server workflows, research, and examples.

<details>
<summary>Installation and existing task notes</summary>

The full skill is this `skills/pptagent/` directory. Python and Node dependencies are declared locally; the installer uses `npm ci`. Pass `--skip-runtime` only when Node dependencies have already been installed.

Existing tasks created with the earlier standalone scripts need fresh renders, reviews, and a build to establish the current evidence format. Use `task.json` for the page count, aspect ratio, and language, and the CLI's `scaffold` command for starter slides. Run `scripts/pptagent.py --help` with the skill's Python interpreter to inspect the available commands.

</details>

---

<p align="center">
  Part of <a href="../../README.md">PPTAgent</a> · <a href="LICENSE">MIT License</a>
</p>
