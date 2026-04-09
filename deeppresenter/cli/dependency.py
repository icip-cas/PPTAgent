"""Dependency management: system packages, Docker, Node, Playwright, etc."""

import os
import platform
import shutil
import subprocess
import sys

from rich.prompt import Confirm

import deeppresenter.utils.webview as webview

from .common import LOCAL_LID_MODEL, console, run_streaming_command

SANDBOX_IMAGE = "deeppresenter-sandbox"
SANDBOX_IMAGE_SOURCE = "forceless/deeppresenter-sandbox"
SANDBOX_IMAGE_MIRROR = "docker.1ms.run/forceless/deeppresenter-sandbox"


def ensure_supported_platform() -> None:
    """Exit early on unsupported platforms."""
    if platform.system().lower() == "windows":
        console.print(
            "[bold red]✗[/bold red] Windows is not supported. Please use WSL instead."
        )
        raise SystemExit(1)


def ensure_homebrew() -> bool:
    """Ensure Homebrew is installed on macOS."""
    if shutil.which("brew") is not None:
        console.print("[green]✓[/green] Homebrew already installed")
        return True

    console.print("[yellow]Homebrew not found, installing...[/yellow]")
    if not Confirm.ask(
        "Install Homebrew? (required for other dependencies)", default=True
    ):
        return False

    console.print("[cyan]Running Homebrew installer (may require password)...[/cyan]")
    return (
        run_streaming_command(
            [
                "/bin/bash",
                "-c",
                "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)",
            ],
            success_message="[green]✓[/green] Homebrew installed successfully",
            failure_message="[bold red]✗[/bold red] Homebrew installation failed",
        )
        and shutil.which("brew") is not None
    )


def ensure_llamacpp() -> bool:
    """Ensure llama.cpp is available for local model service."""
    if shutil.which("llama-server") is not None:
        console.print("[green]✓[/green] llama.cpp already installed")
    else:
        if not ensure_homebrew():
            console.print(
                "[bold red]✗[/bold red] Homebrew is required for local model setup"
            )
            return False

        console.print("[cyan]Installing llama.cpp with Homebrew...[/cyan]")
        if not run_streaming_command(
            ["brew", "install", "llama.cpp"],
            success_message="[green]✓[/green] llama.cpp installed",
            failure_message="[bold red]✗[/bold red] Failed to install llama.cpp",
        ):
            return False

    modelscope_cmd = (
        ["modelscope", "download", LOCAL_LID_MODEL]
        if shutil.which("modelscope") is not None
        else [sys.executable, "-m", "modelscope", "download", LOCAL_LID_MODEL]
    )

    console.print(f"[cyan]Downloading {LOCAL_LID_MODEL} with ModelScope...[/cyan]")
    return run_streaming_command(
        modelscope_cmd,
        success_message=f"[green]✓[/green] {LOCAL_LID_MODEL} downloaded",
        failure_message=f"[bold red]✗[/bold red] Failed to download {LOCAL_LID_MODEL}",
    )


def ensure_docker() -> bool:
    if shutil.which("docker") is not None:
        console.print("[green]✓[/green] Docker already installed")
        return True

    console.print("[yellow]Docker not found, installing via Homebrew...[/yellow]")

    if not ensure_homebrew():
        return False

    try:
        success = run_streaming_command(
            ["brew", "install", "--cask", "docker"],
            success_message="[green]✓[/green] Docker installed",
            failure_message="[bold red]✗[/bold red] Failed to install Docker",
        )
        if success:
            console.print(
                "[yellow]Note: You may need to start Docker Desktop manually[/yellow]"
            )
        return success
    except FileNotFoundError:
        console.print(
            "[bold red]✗[/bold red] brew command not found after installation"
        )
        return False


def ensure_node() -> bool:
    """Ensure Node.js/npm is installed on macOS."""
    if shutil.which("npm") is not None:
        console.print("[green]✓[/green] Node.js/npm already installed")
        return True

    console.print("[yellow]Node.js not found, installing via Homebrew...[/yellow]")
    if not Confirm.ask("Install Node.js? (required for PPT generation)", default=True):
        console.print(
            "[bold red]✗[/bold red] Node.js is required for DeepPresenter to work"
        )
        return False

    if not ensure_homebrew():
        return False

    try:
        return run_streaming_command(
            ["brew", "install", "node"],
            success_message="[green]✓[/green] Node.js installed",
            failure_message="[bold red]✗[/bold red] Failed to install Node.js",
        )
    except FileNotFoundError:
        console.print(
            "[bold red]✗[/bold red] brew command not found after installation"
        )
        return False


def check_poppler() -> bool:
    """Check if poppler is installed and try to install it when possible."""
    if shutil.which("pdfinfo") is not None:
        console.print("[green]✓[/green] poppler already installed")
        return True

    system = platform.system().lower()
    if system == "darwin":
        console.print("[yellow]poppler not found, installing via Homebrew...[/yellow]")
        if not ensure_homebrew():
            return False

        try:
            return run_streaming_command(
                ["brew", "install", "poppler"],
                success_message="[green]✓[/green] poppler installed",
                failure_message="[bold red]✗[/bold red] Failed to install poppler",
            )
        except FileNotFoundError:
            console.print(
                "[bold red]✗[/bold red] brew command not found after installation"
            )
            return False

    if system == "linux":
        console.print(
            "[bold red]✗[/bold red] poppler is required. Please install it with `apt install poppler-utils` and rerun onboarding."
        )
        return False

    console.print(
        "[bold red]✗[/bold red] poppler is required. Please install it manually and rerun onboarding."
    )
    return False


def check_playwright_browsers():
    """Ensure Playwright CLI and Chromium browser are installed."""
    console.print("\n[bold cyan]Checking Playwright browsers...[/bold cyan]")

    try:
        if platform.system().lower() == "darwin" and shutil.which("npm") is None:
            if not ensure_node():
                console.print(
                    "[bold red]✗[/bold red] Node.js is required but not available"
                )
                return False

        if shutil.which("playwright") is None:
            console.print(
                "[yellow]⚠[/yellow] Playwright CLI not found, installing globally..."
            )
            if not run_streaming_command(
                ["npm", "--verbose", "install", "-g", "playwright"],
                success_message="[green]✓[/green] Playwright CLI installed",
                failure_message="[yellow]⚠[/yellow] Failed to install Playwright CLI",
            ):
                return False

        return run_streaming_command(
            ["playwright", "install", "chromium"],
            success_message="[green]✓[/green] Playwright browsers installed",
            failure_message="[yellow]⚠[/yellow] Failed to install Playwright browsers",
        )
    except FileNotFoundError:
        console.print(
            "[yellow]⚠[/yellow] Playwright not found. Installing browsers may fail."
        )
        return False
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow] Error installing Playwright browsers: {e}")
        return False


def check_npm_dependencies():
    """Check required html2pptx npm dependencies."""
    console.print("\n[bold cyan]Checking Node.js dependencies...[/bold cyan]")

    if platform.system().lower() == "darwin" and shutil.which("npm") is None:
        if not ensure_node():
            console.print(
                "[bold red]✗[/bold red] Node.js is required but not available"
            )
            return False

    cache_nm = webview._CACHE_NODE_MODULES
    required = webview._REQUIRED_PACKAGES

    if all((cache_nm / pkg).exists() for pkg in required):
        console.print(f"[green]✓[/green] Node.js dependencies found at {cache_nm}")
        return True

    cache_dir = cache_nm.parent
    cache_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        "[yellow]⚠[/yellow] html2pptx Node dependencies missing, installing..."
    )

    try:
        success = run_streaming_command(
            ["npm", "install", "--prefix", str(cache_dir), *required],
            failure_message="[yellow]⚠[/yellow] Failed to install Node.js dependencies",
        )
    except FileNotFoundError:
        console.print("[yellow]⚠[/yellow] npm not found. Please install Node.js first.")
        return False

    if success and all((cache_nm / pkg).exists() for pkg in required):
        console.print("[green]✓[/green] Node.js dependencies installed")
        return True

    console.print("[yellow]Please install dependencies manually:[/yellow]")
    console.print(f"  cd {cache_dir} && npm install {' '.join(required)}")
    return False


def check_docker_image():
    """Check if deeppresenter-sandbox image exists, pull if not."""
    if os.getenv("DEEPPRESENTER_SANDBOX_BACKEND", "").lower() in {
        "kubernetes",
        "k8s",
        "kodo",
    }:
        console.print(
            "[green]✓[/green] Kubernetes sandbox backend enabled, skipping local Docker sandbox image check"
        )
        return True

    console.print("\n[bold cyan]Checking Docker sandbox image...[/bold cyan]")

    if shutil.which("docker") is None:
        if not ensure_docker():
            console.print(
                "[yellow]⚠[/yellow] Docker not available. Please install Docker first."
            )
            return False

    try:
        result = subprocess.run(
            ["docker", "images", "-q", SANDBOX_IMAGE],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0 and result.stdout.strip():
            console.print(f"[green]✓[/green] Docker image {SANDBOX_IMAGE} found")
            return True

        source_image = (
            SANDBOX_IMAGE_MIRROR
            if Confirm.ask(
                "Use mirror source (docker.1ms.run) for sandbox image?", default=True
            )
            else SANDBOX_IMAGE_SOURCE
        )

        console.print(f"[cyan]Pulling Docker image from {source_image}...[/cyan]")
        if not run_streaming_command(
            ["docker", "pull", source_image],
            success_message=f"[green]✓[/green] Pulled Docker image {source_image}",
            failure_message=f"[yellow]⚠[/yellow] Failed to pull Docker image {source_image}",
        ):
            console.print(
                "[yellow]Docker image not found. Please build it locally from source.[/yellow]"
            )
            console.print(f"[yellow]Pull command:[/yellow] docker pull {source_image}")
            console.print(
                f"[yellow]Build command:[/yellow] docker build -t {SANDBOX_IMAGE} -f deeppresenter/docker/SandBox.Dockerfile ."
            )
            console.print(
                f"[yellow]Tag command:[/yellow] docker tag {source_image} {SANDBOX_IMAGE}"
            )
            return False

        return run_streaming_command(
            ["docker", "tag", source_image, SANDBOX_IMAGE],
            success_message=f"[green]✓[/green] Tagged Docker image as {SANDBOX_IMAGE}",
            failure_message=f"[yellow]⚠[/yellow] Failed to tag Docker image as {SANDBOX_IMAGE}",
        )

    except FileNotFoundError:
        console.print(
            "[yellow]⚠[/yellow] Docker not found. Please install Docker to use sandbox features."
        )
        return False
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow] Error checking Docker image: {e}")
        return False
