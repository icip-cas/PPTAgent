import asyncio
import json
import logging
import sys
import uuid
from collections import defaultdict
from pathlib import Path

from docker.errors import DockerException, NotFound
from mcp.types import CallToolResult, TextContent
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageFunctionToolCall as ToolCall,
)

import docker
from deeppresenter.utils import GLOBAL_CONFIG, ChatMessage
from deeppresenter.utils.constants import (
    CUTOFF_WARNING,
    LOGGING_LEVEL,
    TOOL_CACHE,
    TOOL_CUTOFF_LEN,
)
from deeppresenter.utils.log import (
    debug,
    error,
    info,
    set_logger,
    timer,
    warning,
)
from deeppresenter.utils.mcp_client import MCPClient
from deeppresenter.utils.typings import MCPServer, Role


class AgentEnv:
    def __init__(
        self,
        workspace: Path,
        hci_enable: bool = False,
        config_file: str = GLOBAL_CONFIG.mcp_config_file,
    ):
        if isinstance(workspace, str):
            workspace = Path(workspace)
        self.workspace = workspace.absolute()
        self.hci_enable = hci_enable
        with open(config_file, encoding="utf-8") as f:
            raw_conf = json.load(f)
            self.config: list[MCPServer] = [MCPServer(**s) for s in raw_conf]
        # Pass workspace-specific variables to client to avoid global env pollution
        self.client = MCPClient(
            WORKSPACE=str(self.workspace),
            WORKSPACE_ID=self.workspace.stem,
        )
        self.cutoff_len = TOOL_CUTOFF_LEN
        # caching overlong content
        self._tools_dict: dict[str, dict] = {}
        self._server_tools = defaultdict(list)
        self._tool_to_server = {}

        self.tool_history: list[tuple[ToolCall, ChatMessage]] = []
        self.tool_history_file = self.workspace / "history" / "tool_history.jsonl"

    async def tool_execute(
        self,
        tool_call: ToolCall,
        limit_len: bool = False,
    ):
        try:
            server_id = self._tool_to_server[tool_call.function.name]
            with timer(f"Tool `{tool_call.function.name}` execution"):
                if len(tool_call.function.arguments) == 0:
                    arguments = None
                else:
                    arguments = json.loads(tool_call.function.arguments)
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
                        text=f"Tool `{tool_call.function.name}` execution timed out.",
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
        if result.isError:
            warning(
                f"Tool `{tool_call.function.name}` with params:`{arguments}` encountered error:\n {result.content}"
            )

        is_error = False
        content = []
        for block in result.content:
            is_error = is_error or result.isError
            if block.type == "text":
                if limit_len and len(block.text) > self.cutoff_len:
                    hash_id = uuid.uuid4().hex[:8]
                    local_file = (
                        self.workspace / f"{tool_call.function.name}_{hash_id}.txt"
                    )
                    local_file.write_text(block.text)
                    block.text = block.text[: self.cutoff_len] + CUTOFF_WARNING.format(
                        resource_id=str(local_file)
                    )

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
            else:
                raise ValueError(f"Unsupported block type: {block.type}")
        msg = ChatMessage(
            role=Role.TOOL,
            content=content,
            from_tool=tool_call.function,
            tool_call_id=tool_call.id,
            is_error=is_error,
        )
        self.tool_history.append((tool_call, msg))
        return msg

    async def __aenter__(self):
        try:
            client = docker.from_env()
            container = client.containers.get(self.workspace.stem)
            warning(f"Found duplicate {self.workspace.stem}, killed.")
            container.kill()
        # happend if cannot find the container
        except NotFound:
            pass
        except DockerException as e:
            error(f"Docker is not accessible: {e}.")
            sys.exit(1)
        except Exception as e:
            error(f"Unexpected error when checking Docker containers: {e}.")
            sys.exit(1)

        with timer("Connecting MCP servers"):
            connect_tasks = []
            server_configs = []

            for server in self.config:
                name = server.name
                connect_tasks.append(self.client.connect_server(name, server))
                keep_tools = server.keep_tools
                exclude_tools = set(server.exclude_tools)
                server_configs.append((name, keep_tools, exclude_tools))

            # Connect to all servers in parallel
            await asyncio.gather(*connect_tasks)

            # Update tools for each connected server
            for name, keep_tools, exclude_tools in server_configs:
                info(f"Connected to server {name}")
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

        if LOGGING_LEVEL == logging.INFO:
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
        await self.client.cleanup()
        self.tool_history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.tool_history_file, "a", encoding="utf-8") as f:
            for tool_call, msg in self.tool_history:
                f.write(
                    json.dumps([tool_call.model_dump(), msg.text], ensure_ascii=False)
                    + "\n"
                )
        debug(
            f"Agent Environment exited successfully, interaction history saved to: {self.tool_history_file}."
        )

    def get_server_tools(self, server_id: str):
        tools = []
        for tool_name in self._server_tools[server_id]:
            tools.append(self._tools_dict[tool_name])
        return tools


if __name__ == "__main__":
    import asyncio

    from openai.types.chat.chat_completion_message_tool_call import Function

    set_logger("mcp manager")

    async def main():
        workspace = Path("/opt/workspace/test")
        workspace.mkdir(exist_ok=True)
        async with AgentEnv(workspace) as tool_execute:
            result = await tool_execute.tool_execute(
                ToolCall(
                    function=Function(
                        name="execute_command",
                        arguments=json.dumps({"command": "pip install aiohttp"}),
                    ),
                    id="test-tool-call-001",
                    type="function",
                )
            )
            print(result)

    asyncio.run(main())
