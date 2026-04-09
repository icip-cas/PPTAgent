import asyncio
import inspect
import json
import logging
import os
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import docker
import jsonschema
from docker.errors import DockerException, NotFound
from fastmcp.utilities.json_schema import compress_schema
from fastmcp.utilities.types import get_cached_typeadapter
from mcp.types import CallToolResult, TextContent
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageFunctionToolCall as ToolCall,
)
from pydantic import BaseModel

from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.constants import (
    CUTOFF_WARNING,
    LOGGING_LEVEL,
    MCP_CALL_TIMEOUT,
    PACKAGE_DIR,
    TOOL_CACHE,
    TOOL_CUTOFF_LEN,
    WORKSPACE_BASE,
)
from deeppresenter.utils.k8s_sandbox import KubernetesSandbox
from deeppresenter.utils.log import (
    debug,
    error,
    timer,
    warning,
)
from deeppresenter.utils.mcp_client import MCPClient
from deeppresenter.utils.typings import ChatMessage, MCPServer, Role


class ToolTiming(BaseModel):
    total_time: float = 0
    success_count: int = 0
    error_count: int = 0


class AgentEnv:
    def __init__(
        self,
        workspace: Path,
        config: DeepPresenterConfig,
        cutoff_len: int = TOOL_CUTOFF_LEN,
    ):
        if isinstance(workspace, str):
            workspace = Path(workspace)
        self.workspace = workspace.absolute()
        self.cutoff_len = cutoff_len
        self.mcp_configs = []
        with open(config.mcp_config_file, encoding="utf-8") as f:
            for s in json.load(f):
                server = MCPServer(**s)
                if server.network and config.offline_mode:
                    continue
                self.mcp_configs.append(server)
        # Pass workspace-specific variables to client to avoid global env pollution
        host_workspace_base = os.environ.get("DEEPPRESENTER_HOST_WORKSPACE_BASE", None)
        if host_workspace_base:
            # calculate HOST_WORKSPACE for docker-in-docker volume mounting
            host_workspace = str(self.workspace).replace(
                str(WORKSPACE_BASE), host_workspace_base
            )
            debug(
                f"HOST WORKSPACE DETECTED: mapping {host_workspace} to {self.workspace}"
            )
        else:
            # assume paths are the same (local development)
            host_workspace = str(self.workspace)

        envs = {
            "WORKSPACE": str(self.workspace),
            "HOST_WORKSPACE": host_workspace,
            "WORKSPACE_ID": self.workspace.stem,
            "CONFIG_FILE": str(config.file_path),
            "FASTMCP_LOG_LEVEL": "CRITICAL",
            "PACKAGE_DIR": str(PACKAGE_DIR),
            "PYTHONWARNINGS": "ignore",
        }
        if config.offline_mode:
            envs["OFFLINE_MODE"] = "1"
        self.runtime_envs = envs
        self.client = MCPClient(envs=envs)
        self.sandbox_backend = os.getenv(
            "DEEPPRESENTER_SANDBOX_BACKEND", "docker"
        ).lower()
        # caching overlong content
        self.timing_dict = defaultdict(ToolTiming)
        self._local_tools: dict[str, Callable] = {}
        self._tools_dict: dict[str, dict] = {}
        self._server_tools = defaultdict(list)
        self._tool_to_server = {}
        self._k8s_sandboxes: dict[str, KubernetesSandbox] = {}
        self.tool_history: list[tuple[ToolCall, ChatMessage]] = []
        self.tool_history_file = self.workspace / ".history" / "tool_history.jsonl"

    async def tool_execute(
        self,
        tool_call: ToolCall,
    ):
        try:
            start_time = time.time()
            if len(tool_call.function.arguments) == 0:
                arguments = None
            else:
                arguments = json.loads(tool_call.function.arguments)
                try:
                    assert (
                        jsonschema.validate(
                            arguments,
                            self._tools_dict[tool_call.function.name]["function"][
                                "parameters"
                            ],
                        )
                        is None
                    )
                except jsonschema.ValidationError as e:
                    raise f"Input validation error: {e.message}"

            if tool_call.function.name in self._local_tools:
                result = await self._call_local_tool(tool_call.function.name, arguments)
            else:
                server_id = self._tool_to_server[tool_call.function.name]
                result = await self.client.tool_execute(
                    server_id, tool_call.function.name, arguments
                )
        except KeyError:
            result = CallToolResult(
                type="text",
                content=[
                    TextContent(
                        text=f"Tool `{tool_call.function.name}` not found.", type="text"
                    )
                ],
                isError=True,
            )
        except TimeoutError:
            result = CallToolResult(
                content=[
                    TextContent(
                        text=f"Tool `{tool_call.function.name}` execution timed out after {MCP_CALL_TIMEOUT} seconds.",
                        type="text",
                    )
                ],
                isError=True,
            )
        except Exception as e:
            result = CallToolResult(
                content=[
                    TextContent(
                        text=f"Tool `{tool_call.function.name}` execution failed with error: {e}",
                        type="text",
                    )
                ],
                isError=True,
            )
        finally:
            elapsed = time.time() - start_time
            debug(
                f"Tool `{tool_call.function.name}` execution took {elapsed:.2f} seconds"
            )
            self.timing_dict[tool_call.function.name].total_time += elapsed
        if result.isError:
            self.timing_dict[tool_call.function.name].error_count += 1
            warning(
                f"Tool `{tool_call.function.name}` with params:`{tool_call.function.arguments}` encountered error: {result.content}"
            )
        else:
            self.timing_dict[tool_call.function.name].success_count += 1

        if len(result.content) != 1 or any(
            c.type not in ["image", "text"] for c in result.content
        ):
            raise ValueError(
                f"Only one text/image block is supported currently. While getting {result.content} from {tool_call.function.name}"
            )
        content = []
        block = result.content[0]
        if block.type == "text":
            if len(block.text) > self.cutoff_len:
                truncated = block.text[: self.cutoff_len]
                truncated = truncated[: truncated.rfind("\n")]

                # checking if we are reading from local file
                if tool_call.function.name == "read_file":
                    local_file = arguments["path"]
                else:
                    hash_id = uuid.uuid4().hex[:4]
                    local_file = (
                        self.workspace / f"{tool_call.function.name}_{hash_id}.txt"
                    )
                    local_file.write_text(block.text)

                truncated += CUTOFF_WARNING.format(
                    line=truncated.count("\n"), resource_id=str(local_file)
                )
                block.text = truncated

            content.append(
                {
                    "type": "text",
                    "text": block.text,
                }
            )
        elif block.type == "image":
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": block.data},
                }
            )
        msg = ChatMessage(
            role=Role.TOOL,
            content=content,
            from_tool=tool_call.function,
            tool_call_id=tool_call.id,
            is_error=result.isError,
        )
        self.tool_history.append((tool_call, msg))
        return msg

    async def __aenter__(self):
        if self.sandbox_backend not in {"kubernetes", "k8s", "kodo"}:
            try:
                client = docker.from_env()
                container = client.containers.get(self.workspace.stem)
                warning(
                    f"Found duplicated sandbox container id={self.workspace.stem}, killed."
                )
                container.remove(force=True)
            # happend if cannot find the container
            except NotFound:
                pass
            except DockerException as e:
                error(f"Docker is not accessible: {e}.")
                sys.exit(1)
            except Exception as e:
                error(f"Unexpected error when launching docker containers: {e}.")
                sys.exit(1)

        with timer("Connecting MCP servers"):
            await asyncio.gather(
                *[self.connect_server(server) for server in self.mcp_configs]
            )

        if LOGGING_LEVEL <= logging.INFO:
            debug(
                f"Found {len(self._tools_dict)} tools, writing to {TOOL_CACHE}\nTools: {', '.join(self._tools_dict.keys())}"
            )
            with open(TOOL_CACHE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "server_tools": self._server_tools,
                        "tool_specs": list(self._tools_dict.values()),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up all MCP connections and resources"""
        for server_name in list(self._server_tools.keys()):
            await self.disconnect_server(server_name)
        self.tool_history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.tool_history_file, "a", encoding="utf-8") as f:
            for tool_call, msg in self.tool_history:
                f.write(
                    json.dumps(
                        [tool_call.model_dump(), msg.model_dump()], ensure_ascii=False
                    )
                    + "\n"
                )
        with (self.workspace / ".history" / "tools_time_cost.json").open(
            "w", encoding="utf-8"
        ) as f:
            timing_data = {
                name: timing.model_dump()
                for name, timing in sorted(
                    self.timing_dict.items(),
                    key=lambda x: x[1].total_time,
                    reverse=True,
                )
            }
            json.dump(
                timing_data,
                f,
                ensure_ascii=False,
                indent=2,
            )
        debug(
            f"Agent Environment exited successfully, interaction history saved to: {self.tool_history_file}."
        )

    async def connect_server(self, server: MCPServer):
        """Connect to a single MCP server and register its tools."""
        name = server.name
        if name == "sandbox" and self.sandbox_backend in {"kubernetes", "k8s", "kodo"}:
            await self._connect_k8s_sandbox(server)
            return
        await self.client.connect_server(name, server)
        debug(f"Connected to server {name}")

        keep_tools = server.keep_tools
        exclude_tools = set(server.exclude_tools)

        tools_dict = await self.client.list_tools(name)
        for tool_name, tool_info in tools_dict.items():
            if (
                keep_tools is None or tool_name in keep_tools
            ) and tool_name not in exclude_tools:
                tool = {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_info.description,
                        "parameters": tool_info.inputSchema,
                    },
                }
                self._tools_dict[tool_name] = tool
                self._server_tools[name].append(tool_name)
                self._tool_to_server[tool_name] = name

    async def _connect_k8s_sandbox(self, server: MCPServer):
        image = os.getenv("DEEPPRESENTER_K8S_IMAGE") or server.env.get("IMAGE")
        if not image and server.args:
            image = server.args[-1]
        if not image:
            raise ValueError(
                "K8s sandbox backend requires an image. Set DEEPPRESENTER_K8S_IMAGE or keep the sandbox image as the last docker arg."
            )
        sandbox = KubernetesSandbox(
            workspace=self.workspace,
            runtime_envs=self.runtime_envs,
            image=image,
        )
        await sandbox.start()
        self._k8s_sandboxes[server.name] = sandbox
        debug(f"Connected to k8s sandbox using image {image}")

        local_tool_defs = [
            ("read_file", sandbox.read_file),
            ("write_file", sandbox.write_file),
            ("list_directory", sandbox.list_directory),
            ("create_directory", sandbox.create_directory),
            ("get_file_info", sandbox.get_file_info),
            ("execute_command", sandbox.execute_command),
        ]
        for tool_name, func in local_tool_defs:
            self.register_tool(func, name=tool_name)
            self._server_tools[server.name].append(tool_name)
            self._tool_to_server[tool_name] = server.name

    async def disconnect_server(self, server_name: str):
        """Disconnect a single MCP server and clean up its tools."""
        if server_name not in self._server_tools:
            return
        for tool_name in self._server_tools[server_name]:
            self._tools_dict.pop(tool_name, None)
            self._tool_to_server.pop(tool_name, None)
            self._local_tools.pop(tool_name, None)
        del self._server_tools[server_name]
        if server_name in self._k8s_sandboxes:
            await self._k8s_sandboxes[server_name].cleanup()
            self._k8s_sandboxes.pop(server_name, None)
        else:
            await self.client._close_server(server_name)
        debug(f"Disconnected from server {server_name}")

    def get_server_tools(self, server_name: str) -> list[dict]:
        tools = []
        for tool_name in self._server_tools[server_name]:
            tools.append(self._tools_dict[tool_name])
        return tools

    def register_tool(
        self,
        func: Callable,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Register a callable (function or bound method) as a tool.

        The JSON Schema for parameters is auto-generated from type hints.
        Supports both sync and async callables.
        """
        tool_name = name or func.__name__
        tool_desc = description or inspect.getdoc(func) or ""
        schema = get_cached_typeadapter(func).json_schema()
        schema = compress_schema(schema, prune_titles=True)
        self._tools_dict[tool_name] = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_desc,
                "parameters": schema,
            },
        }
        self._local_tools[tool_name] = func

    async def _call_local_tool(
        self, name: str, arguments: dict | None
    ) -> CallToolResult:
        """Execute a locally registered tool and wrap the result."""
        func = self._local_tools[name]
        kwargs = arguments or {}
        raw = (
            await func(**kwargs)
            if inspect.iscoroutinefunction(func)
            else func(**kwargs)
        )
        return CallToolResult(
            content=[TextContent(text=str(raw), type="text")],
            isError=False,
        )
