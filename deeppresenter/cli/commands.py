import asyncio
import json
import os
import platform
import shutil
import signal
import sys
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from deeppresenter.main import AgentLoop, InputRequest
from deeppresenter.utils.config import DeepPresenterConfig

from .common import (
    CACHE_DIR,
    CONFIG_DIR,
    CONFIG_FILE,
    MCP_FILE,
    PACKAGE_DIR,
    REQUIRED_LLM_KEYS,
    console,
    version,
)
from .dependency import (
    check_docker_image,
    check_npm_dependencies,
    check_playwright_browsers,
    check_poppler,
    ensure_llamacpp,
    ensure_supported_platform,
)
from .model import (
    LOCAL_BASE_URL,
    LOCAL_MODEL,
    has_complete_model_config,
    is_local_model_server_running,
    is_onboarded,
    prompt_llm_config,
    setup_inference,
    uses_local_model,
)


def onboard():
    """Configure DeepPresenter (config.yaml and mcp.json)."""
    ensure_supported_platform()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    existing_config = None
    if is_onboarded():
        console.print("[yellow]Configuration already exists.[/yellow]")
        console.print(f"[dim]Config file: {CONFIG_FILE}[/dim]")
        console.print(f"[dim]{CONFIG_FILE.read_text(encoding='utf-8').rstrip()}[/dim]")

        if not Confirm.ask(
            "\nDo you want to reconfigure (existing config will be backed up)?",
            default=False,
        ):
            console.print("[green]Keeping existing configuration.[/green]")
            return

        with open(CONFIG_FILE) as f:
            existing_config = yaml.safe_load(f)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = CONFIG_DIR / f"backup_{timestamp}"
        backup_dir.mkdir(exist_ok=True)
        shutil.copy(CONFIG_FILE, backup_dir / "config.yaml")
        shutil.copy(MCP_FILE, backup_dir / "mcp.json")
        console.print(f"[green]✓[/green] Backed up to {backup_dir}")

    console.print(
        Panel.fit(
            f"[bold green]Welcome to DeepPresenter v{version}![/bold green]\n"
            "Let's configure your environment.",
            title="Onboarding",
        )
    )

    check_docker_image()
    check_playwright_browsers()
    check_npm_dependencies()
    if not check_poppler():
        sys.exit(1)

    local_config = Path.cwd() / "deeppresenter" / "config.yaml"
    local_mcp = Path.cwd() / "deeppresenter" / "mcp.json"

    config_data = None
    mcp_data = None
    local_model_pid = None

    if local_config.exists() and local_mcp.exists():
        console.print("\n[cyan]Found existing config in current directory:[/cyan]")
        console.print(f"  • {local_config}")
        console.print(f"  • {local_mcp}")

        if Confirm.ask("\nDo you want to reuse these configurations?", default=True):
            console.print("[green]✓[/green] Reusing existing configurations")
            with open(local_config) as f:
                config_data = yaml.safe_load(f)
            with open(local_mcp) as f:
                mcp_data = json.load(f)

    if config_data is None or mcp_data is None:
        with open(PACKAGE_DIR / "config.yaml.example") as f:
            config_data = yaml.safe_load(f)
        with open(PACKAGE_DIR / "mcp.json.example") as f:
            mcp_data = json.load(f)

        use_local_model = False
        if not has_complete_model_config(existing_config):
            console.print("\n[bold yellow]Quick Setup[/bold yellow]")
            use_local_model = Confirm.ask(
                f"Configure local model service with {LOCAL_MODEL}?",
                default=True,
            )
            if use_local_model and not ensure_llamacpp():
                console.print(
                    "[bold red]✗[/bold red] Failed to prepare local model runtime. Please try starting it manually with llama-server, or configure another API instead."
                )
                sys.exit(1)
            if use_local_model:
                try:
                    local_model_pid = setup_inference()
                except Exception as e:
                    console.print(
                        f"[bold red]✗[/bold red] Failed to start local model service. Please try running `llama-server -hf {LOCAL_MODEL} -c 100000 --port 7811 --log-disable --reasoning-budget 0` manually, or configure another API instead."
                    )
                    console.print(f"[dim]{type(e).__name__}: {e!r}[/dim]")
                    sys.exit(1)

        last_config = None
        console.print("\n[bold yellow]Required LLM Configurations[/bold yellow]")

        if use_local_model:
            local_cfg = {
                "base_url": LOCAL_BASE_URL,
                "model": LOCAL_MODEL,
                "api_key": "",
            }
            for key in REQUIRED_LLM_KEYS:
                display_name = " ".join([part.capitalize() for part in key.split("_")])
                config_data[key] = dict(local_cfg)
                last_config = (display_name, dict(local_cfg))
                console.print(
                    f"[green]✓[/green] {display_name}: {LOCAL_MODEL} @ {LOCAL_BASE_URL}"
                )
            config_data["vision_model"] = None
        else:
            research_agent = prompt_llm_config(
                "Research Agent",
                existing=existing_config.get("research_agent")
                if existing_config
                else None,
                previous_config=last_config,
            )
            config_data["research_agent"] = research_agent
            last_config = ("Research Agent", research_agent)

            design_agent = prompt_llm_config(
                "Design Agent",
                existing=existing_config.get("design_agent")
                if existing_config
                else None,
                previous_config=last_config,
            )
            config_data["design_agent"] = design_agent
            last_config = ("Design Agent", design_agent)

            long_context = prompt_llm_config(
                "Long Context Model",
                existing=existing_config.get("long_context_model")
                if existing_config
                else None,
                previous_config=last_config,
            )
            config_data["long_context_model"] = long_context
            last_config = ("Long Context Model", long_context)

            vision_model = prompt_llm_config(
                "Vision Model",
                optional=True,
                existing=existing_config.get("vision_model")
                if existing_config
                else None,
                previous_config=last_config,
                reuse_previous_default=False,
            )
            config_data["vision_model"] = vision_model
            last_config = ("Vision Model", vision_model)

        console.print("\n[bold yellow]Optional Configurations[/bold yellow]")
        t2i_config = prompt_llm_config(
            "Text-to-Image Model",
            optional=True,
            existing=existing_config.get("t2i_model") if existing_config else None,
            previous_config=last_config,
            reuse_previous_default=False,
        )
        if t2i_config:
            config_data["t2i_model"] = t2i_config

        console.print("\n[bold cyan]MCP Configuration[/bold cyan]")
        if Confirm.ask("Configure Tavily API key for web search?", default=False):
            tavily_key = Prompt.ask("Tavily API key", password=True)
            for server in mcp_data:
                if server.get("name") == "search":
                    server["env"]["TAVILY_API_KEY"] = tavily_key
                    break
            else:
                raise ValueError("search server not found in mcp.json")

        if Confirm.ask("Configure MinerU API key for PDF parsing?", default=False):
            mineru_key = Prompt.ask("MinerU API key", password=True)
            for server in mcp_data:
                if server.get("name") == "any2markdown":
                    server["env"]["MINERU_API_KEY"] = mineru_key
                    break
            else:
                raise ValueError("any2markdown server not found in mcp.json")

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

    with open(MCP_FILE, "w") as f:
        json.dump(mcp_data, f, indent=2, ensure_ascii=False)

    console.print(f"\n[bold green]✓[/bold green] Configuration saved to {CONFIG_DIR}")

    console.print("\n[bold cyan]Validating LLM configurations...[/bold cyan]")
    try:
        config = DeepPresenterConfig.load_from_file(str(CONFIG_FILE))
        if uses_local_model(config):
            pid = setup_inference()
            if local_model_pid is None:
                local_model_pid = pid
        asyncio.run(config.validate_llms())
        console.print("[bold green]✓[/bold green] All LLMs validated successfully!")
    except Exception as e:
        console.print(f"[bold red]✗[/bold red] Validation failed: {e}")
        console.print(f"[dim]{type(e).__name__}: {e!r}[/dim]")
        console.print("Please check your configuration and try again.")
        sys.exit(1)
    finally:
        if local_model_pid is not None:
            try:
                os.kill(local_model_pid, signal.SIGTERM)
            except OSError:
                pass

    package_config = PACKAGE_DIR / "config.yaml"
    package_mcp = PACKAGE_DIR / "mcp.json"
    saved_local_files: list[Path] = []

    if not package_config.exists():
        with open(package_config, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
        saved_local_files.append(package_config)

    if not package_mcp.exists():
        with open(package_mcp, "w") as f:
            json.dump(mcp_data, f, indent=2, ensure_ascii=False)
        saved_local_files.append(package_mcp)

    if saved_local_files:
        console.print("\n[bold green]✓[/bold green] Saved local configuration files:")
        for path in saved_local_files:
            console.print(f"  • {path}")


def generate(
    prompt: Annotated[str, typer.Argument(help="Presentation prompt/instruction")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output file path (e.g., output.pptx)"),
    ],
    files: Annotated[
        list[Path], typer.Option("--file", "-f", help="Attachment files")
    ] = None,
    pages: Annotated[
        str, typer.Option("--pages", "-p", help="Number of pages (e.g., '8', '5-10')")
    ] = None,
    aspect_ratio: Annotated[
        str,
        typer.Option("--aspect", "-a", help="Aspect ratio (16:9, 4:3, A1, A3, A2, A4)"),
    ] = "16:9",
    language: Annotated[
        str, typer.Option("--lang", "-l", help="Language (en/zh)")
    ] = "en",
):
    """Generate a presentation from prompt and optional files."""
    ensure_supported_platform()
    if not is_onboarded():
        console.print(
            "[bold red]Error:[/bold red] Please run 'deeppresenter onboard' (or 'pptagent onboard') first"
        )
        sys.exit(1)

    attachments = []
    if files:
        for f in files:
            if not f.exists():
                console.print(f"[bold red]Error:[/bold red] File not found: {f}")
                sys.exit(1)
            attachments.append(str(f.resolve()))

    request = InputRequest(
        instruction=prompt,
        attachments=attachments,
        num_pages=pages,
        powerpoint_type=aspect_ratio,
    )

    config = DeepPresenterConfig.load_from_file(str(CONFIG_FILE))
    config.mcp_config_file = str(MCP_FILE)

    local_model_pid = None

    async def run():
        if uses_local_model(config):
            nonlocal local_model_pid
            local_model_pid = setup_inference()
        session_id = str(uuid.uuid4())[:8]

        loop = AgentLoop(
            config=config,
            session_id=session_id,
            workspace=None,
            language=language,
        )

        console.print(
            Panel.fit(
                f"[bold]Prompt:[/bold] {prompt}\n"
                f"[bold]Attachments:[/bold] {len(attachments)}\n"
                f"[bold]Workspace:[/bold] {loop.workspace}\n"
                f"[bold]Version:[/bold] {version}",
                title="Generation Task",
            )
        )

        try:
            async for msg in loop.run(request):
                if isinstance(msg, (str, Path)):
                    generated_file = Path(msg)
                    output_path = Path(output).resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(generated_file, output_path)
                    console.print(
                        f"\n[bold green]✓[/bold green] Generated: {generated_file}"
                    )
                    console.print(
                        f"[bold green]✓[/bold green] Copied to: {output_path}"
                    )
                    return str(output_path)
        except Exception as e:
            console.print(f"[bold red]✗[/bold red] Generation failed: {e}")
            raise

    try:
        result = asyncio.run(run())
        console.print(f"\n[bold green]Success![/bold green] Output: {result}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Failed:[/bold red] {e}")
        console.print("\n[dim]Traceback:[/dim]")
        console.print(traceback.format_exc())
        sys.exit(1)
    finally:
        if local_model_pid is not None:
            try:
                os.kill(local_model_pid, signal.SIGTERM)
            except OSError:
                pass


def config():
    """Show current configuration."""
    if not is_onboarded():
        console.print(
            "[bold red]Not configured.[/bold red] Run 'deeppresenter onboard' (or 'pptagent onboard') first."
        )
        return

    console.print(f"\n[bold]Config file:[/bold] {CONFIG_FILE}")
    console.print(f"[bold]MCP file:[/bold] {MCP_FILE}")

    with open(CONFIG_FILE) as f:
        config_data = yaml.safe_load(f)

    console.print("\n[bold cyan]LLM Configuration:[/bold cyan]")
    for key in [
        "research_agent",
        "design_agent",
        "long_context_model",
        "vision_model",
        "t2i_model",
    ]:
        if key in config_data:
            llm = config_data[key]
            if isinstance(llm, dict):
                console.print(f"  {key}: {llm.get('model', 'N/A')}")


def clean():
    """Remove DeepPresenter user config and cache directories."""
    targets = [CONFIG_DIR, CACHE_DIR]
    console.print("[bold yellow]This will remove:[/bold yellow]")
    for path in targets:
        console.print(f"  • {path}")

    if not Confirm.ask("Proceed with clean?", default=False):
        return

    removed: list[Path] = []

    for path in targets:
        if path.exists():
            shutil.rmtree(path)
            removed.append(path)

    if removed:
        console.print("[bold green]✓[/bold green] Removed:")
        for path in removed:
            console.print(f"  • {path}")


def _find_local_model_pid() -> int | None:
    """Find PID of running llama-server or sglang via ps."""
    import subprocess as sp

    try:
        out = sp.check_output(["ps", "aux"], text=True)
        for line in out.splitlines():
            if ("llama-server" in line or "sglang" in line) and "grep" not in line:
                return int(line.split()[1])
    except Exception:
        pass
    return None


def serve():
    """Start local model service and show where it is available."""
    ensure_supported_platform()
    ui_url = LOCAL_BASE_URL.rsplit("/v1", 1)[0]

    if is_local_model_server_running():
        pid = _find_local_model_pid()
        pid_str = f" (PID: {pid})" if pid else ""
        console.print(
            f"[green]✓[/green] Local model service is already running{pid_str} at {ui_url}"
        )
        return

    if platform.system().lower() == "darwin" and not ensure_llamacpp():
        console.print(
            "[bold red]✗[/bold red] Failed to prepare local model runtime. Please try starting it manually with llama-server, or configure another API instead."
        )
        sys.exit(1)

    try:
        pid = setup_inference()
    except Exception as e:
        console.print(
            f"[bold red]✗[/bold red] Failed to start local model service. Please try running `llama-server -hf {LOCAL_MODEL} -c 100000 --port 7811 --log-disable --reasoning-budget 0` manually."
        )
        console.print(f"[dim]{e}[/dim]")
        sys.exit(1)

    pid = pid or _find_local_model_pid()
    pid_str = f" (PID: {pid})" if pid else ""
    console.print(f"[green]✓[/green] Local model service is ready{pid_str} at {ui_url}")
