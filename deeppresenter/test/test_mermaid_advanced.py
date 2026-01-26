"""
Test mermaid with the most complex scenario.
"""

import pytest


class TestMermaidAdvanced:
    """Test mermaid with the most complex scenario."""

    @pytest.mark.asyncio
    async def test_mermaid_sequence_chinese(
        self, agent_env, workspace, mermaid_sequence_diagram, tool_call_helper
    ):
        """Test mermaid sequence diagram with Chinese text and multiple participants."""
        # Write the sequence diagram
        diagram_path = workspace / "sequence.mmd"
        write_call = tool_call_helper(
            "write_file",
            {"path": str(diagram_path), "content": mermaid_sequence_diagram},
        )
        write_result = await agent_env.tool_execute(write_call)
        assert not write_result.is_error, (
            f"Failed to write diagram: {write_result.text}"
        )

        # Create Puppeteer config to allow running Chromium as root
        puppeteer_config_path = workspace / ".puppeteerrc.json"
        puppeteer_config = '{"args":["--no-sandbox","--disable-setuid-sandbox"]}'
        config_call = tool_call_helper(
            "write_file",
            {"path": str(puppeteer_config_path), "content": puppeteer_config},
        )
        config_result = await agent_env.tool_execute(config_call)
        assert not config_result.is_error, (
            f"Failed to write Puppeteer config: {config_result.text}"
        )

        # Generate PNG using mmdc with Puppeteer config
        output_path = workspace / "sequence_diagram.png"
        exec_call = tool_call_helper(
            "execute_command",
            {
                "command": f"mmdc -i {diagram_path} -o {output_path} -p {puppeteer_config_path}"
            },
        )
        exec_result = await agent_env.tool_execute(exec_call)
        assert not exec_result.is_error, f"mmdc execution failed: {exec_result.text}"
        assert "Error:" not in exec_result.text, (
            f"mmdc reported error: {exec_result.text}"
        )

        # Verify the output file exists
        list_call = tool_call_helper(
            "list_directory",
            {"path": str(workspace)},
        )
        list_result = await agent_env.tool_execute(list_call)
        assert "sequence_diagram.png" in list_result.text, "Sequence diagram not found"
