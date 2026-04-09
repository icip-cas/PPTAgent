import asyncio
import json
import os
import re
import shlex
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from deeppresenter.utils.log import debug

DEFAULT_TIMEOUT = 300
_PROXY_VARS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ftp_proxy",
    "FTP_PROXY",
    "no_proxy",
    "NO_PROXY",
)


@contextmanager
def _disable_proxy():
    backup = {}
    try:
        for key in _PROXY_VARS:
            if key in os.environ:
                backup[key] = os.environ.pop(key)
        yield
    finally:
        os.environ.update(backup)


def _parse_json_env(name: str, default: Any):
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {name}: {e}") from e


def _merge_dict(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for key, value in src.items():
        if key in dst and isinstance(dst[key], dict) and isinstance(value, dict):
            _merge_dict(dst[key], value)
        else:
            dst[key] = value
    return dst


class KubernetesSandbox:
    """A minimal k8s-backed sandbox that mirrors the core sandbox tools.

    The pod is used for command execution. File operations remain local so that
    generated artifacts stay visible to the host process immediately.
    This assumes the configured workspace path is shared between the host and
    the sandbox pod, typically via PVC/hostPath mounts supplied through
    `DEEPPRESENTER_K8S_POD_SPEC_PATCH`.
    """

    def __init__(
        self,
        workspace: Path,
        runtime_envs: dict[str, str],
        image: str,
    ):
        self.workspace = workspace.resolve()
        self.runtime_envs = dict(runtime_envs)
        self.image = os.getenv("DEEPPRESENTER_K8S_IMAGE", image)
        self.namespace = os.getenv("DEEPPRESENTER_K8S_NAMESPACE", "default")
        self.kubeconfig_path = os.getenv("DEEPPRESENTER_K8S_KUBECONFIG") or None
        self.node_selector = _parse_json_env("DEEPPRESENTER_K8S_NODE_SELECTOR", {})
        self.resources = _parse_json_env("DEEPPRESENTER_K8S_RESOURCES", {})
        self.pod_spec_patch = _parse_json_env("DEEPPRESENTER_K8S_POD_SPEC_PATCH", {})
        self.startup_command = os.getenv(
            "DEEPPRESENTER_K8S_SANDBOX_COMMAND", "sleep infinity"
        )
        self.exec_prefix = os.getenv(
            "DEEPPRESENTER_K8S_EXEC_PREFIX",
            f"cd {shlex.quote(str(self.workspace))} && ",
        )
        self.pod_name = self._build_pod_name()
        self.client = None
        self.async_client = None
        self.ws_api_client = None
        self._initialized = False

    def _build_pod_name(self) -> str:
        stem = self.workspace.stem.lower()
        stem = re.sub(r"[^a-z0-9-]+", "-", stem).strip("-")
        stem = stem[:40] or "sandbox"
        return f"dp-sandbox-{stem}"

    def _resolve_local_path(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        p = p.resolve()
        if not p.is_relative_to(self.workspace):
            raise ValueError(
                f"Path {p} is outside workspace {self.workspace}. K8s sandbox only permits workspace paths."
            )
        return p

    async def start(self):
        if self._initialized:
            return

        try:
            from kubernetes_asyncio import client as async_client
            from kubernetes_asyncio import config as async_config
        except ImportError as e:
            raise RuntimeError(
                "Kubernetes sandbox requires `kubernetes-asyncio`. Install project dependencies again after the patch."
            ) from e

        self.async_client = async_client
        with _disable_proxy():
            if self.kubeconfig_path:
                await async_config.load_kube_config(config_file=self.kubeconfig_path)
            else:
                await async_config.load_kube_config()

        self.client = async_client.CoreV1Api()

        try:
            await self.client.read_namespaced_pod(
                name=self.pod_name, namespace=self.namespace, _request_timeout=30
            )
            debug(
                f"Reusing existing k8s sandbox pod {self.pod_name} in namespace {self.namespace}"
            )
        except async_client.ApiException as e:
            if e.status != 404:
                raise
            pod_body = self._create_pod_spec()
            await self.client.create_namespaced_pod(
                namespace=self.namespace,
                body=pod_body,
                _request_timeout=120,
            )
            await self._wait_for_running()

        self._initialized = True

    def _create_pod_spec(self) -> dict[str, Any]:
        env_spec = [
            {"name": key, "value": str(value)}
            for key, value in sorted(self.runtime_envs.items())
        ]
        env_spec.append({"name": "WORKSPACE", "value": str(self.workspace)})
        pod = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": self.pod_name},
            "spec": {
                "restartPolicy": "Never",
                "containers": [
                    {
                        "name": "sandbox",
                        "image": self.image,
                        "command": ["/bin/sh", "-c"],
                        "args": [self.startup_command],
                        "stdin": True,
                        "tty": True,
                        "env": env_spec,
                    }
                ],
            },
        }
        if self.resources:
            pod["spec"]["containers"][0]["resources"] = self.resources
        if self.node_selector:
            pod["spec"]["nodeSelector"] = self.node_selector
        if self.pod_spec_patch:
            pod = _merge_dict(pod, self.pod_spec_patch)
        return pod

    async def _wait_for_running(self, timeout: int = 600):
        start = time.time()
        while True:
            pod = await self.client.read_namespaced_pod(
                name=self.pod_name,
                namespace=self.namespace,
                _request_timeout=30,
            )
            phase = pod.status.phase
            if phase == "Running":
                return
            if phase in {"Failed", "Succeeded", "Unknown"}:
                raise RuntimeError(
                    f"K8s sandbox pod {self.pod_name} entered terminal phase {phase}"
                )
            if time.time() - start > timeout:
                raise TimeoutError(
                    f"K8s sandbox pod {self.pod_name} not running after {timeout}s"
                )
            await asyncio.sleep(2)

    async def cleanup(self):
        if self.client is None or self.async_client is None:
            return
        try:
            await self.client.delete_namespaced_pod(
                name=self.pod_name,
                namespace=self.namespace,
                body=self.async_client.V1DeleteOptions(grace_period_seconds=0),
                _request_timeout=30,
            )
        except self.async_client.ApiException as e:
            if e.status != 404:
                raise
        finally:
            await self.client.api_client.close()
            self.client = None
            self.async_client = None
            self._initialized = False

    async def read_file(
        self,
        path: str,
        offset: int = 0,
        length: int | None = None,
    ) -> str:
        """Read a UTF-8 text file from the current workspace."""
        real_path = self._resolve_local_path(path)
        with open(real_path, encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            return f.read() if length is None else f.read(length)

    async def write_file(self, path: str, content: str) -> str:
        """Write a UTF-8 text file into the current workspace."""
        real_path = self._resolve_local_path(path)
        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_text(content, encoding="utf-8")
        return f"File written to {real_path}"

    async def list_directory(self, path: str = ".") -> str:
        """List direct children of a workspace directory."""
        real_path = self._resolve_local_path(path)
        if not real_path.exists():
            raise FileNotFoundError(f"Directory does not exist: {real_path}")
        if not real_path.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {real_path}")
        lines = []
        for item in sorted(real_path.iterdir(), key=lambda p: (not p.is_dir(), p.name)):
            kind = "dir" if item.is_dir() else "file"
            size = item.stat().st_size if item.is_file() else "-"
            lines.append(f"{kind}\t{size}\t{item.name}")
        return "\n".join(lines) if lines else "(empty directory)"

    async def create_directory(self, path: str) -> str:
        """Create a directory inside the current workspace."""
        real_path = self._resolve_local_path(path)
        real_path.mkdir(parents=True, exist_ok=True)
        return f"Directory created: {real_path}"

    async def get_file_info(self, path: str) -> str:
        """Return metadata for a workspace file or directory."""
        real_path = self._resolve_local_path(path)
        if not real_path.exists():
            raise FileNotFoundError(f"Path does not exist: {real_path}")
        stat = real_path.stat()
        return json.dumps(
            {
                "path": str(real_path),
                "type": "directory" if real_path.is_dir() else "file",
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            },
            ensure_ascii=False,
            indent=2,
        )

    async def execute_command(
        self, command: str, timeout: int = DEFAULT_TIMEOUT
    ) -> str:
        """Run a shell command inside the sandbox pod."""
        await self.start()
        wrapped = self.exec_prefix + command
        output, exit_code = await asyncio.wait_for(
            self._exec_in_pod(wrapped), timeout=timeout + 5
        )
        if exit_code != 0:
            raise RuntimeError(output)
        return output

    async def _exec_in_pod(self, command: str) -> tuple[str, int]:
        from kubernetes_asyncio.stream import WsApiClient

        ws_client = WsApiClient()
        ws_api = self.async_client.CoreV1Api(api_client=ws_client)
        try:
            resp = await ws_api.connect_get_namespaced_pod_exec(
                self.pod_name,
                self.namespace,
                command=["/bin/sh", "-c", command],
                stderr=True,
                stdin=False,
                stdout=True,
                tty=False,
            )
            output = resp if isinstance(resp, str) else ""
            output = re.sub(r"\x1b\[[0-9;]*m|\r", "", output)
            return output, 0
        except Exception as e:
            return f"Error: {e!r}", -1
        finally:
            await ws_client.close()
